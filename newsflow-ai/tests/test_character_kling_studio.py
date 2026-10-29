"""Focused new character workflow tests: only synthetic images, fake providers and local media."""
import io
import json
from types import SimpleNamespace
from uuid import uuid4
import pytest
from PIL import Image
from test_api_settings import sessions, store, configured
from newsflow.character.service import CharacterService
from newsflow.character.schema import CharacterError
from newsflow.character.kling import (K3,O3,MODELS,DEFAULTS,validate,check,snapshot,normalize_reference,
    generation_reference,KlingClient,dimensions)
from newsflow.character.studio_story import StudioStoryboard,prompts
from newsflow.character.claude import CharacterWriter
from newsflow.intelligence.api_settings import FakeAPIBudgetService
from newsflow.intelligence.provider import Options
from newsflow.video.ai.contracts import ProviderAmbiguousSubmit

def png(kind='PNG'):
    buf=io.BytesIO();Image.new('RGB',(256,256),'blue').save(buf,format=kind);return buf.getvalue()

def story(duration=55,sound='off'):
    return {'plan':{'situation':'여행','contrast':'친구와 만남','punchline':'집으로 돌아옴'},
            'title':'새로운 여행','hook_caption':'새로운 모험', 'end_caption':'다음 이야기에서 만나요',
            'scenes':[{'seconds':duration//5,'role':'setup' if i==0 else 'punchline' if i==4 else 'build',
                       'action':'The reference character walks along an original forest path.',
                       'caption':f'장면 {i+1}','sfx':'ambient wind','narration':'반가워요' if sound=='on' else ''}
                      for i in range(5)]}

class Writer:
    calls=0
    last_usage={'prompt_tokens':100,'completion_tokens':500}
    unknown=False
    def write_studio(self,payload,options,reference):
        self.calls+=1
        assert reference.startswith(b'\x89PNG') and options.model=='claude-sonnet-4-6'
        if self.unknown:
            self.last_usage=None
            raise ConnectionError('synthetic only')
        return StudioStoryboard.model_validate(story(payload['duration'],payload['sound']))

class FakeKling(KlingClient):
    calls=0
    uploads=0
    ambiguous=False
    def upload_reference(self,path):
        self.uploads+=1;return 'https://example.com/synthetic.png'
    def estimate(self,payload):return '0.10'
    def submit_scene(self,payload,key):
        self.calls+=1
        if self.ambiguous:raise ProviderAmbiguousSubmit()
        return {'request_id':key,'status_url':f'https://api.higgsfield.ai/requests/{key}/status'}

@pytest.fixture
def studio(tmp_path,sessions,store):
    configured(sessions)
    writer=Writer()
    s=CharacterService(tmp_path/'private',sessions,store,writer=writer,budget=FakeAPIBudgetService(sessions))
    clients={}
    def video(job):
        settings=check(job['studio_selection']);key=job['studio_selection']['fingerprint']
        if key not in clients:clients[key]=FakeKling(lambda:'synthetic-only',settings)
        return clients[key]
    s.video_for=video
    return SimpleNamespace(service=s,writer=writer,clients=clients)

def create(studio,**kw):
    return studio.service.create_studio('참조 캐릭터 여행','10','20',reference=png(),
                   settings={**DEFAULTS,**kw},request_id=uuid4().hex)[0]

@pytest.mark.parametrize('model',[K3,O3])
@pytest.mark.parametrize('sound',['on','off'])
@pytest.mark.parametrize('ratio',['9:16'])
def test_payload_uses_only_model_supported_fields(model,sound,ratio):
    settings={**DEFAULTS,'video_model':model,'sound':sound,'aspect_ratio':ratio}
    client=KlingClient(lambda:'synthetic',settings)
    p=client.payload('A character walks.',11,'https://example.com/reference.png')
    assert p['sound']==sound and p['duration']==11 and p['multi_shots'] is False
    assert not {'resolution','generate_audio','voice_id','style','quality'} & p.keys()
    if model==K3:
        assert set(p)=={'prompt','duration','sound','multi_shots','image_url'}
    else:
        assert p['mode']=='std' and p['aspect_ratio']==ratio and len(p['image_urls'])==1

@pytest.mark.parametrize('key,value',[('video_model','bytedance/seedance-2.0/reference-to-video'),
    ('video_model','kling-pro'),('style','injected'),('aspect_ratio','4:3'),('output_quality','4k'),
    ('sound','voice-id'),('duration',True),('duration',61),('script_model','not-supported')])
def test_unsupported_configuration_is_rejected(key,value):
    with pytest.raises(CharacterError):validate({**DEFAULTS,key:value})

