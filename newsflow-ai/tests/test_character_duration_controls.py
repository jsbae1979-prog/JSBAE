"""Selected total length retimes five saved beats locally; no real providers."""
from copy import deepcopy
from uuid import uuid4

import pytest
from test_api_settings import sessions, store
from test_character_kling_studio import studio
from test_character_reuse_story import source_job
from test_character_single_video import seeded
from test_character_visibility import files

from newsflow.character.kling import DEFAULTS, check, validate
from newsflow.character.schema import CharacterError
from newsflow.character.service import fingerprint, generation_rows
from newsflow.character.studio_story import StudioStoryboard, prompts


@pytest.mark.parametrize('total',range(15,61,5))
def test_total_duration_contract_is_five_supported_native_clips(total):
    assert validate({**DEFAULTS,'duration':total,'clip_seconds':total//5})['duration']==total


@pytest.mark.parametrize('total,seconds',[(14,3),(16,3),(30,5),(60,15),(65,13),(True,3)])
def test_total_duration_rejects_other_clip_counts_and_invalid_totals(total,seconds):
    with pytest.raises(CharacterError):validate({**DEFAULTS,'duration':total,'clip_seconds':seconds})


@pytest.mark.parametrize('total',[30,45])
def test_retime_new_copy_preserves_unknown_source_and_original_story_provenance(studio,total):
    service=studio.service
    source,settings,provider=source_job(studio)
    original=service.read(source);before=files(service,source)
    identifier,_=service.reuse_story(source,{**settings,'duration':total,'clip_seconds':total//5},
                                    '10','20',request_id=uuid4().hex,consent=True)
    copied=service.read(identifier)
    assert copied['duration']==total and copied['scenes']==[]
    assert [scene['seconds'] for scene in copied['script']['scenes']]==[total//5]*5
    assert [row['seconds'] for row in generation_rows(copied)]==[total//5]*5
    for old,new in zip(original['script']['scenes'],copied['script']['scenes']):
        assert {k:v for k,v in old.items() if k not in {'seconds','narration'}}=={
            k:v for k,v in new.items() if k not in {'seconds','narration'}}
    assert copied['script']['plan']==original['script']['plan']
    assert copied['reused_story']['source_story_sha256']==fingerprint(original['script'])
    assert copied['reused_story']['source_plan_hash']==original['plan_hash']
    assert copied['reused_story']['retimed']=={'source_duration':15,'duration':total,'clip_seconds':total//5}
    assert copied['plan_hash']==service.plan_hash(copied)
    assert service.read(source)==original and files(service,source)==before
    assert provider.calls==provider.uploads==studio.writer.calls==0


def test_changed_quoted_length_archives_original_and_requires_fresh_five_clip_quote(studio):
    service=studio.service;identifier,provider,estimates=seeded(studio)
    service.prepare(identifier,consent=True,script_reviewed=True)
    original=service.read(identifier)
    assert len(estimates)==5
    settings={**check(original['studio_selection']),'duration':30,'clip_seconds':6}
    service.update_studio_settings(identifier,settings,'10','20')
    updated=service.read(identifier)
    assert updated['state']=='script_review' and updated['duration']==30 and updated['scenes']==[]
    assert not any(key in updated for key in ('quote_hash','quoted_at','quote_total_usd','quote_key_id'))
    archived=updated['quote_history'][0]
    for key in ('script','duration','plan_hash','scenes','prompts','studio_selection','quote_hash'):
        assert archived[key]==original[key]
    assert [scene['seconds'] for scene in updated['script']['scenes']]==[6]*5
    assert updated['plan_hash']!=original['plan_hash']
    with pytest.raises(CharacterError):service.submit(identifier,consent=True,quote_hash=original['quote_hash'])
    current_provider=service.video_for(updated);new_estimates=[]
    current_provider.estimate=lambda payload:(new_estimates.append(deepcopy(payload)) or '0.10')
    service.prepare(identifier,consent=True,script_reviewed=True)
    quoted=service.read(identifier)
    assert len(new_estimates)==5 and [row['duration'] for row in new_estimates]==[6]*5
    assert quoted['quote_hash']!=original['quote_hash'] and quoted['quote_history']==updated['quote_history']
    assert provider.calls==current_provider.calls==studio.writer.calls==0


def test_explicit_unquoted_save_retimes_to_five_nine_second_beats(studio):
    service=studio.service;identifier,provider,_=seeded(studio)
    original=service.read(identifier)
    service.update_studio_settings(identifier,{**check(original['studio_selection']),'duration':45,'clip_seconds':9},'10','20')
    updated=service.read(identifier)
    assert updated['duration']==45 and [row['seconds'] for row in updated['script']['scenes']]==[9]*5
    assert [row['seconds'] for row in generation_rows(updated)]==[9]*5
    assert updated['script']['plan']==original['script']['plan'] and updated['scenes']==[]
    assert studio.writer.calls==provider.calls==provider.uploads==0


@pytest.mark.parametrize('evidence',[
    {'state':'submission_unknown'}, {'state':'generating'}, {'state':'clips_review'},
    {'reported_billed_usd':'0.10'}, {'reserved_usd':'0.10'}, {'submitted_at':'2026-10-29'},
    {'quote_approvals':[{'day':'2026-10-29','usd':'0.10','scope':'initial'}]},
    {'scenes':[{'state':'submitted','payload':{'duration':3},'handle':{'request_id':'synthetic'}}]},
])
def test_existing_paid_reserved_submitted_and_unknown_jobs_cannot_be_retimed(studio,evidence):
    service=studio.service;identifier,provider,_=seeded(studio)
    job=service.read(identifier);job.update(deepcopy(evidence));service.save(job)
    before=files(service,identifier)
    with pytest.raises(CharacterError):
        service.update_studio_settings(identifier,{**check(job['studio_selection']),'duration':30,'clip_seconds':6},'10','20')
    assert service.read(identifier)==job and files(service,identifier)==before
    assert studio.writer.calls==provider.calls==provider.uploads==0


def test_model_that_does_not_support_selected_native_clip_duration_stops_before_writes(studio,monkeypatch):
    from newsflow.character.kling import CATALOG
    service=studio.service;source,settings,provider=source_job(studio)
    original_model=CATALOG.model
    def restricted(identifier):
        model=original_model(identifier)
        if model is not None:model['duration']={'options':[3,5],'default':3}
        return model
    monkeypatch.setattr(CATALOG,'model',restricted)
    before=files(service,source)
    settings={**settings,'duration':30,'clip_seconds':6}
    with pytest.raises(CharacterError):service.update_studio_settings(source,settings,'10','20')
    with pytest.raises(CharacterError):
        service.reuse_story(source,settings,'10','20',request_id=uuid4().hex,consent=True)
    assert files(service,source)==before and len(service.listing())==1
    assert studio.writer.calls==provider.calls==provider.uploads==0


def test_legacy_three_scene_story_remains_readable_and_cannot_gain_fabricated_beats(studio):
    service=studio.service;identifier,provider,_=seeded(studio)
    job=service.read(identifier);settings=check(job['studio_selection'])
    job['script']['scenes']=[job['script']['scenes'][index] for index in (0,2,4)]
    for scene in job['script']['scenes']:scene['seconds']=5
    job['prompts']=prompts(StudioStoryboard.model_validate(job['script']),settings,job['character'])
    job['plan_hash']=service.plan_hash(job);service.save(job)
    before=files(service,identifier)
    changed={**settings,'duration':30,'clip_seconds':6}
    with pytest.raises(CharacterError,match='3~4장면'):
        service.update_studio_settings(identifier,changed,'10','20')
    with pytest.raises(CharacterError,match='3~4장면'):
        service.reuse_story(identifier,changed,'10','20',request_id=uuid4().hex,consent=True)
    assert service.read(identifier)==job and files(service,identifier)==before
    copied_id,_=service.reuse_story(identifier,settings,'10','20',request_id=uuid4().hex,consent=True)
    copied=service.read(copied_id)
    assert len(copied['script']['scenes'])==3 and [row['seconds'] for row in copied['script']['scenes']]==[5]*3
    assert studio.writer.calls==provider.calls==provider.uploads==0
