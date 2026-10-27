"""Full-scene plan/voice contract and media Fake verification, never live providers."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_ai_video_service import add_article, make_draft
from test_voice_engines import config

from newsflow.db.models import (
    AIVideoPlan,
    AIVideoScene,
    AppSetting,
    ContentDraft,
    IntelligenceRun,
    VideoAIModel,
    VideoAIUsage,
)
from newsflow.video.ai.fake import FakeVideoProvider
from newsflow.video.ai.production import COMMON_STYLE, DEFAULT_MODEL, read_contract
from newsflow.video.ai.service import AIVideoCoordinator, AIVideoError
from newsflow.video.ai.settings import save_model, write_settings
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.tts import FakeTTS


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    for name in ['NEWSFLOW_AI_API_KEY','NEWSFLOW_ANTHROPIC_API_KEY','NEWSFLOW_VIDEO_AI_KEY','NEWSFLOW_ELEVENLABS_KEY','NEWSFLOW_IMAGE_DELIVERY_KEY']:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr('urllib.request.OpenerDirector.open', lambda *a, **k: pytest.fail('No external HTTP'))
    monkeypatch.setattr('newsflow.publishing.instagram.MetaUploadTransport.request', lambda *a, **k: pytest.fail('No SNS'))
    monkeypatch.setattr('newsflow.video.tts.WindowsTTS.voice_details', lambda _: [])
    monkeypatch.setattr('newsflow.video.supertonic_tts.SupertonicTTS.voices', lambda _: [])


@pytest.fixture
def full(app, monkeypatch):
    app.state.video_ai.close()
    provider = FakeVideoProvider(steps=1)
    service = AIVideoCoordinator(app.state.sessions, app.state.config.data_dir, app.state.video,
                                 app.state.video_ai.keys, provider)
    monkeypatch.setattr(service, 'wake', lambda: None)
    app.state.video_ai = service
    app.state.video.engine, app.state.video.tts = FakeRenderAdapter(), FakeTTS()
    write_settings(app.state.sessions, provider='higgsfield', approved=True, monthly_limit='', job_limit='', host='api.higgsfield.ai', currency='USD', max_active=2, timeout_minutes=5, poll_seconds=10)
    save_model(app.state.sessions, path=DEFAULT_MODEL, label='PixVerse V6', price_per_second='',
               durations='5,10,15', resolution='720p', confirmed=True)
    draft_id = make_draft(app, add_article(app, 'full'))
    yield SimpleNamespace(app=app, service=service, provider=provider, draft_id=draft_id)
    service.close()
    app.state.video.close()


def rev(full, plan):
    with full.app.state.sessions() as s:
        return s.get(AIVideoPlan, plan).revision


def rows(full, plan):
    with full.app.state.sessions() as s:
        return list(s.scalars(select(AIVideoScene).where(AIVideoScene.plan_id == plan).order_by(AIVideoScene.position)))


def new_plan(full, duration=30, voice='offline-silence'):
    with full.app.state.sessions.begin() as s:
        draft = s.get(ContentDraft, full.draft_id)
        content = deepcopy(draft.content)
        # Six 5/7.5/10-second scenes fit the actual PixVerse 1..15-second input contract.
        content['scenes'] = [deepcopy(content['scenes'][i % len(content['scenes'])]) for i in range(6)]
        for scene in content['scenes']:
            scene['caption'] = '새로운 기술의 변화'
        draft.content = content
        run = s.get(IntelligenceRun, draft.run_id)
        production = {'version': 1, 'script_review': True, 'video_provider': 'higgsfield', 'voice': voice,
                      'external_tts_consent': voice == 'elevenlabs'}
        if voice == 'elevenlabs':
            production['elevenlabs'] = config()
        run.options = {**run.options, 'production_context': {'production_options': production}}
    return full.service.create_plan(full.draft_id, duration, mode='full', model_path=DEFAULT_MODEL)


@pytest.mark.parametrize('duration', [30,45,60])
def test_full_plan_all_scenes_model_style_and_no_guessed_reservation(full, duration):
    plan = new_plan(full, duration)
    scenes = rows(full, plan)
    assert len(scenes) == 6 and all(s.source == 'generated' and s.model_path == DEFAULT_MODEL for s in scenes)
    assert all(COMMON_STYLE in s.prompt and 1 <= s.clip_seconds <= 15 for s in scenes)
    assert scenes[-1].end_ms == duration*1000
    estimate = full.service.estimate(plan)
    assert estimate['can_submit'], estimate['problems']
    assert estimate['total'] == '' and estimate['remaining'] is None
    assert full.provider.calls == []
    with pytest.raises(AIVideoError):
        full.service.confirm_generation(plan, rev(full,plan), '', False)
    assert full.service.confirm_generation(plan, rev(full,plan), '', True) == 6
    with full.app.state.sessions() as s:
        usage=list(s.scalars(select(VideoAIUsage)))
        assert len(usage)==6 and {u.estimated_cost for u in usage}=={'0'}
    with pytest.raises(AIVideoError):
        full.service.confirm_generation(plan, rev(full,plan), '', True)
    assert full.provider.calls == []


def test_full_plan_no_card_fallback_and_model_change_blocks_before_post(full):
    plan=new_plan(full)
    with pytest.raises(AIVideoError,match='카드'):
        full.service.update_scenes(plan, rev(full,plan), [{'position':0,'source':'card'}])
    full.service.confirm_generation(plan, rev(full,plan), '', True)
    with full.app.state.sessions.begin() as s:
        row=s.scalar(select(VideoAIModel).where(VideoAIModel.path==DEFAULT_MODEL))
        row.resolution='1080p'
    full.service.tick()
    assert not any(c[0]=='submit' for c in full.provider.calls)


def test_full_plan_unknown_never_replays(full):
    plan=new_plan(full)
    full.service.update_scenes(plan, rev(full,plan), [{'position':0, 'source':'generated',
        'prompt': COMMON_STYLE+' [fake:ambiguous]', 'model_path':DEFAULT_MODEL}])
    full.service.confirm_generation(plan, rev(full,plan), '', True)
    full.service.tick()
    unknown=next(s for s in rows(full,plan) if s.status=='unknown')
    unknown_key=unknown.submit_key
    full.service.recover()
    full.service.tick()
    assert len([c for c in full.provider.calls if c[0]=='submit' and c[2]==unknown_key])==1
    assert any(s.status=='unknown' for s in rows(full,plan))
    with pytest.raises(AIVideoError):
        full.service.confirm_generation(plan, rev(full,plan), '', True)


@pytest.mark.parametrize('voice',['offline-silence','elevenlabs'])
def test_voice_model_consent_frozen_and_clips_reused_for_composition(full, monkeypatch, voice):
    plan=new_plan(full, voice=voice)
    with full.app.state.sessions() as s:
        saved=read_contract(s,plan)
    assert saved['production']['voice']==voice
    # Global voice/model edits cannot replace the existing production snapshot.
    with full.app.state.sessions.begin() as s:
        row=s.get(AppSetting,'preview_voice')
        if row: row.value='other-voice'
    captured=[]
    monkeypatch.setattr(full.app.state.video,'_start',lambda *a,**k: captured.append((a,k)) or 123)
    clips=full.app.state.video.clip_store
    specs=[]
    for index in range(6):
        target=clips.new_path()
        target.write_bytes(b'Fake validated clip handle')
        import hashlib
        specs.append({'clip':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    monkeypatch.setattr(clips,'path',lambda name: clips.root/name)
    full.app.state.video.start_ai(plan,full.draft_id,30,specs,clips)
    assert captured[0][0][2]==voice
    assert captured[0][1]['external_tts_consent']==(voice=='elevenlabs')
    if voice=='elevenlabs':
        assert captured[0][1]['elevenlabs_config']==config()
    assert not full.provider.calls


def test_full_ai_gui_defaults_and_empty_cost_confirmation(full):
    from conftest import csrf
    from fastapi.testclient import TestClient
    with TestClient(full.app, base_url='http://127.0.0.1') as client:
        plan=new_plan(full)
        text=client.get(f'/video/ai/plans/{plan}').text
        assert '전체 장면 유료 생성 승인' in text and '전체 AI 영상' in client.get('/video/ai').text
        response=client.post(f'/video/ai/plans/{plan}/confirm',data={
            'csrf_token':csrf(client),'revision':rev(full,plan),'shown_total':'','confirmed':'true'},follow_redirects=False)
        assert response.status_code==303

def test_current_status_and_preflight_do_not_require_guessed_money(full, monkeypatch):
    from pathlib import Path

    from newsflow.gui.production_status import production_context
    from newsflow.video.ai.preflight import inspect_setup
    keys = SimpleNamespace(status=lambda: {'configured': True}, key=lambda: 'syntheticid:syntheticsecret-value')
    monkeypatch.setattr(full.service, 'keys', keys)
    monkeypatch.setattr('newsflow.video.ai.preflight.FFmpegAdapter.check',
                        lambda _: (Path('fake-ffmpeg'), Path('fake-probe'), 'test'))
    report = inspect_setup(full.app.state.sessions, keys, reported=True)
    assert report['local_ready'], report['checks']
    assert report['actual_service'] == 'NOT VERIFIED' and report['new_reservations'] == 0
    assert inspect_setup(full.app.state.sessions, keys)['local_ready'] is False  # preserved legacy contract
    context = production_context(SimpleNamespace(app=full.app))
    state = context['provider_statuses']['higgsfield']
    assert state['status_code'] == 'configured'
    assert '예산' not in state['configuration'] and '미검증' in state['configuration']
    keys.status = lambda: {'configured': False}
    assert not inspect_setup(full.app.state.sessions, keys, reported=True)['local_ready']
    assert full.provider.calls == []
