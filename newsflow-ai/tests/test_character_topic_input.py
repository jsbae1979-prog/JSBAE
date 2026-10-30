"""Textarea topic handling: local synthetic drafts, without writer/provider calls."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_api_settings import sessions, store
from test_character_kling_studio import png, studio

from newsflow.character.kling import DEFAULTS, O3, check
from newsflow.character.schema import CharacterError, clean_text, clean_topic
from newsflow.character.registry import CharacterRegistry
from test_character_registry_v3 import profile
from newsflow.creation.image_studio import ImageStudio
from newsflow.gui.character_routes import create as create_route


@pytest.mark.parametrize('separator',['\n','\r','\r\n','\t','\r\n\t'])
def test_normal_textarea_separators_become_topic_spaces_without_relaxing_clean_text(separator):
    assert clean_topic(f'토끼가 정원을 가꾼다{separator}채소를 보고 기뻐한다')=='토끼가 정원을 가꾼다 채소를 보고 기뻐한다'
    with pytest.raises(CharacterError):clean_text(f'토끼{separator}정원',150)


@pytest.mark.parametrize('control',['\x00','\x01','\x08','\x0b','\x0c','\x1b','\x1f','\x7f','\x85'])
def test_other_control_characters_in_topics_are_rejected(control):
    with pytest.raises(CharacterError):clean_topic(f'토끼{control}정원')


@pytest.mark.parametrize('topic',[
    '', ' \r\n\t ', None, '가'*151, '가'*75+'\r\n'+'나'*74,
    '토끼\n sk-ant-synthetic', '토끼\t sk-proj-synthetic', 'Bearer\nsynthetic', 'HF_KEY\t=synthetic',
])
def test_topic_length_and_key_patterns_still_reject_invalid_input(topic):
    with pytest.raises(CharacterError):clean_topic(topic)


@pytest.mark.parametrize('reference_kind',['upload','library'])
def test_two_line_topic_creates_local_o3_thirty_second_draft_with_selected_settings_unchanged(studio,tmp_path,reference_kind):
    service=studio.service
    library=ImageStudio(None,tmp_path/'library',None)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(character=service,image_studio=library,
        config=SimpleNamespace(data_dir=tmp_path))))
    settings={**DEFAULTS,'video_model':O3,'native_resolution':'std','duration':30,'clip_seconds':6,
              'sound':'on','output_quality':'1080p'}
    topic='작은 토끼가 정원에서 채소를 가꾸고\n자라난 채소를 보고 기뻐하는 새로운 이야기'
    asset=(library.save_character(png(),'synthetic.png')['id'] if reference_kind=='library'
           else library.asset_bytes(png()))
    registered=CharacterRegistry(tmp_path,library).save(profile(),asset)
    response=create_route(request=request,
        reference=None,
        topic=topic,episode_limit='5.00',day_limit='10.00',script_model='',video_model='',
        reference_asset='',reference_job='',studio_settings=json.dumps(settings),request_id=uuid4().hex,
        character_id=registered['id'],character_revision=registered['revision'])
    assert response.status_code==200
    result=json.loads(response.body);job=service.read(result['id'])
    assert result['created'] and job['state']=='needs_script' and job['script'] is None
    assert job['automation_version']==1 and job['character_id']==registered['id']
    assert job['topic']==topic.replace('\n',' ') and check(job['studio_selection'])==settings
    assert job['duration']==30 and job['studio_selection']['clip_seconds']==6
    assert studio.writer.calls==0 and studio.clients=={}


def test_legacy_create_uses_topic_normalization_without_changing_prior_jobs(studio):
    service=studio.service
    identifier=service.create('토끼의\r\n새로운\t여행','5','10',reference=png())
    job=service.read(identifier)
    assert job['topic']=='토끼의 새로운 여행' and job['state']=='needs_script'
    assert studio.writer.calls==0 and studio.clients=={}


@pytest.mark.parametrize('topic',['토끼\x00정원','토끼\x1b정원','토끼\nBearer synthetic','가'*61,'가'*151])
def test_route_rejects_other_controls_keys_and_oversize_before_creating_any_draft(studio,topic,tmp_path):
    settings={**DEFAULTS,'video_model':O3,'native_resolution':'std','duration':30,'clip_seconds':6}
    library=ImageStudio(None,tmp_path/'library',None)
    registered=CharacterRegistry(tmp_path,library).save(profile(),library.asset_bytes(png()))
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(character=studio.service,image_studio=library,
        config=SimpleNamespace(data_dir=tmp_path))))
    response=create_route(request=request,
        reference=None,topic=topic,episode_limit='5',day_limit='10',
        script_model='',video_model='',reference_asset='',reference_job='',
        studio_settings=json.dumps(settings),request_id=uuid4().hex,
        character_id=registered['id'],character_revision=registered['revision'])
    assert response.status_code==422 and studio.service.listing()==[]
    assert studio.writer.calls==0 and studio.clients=={}
