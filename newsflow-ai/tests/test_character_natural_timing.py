"""Small boundary tolerance without paid retry, text rewrite or forced stretching."""
from copy import deepcopy
import json
import pytest
from newsflow.character.episode_story import EpisodeScript,validate_episode
from newsflow.character.episode_policy import total_playback_seconds
from newsflow.character import episode_policy,editing
from newsflow.character.kling import O3
from newsflow.character.schema import CharacterError
from newsflow.video_models.catalog import CATALOG
from test_character_episode_schema import script
from test_character_episode_automation import setup_episode
from test_character_validation_feedback import bounded_authoring
from test_character_episode_editing import synthetic_sources

def marginal_story():
    value=script(50)
    for scene,seconds in zip(value['scenes'],[7,8,7,6]):scene['seconds']=seconds
    value['scenes'][1].update(speed='fast',fast_intensity='weak')
    value['scenes'][-1]['freeze_end']='strong'
    return value

def test_near_boundary_is_accepted_without_changing_any_story_field():
    value=marginal_story();before=deepcopy(value)
    assert total_playback_seconds(value)==pytest.approx(27.9)
    result=validate_episode(value,30,CATALOG.model(O3))
    assert value==before and result.model_dump(by_alias=True)==before
    timeline=editing.edit_timeline(result,30)
    assert sum(s['seconds'] for s in timeline)==pytest.approx(27.9)
    assert timeline[-1]['freeze_seconds']==pytest.approx(1.5)
    assert [s['source_seconds'] for s in timeline]==[7,8,7,6]
    assert [s['speed'] for s in timeline]==[1,1.25,1,1]

@pytest.mark.parametrize('total,valid',[(27.9,True),(27.899,False),(28,True),(30,True),(30.001,False),(23.1,False),(27.1,False)])
def test_boundary_remains_bounded_and_no_broad_relaxation(total,valid,monkeypatch):
    monkeypatch.setattr(episode_policy,'total_playback_seconds',lambda *a,**k:total)
    if valid:validate_episode(marginal_story(),30,CATALOG.model(O3))
    else:
        with pytest.raises(CharacterError):validate_episode(marginal_story(),30,CATALOG.model(O3))

def test_fake_single_request_no_paid_retry_or_scene_seconds_change(tmp_path):
    service,video,i,_,_=setup_episode(tmp_path,target=30)
    value=marginal_story();authoring,adapter,budget=bounded_authoring(value);service.authoring=authoring
    service.write(i,consent=True)
    job=service.read(i)
    assert job['state']=='script_review' and job['script']==value
    assert len(adapter.bodies)==1 and len(job['text_reservations'])==1 and not video.sent and not video.uploads

def test_saved_response_free_recovery_retains_evidence_and_cost(tmp_path,monkeypatch):
    service,video,i,_,_=setup_episode(tmp_path,target=30)
    value=marginal_story();authoring,adapter,budget=bounded_authoring(value);service.authoring=authoring
    monkeypatch.setattr(episode_policy,'MIN_PLAYBACK_BOUNDARY_TOLERANCE',0)
    with pytest.raises(CharacterError):service.write(i,consent=True)
    failed=service.read(i);responses=deepcopy(failed['script_responses']);cost=deepcopy(failed['text_reservations'])
    monkeypatch.setattr(episode_policy,'MIN_PLAYBACK_BOUNDARY_TOLERANCE',.1)
    authoring.generate=lambda *a,**k:pytest.fail('No additional provider request')
    service.recover_story_response(i,consent=True)
    result=service.read(i)
    assert result['state']=='script_review' and result['script']==value
    assert result['script_responses']==responses and result['text_reservations']==cost and len(adapter.bodies)==1
    assert not video.sent and not video.uploads

def test_real_local_ffmpeg_keeps_27_9_seconds_instead_of_padding_to_30(tmp_path,synthetic_sources):
    value=EpisodeScript.model_validate(marginal_story())
    result=editing.compose_episode(tmp_path,value,[synthetic_sources[1]]*4,
        settings={'duration':30,'aspect_ratio':'9:16','sound':'on'})
    assert result['media']['duration']==pytest.approx(27.9,abs=.1)
    assert result['timeline'][-1]['freeze_seconds']==pytest.approx(1.5)
    evidence=json.loads((tmp_path/'compose/edit-evidence.json').read_text(encoding='utf8'))
    assert evidence['target_seconds']==30 and evidence['output_seconds']==pytest.approx(27.9)
