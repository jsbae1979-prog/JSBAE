"""Category collection contract with synthetic stores and Fake adapters only."""
from datetime import timedelta
from email.utils import format_datetime
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
import json
import pytest
from sqlalchemy import select
from conftest import csrf
from test_google_news_trends import no_external_calls, TREND
from test_serpapi_news import setup_serpapi, register
from newsflow.db.models import NewsArticle, IntelligenceRun, utcnow
from newsflow.news.ranking import CATEGORIES, CATEGORY_WORDS, classify, category_query, category_feeds, selected_categories
from newsflow.news.curator import Curator
from newsflow.news.collector import CollectedArticle
from newsflow.news.trends import TRENDS_URL
from newsflow.news.serpapi import SerpApiError
from newsflow.news.rss_adapter import validate_url, FeedError


@pytest.mark.parametrize('title,category', [('아이돌 컴백','연예'),('드라마 주연 배우','연예'),('웹툰 원작 예능','연예'),('미술 전시','문화'),('뮤지컬 공연','문화'),('영화 아이돌','문화')])
def test_classification(title,category):
    assert classify(title)==category
    assert len(CATEGORIES)==8
    words=[w.casefold() for row in CATEGORY_WORDS.values() for w in row]
    assert len(words)==len(set(words))


@pytest.mark.parametrize('bad', [['가짜'],['전체'],['정치',''],[None],'정치', ['정치']*9])
def test_invalid_categories(bad):
    with pytest.raises(ValueError): selected_categories(bad)


def test_category_plan_queries_and_public_urls():
    assert selected_categories(['연예','정치','연예'])==['정치','연예']
    assert selected_categories([])==[]
    for name in CATEGORIES:
        query=category_query(name)
        assert query.endswith(' when:1d') and ' OR ' in query and len(query)<600
        for url in category_feeds(name):
            assert validate_url(url)==url and urlsplit(url).hostname=='news.google.com'
            params=parse_qs(urlsplit(url).query)
            assert params['hl']==['ko'] and params['gl']==['KR']
            if name in ('정치','문화'): assert params['q']==[query]
    assert len(category_feeds('IT·과학'))==2


def article(n, *, title=None, age=1):
    titles=['의회 의결 절차 안내', '아이돌 앨범 출시 소식', '중앙은행 기준금리 공표', '새 우주망원경 관측 시작', '법원 판결 요지 공개', '국제 육상대회 일정']
    return CollectedArticle(title or titles[n % len(titles)],f'https://example.org/fixture/{n}','합성 출처','합성 기사 설명',utcnow()-timedelta(hours=age) if age is not None else None)


def feed(items):
    return ('<rss version="2.0"><channel><title>합성 분야</title>'+''.join(
        f'<item><title>{x.title}</title><link>{x.url}</link><description>{x.summary}</description>'
        +(f'<pubDate>{format_datetime(x.published_at,usegmt=True)}</pubDate>' if x.published_at else '')+'</item>' for x in items)+'</channel></rss>').encode()


def test_rss_selected_feeds_merge_age_cleanup_and_old_category_preserved(client,app,fake):
    curator=Curator(app.state.coordinator)
    fake.feeds[TRENDS_URL]=TREND
    # A pre-existing row is not reclassified when received again through another category.
    from newsflow.db.models import NewsSource
    with app.state.sessions.begin() as session:
        src=NewsSource(name='합성 이전',url='https://example.org/feed',enabled=False);session.add(src);session.flush()
        old=curator.news.store_articles(session,src.id,[article(1)],category='문화')['article_ids'][0]
        discarded=curator.news.store_articles(session,src.id,[article(101,title='이전 수집 대상')])['article_ids'][0]
    tech=[article(0),article(1),article(2),article(3),article(4,age=70),article(5,age=None)]
    fake.feeds.update({category_feeds('IT·과학')[0]:feed(tech),category_feeds('IT·과학')[1]:feed([article(0)]),category_feeds('연예')[0]:feed([article(1),article(9,title='합성 예능 새 시즌')])})
    response=client.post('/news/curation/refresh',data={'csrf_token':csrf(client),'permission':'true','categories':['연예','IT·과학'],'hours':'24'})
    assert response.status_code==200
    assert fake.calls==[*category_feeds('IT·과학'),*category_feeds('연예'),TRENDS_URL]
    ctx=curator.context();summary=ctx['collection']
    assert summary['recent_filter']['excluded_old']==1 and summary['recent_filter']['unknown_published_at']==1
    assert len(summary['article_ids'])==len(set(summary['article_ids']))==6
    assert summary['category_counts']==[{'category':'IT·과학','collected':6,'kept':5,'status':'success'},{'category':'연예','collected':2,'kept':2,'status':'success'}]
    with app.state.sessions() as session:
        assert session.get(NewsArticle,old).category=='문화'
        assert session.get(NewsArticle,discarded) is None
        assert session.scalar(select(NewsArticle).where(NewsArticle.url.endswith('/0'))).category=='IT·과학'
    assert 'category-collection-summary' in response.text
    view=client.get('/api/studio/modules/news').json()
    assert view['catalog']['newsCategories']==list(CATEGORIES)
    assert view['catalog']['categoryCollection']==summary['category_counts']


