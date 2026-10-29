"""Bounded unspoken direction; synthetic lengths only, never private story text."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from newsflow.character.claude import CharacterWriter, StudioResponseError, studio_output_schema
from newsflow.character.schema import Plan, Scene
from newsflow.character.studio_story import INSTRUCTION, StudioStoryboard
from newsflow.intelligence.provider import Options


PAYLOAD={'topic':'합성 정원 이야기','duration':30,'clip_seconds':6,'scene_count':5,'sound':'on'}


def candidate():
    return {'plan':dict(zip(('situation','contrast','punchline'),('P'*size for size in (183,164,186)))),
            'title':'합성 정원','hook_caption':'새로운 정원','end_caption':'다음 이야기',
            'scenes':[{'seconds':6,'role':'setup' if index==0 else 'punchline' if index==4 else 'build',
                       'action':'A rabbit waters a garden.', 'caption':f'장면 {index+1}',
                       'sfx':'S'*size,'narration':''} for index,size in enumerate((62,57,64,66,88))]}


def test_complete_existing_shape_is_valid_with_bounded_studio_direction_and_no_truncation(monkeypatch):
    original=candidate();before=deepcopy(original)
    writer=CharacterWriter(lambda:'synthetic-only');calls=[]
    def reply(body,options):
        calls.append(body)
        return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(original)}]}
    monkeypatch.setattr(writer,'_post',reply)
    result=writer.write_studio(PAYLOAD,Options(model='claude-sonnet-4-6',max_tokens=3000))
    assert result.model_dump()==before==original==writer.last_candidate
    assert len(calls)==1 and writer.last_failure is None
    assert [scene.seconds for scene in result.scenes]==[6]*5


@pytest.mark.parametrize('field',['situation','contrast','punchline'])
def test_studio_plan_still_rejects_over_200_characters_and_keeps_original_candidate(monkeypatch,field):
    value=candidate();value['plan'][field]='P'*201
    writer=CharacterWriter(lambda:'synthetic-only')
    monkeypatch.setattr(writer,'_post',lambda *args:{'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value)}]})
    with pytest.raises(StudioResponseError) as caught:
        writer.write_studio(PAYLOAD,Options(model='claude-sonnet-4-6'))
    assert {'loc':['plan',field],'type':'string_too_long'} in caught.value.diagnostics()['validation_errors']
    assert writer.last_candidate==value


def test_studio_sfx_still_rejects_over_100_characters():
    value=candidate();value['scenes'][0]['sfx']='S'*101
    with pytest.raises(ValidationError):StudioStoryboard.model_validate(value)


def test_legacy_plan_and_sfx_limits_are_unchanged():
    with pytest.raises(ValidationError):Plan(situation='P'*151,contrast='C',punchline='P')
    with pytest.raises(ValidationError):Scene(seconds=6,role='setup',action='A rabbit waits.',caption='장면',sfx='S'*61)


@pytest.mark.parametrize('field,size',[('title',101),('hook_caption',31),('end_caption',31)])
def test_visible_text_limits_remain_unchanged(field,size):
    value=candidate();value[field]='T'*size
    with pytest.raises(ValidationError):StudioStoryboard.model_validate(value)


def test_wire_describes_supported_bounded_lengths_and_prompt_states_them_explicitly():
    schema=studio_output_schema(PAYLOAD)
    for field in ('situation','contrast','punchline'):
        node=schema['$defs']['StudioPlan']['properties'][field]
        assert '"maxLength": 200' in node['description'] and 'maxLength' not in node
    node=schema['$defs']['StudioScene']['properties']['sfx']
    assert '"maxLength": 100' in node['description'] and 'maxLength' not in node
    assert 'at most 200 characters' in INSTRUCTION and 'at most 100 characters' in INSTRUCTION
    assert schema['$defs']['StudioScene']['properties']['seconds']['enum']==[6]
