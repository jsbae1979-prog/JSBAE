"""Step 13K synthetic mode contracts. No provider traffic, live keys or user media."""
import json
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

import pytest
from conftest import csrf
from PIL import Image
from test_character_shorts import Video, png

from newsflow.character.schema import CharacterError
from newsflow.character.service import CharacterService
from newsflow.creation.catalog import (
    DEFAULTS,
    IMAGE_MODELS,
    IMAGE_QUALITIES,
    IMAGE_SIZES,
    SelectionError,
    check_snapshot,
    read_defaults,
    save_defaults,
    validate,
)
from newsflow.db.models import AppSetting
from newsflow.publishing.image_generation import ImageGenerationError, OpenAIImageAdapter
from newsflow.publishing.service import PublishingError


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a, **kw):
        pytest.fail('Live provider transport is forbidden')
    monkeypatch.setattr('urllib.request.OpenerDirector.open', deny)
    for key in ('HF_KEY','NEWSFLOW_AI_API_KEY','NEWSFLOW_ANTHROPIC_API_KEY','NEWSFLOW_VIDEO_AI_KEY'):
        monkeypatch.delenv(key, raising=False)


class Fake:
    def __init__(self, error=None):
        self.calls=[]
        self.error=error
    def generate(self, prompt, key, *, selection):
        self.calls.append((prompt, selection.copy()))
        assert key == 'synthetic-only-image-key'
        if self.error:
            raise self.error
        image=BytesIO()
        Image.new('RGB',tuple(map(int,selection['size'].split('x'))),'teal').save(image,'JPEG')
        return image.getvalue(), {'input_tokens':10,'output_tokens':20,'total_tokens':30}


@pytest.fixture
def service(app):
    generation=app.state.image_generation
    generation.keys=SimpleNamespace(key=lambda:'synthetic-only-image-key',status=lambda:{'configured':True})
    generation.adapter=Fake()
    return app.state.image_studio


@pytest.mark.parametrize('mode',['image','character'])
def test_mode_defaults_do_not_write_other_mode_or_news(app,mode):
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key='studio_model_claude_api',value='preserved-news-model'))
    before=read_defaults(app.state.sessions, 'character' if mode=='image' else 'image')
    chosen=deepcopy(DEFAULTS[mode])
    chosen['quality' if mode=='image' else 'script_model']='high' if mode=='image' else 'claude-opus-4-6'
    save_defaults(app.state.sessions,mode,chosen)
    assert read_defaults(app.state.sessions,mode)==chosen
    assert read_defaults(app.state.sessions,'character' if mode=='image' else 'image')==before
    with app.state.sessions() as session:
        assert session.get(AppSetting,'studio_model_claude_api').value=='preserved-news-model'


@pytest.mark.parametrize('model',IMAGE_MODELS)
@pytest.mark.parametrize('size',IMAGE_SIZES)
@pytest.mark.parametrize('quality',IMAGE_QUALITIES)
def test_image_contract_variants_frozen_and_wire_options(service,model,size,quality):
    chosen={'provider': 'openai','model': model,'size': size,'quality': quality}
    identifier=service.create('합성 그림 '+model+size+quality,chosen)
    save_defaults(service.sessions,'image',DEFAULTS['image'])
    assert check_snapshot(service.get(identifier).options['selection'],'image')==chosen
    run=service.execute(identifier,consent=True,reviewed=True)
    assert service.generation.get(run).status=='success'
    assert service.generation.adapter.calls[0][1]==chosen
    with Image.open(service.generation.path(run)) as image:
        assert image.size==tuple(map(int,size.split('x')))
    assert service.execute(identifier,consent=True,reviewed=True)==run
    assert len(service.generation.adapter.calls)==1
    assert service.get(identifier).options['selection']['price_basis']['amount'] is None


@pytest.mark.parametrize('mode,field,value',[
    ('image','model','not-supported'),('image','provider','claude'),('image','size','9000x9000'),
    ('image','quality','auto-invented'),('character','video_model','wan-3.0'),
    ('character','script_provider','openai'),('character','resolution','4k')])
