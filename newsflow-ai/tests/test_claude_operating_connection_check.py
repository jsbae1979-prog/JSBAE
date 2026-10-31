"""Operating metadata-only connection scope; synthetic keys, Fake native/HTTP only."""
from datetime import timedelta
import hashlib
import io
import json
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from bat_distribution import claude_connection_check as boundary
from bat_distribution.operation import OperatingRequests
from newsflow.db.models import APIRequestReservation, AppSetting, utcnow
from newsflow.distribution.local_access import LaunchSession, LocalAccess
from newsflow.intelligence.api_connection import ENDPOINT, MAX_RESPONSE_BYTES, TIMEOUT_SECONDS, read_connection_check
from newsflow.intelligence.api_settings import VERIFICATION_TTL, _recent, read_api_settings, save_api_settings
from newsflow.intelligence.credentials import AnthropicKeyStore, CredentialError
from newsflow.intelligence.provider import NoRedirect
from newsflow.intelligence.settings import _set

KEY='sk-synthetic-claude-metadata-only-0123456789'
MODEL='claude-sonnet-4-6'
CIPHER=b'synthetic-DPAPI-ciphertext-not-a-real-key'


def settings_values(app):
    with app.state.sessions() as session:
        return dict(session.execute(select(AppSetting.key,AppSetting.value)).all())


@pytest.fixture
def isolated(app,monkeypatch):
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a,**k:pytest.fail('Real network forbidden'))
    monkeypatch.setenv('NEWSFLOW_ANTHROPIC_API_KEY','sk-synthetic-environment-never-used-012345')
    path=app.state.config.data_dir/AnthropicKeyStore.FILE
    path.write_bytes(CIPHER)
    class Native:
        def __init__(self):self.buffers=[];self.calls=0
        def unprotect(self,payload,entropy):
            assert payload==bytearray(CIPHER)
            assert entropy==bytearray(hashlib.sha256(AnthropicKeyStore.ENTROPY).digest())
            self.calls+=1
            value=bytearray(KEY.encode());self.buffers.append(value);return value
        def protect(self,*a):pytest.fail('No key mutation authority')
    native=Native();requests=[]
    def fake(request,timeout,limit):
        requests.append((request,timeout,limit))
        return json.dumps({'type':'model','id':MODEL}).encode()
    checker=boundary.install(app,app.state.config.data_dir,lambda:native,transport=fake)
    # The normal/global key path must remain unusable, including in this callback.
    monkeypatch.setattr(app.state.api_keys['claude_api'],'key',lambda:pytest.fail('Global key access forbidden'))
    launch=LaunchSession(18779)
    authenticated=LocalAccess(app,launch)
    client=TestClient(checker.wrap(OperatingRequests(authenticated),authenticated),base_url=launch.origin,
        client=('127.0.0.1',11001))
    token=launch.launch_url().split('#',1)[1]
    assert client.post('/__local/claim',headers={'Origin':launch.origin,'X-NewsFlow-Bootstrap':token}).status_code==204
    client.get('/api/studio/modules/settings')
    yield SimpleNamespace(app=app,checker=checker,native=native,requests=requests,client=client,
        origin=launch.origin,csrf=client.cookies['newsflow_csrf'],keyfile=path,launch=launch)
    client.close()


def check(fixture,**fields):
    return fixture.client.post(boundary.PATH,data={'consent':'true','csrf_token':fixture.csrf,**fields},
        headers={'Origin':fixture.origin},follow_redirects=False)


