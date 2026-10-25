"""Mode-separated selection contracts; synthetic inputs and injected adapters only.

Unsupported image/character options are rejection cases, not newly supported models.
These tests do not certify any provider account, model availability or invoice.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from test_api_settings import configured
from test_character_shorts import Video, Writer, png, prepared
from test_final_production import full as full  # noqa: PLC0414
from test_final_production import new_plan
from test_image_generation import KEY, FakeImage, Wire
from test_image_posts import article

from newsflow.character.higgsfield_client import MODEL as CHARACTER_MODEL
from newsflow.character.schema import CharacterError
from newsflow.character.service import CharacterService
from newsflow.db.models import AIUsage, AIVideoPlan, AppSetting, IntelligenceRun
from newsflow.intelligence.api_settings import FakeAPIBudgetService
from newsflow.intelligence.credentials import AnthropicKeyStore, FakeCipher
from newsflow.publishing.image_generation import (
    MODEL as IMAGE_MODEL,
    ImageGenerationService,
    OpenAIImageAdapter,
)
from newsflow.publishing.service import PublishingError
from newsflow.video.ai.model_contracts import check_model_contract
from newsflow.video.ai.production import DEFAULT_MODEL, model_ready, read_contract
from newsflow.video.ai.service import AIVideoError
from newsflow.video.ai.settings import find_model, save_model


@pytest.fixture(autouse=True)
def fake_only(monkeypatch):
    for name in (
        'HF_KEY', 'NEWSFLOW_AI_API_KEY', 'NEWSFLOW_ANTHROPIC_API_KEY',
        'NEWSFLOW_VIDEO_AI_KEY', 'NEWSFLOW_ELEVENLABS_KEY',
        'NEWSFLOW_IMAGE_DELIVERY_KEY', 'NEWSFLOW_AI_LIVE_TEST',
    ):
        monkeypatch.delenv(name, raising=False)

    def denied(*args, **kwargs):
        pytest.fail('External transport is forbidden in the model-selection contract tests')

    monkeypatch.setattr('urllib.request.OpenerDirector.open', denied)
    monkeypatch.setattr('socket.create_connection', denied)
    monkeypatch.setattr('newsflow.publishing.instagram.MetaUploadTransport.request', denied)
    monkeypatch.setattr('newsflow.video.tts.WindowsTTS.voice_details', lambda _: [])
    monkeypatch.setattr('newsflow.video.supertonic_tts.SupertonicTTS.voices', lambda _: [])


@pytest.fixture
def modes(full, tmp_path):
    app = full.app
    configured(app.state.sessions)
    keys = AnthropicKeyStore(tmp_path / 'synthetic-character-key', FakeCipher())
    keys.save('sk-synthetic-mode-selection-character-0123456789')
    character_video, writer = Video(), Writer()
    character = CharacterService(
        tmp_path / 'synthetic-character', app.state.sessions, keys,
        writer=writer, video=character_video,
        budget=FakeAPIBudgetService(app.state.sessions),
    )
    image = app.state.image_generation
    image.keys = SimpleNamespace(key=lambda: KEY, status=lambda: {'configured': True})
    image.adapter = FakeImage(usage=None)
    return SimpleNamespace(
        news=full, image=image, article_id=article(app),
        character=SimpleNamespace(service=character, video=character_video, writer=writer,
                                  sessions=app.state.sessions, store=keys),
    )


def test_three_modes_keep_snapshots_when_next_job_defaults_change(modes):
    full = modes.news
    plan_id = new_plan(full)
    character_id = modes.character.service.create('합성 모드 분리 확인', '5', '20', reference=png())
    image_id = modes.image.generate(modes.article_id, consent=True)
    with full.app.state.sessions() as session:
        news_before = deepcopy(read_contract(session, plan_id))
    character_before = deepcopy(modes.character.service.read(character_id))
    image_before = deepcopy(modes.image.get(image_id).options)

    # Editing next-job defaults does not authorize or rewrite any existing mode.
    changes = {'studio_provider': 'openai', 'studio_model_openai': 'gpt-4.1-mini',
               'studio_model_claude_api': 'claude-opus-4-6',
               'video_default_voice': 'changed-next-job-only', 'video_ai_provider': 'off'}
    with full.app.state.sessions.begin() as session:
        for key, value in changes.items():
            row = session.get(AppSetting, key)
            if row is None:
                session.add(AppSetting(key=key, value=value))
            else:
                row.value = value
    with full.app.state.sessions() as session:
        assert read_contract(session, plan_id) == news_before
    assert news_before['model']['path'] == DEFAULT_MODEL
    assert modes.character.service.read(character_id) == character_before
    assert character_before['model'] == CHARACTER_MODEL
    assert character_before['claude_model'] == 'claude-sonnet-4-6'
    assert modes.image.get(image_id).options == image_before
    assert image_before['model'] == IMAGE_MODEL
    assert modes.image.generate(modes.article_id, consent=True) == image_id
    assert len(modes.image.adapter.calls) == 1
    assert full.provider.calls == []
    assert modes.character.writer.calls == modes.character.video.calls == 0


def test_unverified_video_model_has_no_invented_price_and_cannot_make_full_plan(modes):
    full = modes.news
    path = 'synthetic/unverified/text-to-video'
    save_model(full.app.state.sessions, path=path, label='Synthetic unverified model',
               price_per_second='', durations='5,10', resolution='720p', confirmed=True)
    model = find_model(full.app.state.sessions, path)
    assert model is not None and model.price_per_second is None
    assert check_model_contract(path, model.durations, model.resolution)[0] == 'NOT VERIFIED'
    assert not model_ready(model)
    with full.app.state.sessions() as session:
        before = session.scalar(select(func.count()).select_from(AIVideoPlan))
    with pytest.raises(AIVideoError, match='모델'):
        full.service.create_plan(full.draft_id, 30, mode='full', model_path=path)
    with full.app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AIVideoPlan)) == before
    assert full.provider.calls == []
    assert modes.image.adapter.calls == []
    assert modes.character.video.calls == modes.character.writer.calls == 0


def test_image_generation_is_fixed_wire_and_does_not_accept_unimplemented_choices(modes):
    wire = Wire()
    OpenAIImageAdapter(wire).generate('Synthetic editorial illustration', KEY)
    assert len(wire.calls) == 1
    request, timeout = wire.calls[0]
    payload = json.loads(request.data)
    assert payload['model'] == IMAGE_MODEL
    assert payload['size'] == '1024x1280' and payload['quality'] == 'medium'
    assert payload['n'] == 1 and payload['output_format'] == 'jpeg' and timeout == 180
    assert not {'image', 'image_urls', 'reference', 'aspect_ratio'} & payload.keys()

    # An uploaded local-card photo is not an image-generation reference API.
    for option in ({'model': 'unsupported-model'}, {'aspect_ratio': '9:16'},
                   {'reference': png()}):
        with pytest.raises(TypeError):
            modes.image.generate(modes.article_id, consent=True, **option)
    with pytest.raises(PublishingError, match='뉴스'):
        modes.image.generate(2147483647, consent=True)
    assert modes.image.adapter.calls == []
    assert modes.image.recent(modes.article_id) == []


def test_image_unknown_preserves_model_context_without_claiming_zero_cost_or_replay(modes):
    modes.image.adapter.failure = TimeoutError('Synthetic interruption')
    identifier = modes.image.generate(modes.article_id, consent=True)
    before = modes.image.get(identifier)
    assert before.status == 'unknown' and before.provider == 'openai'
    assert before.options['model'] == IMAGE_MODEL
    assert before.options['request_hash'] and before.evidence['source']['article_id'] == modes.article_id
    assert before.result['usage'] is None
    assert before.result['billing'] == 'provider_invoice_not_verified'
    rebuilt = ImageGenerationService(modes.image.sessions, modes.image.outputs.parent.parent,
                                     modes.image.keys, adapter=modes.image.adapter)
    rebuilt.recover()
    assert rebuilt.generate(modes.article_id, consent=True) == identifier
    after = rebuilt.get(identifier)
    assert after.options == before.options and after.evidence == before.evidence
    assert after.status == 'unknown' and after.result == before.result
    assert len(modes.image.adapter.calls) == 1
    with modes.image.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AIUsage).where(AIUsage.run_id == identifier)) == 0
        assert session.get(IntelligenceRun, identifier).status == 'unknown'


def test_character_fixed_model_reference_quote_and_plan_change_are_not_silently_substituted(modes):
    character = modes.character
    with pytest.raises(TypeError):
        character.service.create('합성 미지원 모델', '5', '20', reference=png(), model=DEFAULT_MODEL)
    identifier = prepared(character)
    job = character.service.read(identifier)
    assert job['model'] == CHARACTER_MODEL and job['claude_model'] == 'claude-sonnet-4-6'
    assert job['reference_sha256'] and character.video.uploads == 1
    assert job['quote_total_usd'] == '1.50' and job['reported_billed_usd'] is None
    assert all(scene['payload']['aspect_ratio'] == '9:16'
               and scene['payload']['resolution'] == '720p'
               and scene['payload']['image_urls'] == ['https://example.com/character.png']
               and scene['payload']['generate_audio'] is False for scene in job['scenes'])
    quote_hash = job['quote_hash']
    job['claude_model'] = 'synthetic-changed-after-review'
    character.service.save(job)
    with pytest.raises(CharacterError):
        character.service.submit(identifier, consent=True, quote_hash=quote_hash)
    assert character.video.calls == 0 and character.writer.calls == 1
    assert modes.news.provider.calls == [] and modes.image.adapter.calls == []
