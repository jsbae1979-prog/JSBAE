"""Posting text tests use synthetic content/Fake authoring, never external services."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
import json
import pytest
from sqlalchemy import select
from newsflow.db.models import AppSetting,IntelligenceRun
from newsflow.publishing.posting_copy import PostingCopy,Suggestion,Copy,digest,platforms_for
from newsflow.publishing.service import PublishingError
from conftest import csrf
from test_single_workspace import video_fixture
from test_library_visibility import post

VALUE={'title':'합성 제목','description':'합성 설명','hashtags':['#합성']}

@pytest.fixture
def copy_service(app):
    class AI:
        calls=[]
        fail=False
        def generate(self,instruction,payload,schema,options,**kwargs):
            self.calls.append((deepcopy(payload),kwargs))
            if self.fail:raise TimeoutError()
            return Suggestion(**{**VALUE,'title':'검토된 제목','notes':['실제 영상과 내용 일치 여부를 확인하세요.']})
    ai=AI();source={'id':'character:'+'a'*32,'kind':'character','title':'합성 제목','content':{'topic':'합성 주제','story':{}}}
    svc=PostingCopy(app.state,ai=ai,source=lambda i:{**deepcopy(source),'id':i})
    app.state.posting_copy=svc
    return svc,ai,source

def test_explicit_review_apply_and_idempotence(copy_service,app,client):
    svc,ai,source=copy_service;identifier=source['id'];h=digest(source);token=uuid4().hex
    result=svc.review(identifier,h,0,VALUE,'claude_api',token,True)
    assert svc.review(identifier,h,0,VALUE,'claude_api',token,True)==result and len(ai.calls)==1
    assert svc.view(identifier)['copy'] is None
    data={'csrf_token':csrf(client),'project_id':identifier,'source_hash':h,'revision':'0','review_id':str(result['id'])}
    response=client.post('/api/studio/publishing/copy/apply',data=data)
    assert response.status_code==200,response.text
    assert response.json()['copy']['title']=='검토된 제목' and response.json()['approval'] is False
    assert client.post('/api/studio/publishing/copy/apply',data=data).status_code==409
    assert len(ai.calls)==1

def test_consent_different_content_and_unknown_not_replayed(copy_service):
    svc,ai,source=copy_service;identifier=source['id'];h=digest(source);token=uuid4().hex
    with pytest.raises(PublishingError):svc.review(identifier,h,0,VALUE,'claude_api',token,False)
    assert not ai.calls
    ai.fail=True
    with pytest.raises(PublishingError):svc.review(identifier,h,0,VALUE,'claude_api',token,True)
    with pytest.raises(PublishingError):svc.review(identifier,h,0,VALUE,'claude_api',token,True)
    with pytest.raises(PublishingError):svc.review(identifier,h,0,{**VALUE,'title':'다른 제목'},'claude_api',token,True)
    assert len(ai.calls)==1 and svc.view(identifier)['copy'] is None

def test_source_and_revision_protect_edits(copy_service):
    svc,ai,source=copy_service;identifier=source['id'];h=digest(source)
    svc.save(identifier,h,0,VALUE)
    with pytest.raises(PublishingError):svc.save(identifier,h,0,VALUE)
    source['content']['topic']='바뀐 주제'
    with pytest.raises(PublishingError):svc.save(identifier,h,1,VALUE)
    assert svc.view(identifier)['copy']==VALUE and not ai.calls

@pytest.mark.parametrize('value',[{**VALUE,'title':' '},{**VALUE,'title':'x'*101},{**VALUE,'hashtags':['not-a-tag']},{**VALUE,'hashtags':['#Same','#same']}])
def test_bad_copy_rejected(value):
    with pytest.raises(ValueError):Copy.model_validate(value)

def test_real_selected_source_removed_or_missing_stays_unavailable(app,client):
    row=video_fixture(app,'합성 뉴스 제목');identifier='news:'+str(row['id'])
    svc=PostingCopy(app.state);source=svc.source(identifier)
    assert source['kind']=='news' and source['content']['title']=='합성 뉴스 제목'
    assert platforms_for(source)==['youtube','instagram','tiktok','facebook']
    assert platforms_for({'kind':'image'})==['instagram']
    assert post(client,'remove',[identifier]).status_code==200
    with pytest.raises(PublishingError):svc.source(identifier)

def test_http_csrf_and_wrong_review_target(copy_service,client):
    svc,ai,source=copy_service;identifier=source['id'];h=digest(source)
    body={'csrf_token':csrf(client),'project_id':identifier,'source_hash':h,'revision':'0','copy':json.dumps(VALUE)}
    assert client.post('/api/studio/publishing/copy/save',data={**body,'csrf_token':'bad'}).status_code==403
    assert client.post('/api/studio/publishing/copy/save',data=body).status_code==200
    result=svc.review(identifier,h,1,VALUE,'claude_api',uuid4().hex,True)
    wrong={**body,'csrf_token':csrf(client),'revision':'1','project_id':'character:'+'b'*32,'review_id':str(result['id'])}
    assert client.post('/api/studio/publishing/copy/apply',data=wrong).status_code==409
    assert len(ai.calls)==1


def test_format_validation_never_saves_or_calls_ai(copy_service,client):
    svc,ai,source=copy_service
    body={'csrf_token':csrf(client),'project_id':source['id'],'source_hash':digest(source),'copy':json.dumps(VALUE)}
    route='/api/studio/publishing/copy/validate'
    assert client.post(route,data=body).json()=={'valid':True,'published':False,'approval':False}
    assert svc.view(source['id'])['revision']==0 and not ai.calls
    assert client.post(route,data={**body,'copy':json.dumps({**VALUE,'hashtags':['invalid']})}).status_code==422
    assert client.post(route,data={**body,'source_hash':'0'*64}).status_code==409
    assert client.post(route,data={**body,'csrf_token':'bad'}).status_code==403
