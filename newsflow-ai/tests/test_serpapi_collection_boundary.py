"""Exact authenticated collection boundary, synthetic DPAPI and Fake collector only."""
from types import SimpleNamespace
from uuid import uuid4
import pytest
from starlette.testclient import TestClient
from newsflow.distribution.local_access import LaunchSession, LocalAccess
from newsflow.intelligence.credentials import FakeCipher, CredentialError
from newsflow.news.serpapi import SerpApiKeys
from bat_distribution.operation import OperatingRequests
from bat_distribution import serpapi_key_registration, serpapi_collection

@pytest.fixture
def boundary(app, monkeypatch):
    class Native(FakeCipher):
        reads=0
        buffers=[]
        def unprotect(self,data,entropy):
            self.reads+=1
            plain=bytearray(super().unprotect(data,entropy));self.buffers.append(plain);return plain
    from newsflow.distribution.windows_profile import private_directory
    native=Native();root=private_directory(app.state.config.data_dir/"private-collection")
    app.state.config=SimpleNamespace(**{**vars(app.state.config),"data_dir":root})
    registration=serpapi_key_registration.install(app,root,lambda:native)
    owner=serpapi_collection.install(app,root,lambda:native)
    secret='sk-synthetic-serpapi-collection-0123456789'
    entropy=bytearray(__import__('hashlib').sha256(SerpApiKeys.ENTROPY).digest())
    (root/SerpApiKeys.FILE).write_bytes(native.protect(secret.encode(),entropy))
    calls=[]
    def collect(self,keys,token,*,consent,adapter,policy,hours):
        if not consent: raise ValueError('consent required')
        assert keys.key()==secret and hours==24;calls.append((token,policy));return 1
    monkeypatch.setattr('newsflow.news.curator.Curator.serpapi',collect)
    launch=LaunchSession(18779);auth=LocalAccess(app,launch)
    client=TestClient(owner.wrap(registration.wrap(OperatingRequests(auth),auth),auth),
        base_url=launch.origin,client=('127.0.0.1',43211),follow_redirects=False)
    client.cookies.set(launch.cookie_name,launch.claim(launch.launch_url().split('#')[1]));client.get('/studio/news')
    return SimpleNamespace(app=app,client=client,native=native,calls=calls,origin=launch.origin)

@pytest.mark.parametrize('mode',['valid','csrf','origin','session','consent','count'])
def test_scope_auth_consent_and_buffers(boundary,mode):
    r=boundary;body={'csrf_token':r.client.cookies.get('newsflow_csrf'),'request_token':uuid4().hex,
        'consent':'true','collection_policy':'global_trends_v1','maximum_requests':'5'}
    headers={'Origin':r.origin}
    if mode=='csrf':body['csrf_token']='bad'
    if mode=='origin':headers['Origin']='https://outside.invalid'
    if mode=='session':r.client.cookies.clear()
    if mode=='consent':body['consent']='false'
    if mode=='count':body['maximum_requests']='100'
    response=r.client.post(serpapi_collection.PATH,data=body,headers=headers)
    assert response.status_code==(303 if mode=='valid' else 422 if mode in {'consent','count'} else 403)
    assert len(r.calls)==r.native.reads==(1 if mode=='valid' else 0)
    assert all(not any(b) for b in r.native.buffers)
    with pytest.raises(CredentialError):r.app.state.serpapi_keys.key()
    assert r.client.post('/news/curation/refresh',data=body,headers=headers).status_code in {401,403}