def test_authenticated_metadata_get_refreshes_only_proof_and_preserves_secrets_and_budget(isolated):
    f=isolated
    before=settings_values(f.app)
    original=f.keyfile.read_bytes()
    response=check(f)
    assert response.status_code==303
    assert len(f.requests)==1
    request,timeout,limit=f.requests[0]
    assert request.full_url==ENDPOINT+MODEL and request.get_method()=='GET' and request.data is None
    assert timeout==TIMEOUT_SECONDS==15 and limit==MAX_RESPONSE_BYTES
    assert request.get_header('X-api-key')==KEY
    assert f.native.calls==2  # Initial read and unchanged-key verification.
    assert all(not any(value) for value in f.native.buffers)
    assert f.keyfile.read_bytes()==original
    settings=read_api_settings(f.app.state.sessions,'claude_api')
    assert settings.verified_model==MODEL and _recent(settings.authentication_verified_at,utcnow())
    assert not settings.search_verified_at and not settings.request_succeeded_at
    after=settings_values(f.app)
    allowed={'api_claude_api_'+suffix for suffix in ('authentication_verified_at','verified_model',
        'connection_check_id','connection_check_code','connection_checked_at','connection_check_started_at',
        'search_verified_at','request_succeeded_at')}
    assert {k:v for k,v in after.items() if k not in allowed}=={k:v for k,v in before.items() if k not in allowed}
    assert KEY not in response.text and KEY not in json.dumps(after)
    with f.app.state.sessions() as session:
        assert not list(session.scalars(select(APIRequestReservation)))
    # A later explicit request remains possible; there is no cumulative/one-use app limit.
    assert check(f).status_code==303 and len(f.requests)==2


def test_existing_local_auth_origin_csrf_consent_and_loopback_are_required(isolated):
    f=isolated;before=settings_values(f.app)
    authenticated=LocalAccess(f.app,f.launch)
    with TestClient(f.checker.wrap(OperatingRequests(authenticated),authenticated),
            base_url=f.origin,client=('127.0.0.1',11002)) as unauthenticated:
        assert unauthenticated.post(boundary.PATH,data={'consent':'true','csrf_token':f.csrf},
            headers={'Origin':f.origin}).status_code==403
    assert check(f,csrf_token='wrong').status_code==403
    assert f.client.post(boundary.PATH,data={'consent':'true','csrf_token':f.csrf},
        headers={'Origin':'https://outside.invalid'}).status_code==403
    assert check(f,consent='false').status_code==422
    remote=TestClient(f.checker.wrap(OperatingRequests(authenticated),authenticated),
        base_url=f.origin,client=('192.0.2.20',11001))
    assert remote.post(boundary.PATH,data={'consent':'true'}).status_code==403
    assert not f.requests and f.native.calls==0 and settings_values(f.app)==before


@pytest.mark.parametrize('method,path', [('GET',boundary.PATH),('DELETE',boundary.PATH),
    ('POST','/api-settings/openai/check'),('POST','/api-settings/claude_api/check-search'),
    ('POST','/api-settings/claude_api/key'),('POST','/api-settings/claude_api/check/extra'),
    ('POST','/api/studio/characters/auto-story'),('POST','/api-settings/claude_api'),
    ('POST','/v1/messages')])
def test_scope_does_not_expand_other_endpoints(isolated,method,path):
    f=isolated
    response=f.client.request(method,path,data={'consent':'true','csrf_token':f.csrf},
        headers={'Origin':f.origin},follow_redirects=False)
    assert response.status_code==403 and not f.requests and not f.native.calls


def request(url=ENDPOINT+MODEL,method='GET',data=None,extra=None):
    return urllib.request.Request(url,method=method,data=data,headers={
        'Accept':'application/json','x-api-key':KEY,'anthropic-version':'2023-06-01',**(extra or {})})


@pytest.mark.parametrize('kwargs', [{'method':'POST'},{'url':'https://api.anthropic.com/v1/messages'},
    {'url':'https://example.com/v1/models/'+MODEL},{'url':'http://api.anthropic.com/v1/models/'+MODEL},
    {'url':ENDPOINT+MODEL+'?redirect=https://example.com'},{'url':ENDPOINT+'../messages'},
    {'data':b'prompt=not-permitted'},{'extra':{'Host':'example.com'}},
    {'extra':{'Authorization':'Bearer synthetic-disallowed'}}])
def test_transport_rejects_paid_posts_arbitrary_urls_or_payloads_before_dispatch(isolated,kwargs):
    f=isolated;context={'owner':f.checker,'model':MODEL,'sent':False}
    outer=boundary._REQUEST.set(context);inner=boundary._KEY_USE.set(context)
    try:
        with pytest.raises(CredentialError):f.checker._metadata(request(**kwargs),TIMEOUT_SECONDS,MAX_RESPONSE_BYTES)
    finally:
        boundary._KEY_USE.reset(inner);boundary._REQUEST.reset(outer)
    assert not f.requests and not f.native.calls