def test_snapshot_mutation_is_not_silently_accepted():
    frozen=snapshot(DEFAULTS);frozen['sound']='on'
    with pytest.raises(CharacterError):check(frozen)

@pytest.mark.parametrize('model',[K3,O3])
def test_reference_original_is_preserved_and_ratio_is_prepared(tmp_path,model):
    original=normalize_reference(png('JPEG'));path=tmp_path/'reference.png';path.write_bytes(original)
    settings={**DEFAULTS,'video_model':model,'aspect_ratio':'9:16'}
    derived=generation_reference(tmp_path,settings)
    assert path.read_bytes()==original
    with Image.open(derived) as image:
        assert image.size==((720,1280) if model==K3 else (256,256))

@pytest.mark.parametrize('duration',[30,45,55,60])
def test_topic_generates_one_story_with_selected_reference_and_duration(studio,duration):
    i=create(studio,duration=duration,clip_seconds=duration//5)
    studio.service.write(i,consent=True)
    job=studio.service.read(i)
    assert job['state']=='script_review' and sum(s['seconds'] for s in job['script']['scenes'])==duration
    assert studio.writer.calls==1 and 'capybara' not in json.dumps(job['prompts'])
    assert job['made_for_kids'] is None
    with pytest.raises(CharacterError):studio.service.write(i,consent=True)
    assert studio.writer.calls==1

def test_duplicate_identity_never_replays_story_or_overwrites_different_input(studio):
    s=studio.service;rid=uuid4().hex
    kwargs={'reference':png(),'settings':DEFAULTS,'request_id':rid}
    i,new=s.create_studio('여행','10','20',**kwargs);assert new
    s.write(i,consent=True)
    same,new=s.create_studio('여행','10','20',**kwargs)
    assert same==i and not new and studio.writer.calls==1
    with pytest.raises(CharacterError):s.create_studio('다른 주제','10','20',**kwargs)

def test_unknown_story_stays_unknown_without_replay(studio):
    i=create(studio);studio.writer.unknown=True
    with pytest.raises(CharacterError):studio.service.write(i,consent=True)
    with pytest.raises(CharacterError):studio.service.write(i,consent=True)
    assert studio.writer.calls==1 and studio.service.read(i)['response_received'] is False

def test_video_settings_reach_quote_then_freeze_with_approval_and_unknown_protection(studio):
    s=studio.service;i=create(studio);s.write(i,consent=True)
    chosen={**DEFAULTS,'video_model':O3,'sound':'on','style':DEFAULTS['style'],'aspect_ratio':'9:16'}
    s.update_studio_settings(i,chosen,'10','20')
    assert 'soft 3D animated film style' in s.read(i)['prompts'][0]['prompt']
    with pytest.raises(CharacterError):s.prepare(i,consent=True)
    s.prepare(i,consent=True,script_reviewed=True)
    job=s.read(i)
    assert job['quote_total_usd']=='0.50' and all(x['payload']['mode']=='std' and x['payload']['sound']=='on' for x in job['scenes'])
    with pytest.raises(CharacterError):s.update_studio_settings(i,DEFAULTS,'10','20')
    with pytest.raises(CharacterError):s.submit(i,consent=True,quote_hash='altered')
    provider=s.video_for(job);provider.ambiguous=True
    with pytest.raises(CharacterError):s.submit(i,consent=True,quote_hash=job['quote_hash'])
    assert s.read(i)['state']=='submission_unknown' and provider.calls==1
    with pytest.raises(CharacterError):s.submit(i,consent=True,quote_hash=job['quote_hash'])
    assert provider.calls==1

def test_topic_and_generic_schema_are_sent_once_without_reference_or_legacy_mascot(monkeypatch):
    writer=CharacterWriter(lambda:'synthetic')
    seen=[]
    def reply(body,options):
        seen.append(body)
        return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(story())}]}
    monkeypatch.setattr(writer,'_post',reply)
    payload={'duration':15,'topic':'여행','sound':'off','clip_seconds':3,'scene_count':5}
    result=writer.write_studio(payload,Options(model='claude-sonnet-4-6'),png())
    assert len(result.scenes)==5 and len(seen)==1
    assert json.loads(seen[0]['messages'][0]['content'])==payload
    assert not {'base64','media_type','image','source'} & set(seen[0]['messages'][0])
    assert 'fixed original mascot' not in seen[0]['system']
    assert 'output_config' in seen[0]

