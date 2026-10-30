"""New local profile/topic GUI contracts; injected synthetic authoring only."""
import ast
import hashlib
import hmac
from io import BytesIO
import json
from pathlib import Path
import re
import secrets
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.testclient import TestClient

from newsflow.creation.image_studio import ImageStudio
from newsflow.gui.character_routes import router
from newsflow.character.registry import CharacterRegistry
from newsflow.character.schema import CharacterError


def profile(name='별이'):
    return {'name_ko':name,'species':'rabbit','appearance':'A purple rabbit with round ears.',
        'personality':'조용하고 호기심 많음','comedy_formula':{'world':'연구실','setup':'작은 사고','reaction':'태연함'},
        'style_lock':'Soft clay animation, warm light.','supporting_cast':[],
        'audience':'general','made_for_kids':False}


@pytest.fixture
def gui(tmp_path):
    app=FastAPI()
    app.state.config=SimpleNamespace(data_dir=tmp_path)
    app.state.image_studio=ImageStudio(None,tmp_path,None)
    app.include_router(router)
    path=Path(__file__).resolve().parents[1]/'src/newsflow/main.py'
    nodes=[n for n in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in {'valid','security'}]
    scope=dict(app=app,secret=b'synthetic-profile-csrf',hashlib=hashlib,hmac=hmac,re=re,secrets=secrets,
        Request=Request,HTMLResponse=HTMLResponse,StarletteHTTPException=StarletteHTTPException)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),scope)
    client=TestClient(app,base_url='http://127.0.0.1:18779')
    client.get('/api/studio/characters/profiles')
    def post(path,**values):
        return client.post(path,data={**values,'csrf_token':client.cookies.get('newsflow_csrf')},
            headers={'Origin':'http://127.0.0.1:18779'})
    out=BytesIO();Image.new('RGB',(128,128),'teal').save(out,'PNG')
    asset=app.state.image_studio.asset_bytes(out.getvalue())
    return SimpleNamespace(app=app,client=client,post=post,asset=asset,root=tmp_path)


def test_profiles_save_revision_delete_keeps_asset_and_history(gui):
    history=gui.root/'unrelated-job.json';history.write_text('preserve',encoding='utf-8')
    saved=gui.post('/api/studio/characters/profiles/save',profile=json.dumps(profile()),asset=gui.asset)
    assert saved.status_code==200
    row=saved.json();assert row['name_ko']=='별이'
    assert gui.client.get('/api/studio/characters/profiles').json()['profiles']==[row]
    updated=gui.post('/api/studio/characters/profiles/save',profile=json.dumps(profile('달이')),asset=gui.asset,
        identifier=row['id'],revision=row['revision'])
    assert updated.status_code==200 and updated.json()['revision']==2
    stale=gui.post('/api/studio/characters/profiles/save',profile=json.dumps(profile('충돌')),asset=gui.asset,
        identifier=row['id'],revision=1)
    assert stale.status_code==409
    assert gui.post(f"/api/studio/characters/profiles/{row['id']}/delete",revision=2,consent='false').status_code==422
    assert gui.post(f"/api/studio/characters/profiles/{row['id']}/delete",revision=2,consent='true').status_code==200
    assert gui.client.get('/api/studio/characters/profiles').json()=={'profiles':[]}
    assert history.read_text(encoding='utf-8')=='preserve'
    assert gui.app.state.image_studio.asset(gui.asset).exists()


def test_profile_commands_keep_csrf_origin_and_strict_paths(gui):
    path='/api/studio/characters/profiles/save'
    values={'profile':json.dumps(profile()),'asset':gui.asset}
    assert gui.client.post(path,data=values).status_code==403
    assert gui.client.post(path,data={**values,'csrf_token':gui.client.cookies.get('newsflow_csrf')},
        headers={'Origin':'https://outside.invalid'}).status_code==403
    assert gui.post(path,profile=json.dumps(profile()),asset='../outside.png').status_code==409
    assert gui.client.get('/api/studio/characters/profiles').json()['profiles']==[]


