"""Character execution limits include retries, independent of historical daily totals."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_api_settings import sessions, store
from test_character_kling_studio import png, studio
from test_character_reuse_story import source_job
from test_character_single_video import seeded
from test_character_visibility import files

from newsflow.character.kling import DEFAULTS
from newsflow.character.schema import CharacterError
from newsflow.character.service import day_exposure, fingerprint, now


def settings():return {**DEFAULTS,'duration':15,'clip_seconds':3}


@pytest.mark.parametrize('kind',['legacy','studio'])
def test_new_job_ignores_legacy_daily_comparison_and_defaults_missing_day_to_execution(studio,kind):
    service=studio.service
    if kind=='legacy':
        first=service.create('합성 새 작업','10','1',reference=png())
        second=service.create('합성 새 작업','10',reference=png())
    else:
        first,_=service.create_studio('합성 새 작업','10','1',reference=png(),settings=settings(),request_id=uuid4().hex)
        second,_=service.create_studio('합성 새 작업','10',reference=png(),settings=settings(),request_id=uuid4().hex)
    assert service.read(first)['day_limit']=='1' and service.read(first)['episode_limit']=='10'
    assert service.read(second)['day_limit']=='10' and studio.writer.calls==0


def test_reuse_and_safe_settings_save_accept_larger_execution_cap_without_rewriting_original_daily_field(studio):
    service=studio.service;source,chosen,provider=source_job(studio)
    before=files(service,source)
    copied,_=service.reuse_story(source,chosen,'10','1',request_id=uuid4().hex,consent=True)
    job=service.read(copied)
    assert job['episode_limit']=='10' and job['day_limit']=='1'
    service.update_studio_settings(copied,chosen,'20')
    updated=service.read(copied)
    assert updated['episode_limit']=='20' and updated['day_limit']=='1'
    assert files(service,source)==before and provider.calls==0 and studio.writer.calls==0


def test_high_historical_unknown_exposure_and_old_daily_field_do_not_block_current_under_cap_quote(studio):
    service=studio.service;source,_,_=source_job(studio)
    old=service.read(source);day=(now()+timedelta(hours=9)).date().isoformat()
    old['quote_approvals']=[{'day':day,'usd':'9999.00','scope':'initial'}];service.save(old)
    original=files(service,source)
    identifier,provider,_=seeded(studio)
    job=service.read(identifier);job.update(episode_limit='2',day_limit='0.01')
    job['plan_hash']=service.plan_hash(job);service.save(job)
    service.prepare(identifier,consent=True,script_reviewed=True)
    quoted=service.read(identifier)
    assert quoted['quote_total_usd']=='0.50'
    service.daily_limit_approval=lambda *_:(_ for _ in ()).throw(AssertionError('Historical daily hook must not execute'))
    service.submit(identifier,consent=True,quote_hash=quoted['quote_hash'])
    submitted=service.read(identifier)
    assert submitted['state']=='generating' and provider.calls==5
    assert submitted['episode_limit']=='2' and submitted['day_limit']=='0.01'
    assert submitted['plan_hash']==quoted['plan_hash'] and submitted['quote_hash']==quoted['quote_hash']
    assert files(service,source)==original and day_exposure(service.read(source),day)==Decimal('9999.00')


def test_current_execution_quote_is_available_above_cap_but_submit_is_blocked(studio):
    service=studio.service;identifier,provider,_=seeded(studio)
    job=service.read(identifier);job.update(episode_limit='0.40',day_limit='10000')
    job['plan_hash']=service.plan_hash(job);service.save(job)
    service.prepare(identifier,consent=True,script_reviewed=True)
    quoted=service.read(identifier);before=files(service,identifier)
    assert quoted['state']=='quoted' and quoted['quote_total_usd']=='0.50'
    with pytest.raises(CharacterError):service.submit(identifier,consent=True,quote_hash=quoted['quote_hash'])
    assert provider.calls==0 and files(service,identifier)==before


def test_actual_official_quote_above_execution_cap_is_visible_without_allowing_generation(studio):
    service=studio.service;identifier,provider,_=seeded(studio)
    job=service.read(identifier);job.update(episode_limit='2',day_limit='10000')
    job['plan_hash']=service.plan_hash(job);service.save(job)
    estimates=[]
    provider.estimate=lambda payload:(estimates.append(payload) or '0.50')
    service.prepare(identifier,consent=True,script_reviewed=True)
    assert len(estimates)==5 and provider.calls==0
    quoted=service.read(identifier)
    assert quoted['state']=='quoted' and quoted['quote_total_usd']=='2.50'
    with pytest.raises(CharacterError):service.submit(identifier,consent=True,quote_hash=quoted['quote_hash'])
    assert provider.calls==0


def retry_quoted(studio,*,extra='0.10',state='failed',cap='2'):
    service=studio.service;identifier,provider,_=seeded(studio)
    job=service.read(identifier);job.update(episode_limit=cap,day_limit='0.01')
    job['plan_hash']=service.plan_hash(job);service.save(job)
    service.prepare(identifier,consent=True,script_reviewed=True)
    job=service.read(identifier)
    scene=job['scenes'][0];scene['state']=state
    job.update(state='retry_quoted',quote_approvals=[{'day':'2026-10-30','usd':'0.50','scope':'initial'}])
    retry={'position':scene['position'],'quote_usd':extra,'at':now().isoformat(),
           'key_id':job['quote_key_id'],'original':fingerprint(scene)}
    job.update(retry=retry,retry_hash=fingerprint(retry));service.save(job)
    return identifier,provider


def test_manual_retry_includes_prior_spend_in_current_episode_cap(studio):
    service=studio.service;identifier,provider=retry_quoted(studio,extra='1.60',cap='2.10')
    original=service.read(identifier)
    service.retry_scene(identifier,consent=True,quote_hash=original['retry_hash'])
    updated=service.read(identifier)
    assert updated['quote_total_usd']=='2.10' and updated['scenes'][0]['attempt']==2 and provider.calls==1
    assert updated['quote_approvals'][-1]['usd']=='1.60' and updated['episode_limit']=='2.10'
    assert updated['scenes'][0]['history'][0]['state']=='failed' and updated['day_limit']=='0.01'
    # 1.60 alone fits, but 0.50 already approved in this episode makes 2.10.
    other,other_provider=retry_quoted(studio,extra='1.60',cap='2')
    before=files(service,other)
    with pytest.raises(CharacterError):
        service.retry_scene(other,consent=True,quote_hash=service.read(other)['retry_hash'])
    assert other_provider.calls==1 and files(service,other)==before


@pytest.mark.parametrize('state',['unknown','submitted'])
def test_unknown_or_already_submitted_scene_cannot_be_retried(studio,state):
    service=studio.service;identifier,provider=retry_quoted(studio,state=state)
    before=files(service,identifier)
    with pytest.raises(CharacterError):
        service.retry_scene(identifier,consent=True,quote_hash=service.read(identifier)['retry_hash'])
    assert provider.calls==0 and files(service,identifier)==before
