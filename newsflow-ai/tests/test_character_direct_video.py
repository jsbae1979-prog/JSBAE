"""Direct image/topic execution: no text provider; original synthetic media only."""
from copy import deepcopy
from uuid import uuid4
import pytest
from newsflow.character.direct_video import make_plan,segment_lengths,validate_plan
from newsflow.character.schema import CharacterError
from newsflow.character.kling import check,O3,K3
from newsflow.character.service import generation_rows
from newsflow.video_models.catalog import CATALOG
from test_character_episode_automation import setup_episode
from test_character_episode_schema import image

@pytest.mark.parametrize('model_id',[O3,K3])
@pytest.mark.parametrize('target',[15,30,60])
def test_native_duration_segments_cover_one_video_and_continue(model_id,target):
    model=CATALOG.model(model_id);lengths=segment_lengths(target,model)
    assert sum(lengths)==target and max(lengths)<=model['duration']['max']
    plan=make_plan('주제에서 시작하는 하나의 연속 영상',target,model,allow_continuation=target>15)
    assert plan.scenes[0].continuity=='cut' and all(s.continuity=='continue' and s.from_scene==s.no-1 for s in plan.scenes[1:])
    assert not plan.hook_caption and not plan.end_caption
    assert validate_plan(plan.model_dump(by_alias=True),target,model,plan.topic,allow_continuation=target>15)==plan

def test_direct_plan_does_not_accept_changed_subject_or_unapproved_timing():
    model=CATALOG.model(O3);plan=make_plan('원래 주제',30,model,allow_continuation=True).model_dump(by_alias=True)
    with pytest.raises(CharacterError):validate_plan(plan,30,model,'다른 주제')
    plan['scenes'][1]['seconds']-=1
    with pytest.raises(CharacterError):validate_plan(plan,30,model,'원래 주제')

@pytest.mark.parametrize('target',[15,30])
def test_image_topic_to_fake_video_and_final_mp4_has_zero_story_calls(tmp_path,target):
    s,v,old,registry,profile=setup_episode(tmp_path)
    settings={**check(s.read(old)['studio_selection']),'duration':target}
    raw=s.folder(old).joinpath('reference.png').read_bytes()
    # The uploaded image belongs to the same local image store; no registry write.
    from newsflow.creation.image_studio import ImageStudio
    images=ImageStudio(None,tmp_path,None);asset=images.asset_bytes(raw);raw=images.asset(asset).read_bytes()
    original_profiles=registry.list()
    identifier,created=s.create_episode('주어진 캐릭터가 바람에 날린 모자를 찾아요','5',reference=raw,settings=settings,
      request_id=uuid4().hex,reference_asset=asset,direct_video=True,direct_extension=target>15)
    job=s.read(identifier)
    assert created and job['direct_video'] and job['state']=='script_review' and job['text_provider_calls']==0
    assert not s.authoring.calls and registry.list()==original_profiles
    assert len(generation_rows(job))==1 if target==15 else len(generation_rows(job))==2
    assert all(job['topic'] in row['prompt'] for row in generation_rows(job))
    s.prepare(identifier,consent=True,script_reviewed=True)
    assert s.read(identifier)['state']=='quoted' and not v.sent and not s.authoring.calls
    quote=s.read(identifier)['quote_hash'];s.submit(identifier,consent=True,quote_hash=quote)
    assert len(v.sent)==1
    for _ in range(len(s.read(identifier)['scenes'])+1):
        if s.read(identifier)['state']=='clips_review':break
        s.check(identifier,consent=True)
    job=s.read(identifier);assert job['state']=='clips_review' and len(v.sent)==len(job['scenes'])
    for row in job['scenes'][1:]:
        assert row['dependency']['clip_sha256']==job['scenes'][row['from']-1]['sha256']
        assert row['payload']['first_frame_url'].endswith('-last.png')
    final=s.render(identifier,reviewed=True);out=s.read(identifier)['output']
    assert final.exists() and out['media']['duration']==pytest.approx(target,abs=1/30) and out['media']['has_audio']
    assert not out['captions_added'] and not out['voice_added'] and not s.authoring.calls
    assert s.render(identifier,reviewed=True)==final and len(v.sent)==len(job['scenes'])

def test_direct_and_story_modes_cannot_share_an_idempotency_key(tmp_path):
    s,v,old,registry,profile=setup_episode(tmp_path)
    original=s.read(old);request_id=original['studio_request_id']
    with pytest.raises(CharacterError):s.create_episode(original['topic'],'5',reference=image(),settings=check(original['studio_selection']),
      request_id=request_id,profile=profile,direct_video=True)
    assert s.read(old)==original and not s.authoring.calls and not v.sent


def test_long_direct_video_requires_explicit_continuation_choice():
    with pytest.raises(CharacterError):make_plan('이어 만들기를 선택하지 않은 주제',30,CATALOG.model(O3))


def test_unknown_direct_submit_is_not_replayed(tmp_path):
    s,v,old,registry,profile=setup_episode(tmp_path)
    identifier,_=s.create_episode('미확정 결과 재전송 방지용 합성 주제','5',reference=image(),
      settings=check(s.read(old)['studio_selection']),request_id=uuid4().hex,profile=profile,direct_video=True)
    s.prepare(identifier,consent=True,script_reviewed=True);quote=s.read(identifier)['quote_hash'];v.unknown=True
    with pytest.raises(CharacterError):s.submit(identifier,consent=True,quote_hash=quote)
    assert s.read(identifier)['state']=='submission_unknown' and len(v.sent)==1
    with pytest.raises(CharacterError):s.submit(identifier,consent=True,quote_hash=quote)
    assert len(v.sent)==1 and not s.authoring.calls
