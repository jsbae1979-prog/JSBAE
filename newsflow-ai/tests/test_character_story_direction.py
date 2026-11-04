"""Profile-linked story direction: local Fake responses, no network or keys."""
from copy import deepcopy
import json
import pytest

from newsflow.character.claude import CharacterWriter,StudioResponseError
from newsflow.character.studio_story import INSTRUCTION,StudioStoryboard,prompts
from newsflow.character.episode_story import SCRIPT_INSTRUCTION,script_input,EpisodeScript,prompts as episode_prompts
from newsflow.character.kling import DEFAULTS,O3
from newsflow.video_models.catalog import CATALOG
from newsflow.intelligence.provider import Options
from test_character_episode_schema import profile,script
from test_character_kling_studio import story


def test_two_characters_are_passed_to_studio_writer_without_visual_data_or_cross_contamination(monkeypatch):
    bodies=[];writer=CharacterWriter(lambda:'synthetic-only')
    def fake(body,options):
        bodies.append(deepcopy(body))
        value=story(15,'off')
        return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value)}]}
    monkeypatch.setattr(writer,'_post',fake)
    first=profile('합성 토끼','rabbit');second=profile('합성 펭귄','penguin')
    second.update(personality='느긋하고 엉뚱함',comedy_formula={'world':'학교','setup':'자꾸 뒤바뀌는 가방','reaction':'태연히 다른 길로 걸어감'})
    before=deepcopy([first,second])
    for p in (first,second):
        writer.write_studio({'topic':'같은 합성 주제','duration':15,'scene_count':5,'clip_seconds':3,'sound':'on','character':p},
                            Options(model='claude-sonnet-4-6'),reference=object())
    values=[json.loads(body['messages'][0]['content'])['character'] for body in bodies]
    for p,value in zip((first,second),values):
        assert value['name']==p['name_ko'] and value['personality']==p['personality']
        assert value['recurring_situation']==p['comedy_formula']['setup']
        assert value['signature_reaction']==p['comedy_formula']['reaction'] and value['world']==p['comedy_formula']['world']
        assert not {'appearance','appearance_en','style_lock','style_en','reference_image','asset'} & value.keys()
    assert values[0]['name'] not in json.dumps(values[1],ensure_ascii=False)
    assert [first,second]==before


def test_current_episode_input_has_same_canonical_character_directions():
    p=profile();p['supporting_cast']=[{'id':'helper','appearance':'Visual description not sent to writer'}]
    value=script_input(p,'합성 주제',15,CATALOG.model(O3),True)['character']
    assert value['name']==p['name_ko'] and value['recurring_situation']==p['comedy_formula']['setup']
    assert value['signature_reaction']==p['comedy_formula']['reaction']
    assert 'appearance' not in json.dumps(value) and 'style_lock' not in value


@pytest.mark.parametrize('instruction',[INSTRUCTION,SCRIPT_INSTRUCTION])
def test_instructions_link_character_situation_and_signature_ending(instruction):
    assert 'No fixed mascot or workplace plot' not in instruction
    for field in ('recurring_situation','signature_reaction','personality','world'):
        assert 'input.character.'+field in instruction
    assert 'last scene' in instruction and 'plan.punchline' in instruction


@pytest.mark.parametrize('sound',['on','off'])
def test_legacy_roles_and_ambient_sound_never_request_old_saved_dialogue(sound):
    value=StudioStoryboard.model_validate(story(15,'on'))
    original=value.model_dump()
    rows=prompts(value,{**DEFAULTS,'sound':sound})
    assert 'Establish the situation clearly.' in rows[0]['prompt']
    assert 'contrast between the character' in rows[1]['prompt']
    assert "Comedic payoff: hold the character's reaction" in rows[-1]['prompt']
    for row in rows:
        assert 'No dialogue, no voices, no music.' in row['prompt']
        assert '반가워요' not in row['prompt'] and 'lip sync' not in row['prompt']
        assert 'In-character Korean dialogue' not in row['prompt'] and 'Infer natural Korean' not in row['prompt']
        if sound=='on':assert 'Ambient sound effects only:' in row['prompt']
    assert value.model_dump()==original  # Legacy narration bytes are not rewritten.


def test_current_episode_prompts_include_punchline_role_and_ambient_only_sound():
    value=EpisodeScript.model_validate(script())
    rows=episode_prompts(value,{**DEFAULTS,'sound':'on'},profile())
    assert 'Establish the situation clearly.' in rows[0]['prompt']
    assert 'Comedic payoff:' in rows[-1]['prompt']
    assert all('Ambient sound effects only:' in r['prompt'] and 'No dialogue' in r['prompt'] for r in rows)


def test_writer_rejects_nonempty_new_narration_without_paid_retry(monkeypatch):
    writer=CharacterWriter(lambda:'synthetic-only');calls=[]
    def fake(body,options):
        calls.append(body)
        return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(story(15,'on'))}]}
    monkeypatch.setattr(writer,'_post',fake)
    with pytest.raises(StudioResponseError):
        writer.write_studio({'topic':'합성 주제','duration':15,'scene_count':5,'clip_seconds':3,'sound':'on','character':profile()},Options())
    assert len(calls)==1
