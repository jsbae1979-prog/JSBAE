"""Offline draft scoping and operation routing; never call a provider."""
from types import SimpleNamespace
from copy import deepcopy
import pytest
from starlette.testclient import TestClient
from newsflow.creation.top_three_feeds import TopThreeFeeds
from newsflow.creation.catalog import DEFAULTS
from newsflow.publishing.service import PublishingError
from bat_distribution.operation import OperatingRequests

@pytest.fixture
def feeds(app,monkeypatch,request):
    items=[{'rank':n,'article_id':n,'article_ids':[n], 'title':f'합성 뉴스 {n}',
        'body':f'합성 요약 {n}', 'references':[{'url':f'https://example.com/news/{n}','publisher':'Fixture'}],
        'selection':{'draft_id':None},'origin':'saved'} for n in (1,2,3)]
    if getattr(request,'param',None)=='analysis_feed_copy':
        for item in items:
            item['feed_copy']={'title':f"독립 제목 {item['rank']}\n계획 검토",'description':f"해당 핵심 설명 {item['rank']}"}
    monkeypatch.setattr('newsflow.creation.top_three_feeds.selection',lambda s,i:{'run':SimpleNamespace(id=i,evidence={'curation_contract':{'top_k':3}}),'items':deepcopy(items)})
    service=TopThreeFeeds(app.state.sessions,app.state.config.data_dir,SimpleNamespace(adapter=None))
    app.state.top_three_feeds=service
    return service

@pytest.mark.parametrize('rank',[None,1,2,3])
def test_exact_scope_and_idempotent_local_save(feeds,rank):
    identifier=feeds.create(42,DEFAULTS['image'],rank=rank)
    view=feeds.view(identifier)
    ranks=[1,2,3] if rank is None else [rank]
    assert [i['rank'] for i in view['items']]==ranks
    assert [i['source']['article_id'] for i in view['items']]==ranks
    assert view['plannedImages']==view['maxGenerations']==len(ranks)
    assert not view['canGenerate']
    assert feeds.create(42,DEFAULTS['image'],rank=rank)==identifier
    with pytest.raises(PublishingError,match='공식 견적'):feeds.step(identifier,consent=True,reviewed=True)
    assert feeds.view(identifier)['status']=='saved'
    feeds.change(identifier,1,'edit',rank=ranks[0],title='Reviewed title',body='Reviewed body')
    assert feeds.view(identifier)['items'][0]['content']['title']=='Reviewed title'

@pytest.mark.parametrize('rank',[0,4,True,'2'])
def test_invalid_rank_does_not_create_draft(feeds,rank):
    with pytest.raises(PublishingError):feeds.create(42,DEFAULTS['image'],rank=rank)
    assert not feeds.recent()

def test_route_forwards_selected_rank_and_preserves_csrf(app,feeds):
    with TestClient(OperatingRequests(app),base_url="http://127.0.0.1:18779") as c:
        c.get('/studio/images')
        body={**DEFAULTS['image'],'analysis_id':'42','rank':'3','csrf_token':c.cookies.get('newsflow_csrf')}
        assert c.post('/api/feed-batches',data={**body,'csrf_token':'bad'}).status_code==403
        response=c.post('/api/feed-batches',data=body)
        assert response.status_code==200,response.text
        result=response.json();identifier=result['id']
        assert [i['rank'] for i in result['items']]==[3]
        assert c.post(f'/api/feed-batches/{identifier}/change',data={**body,'action':'edit','revision':'1','title':'Title','body':'Summary'}).status_code==200
        assert c.post(f'/api/feed-batches/{identifier}/change',data={**body,'action':'regenerate','rank':'3','revision':'2','consent':'true','reviewed':'true'}).status_code==422  # reaches local validation; pending cannot regenerate
        assert c.post(f'/api/feed-batches/{identifier}/step',data=body).status_code==403


def test_changed_model_not_silently_replaced_with_old_batch(feeds):
    identifier=feeds.create(42,DEFAULTS['image'])
    with pytest.raises(PublishingError,match='다른 모델'):
        feeds.create(42,{**DEFAULTS['image'],'quality':'high'})
    assert feeds.view(identifier)['selection']['quality']==DEFAULTS['image']['quality']
    assert len(feeds.recent())==1


def query_selection(monkeypatch, urls, *, shared_id=False):
    rows=[{'rank':n,'article_id':n,'article_ids':[1 if shared_id and n==2 else n],
        'title':f'서로 다른 사건 {url}','body':f'합성 요약 {n}',
        'references':[{'url':url,'publisher':'Fixture'}],
        'selection':{'draft_id':None},'origin':'saved'} for n,url in enumerate(urls,1)]
    monkeypatch.setattr('newsflow.creation.top_three_feeds.selection',lambda s,i:{
        'run':SimpleNamespace(id=i,evidence={'curation_contract':{'top_k':3}}),'items':deepcopy(rows)})

def test_distinct_query_article_ids_are_not_duplicate_events(feeds,monkeypatch):
    query_selection(monkeypatch,[f'https://example.com/news/article.html?no={n}' for n in (11,22,33)])
    i=feeds.create(100,DEFAULTS['image'])
    assert len(feeds.get(i).result['items'])==3

@pytest.mark.parametrize('kind',['query_order','tracking','article_id'])
def test_same_article_still_rejected_without_paid_call(feeds,monkeypatch,kind):
    first='https://example.com/article?no=1&section=2'
    second={'query_order':'https://example.com/article?section=2&no=1',
        'tracking':first+'&utm_source=test#top','article_id':'https://other.example/article/2'}[kind]
    query_selection(monkeypatch,[first,second,'https://example.com/article?no=3'],shared_id=kind=='article_id')
    with pytest.raises(PublishingError,match='중복'):feeds.create(100,DEFAULTS['image'])
    assert not feeds.recent()

@pytest.mark.parametrize('same',[True,False])
def test_legacy_path_claim_checks_actual_article_and_preserves_record(feeds,monkeypatch,same):
    from newsflow.db.models import AppSetting
    from newsflow.creation.top_three_feeds import digest
    query_selection(monkeypatch,[f'https://example.com/article?no={n}' for n in (11,22,33)])
    old=feeds.create(90,DEFAULTS['image'],rank=1)
    key='top3-event:'+digest(['source','example.com','/article'])[:38]
    with feeds.sessions.begin() as db:db.add(AppSetting(key=key,value=str(old)))
    query_selection(monkeypatch,[f'https://example.com/article?no={n}' for n in ((11,44,55) if same else (44,55,66))])
    if same:
        with pytest.raises(PublishingError,match='이미 TOP 3'):feeds.create(100,DEFAULTS['image'])
    else:
        new=feeds.create(100,DEFAULTS['image']);assert new!=old
    with feeds.sessions() as db:assert db.get(AppSetting,key).value==str(old)
