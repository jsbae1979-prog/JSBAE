"""Real new request boundary, Fake transports/DPAPI only."""
from types import SimpleNamespace
from copy import deepcopy
from uuid import uuid4
import json,hashlib
import pytest
from starlette.testclient import TestClient
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from newsflow.distribution.windows_profile import private_directory
from newsflow.intelligence.credentials import FakeCipher,AnthropicKeyStore,AIKeyStore,CredentialError
from newsflow.intelligence.api_settings import FakeAPIBudgetService
from newsflow.intelligence.api_providers import AnthropicProvider,OpenAISearchProvider
from newsflow.publishing.posting_copy import digest
from bat_distribution.posting_copy_access import PostingCopyAccess,PATH
from bat_distribution.operation import OperatingRequests
from test_api_settings import configured
from test_posting_copy import VALUE

@pytest.mark.parametrize('provider',['claude_api','openai'])
def test_scoped_keys_and_single_fake_call(app,monkeypatch,provider):
    root=private_directory(app.state.config.data_dir/'posting-private')
    app.state.config=SimpleNamespace(**{**vars(app.state.config),'data_dir':root})
    class Native(FakeCipher):
        calls=0
        buffers=[]
        def unprotect(self,data,entropy):
            self.calls+=1;p=bytearray(super().unprotect(data,entropy));self.buffers.append(p);return p
    native=Native();kind=AnthropicKeyStore if provider=='claude_api' else AIKeyStore
    configured(app.state.sessions,provider)
    secret='synthetic-posting-review-key-123456789'
    (root/kind.FILE).write_bytes(native.protect(secret.encode(),hashlib.sha256(kind.ENTROPY).digest()))
    calls=[]
    def fake_post(self,body,options):
        assert self.key_provider()==secret
        calls.append(body);self.last_usage={'prompt_tokens':30,'completion_tokens':30}
        text=json.dumps({**VALUE,'notes':['합성 검토']},ensure_ascii=False)
        return {'stop_reason':'end_turn','content':[{'type':'text','text':text}]} if provider=='claude_api' else {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}
    monkeypatch.setattr(AnthropicProvider,'_post',fake_post);monkeypatch.setattr(OpenAISearchProvider,'_post',fake_post)
    owner=PostingCopyAccess(app,root,lambda:native,budget=FakeAPIBudgetService(app.state.sessions))
    source={'id':'character:'+'a'*32,'kind':'character','title':'합성 제목','content':{'topic':'합성 주제'}}
    app.state.posting_copy.source=lambda i:deepcopy(source)
    session=LaunchSession(18779);auth=LocalAccess(app,session)
    with TestClient(owner.wrap(OperatingRequests(auth),auth),base_url=session.origin,client=('127.0.0.1',43210),follow_redirects=False) as c:
        c.cookies.set(session.cookie_name,session.claim(session.launch_url().split('#')[1]));c.get('/studio/publishing')
        body={'project_id':source['id'],'source_hash':digest(source),'revision':'0','copy':json.dumps(VALUE),'provider':provider,'request_id':uuid4().hex,'consent':'true','csrf_token':c.cookies.get('newsflow_csrf')}
        assert c.post(PATH,data={**body,'csrf_token':'bad'},headers={'Origin':session.origin}).status_code==403
        assert c.post(PATH,data=body,headers={'Origin':'https://outside.invalid'}).status_code==403
        assert c.post(PATH,data={**body,'consent':'false'},headers={'Origin':session.origin}).status_code==409
        assert not calls and native.calls==0
        result=c.post(PATH,data=body,headers={'Origin':session.origin})
        assert result.status_code==200,result.text
        assert len(calls)==native.calls==1 and all(not any(x) for x in native.buffers)
        assert c.post(PATH,data=body,headers={'Origin':session.origin}).status_code==200
        assert len(calls)==1
        c.cookies.clear();assert c.post(PATH,data=body,headers={'Origin':session.origin}).status_code==403
        assert len(calls)==1
    with pytest.raises(CredentialError):app.state.posting_copy.ai.keys[provider].key()
