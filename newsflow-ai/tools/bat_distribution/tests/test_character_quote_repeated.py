"""Normal explicit repeated/multiclip quote refinement; fake adapters only."""
import json
import pytest
from test_character_quote_only import quoted,receipts,latest_receipt,assert_old_state_unchanged
from newsflow.character.kling import check,snapshot
from newsflow.character.studio_story import StudioStoryboard,prompts
from newsflow.character.schema import CharacterError
from test_character_kling_studio import story,studio
from test_api_settings import sessions,store


def reset(value):
    job=value.service.read(value.identifier)
    job.update(state='script_review',scenes=[])
    value.service.save(job)
    value.state.previous_estimates=value.state.calls.count('estimate')


def test_legacy_unsubmitted_script_can_quote_without_touching_trial_ledger(quoted):
    prior=json.loads(quoted.journal.read_bytes());prior['job_id']=quoted.identifier
    quoted.journal.write_text(json.dumps(prior),encoding='utf8')
    quoted.journal_before=quoted.journal.read_bytes()
    assert quoted.post()==200
    assert latest_receipt(quoted)['state']=='quoted' and quoted.service._operating_quote_only is True
    assert_old_state_unchanged(quoted)


def test_catalog_valid_55_seconds_quotes_five_planned_clips(quoted):
    service=quoted.service;job=service.read(quoted.identifier)
    settings={**check(job['studio_selection']),'duration':55,'clip_seconds':11}
    script=StudioStoryboard.model_validate(story(55,'off'))
    job.update(duration=55,studio_selection=snapshot(settings),script=script.model_dump(),
               prompts=prompts(script,settings,job['character']))
    job['plan_hash']=service.plan_hash(job);service.save(job)
    assert quoted.post()==200
    current=service.read(quoted.identifier);receipt=latest_receipt(quoted)
    assert len(current['scenes'])==5 and receipt['planned_estimates']==5
    assert receipt['calls']=={'upload':1,'estimate':5}
    assert [row['payload']['duration'] for row in current['scenes']]==[11]*5
    assert receipt['generation_requests']==0
    assert_old_state_unchanged(quoted)


def test_request_cannot_exceed_its_actual_plan_estimate_count(quoted):
    def inside(scope):
        if scope._read(quoted.identifier)['calls']['estimate']==5:
            with pytest.raises(CharacterError):scope.claim('estimate')
    quoted.state.inside=inside
    assert quoted.post()==200
    assert latest_receipt(quoted)['calls']['estimate']==5
    assert quoted.state.calls==['upload']+['estimate']*5


def test_two_explicit_quotes_after_user_reset_keep_first_receipt(quoted):
    assert quoted.post()==200
    first=receipts(quoted)[0];before=first.read_bytes()
    reset(quoted)
    assert quoted.post()==200
    assert len(receipts(quoted))==2 and first.read_bytes()==before
    assert quoted.state.calls.count('estimate')==10
    assert latest_receipt(quoted)['state']=='quoted'
    assert_old_state_unchanged(quoted)


def test_unknown_quote_is_preserved_then_explicit_user_reset_can_quote_again(quoted):
    quoted.state.fail='estimate'
    assert quoted.post()==409
    failed=receipts(quoted)[0];before=failed.read_bytes()
    assert latest_receipt(quoted)['state']=='failed_or_unknown'
    count=len(quoted.state.calls)
    assert quoted.post()==409 and len(quoted.state.calls)==count and len(receipts(quoted))==1
    reset(quoted);quoted.state.fail=None
    assert quoted.post()==200
    assert len(receipts(quoted))==2 and failed.read_bytes()==before
    assert latest_receipt(quoted)['state']=='quoted'
    assert quoted.state.calls.count('estimate')==6
    assert_old_state_unchanged(quoted)
