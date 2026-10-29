"""One approved trial; synthetic files/ciphers/ASGI only, no provider or app startup."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest
from starlette.testclient import TestClient

from bat_distribution import character_trial as m
from newsflow.character.schema import CharacterError
from newsflow.intelligence.credentials import CredentialError

ID = 'a'*32
OTHER = 'b'*32
TOPIC = '월요일 아침 9시 1분, 지각했는데 태평하게 출근'
REFERENCE = b'synthetic reference; never a real user asset'
KEY = 'synthetic-trial-key-0123456789'


class Cipher:
    calls = 0
    def unprotect(self, payload, entropy):
        self.calls += 1
        return bytearray(KEY.encode())


class Budget:
    def __init__(self):
        self.rows = {}
        self.calls = []
        self.block = False
    def reserve(self, **kwargs):
        self.calls.append(('reserve', kwargs['request_id']))
        if self.block:
            raise CharacterError('blocked')
        identifier = 'c'*32
        self.rows[identifier] = ('reserved', None)
        return SimpleNamespace(id=identifier)
    def finish(self, identifier, **kwargs):
        self.calls.append(('finish', identifier, kwargs['status']))
        self.rows[identifier] = (kwargs['status'], '.01' if kwargs['status']=='success' else None)


class Writer:
    def __init__(self, key):
        self.key = key


class Client:
    def __init__(self, service):
        self.service = service
        self.fail_submit = False
        self.calls = []
    def credential(self):
        return self.service.video_keys.key()
    def upload_reference(self, path):
        assert self.credential() == KEY
        self.calls.append('upload')
        return 'https://example.com/synthetic.png'
    def payload(self, prompt, seconds, url):
        return {'prompt':prompt,'duration':seconds,'sound':'off','multi_shots':False,'image_url':url}
    def estimate(self, payload):
        assert self.credential() == KEY
        self.calls.append('estimate')
        return '.10'
    def submit_scene(self, payload, identifier):
        assert self.credential() == KEY
        self.calls.append('submit')
        if self.fail_submit:
            raise ConnectionError('synthetic outcome unknown')
        return {'request_id':identifier}
    def check(self, handle):
        assert self.credential() == KEY
        self.calls.append('status')
        return SimpleNamespace(state='completed')
    def fetch(self, *args):
        self.calls.append('fetch')


class Service:
    def __init__(self, root):
        self.root = root/'character'
        self.root.mkdir()
        self.sessions = object()
        self.budget = Budget()
        self.keys = None
        self.video_keys = None
        self.writer = None
        self.client = Client(self)
        self.fail_write = False
        self.jobs = {}
        for identifier in (ID, OTHER):
            folder = self.root/identifier
            folder.mkdir()
            (folder/'reference.png').write_bytes(REFERENCE)
            self.jobs[identifier] = {
                'id':identifier,'topic':TOPIC,'reference_sha256':hashlib.sha256(REFERENCE).hexdigest(),
                'model':m.K3,'claude_model':m.CLAUDE,'duration':15,'episode_limit':'2.75',
                'studio_selection':{'video_model':m.K3,'script_model':m.CLAUDE,'duration':15,
                                    'clip_seconds':3,'sound':'off'},
                'state':'needs_script','script':None,'scenes':[]}
    def read(self, identifier):
        return deepcopy(self.jobs[identifier])
    def folder(self, identifier):
        return self.root/identifier
    def video_for(self, job):
        return self.client
    def write(self, identifier, **kwargs):
        reservation = self.budget.reserve(provider='claude_api', request_id='character:'+identifier,
            kind='script', model=m.CLAUDE, max_output_tokens=3000, key_store=self.keys)
        self.jobs[identifier]['state'] = 'writing'
        assert self.writer.key() == KEY
        if self.fail_write:
            self.budget.finish(reservation.id, status='unknown', usage=None)
            self.jobs[identifier]['state'] = 'script_failed'
            raise CharacterError('provider')
        self.budget.finish(reservation.id,status='success',usage={'prompt_tokens':10,'completion_tokens':10})
        self.jobs[identifier].update(state='script_review',script={'scenes':[{'seconds':3} for _ in range(5)]})
    def prepare(self, identifier, **kwargs):
        job = self.jobs[identifier]
        provider = self.video_for(job)
        url = provider.upload_reference(self.folder(identifier)/'reference.png')
        scenes = []
        for n in range(1):
            payload = provider.payload('synthetic combined story',15,url)
            quote = provider.estimate(payload)
            scenes.append({'state':'not_submitted','payload':payload,'quote_usd':quote,'idempotency_key':str(n)*32})
        job.update(state='quoted',scenes=scenes,quote_total_usd='.10')
    def submit(self, identifier, **kwargs):
        job = self.jobs[identifier]
        job['state'] = 'generating'
        for scene in job['scenes']:
            try:
                scene['handle'] = self.video_for(job).submit_scene(scene['payload'],scene['idempotency_key'])
                scene['state'] = 'submitted'
            except BaseException:
                scene['state'] = 'unknown'
                job['state'] = 'submission_unknown'
                raise
    def check(self, identifier, **kwargs):
        job = self.jobs[identifier]
        for scene in job['scenes']:
            provider = self.video_for(job)
            status = provider.check(scene['handle'])
            provider.fetch(status,'synthetic-only',None)
        job['state'] = 'clips_review'
    def render(self, identifier, **kwargs):
        self.jobs[identifier]['state'] = 'completed'


class Inner:
    """Records delegation and enforces synthetic auth/Origin/CSRF before service calls."""
    def __init__(self, service):
        self.service = service
        self.calls = 0
    async def __call__(self, scope, receive, send):
        self.calls += 1
        body = b''
        while True:
            message = await receive()
            body += message.get('body',b'')
            if not message.get('more_body'):
                break
        headers = dict(scope['headers'])
        form = parse_qs(body.decode())
        valid = (headers.get(b'x-test-auth')==b'yes' and
                 headers.get(b'origin')==b'http://127.0.0.1:18768' and
                 form.get('csrf_token')==['synthetic-csrf'])
        status = 403
        if valid:
            path = scope['path']
            if path == '/api/studio/characters/auto-story':
                identifier, action = form['job_id'][0], 'write'
            else:
                _, _, identifier, action = path.split('/')
            try:
                getattr(self.service,action)(identifier,consent=True,reviewed=True,script_reviewed=True)
                status = 200
            except (CharacterError, ConnectionError, CredentialError):
                status = 409
        await send({'type':'http.response.start','status':status,'headers':[]})
        await send({'type':'http.response.body','body':b'synthetic only'})


async def denied(scope, receive, send):
    await send({'type':'http.response.start','status':403,'headers':[]})
    await send({'type':'http.response.body','body':b'normal existing boundary'})


@pytest.fixture
def sample(tmp_path, monkeypatch):
    def private(path):
        assert path.is_relative_to(tmp_path)
        path.mkdir(exist_ok=True)
        return path
    monkeypatch.setattr(m,'_private',private)
    monkeypatch.setattr(m,'CharacterWriter',Writer)
    monkeypatch.setattr(m,'_prices',lambda sessions:{'input':'3','output':'15'})
    service = Service(tmp_path)
    original_budget = service.budget
    monkeypatch.setattr(m,'_reservation',lambda sessions, identifier:original_budget.rows[identifier])
    policy = {'schemaVersion':1,'id':'e'*32,'expires_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat(),
              'topic':TOPIC,'reference_sha256':hashlib.sha256(REFERENCE).hexdigest(),
              'script_model':m.CLAUDE,'video_model':m.K3,'duration':15,'clip_seconds':3,'scene_count':5,
              'sound':'off','script_limit_usd':'.25','video_limit_usd':'2.75','total_limit_usd':'3'}
    for filename in ('anthropic-api-key.dpapi','video-ai-key.dpapi'):
        (tmp_path/filename).write_bytes(b'synthetic ciphertext only')
    native = Cipher()
    trial = m.install(SimpleNamespace(state=SimpleNamespace(character=service)),tmp_path,policy,lambda:native)
    inner = Inner(service)
    client = TestClient(trial.wrap(denied,inner),base_url='http://127.0.0.1:18768')
    def post(action,identifier=ID,**kwargs):
        path = '/api/studio/characters/auto-story' if action=='auto-story' else f'/character/{identifier}/{action}'
        headers = {'x-test-auth':'yes','Origin':'http://127.0.0.1:18768'}
        headers.update(kwargs.pop('headers',{}))
        return client.post(path,headers=headers,data={'job_id':identifier,'csrf_token':'synthetic-csrf',**kwargs})
    return SimpleNamespace(trial=trial,service=service,client=client,post=post,policy=policy,native=native,
                           budget=original_budget,inner=inner,root=tmp_path)


def read(sample):
    return json.loads(sample.trial.path.read_bytes())


def test_one_story_one_fifteen_second_quote_and_submission_and_local_render(sample):
    for action in ('auto-story','prepare','submit','check','render'):
        assert sample.post(action).status_code == 200
    row = read(sample)
    assert row['job_id'] == ID
    assert row['calls'] == {'auto-story':1,'prepare':1,'submit':1,'check':1,'render':1}
    assert row['native_calls'] == {'upload':1,'estimate':1,'submit_scene':1,'status':1,'fetch':1}
    assert row['script']['reserved_usd']=='0.25' and row['video']['reserved_usd']=='0.10'
    assert len(sample.service.jobs[ID]['scenes'])==1
    assert sample.service.jobs[ID]['scenes'][0]['payload']['duration']==15
    assert sample.service.jobs[ID]['state']=='completed'
    assert [event[0] for event in sample.budget.calls]==['reserve','finish']
    assert m._CONTEXT.get() is None


@pytest.mark.parametrize('action',['auto-story','prepare','submit','check','render'])
def test_missing_auth_does_not_claim_or_decrypt(sample,action):
    assert sample.post(action,headers={'x-test-auth':'no'}).status_code==403
    assert not read(sample)['calls'] and sample.native.calls==0


@pytest.mark.parametrize('headers,data',[({'Origin':'https://example.com'},{}),({}, {'csrf_token':'wrong'})])
def test_original_inner_origin_and_csrf_policy_still_runs(sample,headers,data):
    assert sample.post('auto-story',headers=headers,**data).status_code==403
    assert not read(sample)['calls'] and sample.native.calls==0


@pytest.mark.parametrize('path',['/character/'+ID+'/retry-scene','/character/'+ID+'/retry-quote',
    '/character/'+ID+'/write','/api/studio/characters/auto-story/','/ai/generate','/publishing/execute'])
def test_no_other_live_or_retry_routes_added(sample,path):
    assert sample.client.post(path).status_code==403
    assert sample.inner.calls==0 and sample.native.calls==0


@pytest.mark.parametrize('key,value',[('topic','unapproved topic'),('model','other/model'),('duration',55),
                                     ('reference_sha256','0'*64),('episode_limit','3')])
def test_changed_job_scope_is_rejected_before_inner_call(sample,key,value):
    sample.service.jobs[ID][key]=value
    assert sample.post('auto-story').status_code==403
    assert sample.inner.calls==0 and sample.native.calls==0


@pytest.mark.parametrize('key,value',[('sound','on'),('clip_seconds',11),('script_model','claude-opus-4-6')])
def test_changed_settings_cannot_reuse_approval(sample,key,value):
    sample.service.jobs[ID]['studio_selection'][key]=value
    assert sample.post('auto-story').status_code==403


def test_expired_scope_never_reaches_inner_app(sample,monkeypatch):
    monkeypatch.setattr(m,'_now',lambda:datetime.fromisoformat(sample.policy['expires_at'])+timedelta(seconds=1))
    assert sample.post('auto-story').status_code==403
    assert sample.inner.calls==0 and sample.native.calls==0


def test_policy_change_cannot_reset_private_journal(sample):
    changed={**sample.policy,'topic':'different'}
    with pytest.raises(CharacterError):
        m.Trial(sample.service,sample.root,changed)
    assert not read(sample)['calls']


def test_existing_scope_binds_only_one_job(sample):
    assert sample.post('auto-story').status_code==200
    assert sample.post('auto-story',OTHER).status_code==409
    assert read(sample)['job_id']==ID and read(sample)['calls']['auto-story']==1


def test_restart_reuses_persistent_call_counts_without_reset(sample):
    assert sample.post('auto-story').status_code==200
    again=m.Trial(sample.service,sample.root,sample.policy)
    with again.journal() as row:
        assert row['job_id']==ID and row['calls']['auto-story']==1
    assert sample.post('auto-story').status_code==409


def test_unknown_story_preserves_original_ledger_and_stops_video(sample):
    sample.service.fail_write=True
    sample.budget.rows['old-unknown']=('unknown',None)
    assert sample.post('auto-story').status_code==409
    assert sample.budget.rows['old-unknown']==('unknown',None)
    assert read(sample)['script']['state']=='unknown_or_over_limit'
    sample.service.jobs[ID]['state']='needs_script'
    assert sample.post('auto-story').status_code==409
    sample.service.jobs[ID]['state']='script_review'
    assert sample.post('prepare').status_code==409
    assert sample.service.client.calls==[]


def test_unknown_submission_preserves_exposure_and_never_retries(sample):
    assert sample.post('auto-story').status_code==200
    assert sample.post('prepare').status_code==200
    sample.service.client.fail_submit=True
    assert sample.post('submit').status_code==409
    row=read(sample)
    assert row['video']['state']=='reserved' and row['video']['reserved_usd']=='0.10'
    assert row['native_calls']['submit_scene']==1
    sample.service.jobs[ID]['state']='quoted'
    assert sample.post('submit').status_code==409
    assert sample.service.client.calls.count('submit')==1


def test_quote_over_limit_is_not_submitted(sample):
    assert sample.post('auto-story').status_code==200
    assert sample.post('prepare').status_code==200
    job=sample.service.jobs[ID]
    for scene in job['scenes']:scene['quote_usd']='3.00'
    job['quote_total_usd']='3.00'
    assert sample.post('submit').status_code==409
    assert 'submit' not in sample.service.client.calls


def test_expensive_script_prices_rejected_before_existing_reserve(sample,monkeypatch):
    monkeypatch.setattr(m,'_prices',lambda sessions:{'input':'30','output':'150'})
    assert sample.post('auto-story').status_code==409
    assert not sample.budget.calls and sample.native.calls==0


def test_existing_authentication_or_unknown_gate_is_not_bypassed(sample):
    sample.budget.block=True
    sample.budget.rows['historic']=('unknown',None)
    assert sample.post('auto-story').status_code==409
    assert sample.budget.rows['historic']==('unknown',None) and sample.native.calls==0
    assert read(sample)['script']['state']=='reserved'


def test_keys_cannot_be_used_stored_or_deleted_outside_request_context(sample):
    for store in (sample.service.keys,sample.service.video_keys):
        with pytest.raises(CharacterError):store.key()
        with pytest.raises(CredentialError):store.save(KEY)
        with pytest.raises(CredentialError):store.clear()
        with pytest.raises(CredentialError):store._cipher.protect(bytearray(b'fake'),bytearray())
    assert sample.native.calls==0


def test_external_reference_change_is_rejected(sample):
    (sample.service.folder(ID)/'reference.png').write_bytes(b'changed synthetic asset')
    assert sample.post('auto-story').status_code==403 and sample.native.calls==0


def test_cipher_rejects_other_entropy_even_inside_valid_request(sample):
    original=sample.service.writer.key
    def wrong():
        return sample.service.keys._cipher.unprotect(bytearray(b'fake'),bytearray(b'wrong entropy'))
    sample.service.writer.key=wrong
    assert sample.post('auto-story').status_code==409
    assert sample.native.calls==0
    sample.service.writer.key=original


def test_cipher_cannot_read_higgsfield_key_during_claude_story(sample):
    sample.service.writer.key=sample.service.video_keys.key
    assert sample.post('auto-story').status_code==409 and sample.native.calls==0


def test_global_deny_cipher_is_not_replaced(sample,monkeypatch):
    from newsflow.oauth import vault,production_dpapi
    first,second=object(),object()
    monkeypatch.setattr(vault,'_DPAPI',first)
    monkeypatch.setattr(production_dpapi,'_DPAPI',second)
    assert sample.post('auto-story').status_code==200
    assert vault._DPAPI is first and production_dpapi._DPAPI is second



def test_expiry_after_dispatch_still_records_usage_but_blocks_more_execution(sample,monkeypatch):
    original=sample.service.writer.key
    def expiring():
        result=original()
        monkeypatch.setattr(m,'_now',lambda:datetime.fromisoformat(sample.policy['expires_at'])+timedelta(seconds=1))
        return result
    sample.service.writer.key=expiring
    assert sample.post('auto-story').status_code==409
    row=read(sample)
    assert row['script']['state']=='reported'
    assert sample.budget.rows['c'*32]==('success','.01')
    assert sample.post('prepare').status_code==403


def test_real_localaccess_and_original_csrf_protect_new_trial_route(sample):
    import ast,hashlib,hmac,re,secrets
    from fastapi import FastAPI,Form,Request
    from fastapi.responses import HTMLResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from newsflow.distribution.local_access import LaunchSession,LocalAccess

    app=FastAPI()
    @app.get('/api/studio/video-models')
    async def models():return {'synthetic':True}
    @app.post('/api/studio/characters/auto-story')
    def story(job_id: str=Form(...)):
        sample.service.write(job_id,consent=True)
        return {'saved':True}

    # Existing middleware source only, never create_app or the BAT entrypoint.
    path=Path(__file__).resolve().parents[3]/'src/newsflow/main.py'
    tree=ast.parse(path.read_text(encoding='utf8'))
    nodes=[node for node in ast.walk(tree)
           if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'valid','security'}]
    assert len(nodes)==2
    namespace=dict(app=app,secret=b'synthetic-trial-csrf',hashlib=hashlib,hmac=hmac,re=re,
                   secrets=secrets,Request=Request,HTMLResponse=HTMLResponse,StarletteHTTPException=StarletteHTTPException)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
    session=LaunchSession(18771)
    authenticated=LocalAccess(app,session)
    # The normal branch already includes LocalAccess, just as the operating hook.
    client=TestClient(sample.trial.wrap(authenticated,authenticated),base_url=session.origin,
                      client=('127.0.0.1',11001))
    target='/api/studio/characters/auto-story'
    data={'job_id':ID,'csrf_token':'bad'}
    assert client.post(target,data=data,headers={'Origin':session.origin}).status_code==403
    assert not read(sample)['calls'] and sample.native.calls==0
    token=session.launch_url().split('#',1)[1]
    assert client.post('/__local/claim',headers={'Origin':session.origin,'X-NewsFlow-Bootstrap':token}).status_code==204
    assert client.get('/api/studio/video-models').status_code==200
    csrf=client.cookies.get('newsflow_csrf')
    assert client.post(target,data=data,headers={'Origin':session.origin}).status_code==403
    data['csrf_token']=csrf
    assert client.post(target,data=data,headers={'Origin':'https://outside.invalid'}).status_code==403
    assert not read(sample)['calls'] and sample.native.calls==0
    assert client.post(target,data=data,headers={'Origin':session.origin}).status_code==200
    assert read(sample)['calls']=={'auto-story':1}
    assert m._CONTEXT.get() is None