def test_unsupported_combinations_rejected(mode,field,value):
    chosen=deepcopy(DEFAULTS[mode]);chosen[field]=value
    with pytest.raises(SelectionError):validate(mode,chosen)


@pytest.mark.parametrize('consent,reviewed',[(False,False),(True,False),(False,True)])
def test_explicit_approval_required(service,consent,reviewed):
    identifier=service.create('합성 이미지',DEFAULTS['image'])
    with pytest.raises(PublishingError):service.execute(identifier,consent=consent,reviewed=reviewed)
    assert service.generation.adapter.calls==[]


@pytest.mark.parametrize('error,status',[(TimeoutError(),'unknown'),
    (ImageGenerationError('authentication_failed',uncertain=False,http_status=401),'failed')])
def test_failed_request_never_replayed(service,error,status):
    service.generation.adapter=Fake(error)
    identifier=service.create('실패 합성 이미지',DEFAULTS['image'])
    run=service.execute(identifier,consent=True,reviewed=True)
    service.generation.recover()
    assert service.execute(identifier,consent=True,reviewed=True)==run
    assert service.generation.get(run).status==status
    assert len(service.generation.adapter.calls)==1


def test_reference_local_only_and_reusable(service):
    identifier=service.create('참조 그림',DEFAULTS['image'],reference=png())
    row=service.get(identifier)
    assert service.asset(row.options['reference']).is_file()
    with pytest.raises(PublishingError,match='미구현'):service.execute(identifier,consent=True,reviewed=True)
    assert service.generation.adapter.calls==[]


@pytest.mark.parametrize('name',['../secret.png','C:/secret.png','https://example.com/image.png','studio-'+'0'*64+'.png'])
def test_asset_path_and_hash_protection(service,name):
    with pytest.raises((ValueError,OSError,PublishingError)):
        service.asset(name)


def test_output_reuse_requires_review_preserves_old_asset(service):
    identifier=service.create('재사용 그림',DEFAULTS['image'])
    service.execute(identifier,consent=True,reviewed=True)
    with pytest.raises(PublishingError):service.export(identifier)
    name=service.export(identifier,reviewed=True)
    before=service.asset(name).read_bytes()
    assert service.export(identifier,reviewed=True)==name
    assert service.asset(name).read_bytes()==before


def test_user_store_is_separate(app,tmp_path,service):
    from newsflow.config import Settings
    from newsflow.main import create_app
    from newsflow.news.rss_adapter import FakeRSSAdapter
    second=create_app(Settings(data_dir=tmp_path/'other-user'),FakeRSSAdapter({}))
    chosen={**DEFAULTS['image'],'quality':'high'}
    save_defaults(app.state.sessions,'image',chosen)
    assert read_defaults(second.state.sessions,'image')==DEFAULTS['image']
    identifier=service.create('다른 사용자와 분리',chosen)
    with pytest.raises(PublishingError):second.state.image_studio.get(identifier)
    assert second.state.image_generation.keys.path.parent != app.state.config.data_dir
    assert app.state.api_keys['claude_api'].path!=second.state.api_keys['claude_api'].path


def test_character_selection_frozen_and_injected_video_preserved(app,tmp_path):
    fake=Video()
    character=CharacterService(tmp_path/'character-test',app.state.sessions,SimpleNamespace(key=lambda:'fake'),video=fake)
    chosen={**DEFAULTS['character'],'script_model':'claude-opus-4-6'}
    identifier=character.create('합성 캐릭터','5','20',reference=png(),selection=chosen)
    save_defaults(app.state.sessions,'character',DEFAULTS['character'])
    job=character.read(identifier)
    assert job['claude_model']=='claude-opus-4-6'
    assert character.video_for(job) is fake
    assert job['selection']['account_verified'] is False
    job['claude_model']='claude-sonnet-4-6'
    character.save(job)
    with pytest.raises(CharacterError):character.read(identifier)


