"""Pure versioned episode schema, duration and silent-comedy prompt contracts."""
from copy import deepcopy
import io
from PIL import Image
import pytest
from newsflow.character.episode_story import (EpisodeScript,base_scene_count,scene_range,validate_episode,scene_prompt,script_input)
from newsflow.character.kling import O3
from newsflow.character.schema import CharacterError
from newsflow.video_models.catalog import CATALOG

def image(color='blue'):
    stream=io.BytesIO(); Image.new('RGB',(144,256),color).save(stream,'PNG');return stream.getvalue()


def profile(name='별',species='rabbit'):
    return {'name_ko':name,'species':species,'appearance':f'Original {species} with a blue scarf',
            'personality':'호기심이 많고 침착함','comedy_formula':{'world':'정원','setup':'바쁜 아침','reaction':'천천히 해결'},
            'style_lock':'Original soft three dimensional animation','supporting_cast':[],
            'audience':'general','made_for_kids':False}


def script(seconds=15,subject='별',continuation=True):
    lengths={15:[7,7],20:[9,10],35:[11,11,12],50:[12,12,12,13],60:[14,15,15,15]}[seconds]
    return {'schema_version':3,'plan':{'situation':'정원 정리','escalation':'도구가 흩어짐','reaction':'침착한 해결','punchline':'뜻밖의 꽃'},
            'title':subject+'의 정원','hook_caption':'분주한 아침','end_caption':'다음 이야기도 함께',
            'upload':{'title':subject+'의 정원','description':'합성 테스트','hashtags':['#코미디','#창작','#쇼츠']},
            'scenes':[{'no':i+1,'seconds':n,'continuity':'continue' if i and continuation else 'cut',
                       'from':i if i and continuation else None,
                       'action':'The character picks up a fallen garden tool and stacks it beside the same flower pot.',
                       'camera':'Slow push in on the character face','sound':'Leaves rustle softly',
                       'speed':'normal','fast_intensity':None,'freeze_end':'medium' if i==len(lengths)-1 else 'none',
                       'sfx':[{'at':'end','key':'ding'}] if i==len(lengths)-1 else [],'caption':'차분하게 하나씩'}
                      for i,n in enumerate(lengths)]}


@pytest.mark.parametrize('target,expected',[(15,(2,3)),(20,(2,3)),(35,(3,4)),(50,(4,5)),(60,(4,6))])
def test_variable_scene_boundaries_and_edited_duration(target,expected):
    assert base_scene_count(target)==expected
    model=CATALOG.model(O3)
    result=validate_episode(script(target),target,model)
    assert len(result.scenes)==len(script(target)['scenes'])
    assert max(s.seconds for s in result.scenes)<=15


def test_short_model_extends_scene_count():
    model=deepcopy(CATALOG.model(O3));model['duration']={'min':3,'max':5,'step':1,'default':5}
    assert scene_range(60,model)==(12,13)


@pytest.mark.parametrize('change',['future','first','number','hold','key','dialogue','lip','music','too_long','duration','fast'])
def test_bad_episode_rejected(change):
    value=script()
    if change=='future':value['scenes'][1]['from']=2
    if change=='first':value['scenes'][0].update(continuity='continue',**{'from':1})
    if change=='number':value['scenes'][1]['no']=4
    if change=='hold':value['scenes'][-1]['freeze_end']='none'
    if change=='key':value['scenes'][-1]['sfx'][0]['key']='unlicensed'
    if change=='dialogue':value['scenes'][0]['action']='The character speaks a Korean dialogue.'
    if change=='lip':value['scenes'][0]['camera']='Closeup with lip sync'
    if change=='music':value['scenes'][0]['sound']='Cheerful music'
    if change=='too_long':value['scenes'][0]['action']='A'*301
    if change=='duration':value['scenes'][0]['seconds']=14
    if change=='fast':value['scenes'][0]['speed']='fast'
    with pytest.raises((ValueError,CharacterError)):
        validate_episode(value,15,CATALOG.model(O3))


def test_prompts_no_dialogue_and_character_isolation():
    story=EpisodeScript.model_validate(script())
    a=profile('첫째','rabbit');b=profile('둘째','penguin')
    for character in (a,b):
        prompt=scene_prompt(character,story.scenes[0],True)
        assert character['appearance'] in prompt and character['style_lock'] in prompt
        assert 'no dialogue, no voices, no music' in prompt.lower()
        assert 'lip sync' not in prompt and 'Korean' not in prompt
        assert 'Camera:' in prompt and 'Ambient sound effects only:' in prompt
    assert 'rabbit' not in scene_prompt(b,story.scenes[0],False)
    assert 'Sound effects only' not in scene_prompt(b,story.scenes[0],False)
    payload=script_input(a,'합성 주제',15,CATALOG.model(O3),True)
    assert 'appearance' not in payload['character'] and 'reference_image' not in payload['character']
    assert payload['character']['name_ko']=='첫째'