def test_two_profile_topic_lists_are_isolated_and_status_persists(gui):
    first=gui.post('/api/studio/characters/profiles/save',profile=json.dumps(profile()),asset=gui.asset).json()
    second=gui.post('/api/studio/characters/profiles/save',profile=json.dumps(profile('달이')),asset=gui.asset).json()
    path=f"/api/studio/characters/profiles/{first['id']}/topics"
    row=gui.post(path+'/manual',topic='계산기 고장에도 태연한 토끼').json()
    assert gui.post(path+'/manual',topic=row['topic']).json()['id']==row['id']
    assert gui.client.get(f"/api/studio/characters/profiles/{second['id']}/topics").json()=={'topics':[]}
    assert gui.post(path+f"/{row['id']}/status",status='skipped').json()['topics'][0]['status']=='skipped'
    result=gui.post(path+'/import',content='번호,카테고리,주제\n1,연구,실험 도중 쉬는 토끼')
    assert result.status_code==200 and len(result.json()['topics'])==2


def test_analysis_and_topics_use_selected_provider_and_explicit_consent(gui):
    calls=[]
    class Fake:
        def analyze(self,content,**kwargs):
            if not kwargs['consent']:raise CharacterError('consent')
            calls.append(('image',kwargs['provider'],kwargs['model']))
            return {'species':'rabbit','appearance':'Purple rabbit.','style_suggestion':'Clay animation.',
                'candidates':[{'name_ko':n,'personality':'느긋함','comedy_formula':profile()['comedy_formula']} for n in ('하나','둘','셋')]}
        def topics(self,character,count,existing,**kwargs):
            if not kwargs['consent']:raise CharacterError('consent')
            calls.append(('topics',kwargs['provider'],character['name_ko']))
            return [{'topic':'갑작스런 알람에도 낮잠','category':'연구','joke_type':'태연'}]
    gui.app.state.character_authoring=Fake()
    path='/api/studio/characters/profiles/analyze'
    assert gui.post(path,asset=gui.asset,model='gpt-4.1-mini',request_id='a'*32,consent='false').status_code==409
    assert calls==[]
    assert gui.post(path,asset=gui.asset,model='gpt-4.1-mini',request_id='b'*32,consent='true').status_code==200
    row=gui.post('/api/studio/characters/profiles/save',profile=json.dumps(profile()),asset=gui.asset).json()
    result=gui.post(f"/api/studio/characters/profiles/{row['id']}/topics/generate",model='claude-sonnet-4-6',
        count=1,request_id='c'*32,consent='true')
    assert result.status_code==200 and len(result.json()['topics'])==1
    assert calls==[('image','openai','gpt-4.1-mini'),('topics','claude_api','별이')]


def test_script_edit_passes_revision_hash_without_auto_approval(gui):
    calls=[]
    gui.app.state.character=SimpleNamespace(edit_episode=lambda *args:calls.append(args))
    result=gui.post('/api/studio/characters/'+'a'*32+'/script',script=json.dumps({'schema_version':3}),expected_hash='b'*64)
    assert result.status_code==200 and result.json()['approvalInvalidated'] is True
    assert calls==[('a'*32,{'schema_version':3},'b'*64)]


