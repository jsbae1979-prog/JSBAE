"""Provider verification uses synthetic ciphertext/native/HTTP, never real services."""
import hashlib
import io
import json
from types import SimpleNamespace
import urllib.error
from uuid import uuid4

import pytest
from starlette.testclient import TestClient
from sqlalchemy import select

from bat_distribution import provider_connection_check as boundary
from bat_distribution.operation import OperatingRequests
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from newsflow.intelligence.provider_connections import LIMIT,TIMEOUT,connections
from newsflow.intelligence.credentials import CredentialError
from newsflow.db.models import AppSetting,APIRequestReservation
from newsflow.intelligence.settings import _set
from test_library_visibility import character

KEY='sk-synthetic-provider-probe-0123456789'
RID='12345678-1234-1234-1234-123456789abc'

@pytest.fixture
def probe(app,monkeypatch):
    kinds={'claude':boundary.AnthropicKeyStore,'openai':boundary.AIKeyStore,
           'elevenlabs':boundary.ElevenLabsKeys,'higgsfield':boundary.VideoAIKeyStore}
    ciphertext={}
    for provider,kind in kinds.items():
        raw=('synthetic cipher '+provider).encode();ciphertext[provider]=raw
        (app.state.config.data_dir/kind.FILE).write_bytes(raw)
    class Native:
        calls=0
        def unprotect(self,payload,entropy):
            self.calls+=1
            assert bytes(payload) in ciphertext.values()
            assert bytes(entropy) in {hashlib.sha256(k.ENTROPY).digest() for k in kinds.values()}
            return bytearray(KEY.encode())
        def protect(self,*args):pytest.fail('No key mutation')
    native=Native();calls=[]
    def fake(request,timeout,limit):
        calls.append(request)
        assert request.get_method()=='GET' and request.data is None and timeout==15
        if request.full_url.startswith('https://api.anthropic.com'):
            return json.dumps({'id':request.full_url.rsplit('/',1)[-1],'type':'model'}).encode()
        if request.full_url.startswith('https://api.openai.com'):
            return json.dumps({'id':request.full_url.rsplit('/',1)[-1],'object':'model'}).encode()
        if request.full_url.endswith('/v1/user'):
            return json.dumps({'user_id':'synthetic-user','xi_api_key_preview':'PRIVATE_PREVIEW','first_name':'PRIVATE_NAME'}).encode()
        if request.full_url.endswith('/v1/models'):
            return json.dumps([{'model_id':'eleven_multilingual_v2'}]).encode()
        return json.dumps({'request_id':RID,'status':'completed','video':{'url':'https://example.invalid/never-download'}}).encode()
    checker=boundary.install(app,app.state.config.data_dir,lambda:native,transport=fake)
    monkeypatch.setattr(__import__('urllib.request',fromlist=['build_opener']),'build_opener',lambda *a,**k:pytest.fail('Real network forbidden'))
    session=LaunchSession(18779);authenticated=LocalAccess(app,session)
    client=TestClient(checker.wrap(OperatingRequests(authenticated),authenticated),base_url=session.origin,client=('127.0.0.1',10010))
    token=session.launch_url().split('#',1)[1]
    assert client.post('/__local/claim',headers={'Origin':session.origin,'X-NewsFlow-Bootstrap':token}).status_code==204
    client.get('/api/studio/modules/settings')
    def call(provider,scope,**extra):
        return client.post('/api/studio/providers/'+provider+'/check',data={
            'scope':scope,'consent':'true','csrf_token':client.cookies['newsflow_csrf'],**extra},headers={'Origin':session.origin})
    yield SimpleNamespace(app=app,checker=checker,client=client,call=call,native=native,calls=calls,session=session,kinds=kinds)
    client.close()


def terminal(probe):
    identifier=character(probe.app).split(':')[1]
    service=probe.app.state.character;job=service.read(identifier)
    job['scenes']=[{'position':1,'state':'failed','handle':{'request_id':RID,'status_url':'https://api.higgsfield.ai/requests/'+RID+'/status'}}]
    service.save(job)
    return identifier


