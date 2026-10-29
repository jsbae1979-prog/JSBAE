"""Pure/fake preparation checks after the provider rejected oversized prompts."""
from copy import deepcopy
import hashlib
import pytest

from newsflow.character.service import generation_rows, fingerprint, now
from newsflow.character.kling import DEFAULTS, O3, VIDEO_PROMPT_LIMIT, snapshot
from newsflow.character.schema import CharacterError
from newsflow.character.studio_story import StudioStoryboard, prompts
from newsflow.video_models.catalog import character_config
from test_api_settings import sessions, store
from test_character_kling_studio import studio
from test_character_single_video import seeded


def job():
    scenes=[{'seconds':6,'role':'setup' if i==1 else 'punchline' if i==5 else 'build',
        'action':f'The original character performs unique office reaction number {i}.',
        'caption':f'화면 설명 {i}','sfx':'quiet office', 'narration':''} for i in range(1,6)]
    settings={**DEFAULTS,'video_model':O3,'native_resolution':'std','duration':30,'clip_seconds':6,'sound':'on'}
    script={'title':'월요일 사무실 상황극','plan':{'situation':'지각한 월요일 아침','contrast':'대비는 후반부','punchline':'결말은 마지막 장면'},
            'hook_caption':'늦은 출근','end_caption':'태평한 월요일','scenes':scenes}
    character=character_config()
    return {'duration':30,'studio_selection':snapshot(settings),'character':character,'script':script,
            'prompts':prompts(StudioStoryboard.model_validate(script),settings,character),
            'scenes':[{'state':'failed','payload':{'duration':6,'prompt':'immutable failed request'},
                       'finished_at':'2026-10-30T01:00:00+00:00','attempt':1}],
            'quote_hash':'unchanged-old-quote','quote_approvals':[{'usd':'3.360'}]}


def test_each_clip_keeps_its_complete_beat_and_concise_direction_not_other_beats():
    source=job();before=deepcopy(source)
    rows=generation_rows(source)
    assert len(rows)==5 and [row['seconds'] for row in rows]==[6]*5
    for row,scene in zip(rows,source['script']['scenes']):
        prompt=row['prompt']
        assert source['script']['plan']['situation'] in prompt
        assert source['script']['plan']['contrast'] not in prompt
        assert source['script']['plan']['punchline'] not in prompt
        assert scene['action'] in prompt and scene['sfx'] in prompt
        assert all(other['action'] not in prompt for other in source['script']['scenes'] if other is not scene)
        assert source['character']['appearance'] in prompt and source['character']['style_lock'] in prompt
        assert f"Create only beat {row['position']}/5 as one 6-second shot." in prompt
        assert 'No voiceover or narrator.' in prompt and 'no text, no logos' in prompt
        assert 'Infer natural Korean in-scene sound' in prompt
        assert 'ordered_story' not in prompt and 'Full story context' not in prompt
        assert prompt.endswith(source['prompts'][row['position']-1]['prompt'])
        assert len(prompt)<=VIDEO_PROMPT_LIMIT
    assert source==before


def test_app_bound_is_conservative_and_never_truncates_or_changes_old_records():
    source=job();source['prompts'][0]['prompt']='x'*VIDEO_PROMPT_LIMIT;before=deepcopy(source)
    with pytest.raises(CharacterError) as error:
        generation_rows(source)
    assert error.value.code=='prompt_length' and '보수적 2,000자' in str(error.value)
    assert source==before


def test_maximum_story_fields_fit_without_repeating_whole_story_or_slicing():
    source=job()
    source['script']['plan']={key:'상'*300 for key in source['script']['plan']}
    for i,scene in enumerate(source['script']['scenes'],1):
        scene['action']=f'Action {i}: '+('x'*(300-len(f'Action {i}: ')))
        scene['sfx']='a'*120
        scene['caption']='장'*40
    settings={key:source['studio_selection'][key] for key in DEFAULTS}
    source['prompts']=prompts(StudioStoryboard.model_validate(source['script']),settings,source['character'])
    rows=generation_rows(source)
    assert all(len(row['prompt'])<=VIDEO_PROMPT_LIMIT for row in rows)
    assert all(scene['action'] in row['prompt'] and scene['sfx'] in row['prompt'] for scene,row in zip(source['script']['scenes'],rows))


def test_new_quote_reuses_story_locally_with_five_compact_requests(studio):
    s=studio.service
    identifier,provider,estimates=seeded(studio,duration=30,model=O3)
    before=s.read(identifier)
    s.prepare(identifier,consent=True,script_reviewed=True)
    quoted=s.read(identifier)
    assert len(estimates)==5 and provider.uploads==1 and provider.calls==0
    assert all(row['duration']==6 and len(row['prompt'])<=VIDEO_PROMPT_LIMIT for row in estimates)
    assert quoted['script']==before['script'] and quoted['prompts']==before['prompts']
    assert quoted['plan_hash']==before['plan_hash'] and studio.writer.calls==0


def test_oversized_new_prompt_stops_before_upload_or_estimate(studio):
    s=studio.service
    identifier,provider,estimates=seeded(studio,duration=30,model=O3)
    job=s.read(identifier);job['prompts'][0]['prompt']='x'*(VIDEO_PROMPT_LIMIT+1)
    job['plan_hash']=s.plan_hash(job);s.save(job);before=s.read(identifier)
    with pytest.raises(CharacterError) as error:
        s.prepare(identifier,consent=True,script_reviewed=True)
    assert error.value.code=='prompt_length'
    assert provider.uploads==provider.calls==0 and estimates==[] and s.read(identifier)==before


@pytest.mark.parametrize('action',['submit','retry_quote','retry_submit'])
def test_stored_oversized_payload_is_not_rewritten_or_replayed(studio,action):
    s=studio.service
    identifier,provider,estimates=seeded(studio,duration=30,model=O3)
    s.prepare(identifier,consent=True,script_reviewed=True)
    job=s.read(identifier)
    job['scenes'][0]['payload']['prompt']='x'*(VIDEO_PROMPT_LIMIT+1)
    if action=='submit':
        job['quote_hash']=fingerprint([job['plan_hash'],job['scenes'],job['quoted_at'],job['quote_key_id']])
    else:
        job['state']='scene_review';job['scenes'][0]['state']='failed'
        if action=='retry_submit':
            job['retry']={'position':1,'quote_usd':'0.10','at':now().isoformat(),
                'key_id':hashlib.sha256(b'synthetic-only').hexdigest(),'original':fingerprint(job['scenes'][0])}
            job['retry_hash']=fingerprint(job['retry']);job['state']='retry_quoted'
    s.save(job);before=s.read(identifier);old_estimates=deepcopy(estimates)
    with pytest.raises(CharacterError) as error:
        if action=='submit':s.submit(identifier,consent=True,quote_hash=job['quote_hash'])
        elif action=='retry_quote':s.prepare_retry(identifier,consent=True)
        else:s.retry_scene(identifier,consent=True,quote_hash=job['retry_hash'])
    assert error.value.code=='prompt_length'
    assert s.read(identifier)==before and estimates==old_estimates and provider.calls==0