def test_route_reuses_durable_id_without_auto_replay_and_requires_explicit_consent(studio):
    # Isolated route-only FastAPI client. Full production middleware tested separately.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from newsflow.gui.character_routes import router
    app=FastAPI();app.state.character=studio.service;app.include_router(router)
    client=TestClient(app)
    data={'topic':'참조 캐릭터 여행','studio_settings':json.dumps(DEFAULTS),'request_id':uuid4().hex,'episode_limit':'10','day_limit':'20'}
    local=client.post('/character',data=data,files={'reference':('ref.png',png(),'image/png')})
    assert local.status_code==200 and studio.writer.calls==0
    job=local.json()['id']
    bad=client.post('/api/studio/characters/auto-story',data={'job_id':job,'consent':'false'})
    assert bad.status_code==409 and studio.writer.calls==0
    response=client.post('/api/studio/characters/auto-story',data={'job_id':job,'consent':'true'})
    assert response.status_code==200 and studio.writer.calls==1
    repeated=client.post('/api/studio/characters/auto-story',data={'job_id':job,'consent':'true'})
    assert repeated.json()['id']==response.json()['id']
    assert studio.writer.calls==1

def test_read_view_never_exposes_reference_bytes_or_provider_receipts(studio):
    from newsflow.studio.read_models import character_rows
    i=create(studio);studio.service.write(i,consent=True)
    rows=character_rows(SimpleNamespace(character=studio.service))
    assert rows[0]['studio_selection']['video_model']==K3
    assert not {'reference_sha256','studio_body_hash','studio_request_id','reference','character'} & rows[0].keys()


def test_actual_existing_security_middleware_still_guards_both_calls(studio):
    import ast,hashlib,hmac,re,secrets
    from pathlib import Path
    from fastapi import FastAPI,Request
    from fastapi.responses import HTMLResponse
    from fastapi.testclient import TestClient
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from newsflow.gui.character_routes import router
    source=Path(__file__).parents[1]/'src/newsflow/main.py'
    tree=ast.parse(source.read_text(encoding='utf8'))
    nodes=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in {'valid','security'}]
    assert len(nodes)==2
    app=FastAPI();app.state.character=studio.service;app.include_router(router)
    scope=dict(app=app,secret=b'synthetic-csrf-only',hashlib=hashlib,hmac=hmac,re=re,secrets=secrets,
               Request=Request,HTMLResponse=HTMLResponse,StarletteHTTPException=StarletteHTTPException)
    # Execute exactly the two production functions, retaining the original form limits/origin/cookie checks.
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),scope)
    client=TestClient(app);client.get('/openapi.json')
    csrf=client.cookies.get('newsflow_csrf')
    fields={'topic':'검증 여행','studio_settings':json.dumps(DEFAULTS),'request_id':uuid4().hex,
            'episode_limit':'10','day_limit':'20','csrf_token':csrf}
    assert client.post('/character',data={**fields,'csrf_token':'bad'},files={'reference':('ref.png',png(),'image/png')}).status_code==403
    assert client.post('/character',data=fields,files={'reference':('ref.png',png(),'image/png')},headers={'Origin':'https://outside.invalid'}).status_code==403
    local=client.post('/character',data=fields,files={'reference':('ref.png',png(),'image/png')})
    assert local.status_code==200 and studio.writer.calls==0
    identifier=local.json()['id']
    paid={'job_id':identifier,'consent':'true','csrf_token':csrf}
    assert client.post('/api/studio/characters/auto-story',data={**paid,'csrf_token':'bad'}).status_code==403
    assert client.post('/api/studio/characters/auto-story',data=paid,headers={'Origin':'https://outside.invalid'}).status_code==403
    assert studio.writer.calls==0
    assert client.post('/api/studio/characters/auto-story',data=paid).status_code==200
    assert studio.writer.calls==1
    assert client.post('/api/studio/characters/auto-story',data=paid).status_code==200
    assert studio.writer.calls==1


def test_estimated_budget_overage_blocks_before_reference_upload(studio):
    i=create(studio);s=studio.service;s.write(i,consent=True)
    s.update_studio_settings(i,DEFAULTS,'1','20')
    with pytest.raises(CharacterError):s.prepare(i,consent=True,script_reviewed=True)
    assert not studio.clients and s.read(i)['state']=='script_review'

def test_reference_mutation_blocks_before_claude_request(studio):
    i=create(studio);path=studio.service.folder(i)/'reference.png'
    with Image.open(io.BytesIO(png())) as im:
        im.paste('red',(0,0,50,50));im.save(path,format='PNG')
    with pytest.raises(CharacterError):studio.service.write(i,consent=True)
    assert studio.writer.calls==0