@pytest.mark.parametrize('provider,scope,count',[('claude','text',1),('openai','text',1),('openai','image',1),('elevenlabs','voice',2),('higgsfield','video',1)])
def test_authentication_is_bounded_and_preserves_keys_budget_and_jobs(probe,provider,scope,count):
    terminal(probe)
    paths={kind.FILE:(probe.app.state.config.data_dir/kind.FILE).read_bytes() for kind in probe.kinds.values()}
    before=probe.app.state.character.listing()
    response=probe.call(provider,scope)
    assert response.status_code==200
    result=response.json();assert result['verified'] is True,result
    assert len(probe.calls)==count
    if provider in {'elevenlabs','higgsfield'}:assert result['modelVerified'] is False
    body=response.text
    assert all(secret not in body for secret in (KEY,'PRIVATE_NAME','PRIVATE_PREVIEW','synthetic-user',RID))
    assert probe.app.state.character.listing()==before
    assert all((probe.app.state.config.data_dir/name).read_bytes()==raw for name,raw in paths.items())
    with probe.app.state.sessions() as session:
        assert not list(session.scalars(select(APIRequestReservation)))
        stored=' '.join(session.scalars(select(AppSetting.value)))
        assert all(secret not in stored for secret in (KEY,'PRIVATE_NAME','PRIVATE_PREVIEW','synthetic-user'))
    # A new explicit click is allowed, but no call is automatically replayed.
    assert probe.call(provider,scope).json()['verified'] is True
    assert len(probe.calls)==count*2


def test_status_get_never_reads_plaintext_or_sends_network_and_key_replacement_invalidates(probe):
    probe.call('openai','image');before=len(probe.calls);native=probe.native.calls
    view=probe.client.get('/api/studio/modules/settings').json()
    row=next(s for s in view['services'] if s['id']=='openai')
    assert row['checks']['image']['verified'] is True
    assert len(probe.calls)==before and probe.native.calls==native
    (probe.app.state.config.data_dir/probe.kinds['openai'].FILE).write_bytes(b'changed synthetic ciphertext')
    assert probe.checker.status('openai','image')['verified'] is False


@pytest.mark.parametrize('status,code',[(401,'auth_error'),(403,'permission'),(404,'request_unavailable'),(429,'rate_limit'),(500,'unavailable'),(302,'unavailable')])
def test_http_failures_are_not_success_and_never_retried(probe,status,code):
    terminal(probe)
    def error(request,*args):
        probe.calls.append(request)
        raise urllib.error.HTTPError(request.full_url,status,KEY,{},io.BytesIO(KEY.encode()))
    probe.checker.network=error
    result=probe.call('higgsfield','video').json()
    assert result['code']==code and result['verified'] is False and len(probe.calls)==1
    assert KEY not in json.dumps(result)


def test_higgsfield_without_owned_terminal_request_does_not_send_or_decrypt(probe):
    result=probe.call('higgsfield','video').json()
    assert result['code']=='unsupported' and not probe.calls and not probe.native.calls


@pytest.mark.parametrize('provider,scope',[('claude','image'),('openai','video'),('elevenlabs','text'),('other','text')])
def test_invalid_scope_has_no_key_or_network_access(probe,provider,scope):
    assert probe.call(provider,scope).status_code in {403,422}
    assert not probe.calls and not probe.native.calls


def test_auth_origin_csrf_consent_and_native_scope_remain_required(probe):
    before=probe.native.calls
    assert probe.call('claude','text',consent='false').json()['code']=='consent_required'
    assert probe.call('claude','text',csrf_token='wrong').status_code==403
    url='/api/studio/providers/claude/check'
    assert probe.client.post(url,data={'consent':'true'},headers={'Origin':'https://outside.invalid'}).status_code==403
    with pytest.raises(CredentialError):probe.checker.stores['claude'].key()
    assert probe.native.calls==before and not probe.calls


