"""Synthetic request journals; no network, real keys or operating profile."""
from copy import deepcopy
import json
from uuid import uuid4
import pytest
from sqlalchemy import select
from newsflow.db.models import APIRequestReservation, AppSetting, AuditLog, IntelligenceRun
from newsflow.intelligence.api_settings import APIBudgetService, FakeAPIBudgetService, APISettingsError
from test_api_settings import sessions, configured
from test_character_authoring_v3 import Store
from test_character_saved_approval import reviewed

MODEL = 'claude-sonnet-4-6'


def snapshot(sessions):
    with sessions() as s:
        return {model.__tablename__: [{c.name:deepcopy(getattr(row,c.name)) for c in model.__table__.columns}
            for row in s.scalars(select(model).order_by(model.id if hasattr(model,'id') else model.key))]
            for model in (APIRequestReservation, AppSetting, AuditLog)}


def history(sessions, *, acknowledged=True, request_id=None, status='unknown'):
    configured(sessions)
    b=FakeAPIBudgetService(sessions)
    old=b.reserve(provider='claude_api',request_id=request_id or 'episode:'+'a'*32+':script:1',
        kind='script',model=MODEL,max_output_tokens=1800,key_store=Store())
    if status!='reserved':b.finish(old.id,status=status)
    if acknowledged:reviewed(sessions,old.id)
    return b, old


def claim(sessions, request_id=None, **changes):
    request_id=request_id or 'posting-review:'+uuid4().hex
    values=dict(kind='posting_copy_review',provider='claude_api',status='running',
        options={'model':MODEL,'project_id':'character:'+'b'*32,'fingerprint':'c'*64},
        evidence={'sourceHash':'d'*64},result={},message='synthetic review')
    values.update(changes)
    with sessions.begin() as s:
        run=IntelligenceRun(**values);s.add(run);s.flush()
        s.add(AppSetting(key=request_id,value=str(run.id)))
    return request_id


def reserve(b, request_id):
    return b.reserve_posting_copy(provider='claude_api',request_id=request_id,kind='script',
        model=MODEL,max_output_tokens=1800,key_store=Store())


def test_readiness_and_execution_agree_without_editing_old_journals(sessions):
    b,old=history(sessions);before=snapshot(sessions)
    assert not b.readiness('claude_api',Store(),capability='script')['ready']
    assert b.posting_copy_readiness('claude_api',Store())['ready']
    assert snapshot(sessions)==before  # GET has no acknowledgement side effect.
    new=reserve(b,claim(sessions))
    b.finish(new.id,status='success',usage={'prompt_tokens':10,'completion_tokens':10})
    after=snapshot(sessions)
    assert after[APIRequestReservation.__tablename__][0]==before[APIRequestReservation.__tablename__][0] if old.id<new.id else True
    with sessions() as s:
        row=s.get(APIRequestReservation,old.id)
        original=next(r for r in before[APIRequestReservation.__tablename__] if r['id']==old.id)
        assert {c.name:getattr(row,c.name) for c in row.__table__.columns}==original
        assert s.get(APIRequestReservation,new.id).bounds['posting_copy_review'] is True
        assert any(r.event=='api_posting_copy_scope' for r in s.scalars(select(AuditLog)))
    assert after[AppSetting.__tablename__][:0]==[]  # Settings are checked explicitly below.
    old_settings={r['key']:r['value'] for r in before[AppSetting.__tablename__]}
    after_settings={r['key']:r['value'] for r in after[AppSetting.__tablename__]}
    assert all(after_settings[k]==v for k,v in old_settings.items())


@pytest.mark.parametrize('case',['unreviewed','changed','active','unfinished','unclassified','malformed'])
def test_unrelated_does_not_mean_unconditionally_allowed(sessions,case):
    b,old=history(sessions,acknowledged=case!='unreviewed',status='reserved' if case=='active' else 'unknown',
                  request_id='unclassified-request' if case=='unclassified' else None)
    with sessions.begin() as s:
        row=s.get(APIRequestReservation,old.id)
        if case=='changed':row.estimated_usd='0.123'
        if case=='unfinished':row.finished_at=None
        if case=='malformed':row.bounds={**row.bounds,'character_operation':{'action':'story'}}
    if case=='malformed':reviewed(sessions,old.id) # Even a reviewed invalid scope is blocked.
    assert not b.posting_copy_readiness('claude_api',Store())['ready']
    with pytest.raises(APISettingsError):reserve(b,claim(sessions))


def test_posting_unknown_blocks_new_identifier_even_after_review(sessions):
    configured(sessions);b=FakeAPIBudgetService(sessions)
    first=claim(sessions);r=reserve(b,first);b.finish(r.id,status='unknown');reviewed(sessions,r.id)
    assert not b.posting_copy_readiness('claude_api',Store())['ready']
    with pytest.raises(APISettingsError):reserve(b,first)
    with pytest.raises(APISettingsError):reserve(b,claim(sessions))
    with sessions() as s:assert len(list(s.scalars(select(APIRequestReservation))))==1


def test_new_active_request_rechecked_after_ready_preview(sessions):
    b,old=history(sessions)
    assert b.posting_copy_readiness('claude_api',Store())['ready']
    reserve(b,claim(sessions))
    with pytest.raises(APISettingsError):reserve(b,claim(sessions))


@pytest.mark.parametrize('case',['absent','wrong_kind','wrong_provider','finished','wrong_model','wrong_project'])
def test_scope_cannot_be_used_by_generic_requests(sessions,case):
    b,_=history(sessions)
    changes={}
    if case=='wrong_kind':changes['kind']='analysis'
    if case=='wrong_provider':changes['provider']='openai'
    if case=='finished':changes['status']='success'
    if case in {'wrong_model','wrong_project'}:
        changes['options']={'model':'gpt-4.1-mini' if case=='wrong_model' else MODEL,
            'project_id':'character:'+'b'*32 if case=='wrong_model' else '../invalid','fingerprint':'c'*64}
    identifier='posting-review:'+uuid4().hex if case=='absent' else claim(sessions,**changes)
    with pytest.raises(APISettingsError):reserve(b,identifier)
    with pytest.raises(APISettingsError):
        b.reserve(provider='claude_api',request_id='generic-new',kind='script',model=MODEL,max_output_tokens=1800,key_store=Store())


@pytest.mark.parametrize('changes',[{'approved':False},{'approved':False,'request_limit_usd':'0'},{'request_limit_usd':'0.01'}])
def test_saved_approval_and_cost_limit_remain_enforced(sessions,changes):
    b,_=history(sessions);configured(sessions,**changes)
    with pytest.raises(APISettingsError):reserve(b,claim(sessions))


def test_real_auth_and_missing_key_remain_required(sessions):
    b,_=history(sessions)
    assert not APIBudgetService(sessions).posting_copy_readiness('claude_api',Store())['ready']
    class Missing:
        def status(self):return {'configured':False}
    assert not b.posting_copy_readiness('claude_api',Missing())['ready']
    with pytest.raises(APISettingsError):
        b.reserve_posting_copy(provider='claude_api',request_id=claim(sessions),kind='script',model=MODEL,
            max_output_tokens=1800,key_store=Missing())
