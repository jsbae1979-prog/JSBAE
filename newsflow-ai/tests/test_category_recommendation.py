from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from newsflow.db.models import NewsArticle, utcnow
from newsflow.news.collector import CollectedArticle
from newsflow.news.category_selection import recommend
from newsflow.news.curator import Curator
from newsflow.news.ranking import category_feeds
from newsflow.news.trends import TRENDS_URL
from test_google_news_trends import TREND
from test_category_collection import feed, post_serp, setup_serpapi, register

def item(n, now):
    return CollectedArticle(f'합성 소식 {n} 발표',f'https://example.org/news/{n}','합성 매체','내용 확인',now-timedelta(hours=2))

def test_recommend_before_storage_rank_not_input_order():
    now=datetime(2026,11,3,tzinfo=UTC)
    rows=[item(n,now) for n in range(40)]
    rows[-1]=replace(rows[-1],title='서울 의료 정책 현장 발표 39')
    picked,info=recommend(rows,now,24)
    assert len(picked)==30 and picked[0]==rows[-1]
    assert recommend(list(reversed(rows)),now,24)[0]==picked
    assert info['excluded_rank']==10 and info['measured_popularity'] is False
    assert info['ranking'][0]['components']['주제 중요도']['value']==20

def test_period_dedup_unknown_no_old_backfill():
    now=datetime(2026,11,3,tzinfo=UTC);a=item(1,now)
    rows=[a,replace(a,url=a.url+'?utm_source=x',publisher='다른 매체'),
          replace(item(2,now),published_at=now-timedelta(hours=25)),
          replace(item(3,now),published_at=None),replace(item(4,now),published_at=now+timedelta(hours=1))]
    picked,info=recommend(rows,now,24)
    assert len(picked)==2 and info['duplicates_removed']==1
    assert info['excluded_old']==1 and info['excluded_future']==1 and info['unknown_published_at']==1
    assert info['ranking'][0]['components']['복수 출처']['value']==15
    assert recommend([rows[2]],now,24)[0]==[]

@pytest.mark.parametrize('method',['rss','serpapi'])
def test_collection_persists_only_thirty_per_category(client,app,fake,setup_serpapi,method):
    now=utcnow();a=[item(n,now) for n in range(45)];b=[item(n,now) for n in range(100,140)]
    fake.feeds[TRENDS_URL]=TREND
    curator=Curator(app.state.coordinator)
    if method=='rss':
        fake.feeds[category_feeds('IT·과학')[0]]=feed(a[:25])
        fake.feeds[category_feeds('IT·과학')[1]]=feed(a[25:]+a[:1])
        fake.feeds[category_feeds('연예')[0]]=feed(b)
        curator.refresh(True,24,['IT·과학','연예'])
    else:
        class Search:
            test_only=True
            calls=0
            def search(self,**kw):
                self.calls+=1
                return (a if self.calls==1 else b),{}
        register(client);adapter=Search();app.state.serpapi_adapter=adapter
        assert post_serp(client,uuid4().hex,['IT·과학','연예']).status_code==200
        assert adapter.calls==2
    result=curator.context()['collection']
    assert [r['kept'] for r in result['category_counts']]==[30,30]
    assert all(r['selection']['policy']=='category_recommendation_v1' for r in result['category_counts'])
    assert len(result['article_ids'])==60
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(NewsArticle))==60
    assert result['selection_evidence']
    assert all(not s['measured_popularity'] for s in result['selection_evidence'].values())

def test_rss_storage_failure_finishes_without_replaying(client,app,fake,monkeypatch):
    from newsflow.news import category_collection as collection
    fake.feeds[TRENDS_URL]=TREND
    for url in category_feeds('IT·과학'):
        fake.feeds[url]=feed([item(1,utcnow())])
    calls=[]
    def fail(*args,**kwargs):
        calls.append(1)
        raise OSError('synthetic storage failure')
    monkeypatch.setattr(collection,'_store',fail)
    curator=Curator(app.state.coordinator)
    curator.refresh(True,24,['IT·과학'])
    result=curator.context()['collection']
    assert len(calls)==1 and result['failed']==1
    assert result['category_counts'][0]['status']=='failed'
    assert result['article_ids']==[]
