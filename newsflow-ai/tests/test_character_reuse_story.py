"""Saved-story copies are local, idempotent and separate from unknown provider jobs."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_api_settings import sessions,store
from test_character_kling_studio import studio
from test_character_single_video import seeded
from test_character_visibility import files

from newsflow.character.kling import check
from newsflow.character.schema import CharacterError
from newsflow.character.service import day_exposure
from newsflow.studio.read_models import character_rows
from newsflow.video.ai.contracts import ProviderInputError


def source_job(studio):
    s=studio.service
    identifier,provider,estimates=seeded(studio)
    job=s.read(identifier)
    job.update(state='submission_unknown',quote_total_usd='1.260',
               quote_approvals=[{'day':'2026-10-29','usd':'1.260','scope':'initial'}])
    job['scenes']=[{'position':1,'state':'unknown','attempt':1,'quote_usd':'1.260',
                   'payload':{'duration':15,'sound':'off','prompt':'original unknown provider payload'}}]
    s.save(job)
    settings=check(job['studio_selection'])
    return identifier,{**settings,'sound':'on'},provider


def test_copy_reuses_saved_korean_story_and_png_without_claude_or_original_changes(studio):
    s=studio.service
    source,settings,provider=source_job(studio)
    original=s.read(source)
    before=files(s,source)
    identifier,created=s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,consent=True)
    copied=s.read(identifier)
    assert created and identifier!=source and copied['state']=='script_review'
    assert s.read(source)==original and files(s,source)==before
    assert copied['reference_sha256']==original['reference_sha256']
    assert (s.folder(identifier)/'reference.png').read_bytes()==(s.folder(source)/'reference.png').read_bytes()
    assert copied['studio_selection']['sound']=='on' and copied['scenes']==[]
    assert copied['script']['title']==original['script']['title']
    for old,new in zip(original['script']['scenes'],copied['script']['scenes']):
        assert new['narration']==old.get('narration','')==''
        assert {k:v for k,v in new.items() if k!='narration'}=={k:v for k,v in old.items() if k!='narration'}
    assert copied['reused_story']['source_job_id']==source
    assert copied['reused_story']['dialogue_source']=='story_inferred_audio'
    assert all('Scene context (unspoken):' in row['prompt'] for row in copied['prompts'])
    assert all('Infer natural Korean in-scene sound and character dialogue as the story needs' in row['prompt'] for row in copied['prompts'])
    assert copied['reused_story']['source_plan_hash']==original['plan_hash']
    assert studio.writer.calls==0 and provider.calls==0 and provider.uploads==0
    assert sum((day_exposure(row,'2026-10-29') for row in s.listing()),Decimal(0))==Decimal('1.260')
    view={row['id']:row for row in character_rows(SimpleNamespace(character=s))}
    assert view[source]['state']=='submission_unknown' and view[identifier]['reused_story']['source_job_id']==source


def test_same_request_returns_existing_copy_and_changed_body_is_rejected(studio):
    s=studio.service
    source,settings,provider=source_job(studio)
    request_id=uuid4().hex
    identifier,created=s.reuse_story(source,settings,'2.50','20',request_id=request_id,consent=True)
    again,recreated=s.reuse_story(source,settings,'2.50','20',request_id=request_id,consent=True)
    assert again==identifier and created and not recreated and len(s.listing())==2
    with pytest.raises(CharacterError):
        s.reuse_story(source,settings,'2.40','20',request_id=request_id,consent=True)
    assert len(s.listing())==2 and studio.writer.calls==0 and provider.calls==0


def test_incomplete_local_copy_receipt_prevents_duplicate_or_silent_replay(studio,monkeypatch):
    s=studio.service
    source,settings,provider=source_job(studio)
    before=files(s,source)
    original_save=s.save
    def fail_new(job):
        if job.get('reused_story'):raise OSError('synthetic local commit failure')
        return original_save(job)
    monkeypatch.setattr(s,'save',fail_new)
    request_id=uuid4().hex
    with pytest.raises(OSError):s.reuse_story(source,settings,'2.50','20',request_id=request_id,consent=True)
    receipts=list(s.root.glob('*/reuse-request.json'))
    assert len(receipts)==1 and json.loads(receipts[0].read_bytes())['state']=='copying_or_unknown'
    with pytest.raises(CharacterError):s.reuse_story(source,settings,'2.50','20',request_id=request_id,consent=True)
    assert len(list(s.root.glob('*/reuse-request.json')))==1
    assert files(s,source)==before and len(s.listing())==1 and provider.calls==0


def test_explicit_korean_dialogue_changes_only_the_new_copy(studio):
    s=studio.service
    source,settings,_=source_job(studio)
    original=s.read(source)
    spoken=[f'괜찮아, 장면 {n}도 여유롭게 가자.' for n in range(1,6)]
    identifier,_=s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,dialogues=spoken,consent=True)
    copied=s.read(identifier)
    assert [scene['narration'] for scene in copied['script']['scenes']]==spoken
    assert copied['reused_story']['dialogue_source']=='user_edited' and s.read(source)==original
    for dialogues in (['not Korean']*5,['한 장면만']):
        with pytest.raises(CharacterError):
            s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,dialogues=dialogues,consent=True)
    with pytest.raises(CharacterError):
        s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,consent=False)
    with pytest.raises(CharacterError):
        s.reuse_story(source,{**settings,'duration':30,'clip_seconds':5},'2.50','20',request_id=uuid4().hex,consent=True)
    assert len(s.listing())==2 and studio.writer.calls==0



@pytest.mark.parametrize('provenance',[None,'saved_dialogue_or_caption','user_edited'])
def test_default_reuse_clears_stored_narration_and_preserves_whole_story(studio,provenance):
    from newsflow.character.kling import snapshot
    s=studio.service
    source,settings,provider=source_job(studio)
    job=s.read(source)
    job['studio_selection']=snapshot(settings)
    job['script']['scenes'][0]['narration']='잠깐, 같이 가요.'
    job['script']['scenes'][1]['narration']=job['script']['scenes'][1]['caption']
    if provenance:
        job['reused_story']={'dialogue_source':provenance}
    job['plan_hash']=s.plan_hash(job)
    s.save(job)
    original=files(s,source)
    identifier,_=s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,consent=True)
    copied=s.read(identifier)
    spoken=[scene['narration'] for scene in copied['script']['scenes']]
    assert spoken==['']*5
    assert [scene['action'] for scene in copied['script']['scenes']]==[scene['action'] for scene in job['script']['scenes']]
    s.prepare(identifier,consent=True,script_reviewed=True)
    payload=s.read(identifier)['scenes'][0]['payload']
    assert payload['duration']==15 and payload['sound']=='on'
    assert all(scene['action'] in payload['prompt'] for scene in job['script']['scenes'])
    assert 'choose the pacing, camera and acting' in payload['prompt']
    assert '0-3 seconds:' not in payload['prompt'] and 'No spoken dialogue in this beat.' not in payload['prompt']
    assert files(s,source)==original and studio.writer.calls==0 and provider.calls==0


def test_optional_explicit_dialogue_remains_compatible_with_single_video_payload(studio):
    s=studio.service
    source,settings,_=source_job(studio)
    original=files(s,source)
    spoken=['동료: 잠깐, 같이 가요.','','정말요?','','(주인공) 그럼 출발해요.']
    identifier,_=s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,dialogues=spoken,consent=True)
    copied=s.read(identifier)
    assert [scene['narration'] for scene in copied['script']['scenes']]==spoken
    s.prepare(identifier,consent=True,script_reviewed=True)
    quoted=s.read(identifier)
    assert len(quoted['scenes'])==1 and quoted['scenes'][0]['payload']['sound']=='on'
    prompt=quoted['scenes'][0]['payload']['prompt']
    assert 'Speaker/acting direction (unspoken): 동료.' in prompt
    assert 'Speaker/acting direction (unspoken): 주인공.' in prompt
    assert 'In-character Korean dialogue: "잠깐, 같이 가요."' in prompt
    assert 'In-character Korean dialogue: "정말요?"' in prompt
    assert 'In-character Korean dialogue: "그럼 출발해요."' in prompt
    assert '"동료:' not in prompt and '"(주인공)' not in prompt
    assert 'Scene context (unspoken):' in prompt
    assert 'No voiceover or narrator.' in prompt
    assert 'speaker labels and parenthesized acting cues are unspoken direction.' in prompt
    assert 'Story labels and context are unspoken direction.' in prompt
    assert prompt.count('Infer natural Korean in-scene sound and character dialogue as the story needs')==2
    assert files(s,source)==original and studio.writer.calls==0
    assert all(client.calls==0 for client in studio.clients.values())

def test_submission_diagnostics_preserve_unknown_payload_without_secret_fields_or_retry(studio):
    s=studio.service
    source,settings,oldprovider=source_job(studio)
    original=s.read(source)
    identifier,_=s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,consent=True)
    s.prepare(identifier,consent=True,script_reviewed=True)
    job=s.read(identifier)
    provider=s.video_for(job)
    calls=[]
    def rejected(payload,key):
        calls.append(1)
        error=ProviderInputError(status_code=400)
        error.safe_diagnostics={'http_status':400,'error_code':'invalid_request_error',
            'request_id':'unneeded-1234','message':'synthetic raw secret body','url':'https://outside.invalid',
            'headers':{'Authorization':'synthetic secret'}}
        raise error
    provider.submit_scene=rejected
    payload=deepcopy(job['scenes'][0]['payload'])
    with pytest.raises(CharacterError):s.submit(identifier,consent=True,quote_hash=job['quote_hash'])
    failed=s.read(identifier)
    assert failed['state']=='submission_unknown' and failed['scenes'][0]['payload']==payload
    assert failed['submit_diagnostics']=={'http_status':400,'error_code':'invalid_request_error'}
    assert failed['scenes'][0]['submit_diagnostics']==failed['submit_diagnostics']
    assert 'HTTP 400' in failed['message']
    with pytest.raises(CharacterError):s.submit(identifier,consent=True,quote_hash=job['quote_hash'])
    assert len(calls)==1 and s.read(source)==original and studio.writer.calls==0


@pytest.mark.parametrize('upload_reference',[False,True])
def test_local_copy_route_requires_original_auth_csrf_origin_and_never_enables_paid_routes(studio,upload_reference):
    import ast,hmac,re,secrets
    from fastapi import FastAPI,Request
    from fastapi.responses import HTMLResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.testclient import TestClient
    from bat_distribution.operation import OperatingRequests
    from newsflow.distribution.local_access import LaunchSession,LocalAccess
    from newsflow.gui.character_routes import router
    s=studio.service
    source,settings,provider=source_job(studio)
    original=files(s,source)
    app=FastAPI();app.state.character=s;app.include_router(router)
    path=Path(__file__).resolve().parents[1]/'src/newsflow/main.py'
    tree=ast.parse(path.read_text(encoding='utf8'))
    nodes=[node for node in ast.walk(tree)
           if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'valid','security'}]
    namespace=dict(app=app,secret=b'synthetic-reuse-csrf',hashlib=hashlib,hmac=hmac,re=re,
                   secrets=secrets,Request=Request,HTMLResponse=HTMLResponse,StarletteHTTPException=StarletteHTTPException)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
    session=LaunchSession(18771)
    client=TestClient(OperatingRequests(LocalAccess(app,session)),base_url=session.origin,
                      client=('127.0.0.1',11001))
    endpoint=f'/api/studio/characters/{source}/reuse-story'
    data={'settings':json.dumps(settings),'episode_limit':'2.50','day_limit':'20',
          'request_id':uuid4().hex,'consent':'true','csrf_token':'bad'}
    upload={'files':{'reference':('new.png',replacement_png(),'image/png')}} if upload_reference else {}
    assert client.post(endpoint,data=data,headers={'Origin':session.origin},**upload).status_code==403
    token=session.launch_url().split('#',1)[1]
    assert client.post('/__local/claim',headers={'Origin':session.origin,'X-NewsFlow-Bootstrap':token}).status_code==204
    assert client.get('/api/studio/video-models').status_code==200
    assert client.post(endpoint,data=data,headers={'Origin':session.origin}).status_code==403
    data['csrf_token']=client.cookies.get('newsflow_csrf')
    assert client.post(endpoint,data=data,headers={'Origin':'https://outside.invalid'},**upload).status_code==403
    if upload_reference:
        assert client.post(f'/api/studio/characters/{source}/settings',data=data,headers={'Origin':session.origin},**upload).status_code==415
        huge={'reference':('huge.png',b'x'*(10*1024*1024+65537),'image/png')}
        assert client.post(endpoint,data=data,headers={'Origin':session.origin},files=huge).status_code==413
    response=client.post(endpoint,data=data,headers={'Origin':session.origin},**upload)
    assert response.status_code==200
    assert response.json()['additionalClaudeCalls']==0 and response.json()['reusedStory']
    assert response.json()['state']=='script_review' and response.json()['id']!=source
    copied=s.read(response.json()['id'])
    assert (copied['reference_sha256']!=s.read(source)['reference_sha256']) is upload_reference
    if not upload_reference:
        selected_data={**data,'request_id':uuid4().hex,'reference_job':source}
        selected_response=client.post(endpoint,data=selected_data,headers={'Origin':session.origin})
        assert selected_response.status_code==200
        selected=s.read(selected_response.json()['id'])
        assert selected['reused_story']['target_reference_sha256']==s.read(source)['reference_sha256']
    assert client.get(endpoint).status_code==403
    assert client.post(endpoint+'/',data=data,headers={'Origin':session.origin}).status_code==403
    assert client.post('/api/studio/characters/auto-story',data=data,headers={'Origin':session.origin}).status_code==403
    assert client.post(f"/character/{response.json()['id']}/submit",data=data,headers={'Origin':session.origin}).status_code==403
    assert studio.writer.calls==0 and provider.calls==0 and provider.uploads==0
    assert files(s,source)==original



def test_real_reused_service_job_satisfies_quote_only_trial_provenance(studio,monkeypatch):
    from datetime import UTC,datetime,timedelta
    from bat_distribution import character_trial as trial_module
    s=studio.service
    source,settings,provider=source_job(studio)
    original=s.read(source)
    baseline=files(s,source)
    identifier,_=s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,consent=True)
    def private(path):path.mkdir(exist_ok=True);return path
    monkeypatch.setattr(trial_module,'_private',private)
    policy={'schemaVersion':1,'id':'9'*32,'expires_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat(),
            'topic':original['topic'],'reference_sha256':original['reference_sha256'],
            'script_model':'claude-sonnet-4-6','video_model':original['model'],'duration':15,
            'clip_seconds':3,'scene_count':5,'sound':'on','script_limit_usd':'0',
            'video_limit_usd':'2.50','total_limit_usd':'3','allow_submit':False,
            'reuse_source_job_id':source,'reuse_story_sha256':trial_module._hash(original['script']),
            'prior_trial_ids':[]}
    trial=trial_module.Trial(s,s.root.parent,policy)
    assert trial._valid(identifier)['reused_story']['source_job_id']==source
    with pytest.raises(CharacterError):trial._valid(source)
    assert files(s,source)==baseline and studio.writer.calls==0 and provider.calls==0


def test_runtime_source_hook_uses_only_existing_fixed_hash_pinned_policy_loader():
    import ast
    path=Path(__file__).resolve().parents[1]/'tools/bat_distribution/windows_live.py'
    source=path.read_text(encoding='utf8')
    tree=ast.parse(source)
    start=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='start')
    installs=[node for node in ast.walk(start) if isinstance(node,ast.Call)
              and isinstance(node.func,ast.Name) and node.func.id=='install'
              and any(keyword.arg=='unknown_review' for keyword in node.keywords)]
    assert len(installs)==1
    callback=next(keyword.value for keyword in installs[0].keywords if keyword.arg=='policy_loader')
    assert isinstance(callback,ast.Lambda) and not callback.args.args
    assert ast.unparse(callback.body)=='character_trial_policy(config)'
    assert ast.get_source_segment(source,start).index('character_trial = install(')<source[source.index('def start('):].index('server.config.app = protected')



@pytest.mark.parametrize(('quote','approved_total','raised_daily'),[('1.890','4.50',True),('1.000','3',False)])
def test_real_daily_limit_values_need_scoped_overlay_and_keep_original_quote(studio,monkeypatch,quote,approved_total,raised_daily):
    from datetime import UTC,datetime,timedelta
    from newsflow.character.service import now
    from bat_distribution import character_trial as trial_module
    s=studio.service
    source,settings,_=source_job(studio)
    old=s.read(source)
    day=(now()+timedelta(hours=9)).date().isoformat()
    old['quote_approvals'][0]['day']=day
    s.save(old)
    old_files=files(s,source)
    identifier,_=s.reuse_story(source,settings,'2.50','2.50',request_id=uuid4().hex,consent=True)
    job=s.read(identifier)
    provider=s.video_for(job)
    provider.estimate=lambda payload:quote
    profile=s.root.parent
    parent=profile/'character-trials';parent.mkdir()
    prior_ids=['6'*32,'7'*32]
    old_journals={}
    for prior_id,video in zip(prior_ids,('0','1.260')):
        directory=parent/prior_id;directory.mkdir()
        path=directory/'journal.json'
        row={'schemaVersion':1,'policy_sha256':'a'*64,
             'script':{'state':'reserved','reserved_usd':'0.25'},
             'video':{'state':'reserved' if video!='0' else 'unspent','reserved_usd':video}}
        path.write_text(json.dumps(row),encoding='utf8')
        old_journals[path]=(path.read_bytes(),path.stat().st_mtime_ns)
    policy={'schemaVersion':1,'id':'8'*32,'expires_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat(),
            'topic':old['topic'],'reference_sha256':old['reference_sha256'],
            'script_model':'claude-sonnet-4-6','video_model':old['model'],'duration':15,
            'clip_seconds':3,'scene_count':5,'sound':'on','script_limit_usd':'0',
            'video_limit_usd':'2.50','total_limit_usd':'3','allow_submit':False,
            'reuse_source_job_id':source,'reuse_story_sha256':trial_module._hash(old['script']),
            'prior_trial_ids':prior_ids}
    upgraded={**policy,'total_limit_usd':approved_total,'allow_submit':True}
    def private(path):path.mkdir(exist_ok=True);return path
    monkeypatch.setattr(trial_module,'_private',private)
    original_submit=s.submit
    class NoNative:
        def unprotect(self,*args):raise AssertionError('No real key in this synthetic test')
    trial=trial_module.install(SimpleNamespace(state=SimpleNamespace(character=s)),profile,policy,NoNative,
                               policy_loader=lambda:upgraded)
    prepare=trial_module._CONTEXT.set(SimpleNamespace(trial=trial,action='prepare',job_id=identifier))
    try:s.prepare(identifier,consent=True,script_reviewed=True)
    finally:trial_module._CONTEXT.reset(prepare)
    quoted=s.read(identifier)
    assert quoted['quote_total_usd']==quote and quoted['day_limit']=='2.50'
    quote_hash,plan_hash=quoted['quote_hash'],quoted['plan_hash']
    context=trial_module._CONTEXT.set(SimpleNamespace(trial=trial,action='submit',job_id=identifier))
    try:
        # Exact reported defect: 1.260 + 1.890 = 3.150 > saved day_limit 2.50.
        if raised_daily:
            with pytest.raises(CharacterError):original_submit(identifier,consent=True,quote_hash=quote_hash)
            assert provider.calls==0 and s.read(identifier)['state']=='quoted'
        # The explicit fresh 4.50 overlay is journaled by the trial before this
        # unchanged quote reaches the optional server-owned daily approval hook.
        s.submit(identifier,consent=True,quote_hash=quote_hash)
        with pytest.raises(CharacterError):s.submit(identifier,consent=True,quote_hash=quote_hash)
    finally:trial_module._CONTEXT.reset(context)
    result=s.read(identifier)
    assert provider.calls==1 and result['state']=='generating'
    assert result['day_limit']=='2.50' and result['quote_hash']==quote_hash and result['plan_hash']==plan_hash
    if raised_daily:
        receipt=result['quote_approvals'][0]['daily_limit_approval']
        assert receipt['limit_usd']=='4.50' and receipt['policy_sha256']==trial_module._hash(upgraded)
        assert receipt['base_policy_sha256']==trial.policy_hash and receipt['trial_id']==policy['id']
    else:
        assert 'daily_limit_approval' not in result['quote_approvals'][0]
    assert trial.prior_exposure()==Decimal('1.760')
    assert files(s,source)==old_files
    assert all(path.read_bytes()==data and path.stat().st_mtime_ns==mtime for path,(data,mtime) in old_journals.items())


def replacement_png(color='red'):
    import io
    from PIL import Image
    stream=io.BytesIO()
    Image.new('RGB',(256,256),color).save(stream,format='PNG')
    return stream.getvalue()


@pytest.mark.parametrize('reference_kind',['upload','job'])
def test_reuse_selected_reference_changes_only_copy_and_pins_request_identity(studio,reference_kind):
    from newsflow.character.kling import normalize_reference
    from test_character_kling_studio import create
    s=studio.service
    source,settings,provider=source_job(studio)
    original=files(s,source)
    raw=replacement_png()
    selected=None
    if reference_kind=='upload':
        selection={'reference':raw}
    else:
        selected=create(studio)
        selected_job=s.read(selected)
        (s.folder(selected)/'reference.png').write_bytes(normalize_reference(raw))
        selected_job['reference_sha256']=hashlib.sha256(normalize_reference(raw)).hexdigest()
        s.save(selected_job)
        selection={'reference_job':selected}
    selected_before=files(s,selected) if selected else None
    request=uuid4().hex
    copied_id,created=s.reuse_story(source,settings,'2.50','20',request_id=request,consent=True,**selection)
    copied=s.read(copied_id)
    target_hash=hashlib.sha256(normalize_reference(raw)).hexdigest()
    assert created and copied['state']=='script_review' and copied['scenes']==[]
    assert copied['reference_sha256']==target_hash!=s.read(source)['reference_sha256']
    assert copied['reused_story']['source_reference_sha256']==s.read(source)['reference_sha256']
    assert copied['reused_story']['target_reference_sha256']==target_hash
    assert (s.folder(copied_id)/'reference.png').read_bytes()==normalize_reference(raw)
    assert s.reuse_story(source,settings,'2.50','20',request_id=request,consent=True,**selection)==(copied_id,False)
    with pytest.raises(CharacterError):
        s.reuse_story(source,settings,'2.50','20',request_id=request,reference=replacement_png('green'),consent=True)
    assert files(s,source)==original
    if selected:assert files(s,selected)==selected_before
    assert studio.writer.calls==0 and provider.calls==0 and provider.uploads==0


@pytest.mark.parametrize('raw',[b'',b'not a png',b'x'*(10*1024*1024+1)],ids=['empty','invalid','oversized'])
def test_reuse_rejects_invalid_selected_upload_without_falling_back_to_source(studio,raw):
    s=studio.service
    source,settings,provider=source_job(studio)
    before=files(s,source)
    with pytest.raises(CharacterError):
        s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,reference=raw,consent=True)
    assert files(s,source)==before and len(s.listing())==1
    assert studio.writer.calls==0 and provider.calls==0


def test_reuse_rejects_conflicting_or_tampered_reference_job(studio):
    from test_character_kling_studio import create
    s=studio.service
    source,settings,provider=source_job(studio)
    selected=create(studio)
    original=files(s,source)
    with pytest.raises(CharacterError):
        s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,
                      reference=replacement_png(),reference_job=selected,consent=True)
    (s.folder(selected)/'reference.png').write_bytes(replacement_png('green'))
    with pytest.raises(CharacterError):
        s.reuse_story(source,settings,'2.50','20',request_id=uuid4().hex,reference_job=selected,consent=True)
    assert files(s,source)==original and len(s.listing())==2
    assert studio.writer.calls==0 and provider.calls==0



def test_explicit_quote_refresh_preserves_prior_quote_and_allows_unchanged_settings(studio):
    s=studio.service
    identifier,provider,estimates=seeded(studio)
    s.prepare(identifier,consent=True,script_reviewed=True)
    before=s.read(identifier)
    settings=check(before['studio_selection'])
    s.update_studio_settings(identifier,settings,'10','20')
    reset=s.read(identifier)
    assert reset['state']=='script_review' and reset['scenes']==[] and 'quote_hash' not in reset
    assert reset['quote_history'][0]['quote_hash']==before['quote_hash']
    assert reset['quote_history'][0]['scenes']==before['scenes']
    assert reset['quote_history'][0]['quoted_at']==before['quoted_at']
    assert reset['quote_history'][0]['studio_selection']==before['studio_selection']
    assert len(estimates)==1 and provider.calls==0
    s.prepare(identifier,consent=True,script_reviewed=True)
    second=s.read(identifier)
    assert second['state']=='quoted' and second['quote_hash']!=before['quote_hash'] and len(estimates)==2
    s.update_studio_settings(identifier,settings,'10','20')
    assert len(s.read(identifier)['quote_history'])==2 and len(estimates)==2 and provider.calls==0


def test_failed_quote_requires_manual_settings_refresh_and_keeps_failure_history(studio):
    s=studio.service
    identifier,provider,estimates=seeded(studio)
    def failed(payload):raise ConnectionError('synthetic quote failure')
    provider.estimate=failed
    with pytest.raises(CharacterError):s.prepare(identifier,consent=True,script_reviewed=True)
    failed_job=s.read(identifier)
    assert failed_job['state']=='prepare_failed'
    with pytest.raises(CharacterError):s.prepare(identifier,consent=True,script_reviewed=True)
    settings=check(failed_job['studio_selection'])
    s.update_studio_settings(identifier,{**settings,'sound':'on'},'10','20')
    reset=s.read(identifier)
    assert reset['quote_history'][0]['state']=='prepare_failed' and reset['state']=='script_review'
    assert reset['studio_selection']['sound']=='on' and provider.calls==0
    provider.estimate=lambda payload:'0.10'
    s.prepare(identifier,consent=True,script_reviewed=True)
    assert s.read(identifier)['state']=='quoted' and provider.calls==0


def test_settings_refresh_refuses_paid_reserved_submitted_and_unknown_records(studio):
    from newsflow.character.service import quote_settings_editable
    s=studio.service
    identifier,provider,estimates=seeded(studio)
    s.prepare(identifier,consent=True,script_reviewed=True)
    base=s.read(identifier)
    mutations=[{'state':'submission_unknown'}, {'state':'generating'},
               {'quote_approvals':[{'day':'2026-10-29','usd':'0.10','scope':'initial'}]},
               {'reported_billed_usd':'0.10'}, {'reserved_usd':'0.10'}, {'approved_day':'2026-10-29'}]
    for changes in mutations:
        job={**deepcopy(base),**changes};s.save(job)
        before=files(s,identifier)
        assert not quote_settings_editable(job)
        with pytest.raises(CharacterError):s.update_studio_settings(identifier,check(job['studio_selection']),'10','20')
        assert files(s,identifier)==before
    job=deepcopy(base);job['scenes'][0].update(state='submitted',handle={'request_id':'synthetic'})
    s.save(job);before=files(s,identifier)
    with pytest.raises(CharacterError):s.update_studio_settings(identifier,check(job['studio_selection']),'10','20')
    assert files(s,identifier)==before and provider.calls==0 and len(estimates)==1


def test_normal_operating_quote_projection_hides_trial_caps_without_changing_trial(studio):
    from newsflow.studio.read_models import module_view
    trial=SimpleNamespace(policy={'total_limit_usd':'4.50','sound':'on','expires_at':'2026-10-29T23:59:59+00:00'})
    s=studio.service;s._approved_character_trial=trial
    state=SimpleNamespace(character=s,sessions=s.sessions,video=SimpleNamespace())
    request=SimpleNamespace(app=SimpleNamespace(state=state),state=SimpleNamespace())
    before=module_view(request,'characters')
    assert before['catalog']['characterStudio']['liveTrial']['enabled']
    s._operating_quote_only=True
    normal=module_view(request,'characters')
    assert 'liveTrial' not in normal['catalog']['characterStudio']
    assert s._approved_character_trial is trial and trial.policy['total_limit_usd']=='4.50'



def test_saved_my_character_is_selected_for_local_story_copy_without_changing_source(studio):
    from newsflow.creation.image_studio import ImageStudio
    from newsflow.gui.character_routes import reuse_story
    from newsflow.character.kling import normalize_reference
    service = studio.service
    source, settings, provider = source_job(studio)
    before = files(service, source)
    library = ImageStudio(service.sessions, service.root.parent, None)
    saved = library.save_character(replacement_png(), 'selected character.png')
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(character=service,image_studio=library)))
    arguments = dict(request=request,job_id=source,settings=json.dumps(settings),episode_limit='2.50',
                     day_limit='20',request_id=uuid4().hex,dialogues='[]',consent=True,
                     reference=None,reference_job='',reference_asset=saved['id'])
    copied_response = reuse_story(**arguments)
    copied = service.read(copied_response['id'])
    expected = hashlib.sha256(normalize_reference(library.asset(saved['id']).read_bytes())).hexdigest()
    assert copied['reference_sha256'] == expected != service.read(source)['reference_sha256']
    assert copied['reused_story']['target_reference_sha256'] == expected
    assert files(service, source) == before
    assert len(library.characters()) == 1
    invalid = reuse_story(**{**arguments,'request_id':uuid4().hex,'reference_asset':'../../private.png'})
    assert invalid.status_code == 422
    ambiguous = reuse_story(**{**arguments,'request_id':uuid4().hex,'reference_job':source})
    assert ambiguous.status_code == 422
    assert len(service.listing()) == 2 and files(service,source) == before
    assert studio.writer.calls == 0 and provider.calls == 0 and provider.uploads == 0
