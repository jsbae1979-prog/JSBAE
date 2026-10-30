"""Finite preflight messages only; synthetic settings and Fake transport."""
from datetime import timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from newsflow.character.authoring import AuthoringAI, budget_failure_reason
from newsflow.character.kling import DEFAULTS, O3
from newsflow.character.registry import CharacterRegistry
from newsflow.character.schema import CharacterError
from newsflow.character.service import CharacterService
from newsflow.character.story_response import public_failure
from newsflow.creation.image_studio import ImageStudio
from newsflow.db.models import APIRequestReservation, utcnow
from newsflow.intelligence.api_settings import APIBudgetService, APISettingsError
from newsflow.intelligence.settings import _set
from newsflow.studio.read_models import character_rows
from test_api_settings import sessions, configured
from test_character_authoring_v3 import Store, Adapter, Budget, png
from test_character_episode_schema import profile, script
from test_character_automation_routes import gui

AUTH_ERROR='실제 API 연결 미확인 · 별도 승인 후 검증 필요'
LIMIT_ERROR='이번 요청의 입력·출력·검색 상한이 1회 실행 비용 한도를 넘습니다.'
SECRET='synthetic-private-exception-never-project'


def episode(root, sessions, budget):
    images=ImageStudio(None,root,None)
    saved=CharacterRegistry(root,images).save(profile(),images.asset_bytes(png()))
    service=CharacterService(root,sessions,SimpleNamespace(key=lambda:pytest.fail('No credentials')))
    adapter=Adapter('claude_api',script())
    authoring=AuthoringAI({'claude_api':Store()},budget,{'claude_api':adapter})
    service.authoring=authoring
    identifier,_=service.create_episode('합성 설정 확인','5',reference=png(),
        settings={**DEFAULTS,'video_model':O3,'native_resolution':'std','duration':15},
        request_id=uuid4().hex,profile=saved)
    return service,authoring,adapter,identifier


class RefusedBudget:
    def __init__(self,error):self.error=error;self.calls=0
    def reserve(self,**kwargs):self.calls+=1;raise self.error
    def finish(self,*args,**kwargs):raise AssertionError('A refused reservation cannot finish')


def test_expired_connection_refusal_has_no_provider_call_and_persists_safe_read_model(sessions,tmp_path):
    configured(sessions)
    with sessions.begin() as session:
        _set(session,'api_claude_api_verified_model','claude-sonnet-4-6')
        _set(session,'api_claude_api_authentication_verified_at',(utcnow()-timedelta(hours=25)).isoformat())
    service,authoring,adapter,identifier=episode(tmp_path,sessions,APIBudgetService(sessions))
    with pytest.raises(CharacterError):service.write(identifier,consent=True)
    job=service.read(identifier)
    assert job['state']=='needs_script' and job['script_attempts']==0 and not job['response_received']
    assert job['script_failure']['preflight_reason']=='authentication_required'
    assert job['script_failure']['dispatched'] is False
    assert authoring.last_failure['reason']=='authentication_required' and not adapter.bodies
    with sessions() as session:assert list(session.scalars(select(APIRequestReservation)))==[]
    projected=character_rows(SimpleNamespace(character=service))[0]
    assert projected['scriptFailure']=={
        'stage':'preflight','reason':'authentication_required','dispatched':False,
        'message':'설정에서 선택한 AI의 연결 상태를 다시 확인하세요. 유료 요청은 전송되지 않았습니다.'}
    assert projected['scriptRetryAllowed'] is False