def test_unsupported_native_quality_reports_field_without_creating_a_job(studio):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from newsflow.gui.character_routes import router
    app=FastAPI();app.state.character=studio.service;app.include_router(router)
    client=TestClient(app)
    data={'topic':'여행','studio_settings':json.dumps({**DEFAULTS,'native_resolution':'1080p'}),
          'request_id':uuid4().hex,'episode_limit':'10','day_limit':'20'}
    response=client.post('/character',data=data,files={'reference':('ref.png',png(),'image/png')})
    assert response.status_code==422 and 'native_resolution' in response.json()['fields']
    assert not studio.service.listing() and studio.writer.calls==0


def test_style_warning_is_frozen_for_the_human_review_checklist(studio,monkeypatch):
    import newsflow.video_models.catalog as catalog_module
    original=catalog_module.styles()
    original[DEFAULTS['style']]['warn']='합성 검증용 AI 생성 표시 확인'
    monkeypatch.setattr(catalog_module,'styles',lambda:original)
    i=create(studio);studio.service.write(i,consent=True)
    assert studio.service.read(i)['character']['style_warn']=='합성 검증용 AI 생성 표시 확인'


def test_catalog_deactivation_preserves_existing_job_read_but_blocks_execution(studio,monkeypatch):
    from copy import deepcopy
    from newsflow.video_models.catalog import CATALOG
    s=studio.service;i=create(studio);s.write(i,consent=True)
    original=CATALOG.refresh()
    changed=deepcopy(original)
    changed['models'][0]['enabled']=False
    monkeypatch.setattr(CATALOG,'_data',changed)
    assert s.read(i)['script']['title']=='새로운 여행'
    with pytest.raises(CharacterError):KlingClient(lambda:'synthetic',check(s.read(i)['studio_selection']))


def test_studio_text_transport_never_reads_or_serializes_large_reference(monkeypatch):
    from newsflow.intelligence.api_providers import MAX_REQUEST_BYTES

    class UnreadReference:
        declared_size = 4_902_024

        def __len__(self):
            raise AssertionError('Claude must not inspect the reference')

        def __bytes__(self):
            raise AssertionError('Claude must not convert the reference')

        def __repr__(self):
            raise AssertionError('Claude must not serialize the reference')

        def read(self, *args):
            raise AssertionError('Claude must not read the reference')

    writer = CharacterWriter(lambda: 'synthetic-only')
    requests = []

    def capture(request, timeout, limit):
        requests.append(request.data)
        return json.dumps({'stop_reason': 'end_turn', 'content': [
            {'type': 'text', 'text': json.dumps(story())}]}).encode('utf-8')

    monkeypatch.setattr(writer, '_open', capture)
    payload = {'duration': 15, 'topic': '친구와 숲을 여행하는 이야기', 'sound': 'off',
               'clip_seconds': 3, 'scene_count': 5}
    writer.write_studio(payload, Options(model='claude-sonnet-4-6', max_tokens=3000), UnreadReference())
    assert len(requests) == 1 and len(requests[0]) <= MAX_REQUEST_BYTES == 64000
    assert json.loads(json.loads(requests[0])['messages'][0]['content']) == payload
    assert all(field not in requests[0] for field in
               (b'"image"', b'"source"', b'"base64"', b'"media_type"'))


def test_studio_text_story_leaves_stored_png_unchanged(tmp_path, monkeypatch):
    import hashlib
    reference = png()
    path = tmp_path / 'reference.png'
    path.write_bytes(reference)
    original_hash = hashlib.sha256(reference).hexdigest()
    writer = CharacterWriter(lambda: 'synthetic-only')
    bodies = []

    def capture(body, options):
        bodies.append(body)
        return {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps(story())}]}

    monkeypatch.setattr(writer, '_post', capture)
    writer.write_studio({'duration': 55, 'topic': '여행', 'sound': 'off'},
                        Options(model='claude-sonnet-4-6'), reference)
    assert isinstance(bodies[0]['messages'][0]['content'], str)
    assert hashlib.sha256(reference).hexdigest() == original_hash
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash


def test_studio_text_transport_timeout_does_not_retry_or_reuse_usage(monkeypatch):
    from newsflow.intelligence.provider import ProviderTimeoutError
    writer = CharacterWriter(lambda: 'synthetic-only')
    writer.last_usage = {'prompt_tokens': 100, 'completion_tokens': 500}
    requests = []

    def timeout(request, timeout, limit):
        requests.append(request.data)
        raise TimeoutError

    monkeypatch.setattr(writer, '_open', timeout)
    options = Options(model='claude-sonnet-4-6')
    with pytest.raises(ProviderTimeoutError):
        writer.write_studio({'duration': 55, 'topic': '여행', 'sound': 'off'}, options)
    assert len(requests) == 1 and writer.last_retried is False and writer.last_usage is None


