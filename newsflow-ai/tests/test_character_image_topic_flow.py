"""Image + topic without registration/analysis; only injected Fake authoring/video."""
from copy import deepcopy
import json
from uuid import uuid4
import pytest
from newsflow.character.kling import check
from newsflow.character.registry import CharacterRegistry
from test_api_settings import sessions
from test_character_automation_routes import gui
from test_character_operating_authoring import connected

def create(c,**changes):
    settings=check(c.service.read(c.identifier)['studio_selection'])
    return c.post('/character',topic='주어진 캐릭터가 우산을 찾는 이야기',episode_limit='5',
      studio_settings=json.dumps(settings),request_id=uuid4().hex,reference_asset=c.gui.asset,**changes)

def test_image_topic_creates_draft_without_registration_or_analysis_and_keeps_exact_reference(connected):
    c=connected;registry=CharacterRegistry(c.gui.root,c.gui.app.state.image_studio);before=registry.list()
    result=create(c);assert result.status_code==200,result.text
    identifier=result.json()['id'];job=c.service.read(identifier)
    assert job['state']=='needs_script' and job['character_reference_mode']=='image_topic'
    assert registry.list()==before and not c.state.calls and not c.state.decryptions and not c.video.sent
    assert job['character']['id'].startswith('ref_') and job['character']['species']==''
    assert c.service.folder(identifier).joinpath('reference.png').exists()
    response=c.post('/api/studio/characters/auto-story',job_id=identifier,consent='true')
    assert response.status_code==200,response.text
    job=c.service.read(identifier);assert job['state']=='script_review' and len(c.state.calls)==1
    assert c.state.calls[0][0]=='claude_api' and not c.video.sent
    body=c.state.calls[0][1]
    assert 'base64' not in json.dumps(body) and 'image_url' not in json.dumps(body)
    assert registry.list()==before
    c.service.prepare(identifier,consent=True,script_reviewed=True)
    quoted=c.service.read(identifier)
    assert quoted['state']=='quoted' and len(quoted['scenes'])==len(quoted['script']['scenes'])
    assert c.video.uploads and not c.video.sent
    assert all('no dialogue, no voices, no music' in row['prompt'].lower() for row in quoted['scenes'])

def test_registered_profile_path_is_preserved_and_references_cannot_be_mixed(connected):
    c=connected;before=deepcopy(c.service.read(c.identifier))
    response=create(c,character_id=c.profile['id'],character_revision=c.profile['revision'])
    assert response.status_code==422 and c.service.read(c.identifier)==before
    assert not c.state.calls

def test_image_only_reference_is_path_checked(connected):
    c=connected;settings=check(c.service.read(c.identifier)['studio_selection'])
    response=c.post('/character',topic='합성 주제',episode_limit='5',studio_settings=json.dumps(settings),
      request_id=uuid4().hex,reference_asset='../outside.png')
    assert response.status_code==422 and not c.state.calls


def test_uploaded_image_does_not_force_reference_library_registration(connected):
    from test_character_episode_schema import image
    c=connected;settings=check(c.service.read(c.identifier)['studio_selection'])
    before=c.gui.app.state.image_studio.characters()
    response=c.client.post('/character',data={
      'topic':'작은 실수에서 시작되는 모험','episode_limit':'5','studio_settings':json.dumps(settings),
      'request_id':uuid4().hex,'csrf_token':c.client.cookies.get('newsflow_csrf')},
      files={'reference':('original.png',image('red'),'image/png')},headers={'Origin':c.launch.origin})
    assert response.status_code==200,response.text
    assert c.gui.app.state.image_studio.characters()==before
    assert not c.state.calls and not c.video.sent


def test_two_unregistered_images_remain_isolated_without_creating_profiles(connected):
    from test_character_episode_schema import image
    c=connected;before=CharacterRegistry(c.gui.root,c.gui.app.state.image_studio).list()
    first=create(c).json()['id']
    other_asset=c.gui.app.state.image_studio.asset_bytes(image('orange'))
    settings=check(c.service.read(c.identifier)['studio_selection'])
    response=c.post('/character',topic='다른 이미지의 별도 이야기',episode_limit='5',studio_settings=json.dumps(settings),
      request_id=uuid4().hex,reference_asset=other_asset)
    assert response.status_code==200
    a,b=c.service.read(first),c.service.read(response.json()['id'])
    assert a['character_id']!=b['character_id'] and a['reference_sha256']!=b['reference_sha256'] and a['topic']!=b['topic']
    assert CharacterRegistry(c.gui.root,c.gui.app.state.image_studio).list()==before and not c.state.calls
