"""Optional profile metadata and required user character facts, with no AI IO."""
from copy import deepcopy
import json

import pytest

from newsflow.character.authoring import AnalysisCandidate, TOPIC_INSTRUCTION
from newsflow.character.episode_story import SCRIPT_INSTRUCTION, script_input, scene_prompt, EpisodeScript
from newsflow.character.registry import CharacterProfile, channel_style_default
from newsflow.character.schema import CharacterError
from newsflow.character.kling import O3
from newsflow.video_models.catalog import CATALOG, character_config
from test_character_registry_v3 import registry, profile
from test_character_episode_schema import script


def minimal(name='구름'):
    return {'name_ko':name, 'appearance':'An original blue rabbit with a scarf.',
            'personality':'서두르지 않고 주변을 살핀다',
            'comedy_formula':{'setup':'늦은 출근길에 비가 쏟아짐', 'reaction':'큰 잎으로 우산을 만듦'}}


@pytest.mark.parametrize('mode', ['missing', 'empty', 'spaces'])
def test_only_five_required_facts_save_with_local_config_defaults(registry, mode):
    service, asset=registry
    value=minimal()
    if mode!='missing':
        blank='' if mode=='empty' else '   '
        value.update(species=blank,style_lock=blank,audience=blank,supporting_cast=[])
        value['comedy_formula']['world']=blank
    before=deepcopy(value)
    saved=service.save(value,asset)
    assert value==before
    assert saved['species']=='' and saved['comedy_formula']['world']==''
    assert saved['style_lock']==character_config()['style_lock']==channel_style_default()
    assert saved['audience']=='general' and saved['supporting_cast']==[]
    assert service.get(saved['id'])==saved


@pytest.mark.parametrize('field', ['name_ko','appearance','personality','setup','reaction'])
@pytest.mark.parametrize('value', [None,'','   '])
def test_required_five_fields_never_replaced_or_inferred(registry, field, value):
    service, asset=registry
    data=minimal()
    target=data['comedy_formula'] if field in {'setup','reaction'} else data
    if value is None: target.pop(field)
    else: target[field]=value
    with pytest.raises(CharacterError):service.save(data,asset)
    assert service.list()==[]


def test_existing_explicit_metadata_and_snapshots_stay_exact(registry, monkeypatch):
    service, asset=registry
    old=profile()
    old.update(style_lock='Original painted animation style.',audience='older teens')
    saved=service.save(old,asset)
    snapshot=service.snapshot(saved['id'])
    path=service.root/(saved['id']+'.json')
    original=path.read_bytes()
    monkeypatch.setattr('newsflow.character.registry.channel_style_default',lambda:'Changed channel style.')
    assert service.get(saved['id'])==snapshot
    assert path.read_bytes()==original
    for key,value in old.items():assert saved[key]==value
    assert json.loads(original)['profile']['comedy_formula']['world']=='정원'


def test_world_is_derived_by_authoring_instruction_not_fabricated_or_cross_copied(registry):
    service, asset=registry
    first=service.save(minimal('구름'),asset)
    other=minimal('별');other['comedy_formula']['setup']='주방에서 그릇을 정리함'
    other['comedy_formula']['reaction']='가장 작은 접시부터 쌓음'
    second=service.save(other,asset)
    model=CATALOG.model(O3)
    a=script_input(first,'비 오는 아침',15,model,True)
    b=script_input(second,'설거지 뒤',15,model,True)
    assert a['character']['comedy_formula']['world']==b['character']['comedy_formula']['world']==''
    assert a['character']['comedy_formula']['setup']!=b['character']['comedy_formula']['setup']
    assert 'derive a fitting setting from comedy_formula.setup' in TOPIC_INSTRUCTION
    assert 'derive a fitting setting from comedy_formula.setup' in SCRIPT_INSTRUCTION
    assert 'appearance' not in a['character'] and 'style_lock' not in a['character']
    prompt=scene_prompt(first,EpisodeScript.model_validate(script()).scenes[0],True)
    assert first['appearance'] in prompt and first['style_lock'] in prompt
    assert service.get(first['id'])['comedy_formula']==first['comedy_formula']


def test_analysis_schema_keeps_world_required_and_supplied_style_must_be_english(registry):
    service, asset=registry
    with pytest.raises(ValueError):
        AnalysisCandidate.model_validate({'name_ko':'구름','personality':'침착함',
            'comedy_formula':{'setup':'비','reaction':'기다림'}})
    with pytest.raises(CharacterError):service.save({**minimal(),'style_lock':'한글만'},asset)
    with pytest.raises(CharacterError):service.save({**minimal(),'appearance':'토끼'},asset)
    assert service.list()==[]