def test_studio_wire_schema_moves_only_unsupported_minitems_and_keeps_local_validation(monkeypatch):
    from newsflow.intelligence.api_providers import _output_schema
    from newsflow.character.claude import _studio_wire_schema
    from pydantic import ValidationError
    writer = CharacterWriter(lambda: 'synthetic-only')
    bodies = []

    def reply(body, options):
        bodies.append(body)
        return {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps(story())}]}

    monkeypatch.setattr(writer, '_post', reply)
    writer.write_studio({'topic': '여행', 'duration': 55, 'clip_seconds': 11,
                         'scene_count': 5, 'sound': 'off'}, Options(model='claude-sonnet-4-6'))
    wire = bodies[0]['output_config']['format']['schema']
    assert 'minItems' not in wire['properties']['scenes']
    assert '"minItems": 3' in wire['properties']['scenes']['description']
    assert _output_schema(StudioStoryboard)['properties']['scenes']['minItems'] == 3
    assert StudioStoryboard.model_json_schema()['properties']['scenes']['minItems'] == 3
    nested = {'anyOf': [{'minItems': 0}, {'minItems': 1}, {'items': {'minItems': 4}}]}
    transformed = _studio_wire_schema(nested)
    assert transformed['anyOf'][:2] == nested['anyOf'][:2]
    assert 'minItems' not in transformed['anyOf'][2]['items']
    assert nested['anyOf'][2]['items']['minItems'] == 4
    invalid = story()
    invalid['scenes'] = invalid['scenes'][:2]
    with pytest.raises(ValidationError):
        StudioStoryboard.model_validate(invalid)
    assert len(bodies) == 1


def test_studio_http_rejection_retains_only_existing_safe_diagnostics_once(monkeypatch):
    import urllib.error
    from newsflow.intelligence.provider import ProviderHTTPResponseError
    records = []
    recorder = SimpleNamespace(save=lambda **details: records.append(details) or 'a' * 32)
    writer = CharacterWriter(lambda: 'synthetic-only', error_recorder=recorder)
    requests = []

    def rejected(request, timeout, limit):
        requests.append(request)
        raw = json.dumps({'error': {'type': 'invalid_request_error', 'message':
                         'Invalid JSON schema in output_config.schema; synthetic-only private-prose'}}).encode()
        raise urllib.error.HTTPError(request.full_url, 400, 'synthetic', {}, io.BytesIO(raw))

    monkeypatch.setattr(writer, '_open', rejected)
    with pytest.raises(ProviderHTTPResponseError):
        writer.write_studio({'topic': '여행', 'duration': 15, 'clip_seconds': 3,
                             'scene_count': 5, 'sound': 'off'}, Options(model='claude-sonnet-4-6'))
    assert writer.last_failure == {'http_status': 400, 'error_type': 'invalid_request_error',
        'request_issue': 'schema_invalid', 'request_fields': ['output_config', 'schema'], 'diagnostic_ref': 'a' * 32}
    assert 'synthetic-only' not in json.dumps(writer.last_failure)
    assert 'private-prose' not in json.dumps(writer.last_failure)
    assert len(requests) == len(records) == 1 and writer.last_usage is None and writer.last_retried is False


def test_future_character_failure_saves_safe_http_details_and_keeps_unknown_stopped(studio, monkeypatch):
    from newsflow.intelligence.provider import ProviderHTTPResponseError
    service = studio.service
    writer = CharacterWriter(lambda: 'synthetic-only')
    requests = []

    def rejected(body, options):
        requests.append(body)
        error = ProviderHTTPResponseError(400, 'invalid_request_error', 'schema_invalid', ['schema'])
        error.details['raw_body'] = 'synthetic-private-response'
        raise error

    monkeypatch.setattr(writer, '_post', rejected)
    service.writer = writer
    identifier = create(studio)
    with pytest.raises(CharacterError):
        service.write(identifier, consent=True)
    job = service.read(identifier)
    assert job['script_failure'] == {'http_status': 400, 'error_type': 'invalid_request_error',
                                    'request_issue': 'schema_invalid', 'request_fields': ['schema']}
    assert job['state'] == 'script_failed' and job['response_received'] is False
    assert 'synthetic-private-response' not in json.dumps(job)
    with pytest.raises(CharacterError):
        service.write(identifier, consent=True)
    assert len(requests) == 1
