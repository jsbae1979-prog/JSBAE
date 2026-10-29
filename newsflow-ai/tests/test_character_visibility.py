"""Recoverable visibility only; synthetic jobs/SQLite, no paid or operating work."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_api_settings import sessions,store
from test_character_kling_studio import studio,create

from newsflow.character.schema import CharacterError
from newsflow.character.service import day_exposure
from newsflow.character.visibility import PREFIX,PROCESSING,read_visibility,set_visibility
from newsflow.db.models import AppSetting
from newsflow.studio.read_models import character_rows


def files(service,identifier):
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in service.folder(identifier).iterdir() if p.is_file()}


def test_history_and_recent_are_independent_recoverable_preferences(studio):
    s=studio.service
    identifier=create(studio)
    before=s.read(identifier)
    baseline=files(s,identifier)
    listing=s.listing()
    assert set_visibility(s,identifier,'history',True)=={
        'id':identifier,'scope':'history','hidden':True,'trashed':True,'recentHidden':False,'recoverable':True}
    assert s.read(identifier)==before and s.listing()==listing and files(s,identifier)==baseline
    assert set_visibility(s,identifier,'recent',True)['recentHidden'] is True
    assert read_visibility(s.sessions)[identifier]=={'trashed':True,'recentHidden':True}
    assert set_visibility(s,identifier,'history',False)['trashed'] is False
    assert read_visibility(s.sessions)[identifier]['recentHidden'] is True
    assert set_visibility(s,identifier,'recent',False)['recentHidden'] is False
    assert s.read(identifier)==before and files(s,identifier)==baseline
    with s.sessions() as db:
        preferences=list(db.scalars(select(AppSetting).where(AppSetting.key.like(PREFIX+'%'))))
        assert len(preferences)==1 and len(preferences[0].key)<=50 and len(preferences[0].value)<=200


def test_read_model_flags_preserve_all_original_rows_and_assets(studio):
    s=studio.service
    first,second=create(studio),create(studio)
    set_visibility(s,first,'history',True)
    set_visibility(s,second,'recent',True)
    rows=character_rows(SimpleNamespace(character=s))
    assert {row['id'] for row in rows}=={first,second}
    by_id={row['id']:row for row in rows}
    assert by_id[first]['trashed'] and not by_id[first]['recentHidden']
    assert by_id[second]['recentHidden'] and not by_id[second]['trashed']
    assert all(row['referenceUrl']==f"/api/studio/characters/{row['id']}/reference" for row in rows)
    assert len(s.listing())==2


@pytest.mark.parametrize('state',sorted(PROCESSING))
def test_history_trash_refuses_processing_without_changing_job_or_preferences(studio,state):
    s=studio.service
    identifier=create(studio)
    job=s.read(identifier)
    job['state']=state
    s.save(job)
    before=files(s,identifier)
    with pytest.raises(CharacterError):set_visibility(s,identifier,'history',True)
    assert read_visibility(s.sessions)=={} and s.read(identifier)==job
    assert files(s,identifier)==before
    # Recent preferences do not stop/cancel a processing job.
    assert set_visibility(s,identifier,'recent',True)['recentHidden']
    assert s.read(identifier)==job


@pytest.mark.parametrize('state',['submission_unknown','status_or_download_failed','script_failed'])
def test_unknown_outcomes_remain_in_budget_listing_with_recoverable_warning(studio,state):
    s=studio.service
    identifier=create(studio)
    job=s.read(identifier)
    job.update(state=state,quote_approvals=[{'day':'2026-10-29','usd':'0.50','scope':'initial'}])
    job['scenes']=[{'position':1,'state':'unknown','attempt':1,'quote_usd':'0.50'}]
    s.save(job)
    before=files(s,identifier)
    result=set_visibility(s,identifier,'history',True)
    assert result['recoverable'] and 'warning' in result
    assert s.read(identifier)==job and files(s,identifier)==before
    assert sum((day_exposure(row,'2026-10-29') for row in s.listing()),Decimal(0))==Decimal('.50')
    assert character_rows(SimpleNamespace(character=s))[0]['trashed']
    set_visibility(s,identifier,'history',False)
    assert s.read(identifier)==job


@pytest.mark.parametrize('scope,hidden',[('delete',True),('history','true'),('recent',1),(None,True)])
def test_bad_scope_or_non_boolean_never_creates_metadata(studio,scope,hidden):
    s=studio.service
    identifier=create(studio)
    with pytest.raises(ValueError):set_visibility(s,identifier,scope,hidden)
    assert read_visibility(s.sessions)=={}


@pytest.mark.parametrize('identifier',['../outside','A'*32,'a'*31,'a'*33,''])
def test_unbounded_job_identifier_is_rejected(studio,identifier):
    with pytest.raises(ValueError):set_visibility(studio.service,identifier,'history',True)
    assert read_visibility(studio.service.sessions)=={}


def test_missing_job_cannot_create_orphan_visibility_setting(studio):
    with pytest.raises(CharacterError):set_visibility(studio.service,'f'*32,'recent',True)
    assert read_visibility(studio.service.sessions)=={}


def test_damaged_preferences_never_hide_jobs_or_get_overwritten(studio):
    s=studio.service
    identifier=create(studio)
    with s.sessions.begin() as db:
        db.add(AppSetting(key=PREFIX+identifier,value='not valid json'))
    assert read_visibility(s.sessions)=={}
    assert not character_rows(SimpleNamespace(character=s))[0]['trashed']
    with pytest.raises(ValueError):set_visibility(s,identifier,'recent',True)
    with s.sessions() as db:assert db.get(AppSetting,PREFIX+identifier).value=='not valid json'


def test_visibility_isolated_between_user_databases(studio,tmp_path):
    from newsflow.db.session import make_engine,migrate,session_factory
    s=studio.service
    identifier=create(studio)
    set_visibility(s,identifier,'recent',True)
    engine=make_engine(tmp_path/'other-user.sqlite3')
    migrate(engine)
    try:assert read_visibility(session_factory(engine))=={}
    finally:engine.dispose()


def test_exact_operating_path_preserves_real_local_auth_origin_and_csrf(studio):
    import ast,hmac,re,secrets
    from fastapi import FastAPI,Request
    from fastapi.responses import HTMLResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.testclient import TestClient
    from bat_distribution.operation import OperatingRequests
    from newsflow.distribution.local_access import LaunchSession,LocalAccess
    from newsflow.gui.character_routes import router
    app=FastAPI()
    app.state.character=studio.service
    app.include_router(router)
    path=Path(__file__).resolve().parents[1]/'src/newsflow/main.py'
    tree=ast.parse(path.read_text(encoding='utf8'))
    nodes=[node for node in ast.walk(tree)
           if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'valid','security'}]
    assert len(nodes)==2
    namespace=dict(app=app,secret=b'synthetic-visibility-csrf',hashlib=hashlib,hmac=hmac,re=re,
                   secrets=secrets,Request=Request,HTMLResponse=HTMLResponse,StarletteHTTPException=StarletteHTTPException)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
    session=LaunchSession(18771)
    client=TestClient(OperatingRequests(LocalAccess(app,session)),base_url=session.origin,
                      client=('127.0.0.1',11001))
    identifier=create(studio)
    endpoint=f'/api/studio/characters/{identifier}/visibility'
    data={'scope':'history','hidden':'true','csrf_token':'bad'}
    assert client.post(endpoint,data=data,headers={'Origin':session.origin}).status_code==403
    token=session.launch_url().split('#',1)[1]
    assert client.post('/__local/claim',headers={'Origin':session.origin,'X-NewsFlow-Bootstrap':token}).status_code==204
    assert client.get('/api/studio/video-models').status_code==200
    csrf=client.cookies.get('newsflow_csrf')
    assert client.post(endpoint,data=data,headers={'Origin':session.origin}).status_code==403
    data['csrf_token']=csrf
    assert client.post(endpoint,data=data,headers={'Origin':'https://outside.invalid'}).status_code==403
    assert read_visibility(studio.service.sessions)=={}
    response=client.post(endpoint,data=data,headers={'Origin':session.origin})
    assert response.status_code==200 and response.json()['trashed']
    assert client.get(endpoint).status_code==403
    assert client.post(endpoint+'/',data=data,headers={'Origin':session.origin}).status_code==403
    assert client.post(endpoint,data={**data,'scope':'delete'},headers={'Origin':session.origin}).status_code==422
    assert client.post(endpoint,data={**data,'hidden':'not-a-bool'},headers={'Origin':session.origin}).status_code==422
    assert client.post('/api/studio/characters/auto-story',data=data,headers={'Origin':session.origin}).status_code==403
    assert client.post(f'/character/{identifier}/submit',data=data,headers={'Origin':session.origin}).status_code==403
    data['hidden']='false'
    assert client.post(endpoint,data=data,headers={'Origin':session.origin}).json()['trashed'] is False


def test_api_processing_trash_responds_conflict_without_deleting_files(studio):
    from newsflow.gui.character_routes import character_visibility
    from fastapi import HTTPException
    s=studio.service
    identifier=create(studio)
    job=s.read(identifier)
    job['state']='generating'
    s.save(job)
    before=files(s,identifier)
    with pytest.raises(HTTPException) as failure:
        character_visibility(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(character=s))),
                             identifier,'history',True)
    assert failure.value.status_code==409 and files(s,identifier)==before
