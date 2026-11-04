"""No Google, real tokens, browser process or production profile in these tests."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient
from bat_distribution import youtube_access as access
from bat_distribution.operation import OperatingRequests
from newsflow.intelligence.credentials import FakeCipher
from newsflow.oauth.activation import youtube_operation
from newsflow.oauth.contracts import OAuthBlocked
from newsflow.oauth.production import ProtocolError, BrowserLaunchError
from test_youtube_connection import CLIENT

@pytest.fixture
def configured(tmp_path):
    calls=[]
    def native():
        calls.append('cipher')
        return FakeCipher()
    service=SimpleNamespace()
    app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path),youtube=service))
    owner=access.install(app,tmp_path,native)
    assert calls==[]
    return owner,service,calls

async def inner(scope,receive,send):
    await send({'type':'http.response.start','status':204,'headers':[]})
    await send({'type':'http.response.body','body':b''})

@pytest.mark.parametrize('path',['/youtube/client','/youtube/connect','/youtube/connect/1/cancel','/youtube/connect/2/reopen'])
def test_exact_connections_reach_inner_auth(configured,path):
    owner,_,_=configured
    async def authenticated(scope,receive,send):
        assert access._REQUEST.get() is owner
        await send({'type':'http.response.start','status':401,'headers':[]})
        await send({'type':'http.response.body','body':b'Authentication required'})
    response=TestClient(owner.wrap(OperatingRequests(inner),authenticated)).post(path)
    assert response.status_code==401
    assert access._REQUEST.get() is None

@pytest.mark.parametrize('method,path',[
 ('GET','/youtube/connect'),('POST','/youtube/connect/0/cancel'),
 ('POST','/youtube/connect/1/link'),('POST','/youtube/connect/1/reopen/extra'),
 ('POST','/youtube/publish/1'),('POST','/youtube/draft'),('GET','/oauth/callback'),
 ('POST','/collection'),('POST','/api/feed-batches/1/step')])
def test_no_other_authority(configured,method,path):
    owner,_,calls=configured
    assert TestClient(owner.wrap(OperatingRequests(inner),inner)).request(method,path).status_code==403
    assert calls==[]

def test_client_is_scoped_and_does_not_read_environment(configured,monkeypatch):
    owner,service,calls=configured
    monkeypatch.setenv('NEWSFLOW_UNUSED_YOUTUBE_CLIENT',CLIENT)
    with pytest.raises(OAuthBlocked):service.client_store.key()
    with pytest.raises(OAuthBlocked):service.client_store.save(CLIENT)
    with pytest.raises(OAuthBlocked):service.client_store.clear()
    async def authenticated(scope,receive,send):
        service.client_store.save(CLIENT)
        assert service.client_store.key()==CLIENT
        await inner(scope,receive,send)
    assert TestClient(owner.wrap(OperatingRequests(inner),authenticated)).post('/youtube/client').status_code==204
    assert calls==['cipher','cipher']
    with pytest.raises(OAuthBlocked):service.client_store.key()

def test_profile_binding(configured,tmp_path):
    owner,service,_=configured
    app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path),youtube=service))
    other=tmp_path/'other';other.mkdir()
    with pytest.raises(OAuthBlocked):access.install(app,other,owner.native_factory)

def test_vault_requires_service_context(configured,monkeypatch):
    owner,service,calls=configured
    with pytest.raises(OAuthBlocked):service.vault._backend()
    seen=[]
    def kernel(root,cipher,sid,**kwargs):
        seen.append((root,sid,kwargs));return object()
    monkeypatch.setattr(access,'_ProductionDPAPIFileKernel',kernel)
    monkeypatch.setattr(access,'_owner_sid',lambda:'synthetic-owner')
    with youtube_operation(consent=True):service.vault._backend()
    assert seen==[(owner.profile/'youtube-oauth','synthetic-owner',{'native':True,'synthetic_only':False})]
    with pytest.raises(OAuthBlocked):service.vault._backend()
    assert calls==['cipher']

def test_chrome_requires_context_and_official_endpoint(monkeypatch):
    browser=access.ChromeOAuthBrowser()
    with pytest.raises(OAuthBlocked):browser.open(SecretStr('https://accounts.google.com/o/oauth2/v2/auth?state=fixture'))
    with youtube_operation(consent=True):
        for url in ['http://accounts.google.com/o/oauth2/v2/auth','https://accounts.google.com.evil/o/oauth2/v2/auth','https://accounts.google.com/o/oauth2/v2/auth#fragment']:
            with pytest.raises(ProtocolError):browser.open(SecretStr(url))

def test_chrome_no_shell_output_or_fallback(monkeypatch,capfd):
    calls=[]
    monkeypatch.setattr(access,'unlinked',lambda p:p)
    monkeypatch.setattr(Path,'is_file',lambda p:True)
    monkeypatch.setattr(access.subprocess,'Popen',lambda args,**kwargs:(calls.append((args,kwargs)) or SimpleNamespace(poll=lambda:None)))
    value='https://accounts.google.com/o/oauth2/v2/auth?state=fixture-do-not-print'
    with youtube_operation(consent=True):access.ChromeOAuthBrowser().open(SecretStr(value))
    assert len(calls)==1 and calls[0][0][1:]==['--new-window',value]
    assert calls[0][1]['shell'] is False
    assert calls[0][1]['stdout']==access.subprocess.DEVNULL
    assert 'fixture-do-not-print' not in str(capfd.readouterr())


def test_connection_worker_completes_with_fake_provider_only(tmp_path,monkeypatch):
    from test_youtube_connection import (FakeTokens,FakeIdentity,FakeBrowser,FakeListener,FakeVault,CHANNEL)
    from newsflow.oauth.youtube import YouTubeConnectionService
    from newsflow.db.models import Base
    from newsflow.db.session import make_engine,session_factory
    engine=make_engine(tmp_path/'fake.db');Base.metadata.create_all(engine)
    service=YouTubeConnectionService(session_factory(engine),tmp_path,token_transport=FakeTokens(),
        identity_transport=FakeIdentity(),listener_factory=FakeListener)
    app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path),youtube=service))
    owner=access.install(app,tmp_path,FakeCipher)
    # Retain the operating vault activation guard, substitute only its file kernel in this test.
    vault=FakeVault()
    monkeypatch.setattr(access,'_owner_sid',lambda:'synthetic-owner')
    monkeypatch.setattr(access,'_ProductionDPAPIFileKernel',lambda *args,**kwargs:vault)
    service.browser=FakeBrowser()
    async def authenticated(scope,receive,send):
        if scope['path']=='/youtube/client':service.save_client(CLIENT)
        else:service.begin(consent=True)
        await inner(scope,receive,send)
    try:
        client=TestClient(owner.wrap(OperatingRequests(inner),authenticated))
        assert client.post('/youtube/client').status_code==204
        assert client.post('/youtube/connect').status_code==204
        for worker in service._workers.values():worker.join(5)
        assert service.accounts()[0]['ready'] and service.accounts()[0]['channel_id']==CHANNEL
        assert service.tokens.calls==[('token','authorization_code')] and service.identity.calls==1
        assert len(vault.data)==1 and access._REQUEST.get() is None
        assert client.post('/youtube/publish/1').status_code==403
    finally:
        service.close();engine.dispose()
