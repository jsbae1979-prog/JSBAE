"""Pure request planning: full unspoken context in every actual clip, no provider."""
from copy import deepcopy
import pytest
from newsflow.character.service import generation_rows
from newsflow.character.kling import DEFAULTS,snapshot
from newsflow.character.schema import CharacterError


def job():
    scenes=[{'seconds':3,'role':'setup' if i==1 else 'punchline' if i==5 else 'build',
        'action':f'The original character performs unique office reaction number {i}.',
        'caption':f'설명 자막 {i}','sfx':'quiet office', 'narration':f'LEGACY_SPOKEN_WORDS_{i}'} for i in range(1,6)]
    return {'duration':15,'studio_selection':snapshot({**DEFAULTS,'duration':15,'clip_seconds':3,'sound':'on'}),
        'script':{'title':'월요일 사무실 상황극','plan':{'situation':'지각한 아침','contrast':'태평한 반응','punchline':'회의가 내일'},
          'hook_caption':'늦은 출근','end_caption':'태평한 월요일','scenes':scenes},
        'prompts':[{'position':i,'seconds':3,'prompt':f'Act naturally on current beat {i}.'} for i in range(1,6)],
        'scenes':[{'state':'submitted','payload':{'duration':15,'prompt':'immutable legacy request'}}]}


def test_every_stateless_clip_gets_all_five_story_beats_but_only_its_own_generation_focus():
    source=job();before=deepcopy(source)
    rows=generation_rows(source)
    assert len(rows)==5 and [row['seconds'] for row in rows]==[3]*5
    for row in rows:
        prompt=row['prompt']
        assert source['script']['title'] in prompt
        assert all(value in prompt for value in source['script']['plan'].values())
        for scene in source['script']['scenes']:
            assert scene['action'] in prompt and scene['caption'] in prompt
            assert scene['narration'] not in prompt
        assert f"Generate only this beat {row['position']} of 5, duration 3 seconds." in prompt
        assert prompt.count('Generate only this beat ')==1
        assert 'UNSPOKEN direction' in prompt and 'No voiceover or narrator.' in prompt
        assert 'Never read descriptions, captions, titles or timing markers aloud.' in prompt
        assert prompt.endswith(source['prompts'][row['position']-1]['prompt']) and len(prompt)<=4500
    assert source==before  # No stored prompts, accepted old payload or plan data is edited.


def test_full_context_over_limit_is_rejected_without_truncating_or_mutating_stored_payloads():
    source=job();source['prompts'][0]['prompt']='x'*4450;before=deepcopy(source)
    with pytest.raises(CharacterError):generation_rows(source)
    assert source==before