class CategorySearch:
    test_only=True
    def __init__(self, fail=None): self.calls=[];self.fail=fail
    def search(self, *, query):
        self.calls.append(query)
        if self.fail and len(self.calls)==2: raise self.fail
        return [article(len(self.calls)),article(0)], {'provider_billed_credits':None}


def post_serp(client,token,categories,maximum=None,policy='korea_v1',hours=24):
    return client.post('/news/curation/serpapi',data={'csrf_token':csrf(client),'request_token':token,'consent':'true',
        'collection_policy':policy,'maximum_requests':str(maximum if maximum is not None else len(set(categories))),
        'categories':categories,'hours':str(hours)})


def test_serp_counts_dedup_replay_and_no_provider_text(client,app,fake,setup_serpapi):
    register(client);fake.feeds[TRENDS_URL]=TREND
    search=CategorySearch();app.state.serpapi_adapter=search
    token=uuid4().hex;response=post_serp(client,token,['정치','연예','연예'])
    assert response.status_code==200
    assert search.calls==[category_query('정치'),category_query('연예')]
    assert post_serp(client,token,['연예','정치']).status_code==200
    assert len(search.calls)==2
    assert post_serp(client,token,['정치'],maximum=1).status_code==422
    with app.state.sessions() as session:
        run=session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind=='news_search'))
        assert run.options['maximum_requests']==2 and run.result['local_request_attempts']==2
        assert run.result['provider_billed_credits'] is None and len(run.result['article_ids'])==3
        assert all(r['status']=='success' for r in run.result['requests'])


@pytest.mark.parametrize('bad,maximum,policy', [(['가짜'],1,'korea_v1'),(['정치','경제'],1,'korea_v1'),(['정치'],5,'global_trends_v1')])
def test_reject_before_claim_or_network(client,app,fake,setup_serpapi,bad,maximum,policy):
    register(client);search=CategorySearch();app.state.serpapi_adapter=search
    assert post_serp(client,uuid4().hex,bad,maximum,policy).status_code==422
    assert search.calls==[] and fake.calls==[]
    assert client.post('/news/curation/refresh',data={'csrf_token':csrf(client),'permission':'true','categories':['bad']}).status_code==422
    with app.state.sessions() as session: assert session.scalar(select(IntelligenceRun)) is None


@pytest.mark.parametrize('code',['timeout_unknown','http_failed'])
def test_failed_category_stops_remaining_no_replay(client,app,fake,setup_serpapi,code):
    register(client);search=CategorySearch(SerpApiError(code));app.state.serpapi_adapter=search
    token=uuid4().hex;categories=['정치','경제','연예']
    assert post_serp(client,token,categories).status_code==422
    assert len(search.calls)==2 and fake.calls==[]
    post_serp(client,token,categories)
    assert len(search.calls)==2
    assert post_serp(client,token,['정치','연예'],hours=48).status_code==422
    with app.state.sessions() as session:
        run=session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind=='news_search'))
        assert run.status==('unknown' if code=='timeout_unknown' else 'failed')
        assert run.result['local_request_attempts']==2
        assert run.result['category_counts'][-1]['status']=='pending'
        assert run.result['requests'][0]['status']=='success'
    assert Curator(app.state.coordinator).context()['ready'] is False


def test_rss_failure_keeps_previous_rows_no_retry(client,app,fake):
    from newsflow.db.models import NewsSource
    curator=Curator(app.state.coordinator)
    with app.state.sessions.begin() as session:
        src=NewsSource(name='합성 이전',url='https://example.org/feed',enabled=False);session.add(src);session.flush()
        old=curator.news.store_articles(session,src.id,[article(55)])['article_ids'][0]
    fake.feeds[category_feeds('정치')[0]]=FeedError('secret-never-log')
    curator.refresh(True,24,['정치'])
    assert fake.calls==category_feeds('정치')
    with app.state.sessions() as session: assert session.get(NewsArticle,old) is not None
    assert 'secret-never-log' not in client.get('/news').text


def test_registries_equal_and_registered_categories():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    a=json.loads((root/'src/newsflow/studio/actions.json').read_text(encoding='utf8'))
    b=json.loads((root/'frontend/src/legacy-actions.json').read_text(encoding='utf8'))
    assert a==b
    for identifier in ('curation_refresh','serpapi_collect'):
        fields=next(x for x in a if x['id']==identifier)['fields']
        assert next(f for f in fields if f['name']=='categories')['type']=='array'
