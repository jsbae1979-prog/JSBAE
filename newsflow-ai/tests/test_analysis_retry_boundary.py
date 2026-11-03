from copy import deepcopy
import hashlib,json
import pytest
from sqlalchemy import select
from starlette.testclient import TestClient
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from newsflow.intelligence.credentials import FakeCipher,AnthropicKeyStore
from newsflow.intelligence.api_settings import FakeAPIBudgetService
from newsflow.news.curator import Curator
from newsflow.db.models import IntelligenceRun,AppSetting
from bat_distribution.operation import OperatingRequests
from bat_distribution.news_analysis_access import NewsAnalysisAccess,PATH
from test_google_news_trends import prepared,no_external_calls

@pytest.mark.parametrize("prepared", ["claude_api"], indirect=True)
def test_schema_failure_retries_only_confirmed_current_run_with_auth(app,prepared):
    _,adapter,mode,_,ids=prepared
    assert mode=='claude_api'
    root=app.state.config.data_dir;native=FakeCipher();kind=AnthropicKeyStore
    (root/kind.FILE).write_bytes(native.protect(b'synthetic-analysis-retry-key-123',hashlib.sha256(kind.ENTROPY).digest()))
    owner=NewsAnalysisAccess(app,root,lambda:native,providers={mode:adapter},budget=FakeAPIBudgetService(app.state.sessions))
    original=adapter.analyze;seen=[]
    def fake(payload,options):
        seen.append(deepcopy(payload))
        return {} if len(seen)==1 else original(payload,options)
    adapter.analyze=fake
    launch=LaunchSession(18779);auth=LocalAccess(app,launch)
    with TestClient(owner.wrap(OperatingRequests(auth),auth),base_url=launch.origin,client=('127.0.0.1',43210),follow_redirects=False) as c:
        c.cookies.set(launch.cookie_name,launch.claim(launch.launch_url().split('#')[1]));c.get('/studio/news')
        body={'csrf_token':c.cookies.get('newsflow_csrf'),'consent':'true','collection_context_id':Curator(app.state.coordinator).context()['run_id']}
        headers={'Origin':launch.origin}
        assert c.post(PATH,data=body,headers=headers).status_code==422
        with app.state.sessions() as db:
            first=db.scalar(select(IntelligenceRun).where(IntelligenceRun.kind=='analysis').order_by(IntelligenceRun.id.desc()))
            first_id=first.id;record=deepcopy(first.result)
        state=c.get('/api/curation/analysis-status',params={'collection_context_id':body['collection_context_id']}).json()
        assert state['canRetry'] and state['runId']==first_id
        assert c.post(PATH,data=body,headers=headers).status_code==409
        retry={**body,'retry_failed_run_id':first_id}
        assert c.post(PATH,data={**retry,'consent':'false'},headers=headers).status_code==422
        assert c.post(PATH,data={**retry,'csrf_token':'bad'},headers=headers).status_code==403
        assert c.post(PATH,data=retry,headers={'Origin':'https://outside.invalid'}).status_code==403
        assert c.post(PATH,data={**retry,'retry_failed_run_id':first_id+999},headers=headers).status_code==409
        assert len(seen)==1
        response=c.post(PATH,data=retry,headers=headers)
        assert response.status_code==303,response.text
        assert c.post(PATH,data=retry,headers=headers).status_code==303
        assert len(seen)==2
        with app.state.sessions() as db:
            assert db.get(IntelligenceRun,first_id).result==record
            claim=db.scalar(select(AppSetting).where(AppSetting.key.like('curation_once:%')))
            history=json.loads(claim.value)['history']
            assert history[0]['run_id']==first_id and history[0]['status']=='failed'
