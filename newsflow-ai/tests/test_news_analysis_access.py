"""Operating request policy, synthetic credentials, Fake providers only."""
from copy import deepcopy
import hashlib
import pytest
from starlette.testclient import TestClient
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from newsflow.intelligence.credentials import FakeCipher,AnthropicKeyStore,AIKeyStore,CredentialError
from newsflow.intelligence.api_settings import FakeAPIBudgetService
from newsflow.news.curator import Curator
from bat_distribution.operation import OperatingRequests
from bat_distribution.news_analysis_access import NewsAnalysisAccess,PATH
from test_google_news_trends import prepared,no_external_calls

@pytest.mark.parametrize('failed',[False,True])
def test_real_request_boundary_fake_analysis_and_no_replay(app,prepared,failed):
    _,adapter,mode,_,ids=prepared
    root=app.state.config.data_dir;native=FakeCipher();kind=AnthropicKeyStore if mode=='claude_api' else AIKeyStore
    secret='synthetic-news-analysis-key-123456789'
    (root/kind.FILE).write_bytes(native.protect(secret.encode(),hashlib.sha256(kind.ENTROPY).digest()))
    owner=NewsAnalysisAccess(app,root,lambda:native,providers={mode:adapter},budget=FakeAPIBudgetService(app.state.sessions))
    original=adapter.analyze;seen=[]
    def fake(payload,options):
        assert owner.keys[mode].key()==secret
        seen.append(deepcopy(payload))
        if failed:raise TimeoutError('synthetic only')
        return original(payload,options)
    adapter.analyze=fake
    session=LaunchSession(18779);auth=LocalAccess(app,session)
    with TestClient(owner.wrap(OperatingRequests(auth),auth),base_url=session.origin,client=('127.0.0.1',43210),follow_redirects=False) as c:
        c.cookies.set(session.cookie_name,session.claim(session.launch_url().split('#')[1]));c.get('/studio/news')
        body={'csrf_token':c.cookies.get('newsflow_csrf'),'consent':'true','collection_context_id':Curator(app.state.coordinator).context()['run_id']}
        headers={'Origin':session.origin}
        assert c.post(PATH,data={**body,'csrf_token':'bad'},headers=headers).status_code==403
        assert c.post(PATH,data=body,headers={'Origin':'https://outside.invalid'}).status_code==403
        assert c.post(PATH,data={**body,'consent':'false'},headers=headers).status_code==422
        assert c.post(PATH,data={**body,'collection_context_id':99999},headers=headers).status_code==409
        assert not seen
        # Unrelated generation stays outside this connection.
        assert c.post('/news/curation/generate',data=body,headers=headers).status_code==403
        assert c.post('/api/feed-batches/1/step',data=body,headers=headers).status_code==403
        result=c.post(PATH,data=body,headers=headers)
        assert result.status_code==(422 if failed else 303),result.text
        assert len(seen)==1 and {a['id'] for a in seen[0]['articles']}==set(ids)
        again=c.post(PATH,data=body,headers=headers)
        assert again.status_code==(409 if failed else 303) and len(seen)==1
        c.cookies.clear();assert c.post(PATH,data=body,headers=headers).status_code==403
    with pytest.raises(CredentialError):owner.keys[mode].key()