@pytest.mark.parametrize('error,reason',[
    (APISettingsError(AUTH_ERROR),'authentication_required'),
    (APISettingsError(LIMIT_ERROR),'settings'),
    (APISettingsError('1회 실행 비용 한도 필요'),'settings'),
    (APISettingsError(AUTH_ERROR+' / '+SECRET),'settings'),
    (APISettingsError(SECRET),'settings'),
    (ValueError(AUTH_ERROR),'settings'),
])
def test_only_reviewed_exact_budget_messages_become_reason_codes(error,reason,tmp_path):
    budget=RefusedBudget(error)
    service,authoring,adapter,identifier=episode(tmp_path,None,budget)
    assert budget_failure_reason(error)==reason
    with pytest.raises(CharacterError):service.write(identifier,consent=True)
    failure=service.read(identifier)['script_failure']
    assert failure['preflight_reason']==reason and public_failure(failure)['dispatched'] is False
    assert SECRET not in json.dumps(failure) and SECRET not in json.dumps(public_failure(failure))
    assert budget.calls==1 and not adapter.bodies


def test_episode_cap_preflight_is_distinct_without_dispatch(tmp_path):
    budget=Budget();original=budget.reserve
    def reserve(**kwargs):
        row=original(**kwargs);row.reserved_usd='6';return row
    budget.reserve=reserve
    service,authoring,adapter,identifier=episode(tmp_path,None,budget)
    with pytest.raises(CharacterError):service.write(identifier,consent=True)
    failure=service.read(identifier)['script_failure']
    assert failure['preflight_reason']=='episode_limit' and not adapter.bodies
    assert public_failure(failure)['reason']=='episode_limit'
    assert budget.finished[0][1]=={'status':'failed','usage':{'prompt_tokens':0,'completion_tokens':0,'search_calls':0}}


@pytest.mark.parametrize('dispatched',[None,True,'false',0])
def test_ambiguous_or_historical_record_does_not_claim_no_dispatch(dispatched):
    value={'failure_stage':'preflight','preflight_reason':'authentication_required','dispatched':dispatched}
    assert public_failure(value) is None


def test_unknown_dispatch_does_not_become_preflight(tmp_path):
    budget=Budget();original=budget.reserve
    def reserve(**kwargs):
        row=original(**kwargs);row.reserved_usd='0.10';return row
    budget.reserve=reserve
    service,authoring,adapter,identifier=episode(tmp_path,None,budget)
    adapter.fail=True
    with pytest.raises(CharacterError):service.write(identifier,consent=True)
    job=service.read(identifier)
    assert job['state']=='script_failed' and job['response_received'] is False
    assert job['script_failure']['failure_stage']!='preflight' and 'preflight_reason' not in job['script_failure']
    assert 'dispatched' not in public_failure(job['script_failure'])
    assert len(adapter.bodies)==1 and budget.finished[0][1]['status']=='unknown'


def test_auto_story_route_uses_fresh_safe_diagnosis_and_keeps_consent_csrf(gui):
    budget=RefusedBudget(APISettingsError(AUTH_ERROR))
    service,authoring,adapter,identifier=episode(gui.root,None,budget)
    gui.app.state.character=service;gui.app.state.character_authoring=authoring
    path='/api/studio/characters/auto-story'
    assert gui.client.post(path,data={'job_id':identifier,'consent':'true'}).status_code==403
    result=gui.post(path,job_id=identifier,consent='true')
    assert result.status_code==409 and result.json()['failure']['reason']=='authentication_required'
    assert result.json()['error']=='설정에서 선택한 AI의 연결 상태를 다시 확인하세요. 유료 요청은 전송되지 않았습니다.'
    assert not adapter.bodies and budget.calls==1
    # A later request that never starts writing must not reuse the prior diagnosis.
    denied=gui.post(path,job_id=identifier,consent='false')
    assert denied.status_code==409 and 'failure' not in denied.json() and budget.calls==1
    original=service.write
    def busy(*args,**kwargs):raise CharacterError('busy')
    service.write=busy
    denied=gui.post(path,job_id=identifier,consent='true')
    assert denied.status_code==409 and 'failure' not in denied.json() and budget.calls==1
    service.write=original


def test_unknown_reason_and_other_fields_never_expose_exception_content():
    safe=public_failure({'failure_stage':'preflight','dispatched':False,
                         'preflight_reason':SECRET,'message':SECRET,'api_key':SECRET})
    assert safe['reason']=='settings' and SECRET not in json.dumps(safe)
