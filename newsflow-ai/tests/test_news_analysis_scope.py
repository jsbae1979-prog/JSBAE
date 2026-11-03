"""Fake reservations only: unrelated history is retained, never replayed."""
import pytest
from sqlalchemy import select
from newsflow.db.models import IntelligenceRun, APIRequestReservation
from newsflow.intelligence.api_settings import APISettingsError, APIBudgetService
from test_posting_copy_scope import sessions, history, snapshot, MODEL, Store, configured, reviewed

def claim(sessions, **changes):
    values=dict(kind="analysis",status="running",provider="claude_api",options={"model":MODEL},
                evidence={"articles":[{"id":1,"title":"Synthetic"}]},result={},message="Fake")
    values.update(changes)
    with sessions.begin() as s:
        row=IntelligenceRun(**values);s.add(row);s.flush();return f"intelligence:{row.id}"

def reserve(b,identifier):
    return b.reserve(provider="claude_api",request_id=identifier,kind="analysis",model=MODEL,
                     max_output_tokens=1800,key_store=Store())

def test_reviewed_history_does_not_block_new_news_or_change_old_records(sessions):
    b,old=history(sessions);before=snapshot(sessions)
    assert b.readiness("claude_api",Store(),"analysis")["ready"]
    assert snapshot(sessions)==before
    new=reserve(b,claim(sessions))
    with sessions() as s:
        row=s.get(APIRequestReservation,old.id)
        assert {c.name:getattr(row,c.name) for c in row.__table__.columns}==next(x for x in before['api_request_reservations'] if x['id']==old.id)
        assert s.get(APIRequestReservation,new.id).bounds['news_analysis']
    with pytest.raises(APISettingsError):reserve(b,old.request_id)

@pytest.mark.parametrize('case',['unreviewed','active','changed','unfinished','unclassified'])
def test_unsafe_history_still_blocks(sessions,case):
    b,old=history(sessions,acknowledged=case!='unreviewed',status='reserved' if case=='active' else 'unknown',
                  request_id='other-operation' if case=='unclassified' else None)
    with sessions.begin() as s:
        row=s.get(APIRequestReservation,old.id)
        if case=='changed':row.estimated_usd='1'
        if case=='unfinished':row.finished_at=None
    assert not b.readiness('claude_api',Store(),'analysis')['ready']
    with pytest.raises(APISettingsError):reserve(b,claim(sessions))

@pytest.mark.parametrize('changes',[{'kind':'script'},{'status':'success'},{'provider':'openai'},
                                  {'options':{'model':'wrong'}},{'evidence':{}}])
def test_exception_requires_current_server_created_analysis(sessions,changes):
    b,_=history(sessions)
    with pytest.raises(APISettingsError):reserve(b,claim(sessions,**changes))
    with pytest.raises(APISettingsError):reserve(b,'intelligence:999999')

def test_active_and_same_analysis_unknown_block_even_after_ready(sessions):
    b,_=history(sessions);assert b.readiness('claude_api',Store(),'analysis')['ready']
    identifier=claim(sessions);new=reserve(b,identifier)
    with pytest.raises(APISettingsError):reserve(b,claim(sessions))
    b.finish(new.id,status='unknown')
    assert not b.readiness('claude_api',Store(),'analysis')['ready']
    with pytest.raises(APISettingsError):reserve(b,identifier)
    with pytest.raises(APISettingsError):reserve(b,claim(sessions))

@pytest.mark.parametrize('changes',[{'approved':False},{'request_limit_usd':'0.01'}])
def test_approval_and_execution_budget_still_required(sessions,changes):
    b,_=history(sessions);configured(sessions,**changes)
    with pytest.raises(APISettingsError):reserve(b,claim(sessions))

def test_real_auth_not_bypassed(sessions):
    history(sessions)
    assert not APIBudgetService(sessions).readiness('claude_api',Store(),'analysis')['ready']
