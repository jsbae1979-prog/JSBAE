"""Stored approval/cap, distinct manual operations; no real key or provider call."""
from copy import deepcopy
import json
from uuid import uuid4
import pytest
from sqlalchemy import select
from newsflow.db.models import APIRequestReservation,AuditLog
from newsflow.character.request_scope import operation_for
from newsflow.intelligence.api_settings import FakeAPIBudgetService,APISettingsError,read_api_settings
from test_api_settings import sessions,configured
from test_character_authoring_v3 import Store
MODEL='claude-sonnet-4-6'

def reviewed(sessions,identifier):
    from newsflow.intelligence.api_settings import _unknown_fingerprint
    with sessions.begin() as s:
        row=s.get(APIRequestReservation,identifier)
        s.add(AuditLog(level='info',event='api_episode_story_once_ack',message=json.dumps({
          'scope':'new_episode_story_once','provider':'claude_api','model':MODEL,
          'unknowns':{identifier:_unknown_fingerprint(row)}})))

def reserve(budget,request_id,*,image=b'first synthetic image',operation=None):
    return budget.reserve_character(provider='claude_api',request_id=request_id,kind='analysis',model=MODEL,
      max_output_tokens=2000,key_store=Store(),operation=operation or operation_for(kind='analysis',
      instruction='synthetic analysis',payload={'request':'original character'},model=MODEL,request_id=request_id,image_bytes=image))

def test_stored_approval_and_cap_are_reused_without_being_consumed(sessions):
    configured(sessions);before=read_api_settings(sessions,'claude_api');budget=FakeAPIBudgetService(sessions)
    for i in range(2):
        r=reserve(budget,f'new-analysis:{i}');budget.finish(r.id,status='success',usage={'prompt_tokens':1,'completion_tokens':1})
    after=read_api_settings(sessions,'claude_api')
    assert after.approved_at==before.approved_at and after.request_limit_usd==before.request_limit_usd

def test_legacy_unrelated_story_does_not_block_new_image_analysis_and_is_not_modified(sessions):
    configured(sessions);b=FakeAPIBudgetService(sessions)
    old=b.reserve(provider='claude_api',request_id='episode:'+'a'*32+':script:1',kind='script',model=MODEL,max_output_tokens=4000,key_store=Store())
    b.finish(old.id,status='unknown');reviewed(sessions,old.id)
    with sessions() as s:
        row=s.get(APIRequestReservation,old.id);before={c.name:deepcopy(getattr(row,c.name)) for c in row.__table__.columns}
    reserve(b,'new-image')
    with sessions() as s:
        row=s.get(APIRequestReservation,old.id);assert {c.name:getattr(row,c.name) for c in row.__table__.columns}==before

def test_same_image_unknown_is_not_retried_with_a_new_request_id(sessions):
    configured(sessions);b=FakeAPIBudgetService(sessions);old=reserve(b,'image-one');b.finish(old.id,status='unknown');reviewed(sessions,old.id)
    with pytest.raises(APISettingsError):reserve(b,'new-id-same-image')
    reserve(b,'different-image',image=b'different original image')

def test_active_request_remains_blocked(sessions):
    configured(sessions);b=FakeAPIBudgetService(sessions);reserve(b,'active')
    with pytest.raises(APISettingsError):reserve(b,'different',image=b'other')

@pytest.mark.parametrize('settings',[{'approved':False},{'request_limit_usd':'0.01'}])
def test_saved_cap_and_permission_still_apply(sessions,settings):
    configured(sessions,**settings)
    with pytest.raises(APISettingsError):reserve(FakeAPIBudgetService(sessions),'blocked')
    with sessions() as s:assert not list(s.scalars(select(APIRequestReservation)))

def test_generic_provider_route_cannot_inherit_character_scope(sessions):
    configured(sessions);b=FakeAPIBudgetService(sessions);old=reserve(b,'image-old');b.finish(old.id,status='unknown')
    with pytest.raises(APISettingsError):
        b.reserve(provider='claude_api',request_id='generic',kind='analysis',model=MODEL,max_output_tokens=2000,key_store=Store())

def test_fresh_unreviewed_unknown_is_not_silently_approved(sessions):
    configured(sessions);b=FakeAPIBudgetService(sessions)
    old=b.reserve(provider='claude_api',request_id='episode:'+'b'*32+':script:1',kind='script',model=MODEL,max_output_tokens=4000,key_store=Store())
    b.finish(old.id,status='unknown')
    with pytest.raises(APISettingsError):reserve(b,'new-image-without-old-review')

def test_operation_record_has_no_image_or_prompt(sessions):
    configured(sessions);b=FakeAPIBudgetService(sessions);r=reserve(b,'image-safe')
    with sessions() as s:
        record=s.get(APIRequestReservation,r.id).bounds['character_operation']
        assert set(record)=={'version','action','key','job_id'}
        assert len(record['key'])==64 and 'synthetic' not in json.dumps(record)


def test_changed_unknown_fingerprint_requires_fresh_review(sessions):
    configured(sessions);b=FakeAPIBudgetService(sessions)
    old=b.reserve(provider='claude_api',request_id='episode:'+'c'*32+':script:1',kind='script',model=MODEL,max_output_tokens=4000,key_store=Store())
    b.finish(old.id,status='unknown');reviewed(sessions,old.id)
    with sessions.begin() as s:s.get(APIRequestReservation,old.id).estimated_usd='0.01'
    with pytest.raises(APISettingsError):reserve(b,'changed-history')