def test_new_jobs_require_profile_and_reuse_matching_draft(gui):
    from uuid import uuid4
    from newsflow.character.kling import DEFAULTS, O3
    from newsflow.character.service import CharacterService
    from test_character_episode_automation import FakeAuthoring
    service=CharacterService(gui.root,None,SimpleNamespace(key=lambda:'synthetic'))
    gui.app.state.character=service
    authoring=FakeAuthoring();gui.app.state.character_authoring=authoring
    values={'topic':'정원의 아침','episode_limit':'5','request_id':uuid4().hex,
        'studio_settings':json.dumps({**DEFAULTS,'video_model':O3,'native_resolution':'std','duration':15,'script_model':'gpt-4.1-mini'})}
    assert gui.post('/character',**values).status_code==422
    assert service.listing()==[]
    registered=gui.post('/api/studio/characters/profiles/save',profile=json.dumps(profile()),asset=gui.asset).json()
    values.update(character_id=registered['id'],character_revision=registered['revision'])
    result=gui.post('/character',**values)
    assert result.status_code==200,result.text
    identifier=result.json()['id']
    assert gui.post('/character',**values).json()['id']==identifier
    assert not authoring.calls
    assert gui.post('/api/studio/characters/auto-story',job_id=identifier,consent='false').status_code==409
    assert gui.post('/api/studio/characters/auto-story',job_id=identifier,consent='true').status_code==200
    assert gui.post('/api/studio/characters/auto-story',job_id=identifier,consent='true').status_code==200
    assert len(authoring.calls)==1
    job=service.read(identifier)
    assert job['automation_version']==1 and job['script_provider']=='openai'
    assert job['character_id']==registered['id'] and job['state']=='script_review'
    assert 'reference_image' not in authoring.calls[0]['character']
    assert gui.client.get(f"/api/studio/characters/profiles/{registered['id']}/topics").json()['topics'][0]['status']=='scripted'


def test_stale_character_revision_and_legacy_forms_never_create(gui):
    from newsflow.character.kling import DEFAULTS
    from newsflow.character.service import CharacterService
    gui.app.state.character=CharacterService(gui.root,None,SimpleNamespace(key=lambda:'synthetic'))
    row=gui.post('/api/studio/characters/profiles/save',profile=json.dumps(profile()),asset=gui.asset).json()
    values={'topic':'정원의 아침','episode_limit':'5','request_id':'a'*32,'studio_settings':json.dumps(DEFAULTS),
        'character_id':row['id'],'character_revision':2}
    assert gui.post('/character',**values).status_code==422
    assert gui.post('/character',topic='옛 양식',episode_limit='5').status_code==422
    assert gui.app.state.character.listing()==[]


def test_regeneration_routes_require_explicit_quote_and_generation_approval(gui):
    calls=[]
    class Service:
        def prepare_regeneration(self,job,position,*,consent=False):
            if not consent:raise CharacterError('consent')
            calls.append(('quote',job,position))
        def regenerate_scenes(self,job,*,consent=False,quote_hash=''):
            if not consent or quote_hash!='b'*64:raise CharacterError('blocked')
            calls.append(('generate',job,quote_hash))
        def cancel_regeneration(self,job,*,quote_hash=''):
            if quote_hash!='b'*64:raise CharacterError('blocked')
            calls.append(('cancel',job))
        def read(self,job):return {'state':'regeneration_quoted'}
    gui.app.state.character=Service();base='/api/studio/characters/'+'a'*32+'/regeneration'
    assert gui.post(base+'/quote',position=2,consent='false').status_code==409 and not calls
    assert gui.post(base+'/quote',position=2,consent='true').status_code==200
    assert calls==[('quote','a'*32,2)]
    assert gui.post(base+'/submit',quote_hash='b'*64,consent='false').status_code==409
    assert gui.post(base+'/submit',quote_hash='b'*64,consent='true').status_code==200
    assert gui.post(base+'/cancel',quote_hash='b'*64).status_code==200
    assert [c[0] for c in calls]==['quote','generate','cancel']


def test_regenerated_clip_route_selects_only_hash_bound_owned_attempt(gui):
    content=b'synthetic-mp4-test';path=gui.root/'scene-2-t2.mp4';path.write_bytes(content)
    record={'position':2,'state':'downloaded','file':path.name,'sha256':hashlib.sha256(content).hexdigest()}
    gui.app.state.character=SimpleNamespace(read=lambda _: {'scenes':[record]},folder=lambda _:gui.root)
    uri='/character/'+'a'*32+'/clips/2'
    assert gui.client.get(uri).content==content
    record['file']='../outside.mp4';assert gui.client.get(uri).status_code==404
    record['file']='scene-1-t2.mp4';assert gui.client.get(uri).status_code==404
    record['file']=path.name;record['sha256']='0'*64
    assert gui.client.get(uri).status_code==404