def test_transport_and_key_scope_end_after_callback_and_never_repeat_same_dispatch(isolated):
    f=isolated
    assert f.checker.check(consent=True).code=='unavailable'
    with pytest.raises(CredentialError):f.checker.store.key()
    context={'owner':f.checker,'model':MODEL,'sent':False}
    outer=boundary._REQUEST.set(context);inner=boundary._KEY_USE.set(context)
    try:
        f.checker._metadata(request(),TIMEOUT_SECONDS,MAX_RESPONSE_BYTES)
        with pytest.raises(CredentialError):f.checker._metadata(request(),TIMEOUT_SECONDS,MAX_RESPONSE_BYTES)
    finally:
        boundary._KEY_USE.reset(inner);boundary._REQUEST.reset(outer)
    assert len(f.requests)==1 and not f.native.calls
    with pytest.raises(CredentialError):f.checker._metadata(request(),TIMEOUT_SECONDS,MAX_RESPONSE_BYTES)
    assert len(f.requests)==1


@pytest.mark.parametrize('status,code',[(401,'auth_error'),(403,'permission'),(404,'model_unavailable'),
    (429,'rate_limit'),(302,'unavailable'),(504,'timeout')])
def test_provider_errors_are_sanitized_and_never_retried(isolated,status,code):
    f=isolated;calls=[]
    def failed(request,timeout,limit):
        calls.append(request)
        raise urllib.error.HTTPError(ENDPOINT+KEY,status,KEY,{'secret':KEY},io.BytesIO(KEY.encode()))
    f.checker.transport=failed
    response=check(f)
    assert response.status_code==422 and len(calls)==1
    assert read_connection_check(f.app.state.sessions).code==code
    assert KEY not in response.text and KEY not in json.dumps(settings_values(f.app))
    assert f.keyfile.read_bytes()==CIPHER


def test_timeout_no_retry_and_redirect_policy_stays_denied(isolated):
    f=isolated;calls=[]
    def failed(*args):calls.append(True);raise TimeoutError(KEY)
    f.checker.transport=failed
    assert check(f).status_code==422 and len(calls)==1
    assert read_connection_check(f.app.state.sessions).code=='timeout'
    assert NoRedirect().redirect_request(request(),None,302,'redirect',{},'https://example.com') is None


def test_missing_stored_key_does_not_use_environment_or_change_verification_ttl(isolated):
    f=isolated;f.keyfile.unlink()  # This fixture's synthetic ciphertext only.
    assert check(f).status_code==422
    assert not f.requests and not f.native.calls
    assert read_connection_check(f.app.state.sessions).code=='key_error'
    assert VERIFICATION_TTL==timedelta(hours=24)
    now=utcnow()
    assert _recent((now-timedelta(hours=23)).isoformat(),now)
    assert not _recent((now-timedelta(hours=25)).isoformat(),now)


def test_model_change_invalidates_proof_without_generation(isolated):
    f=isolated
    assert check(f).status_code==303
    save_api_settings(f.app.state.sessions,'claude_api',model='claude-haiku-4-5',approved=False,
        search_enabled=False,search_approved=False,input_price_per_1m='1',output_price_per_1m='5',
        search_price_per_1k='0')
    settings=read_api_settings(f.app.state.sessions,'claude_api')
    assert not settings.authentication_verified_at and not settings.verified_model
    assert len(f.requests)==1
    with f.app.state.sessions() as session:
        assert not list(session.scalars(select(APIRequestReservation)))


def test_install_does_not_accept_another_profile_or_replace_existing_checker(isolated,tmp_path):
    f=isolated
    with pytest.raises(CredentialError):boundary.install(f.app,f.app.state.config.data_dir,lambda:f.native)
    other=tmp_path/'unrelated';other.mkdir()
    with pytest.raises(CredentialError):boundary.install(f.app,other,lambda:f.native)
    assert not f.requests and not f.native.calls