def test_ui_local_save_no_provider_call_and_csrf(client,service):
    token=csrf(client)
    assert client.get('/image-studio').status_code==200
    form={'prompt': 'GUI 합성 이미지','model': IMAGE_MODELS[0],'size': '1024x1024','quality': 'low'}
    assert client.post('/image-studio/drafts',data=form).status_code==403
    response=client.post('/image-studio/drafts',data={**form,'csrf_token':token})
    assert response.status_code==200
    assert '이미지 초안 #' in response.text
    assert service.generation.adapter.calls==[]
    assert '1024x1024' in response.text


def test_character_ui_choice_and_saved_reference(client,service):
    token=csrf(client)
    name=service.asset_bytes(png())
    response=client.get('/character?reference_asset='+name)
    assert response.status_code==200 and 'claude-opus-4-6' in response.text
    response=client.post('/character',data={'csrf_token': token,'topic': 'GUI 캐릭터','episode_limit': '5','day_limit': '20',
        'reference_asset': name,'script_model': 'claude-opus-4-6','video_model': DEFAULTS['character']['video_model']})
    assert response.status_code==200 and 'claude-opus-4-6' in response.text
    assert service.generation.adapter.calls==[]


@pytest.mark.parametrize('value',[b'not an image', b'', b'x'*(10*1024*1024+1)], ids=['invalid','empty','oversize'])
def test_invalid_reference_not_saved(service,value):
    with pytest.raises(PublishingError): service.asset_bytes(value)
    assert service.assets()==[]


def test_snapshot_tampering_stops_before_key_or_adapter(service):
    identifier=service.create('고정 계약',DEFAULTS['image'])
    from newsflow.db.models import IntelligenceRun
    with service.sessions.begin() as session:
        row=session.get(IntelligenceRun,identifier)
        options=deepcopy(row.options)
        options['selection']['quality']='high'
        row.options=options
    service.generation.keys.key=lambda:pytest.fail('Key loaded before validating snapshot')
    with pytest.raises(SelectionError): service.execute(identifier,consent=True,reviewed=True)
    assert service.generation.adapter.calls==[]


def test_character_new_key_source_and_legacy_source_do_not_mix(app,tmp_path):
    keys=SimpleNamespace(key=lambda:'synthetic-claude')
    video_keys=SimpleNamespace(key=lambda:'synthetic-user-higgsfield')
    service=CharacterService(tmp_path/'characters',app.state.sessions,keys,video_keys=video_keys)
    old=service.create('이전 작업','5','20',reference=png())
    new=service.create('새 작업','5','20',reference=png(),selection=DEFAULTS['character'])
    assert service.video_for(service.read(old)) is service.video
    assert service.video_for(service.read(new)).credential()=='synthetic-user-higgsfield'
    assert service.read(new)['selection']['credential_source']=='user_store'


@pytest.mark.parametrize('model',IMAGE_MODELS)
def test_adapter_preserves_existing_endpoint_with_chosen_options(model):
    from test_image_generation import KEY, Wire
    wire=Wire()
    chosen={**DEFAULTS['image'],'model':model,'size':'1024x1024','quality':'high'}
    OpenAIImageAdapter(wire).generate('합성 wire',KEY,selection=chosen)
    request,timeout=wire.calls[0]
    payload=json.loads(request.data)
    assert request.full_url=='https://api.openai.com/v1/images/generations'
    assert payload['model']==model and payload['size']=='1024x1024' and payload['quality']=='high'
    assert payload['n']==1 and payload['moderation']=='auto' and timeout==180
    assert 'image' not in payload and 'tools' not in payload


def test_news_video_default_is_separate_and_rejects_unverified(app):
    from newsflow.creation.catalog import news_video_default, save_news_video_default
    from newsflow.video.ai.settings import save_model
    path='kling-video/v3.0-turbo/text-to-video'
    save_model(app.state.sessions,path=path,label='Kling synthetic registration',price_per_second='',
               durations='3,5,10,15',resolution='720p',confirmed=True)
    other=read_defaults(app.state.sessions,'character')
    save_news_video_default(app.state.sessions,path)
    assert news_video_default(app.state.sessions)==path
    assert read_defaults(app.state.sessions,'character')==other
    with pytest.raises(SelectionError):save_news_video_default(app.state.sessions,'unsupported/path')
    assert news_video_default(app.state.sessions)==path