def test_operating_transport_rejects_paid_requests_and_extra_headers(probe):
    plan=probe.checker.plan('openai','image')
    context={'owner':probe.checker,'provider':'openai','plan':plan,'sent':0}
    outer=boundary._REQUEST.set(context);inner=boundary._KEY_USE.set(context)
    import urllib.request
    try:
        for request in [urllib.request.Request('https://api.openai.com/v1/images/generations',method='POST',data=b'{}'),
                        urllib.request.Request(plan.urls[0],headers={'Accept':'application/json','Authorization':'Bearer '+KEY,'Host':'outside.invalid'})]:
            with pytest.raises(CredentialError):probe.checker._metadata_transport(request,TIMEOUT,LIMIT)
        assert not probe.calls
    finally:boundary._KEY_USE.reset(inner);boundary._REQUEST.reset(outer)


def test_public_models_response_alone_does_not_authenticate_elevenlabs(probe):
    def denied(request,*args):
        probe.calls.append(request)
        raise urllib.error.HTTPError(request.full_url,403,'denied',{},io.BytesIO())
    probe.checker.network=denied
    result=probe.call('elevenlabs','voice').json()
    assert result['verified'] is False and result['code']=='permission' and len(probe.calls)==1



def test_busy_acquisition_and_missing_key_do_not_decrypt_or_dispatch(probe):
    from newsflow.db.models import utcnow
    with probe.app.state.sessions.begin() as session:
        _set(session,'provider_probe:openai:image',json.dumps({'code':'checking','startedAt':utcnow().isoformat(),'token':'synthetic'}))
    assert probe.call('openai','image').json()['code']=='busy'
    assert not probe.calls and not probe.native.calls
    (probe.app.state.config.data_dir/probe.kinds['claude'].FILE).unlink()
    assert probe.call('claude','text').json()['code']=='key_missing'
    assert not probe.calls and not probe.native.calls


def test_changed_key_during_response_never_marks_new_key_verified(probe):
    fake=probe.checker.network
    def changed(request,*args):
        result=fake(request,*args)
        (probe.app.state.config.data_dir/probe.kinds['openai'].FILE).write_bytes(b'new synthetic ciphertext')
        return result
    probe.checker.network=changed
    result=probe.call('openai','image').json()
    assert result['code']=='stale' and not result['verified'] and len(probe.calls)==1


@pytest.mark.parametrize('raw',[b'not json',b'{"object":"model","id":"wrong","secret":"PRIVATE_PREVIEW"}',b'[]'])
def test_invalid_or_secret_bearing_response_cannot_become_success(probe,raw):
    probe.checker.network=lambda *args:raw
    result=probe.call('openai','image').json()
    assert not result['verified'] and result['code']=='invalid_response'
    assert 'PRIVATE_PREVIEW' not in json.dumps(result)


@pytest.mark.parametrize('raw',['[]','{"code":"success","checkedAt":"not-a-time"}'])
def test_corrupt_cached_result_is_bounded_and_new_explicit_check_repairs_it(probe,raw):
    with probe.app.state.sessions.begin() as session:_set(session,'provider_probe:openai:image',raw)
    assert probe.client.get('/api/studio/modules/settings').status_code==200
    assert probe.checker.status('openai','image')['verified'] is False
    assert probe.call('openai','image').json()['verified'] is True


def test_untrusted_higgsfield_status_url_is_not_a_probe_target(probe):
    identifier=terminal(probe)
    job=probe.app.state.character.read(identifier)
    job['scenes'][0]['handle']['status_url']='https://outside.invalid/requests/'+RID+'/status'
    probe.app.state.character.save(job)
    assert probe.call('higgsfield','video').json()['code']=='unsupported'
    assert not probe.calls and not probe.native.calls
