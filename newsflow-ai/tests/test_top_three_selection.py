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
def feeds(app,monkeypatch):
    items=[{'rank':n,'article_id':n,'article_ids':[n], 'title':f'Synthetic news {n}',
        'body':f'Synthetic summary {n}', 'references':[{'url':f'https://example.com/news/{n}','publisher':'Fixture'}],
        'selection':{'draft_id':None},'origin':'saved'} for n in (1,2,3)]
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
        assert c.post(f'/api/feed-batches/{identifier}/change',data={**body,'action':'regenerate','revision':'2','consent':'true','reviewed':'true'}).status_code==403
        assert c.post(f'/api/feed-batches/{identifier}/step',data=body).status_code==403
