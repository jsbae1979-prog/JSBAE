"""Real studio controls exercise existing services; no paid/network operations."""
from copy import deepcopy
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from conftest import csrf
from sqlalchemy import select
from test_api_shorts_intelligence import api as api_fixture
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_video import video as video_fixture

from newsflow.db.models import ContentDraft, IntelligenceRun, RenderJob, VideoProject
from newsflow.intelligence.presentation import presentation
from newsflow.intelligence.service import IntelligenceError
from newsflow.publishing.analytics import category_performance
from newsflow.video.engine import FakeRenderAdapter, FFmpegAdapter, RenderError, RenderPlan, ScenePlan
from newsflow.video.service import VideoError
from newsflow.video.tts import FakeTTS

api = api_fixture
video = video_fixture
browser = browser_fixture


@pytest.mark.parametrize('style', ['news', 'explainer', 'briefing'])
def test_style_enters_same_provider_request_and_persists_without_fact_approval(api, style):
    service, adapter, sessions, mode, options, ids = api
    analysis = service.analyze(ids[:1], mode, True, options, news_usage='QUICK')
    with sessions() as session:
        original = deepcopy(session.get(IntelligenceRun, analysis).evidence)
    draft_id = service.generate(analysis, 30, mode, True, options, script_style=style,
                                script_tone='friendly', script_audience='beginner')
    expected = presentation(style, 'friendly', 'beginner')
    assert adapter.payloads[-1][1]['presentation'] == expected
    assert adapter.payloads[-1][2] == options.model
    assert adapter.calls == ['analysis', 'script']
    with sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.sources['presentation'] == expected
        assert draft.review_status == 'review_required'
        assert session.get(IntelligenceRun, draft.run_id).options['presentation'] == expected
        assert session.get(IntelligenceRun, analysis).evidence == original
        assert draft.sources['articles'] == original['articles']


@pytest.mark.parametrize('selection', [{'script_style':'untrusted prompt'}, {'script_tone':'verified'},
                                        {'script_audience':'everyone<script>'}])
def test_invalid_style_or_missing_consent_never_calls_adapter(api, selection):
    service, adapter, _, mode, options, ids = api
    analysis = service.analyze(ids[:1], mode, True, options, news_usage='QUICK')
    with pytest.raises(ValueError):
        service.generate(analysis, 30, mode, True, options, **selection)
    with pytest.raises(IntelligenceError):
        service.generate(analysis, 30, mode, False, options, script_style='explainer')
    assert adapter.calls == ['analysis']


def test_style_post_uses_existing_service_and_csrf(api, app, client, monkeypatch):
    service, adapter, sessions, mode, options, ids = api
    analysis = service.analyze(ids[:1], mode, True, options, news_usage='QUICK')
    monkeypatch.setattr('newsflow.gui.intelligence_routes.service', lambda request, production=None: service)
    token = csrf(client)
    data = {'analysis_id':analysis, 'duration':30, 'provider':mode, 'model':options.model,
            'script_style':'briefing', 'script_tone':'friendly', 'script_audience':'beginner', 'consent':'true'}
    assert client.post('/ai/generate', data=data, follow_redirects=False).status_code == 403
    assert client.post('/ai/generate', data={**data, 'csrf_token':token, 'source_draft_id':999},
                       follow_redirects=False).status_code == 422
    assert adapter.calls == ['analysis']
    response = client.post('/ai/generate', data={**data, 'csrf_token': token}, follow_redirects=False)
    assert response.status_code == 303
    with sessions() as session:
        draft = session.scalar(select(ContentDraft))
        assert draft.sources['presentation']['style'] == 'briefing'
    assert adapter.calls == ['analysis', 'script']


def test_effects_are_job_snapshots_not_global_defaults(video, app):
    coordinator, draft_id = video
    class RecordingEngine(FakeRenderAdapter):
        def __init__(self):
            super().__init__()
            self.plans = []

        def render(self, plan, *args):
            self.plans.append(plan)
            return super().render(plan, *args)
    coordinator.engine = RecordingEngine()
    with app.state.sessions() as session:
        count = len(session.get(ContentDraft, draft_id).content['scenes'])
    effects = ['fade'] * count
    identifier = coordinator.start(draft_id, 30, reviewed=True, effects=effects)
    effects[0] = 'cut'
    coordinator.future.result(timeout=15)
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        project = session.get(VideoProject, job.project_id)
        assert project.snapshot['effects'] == ['fade'] * count
        assert job.status == 'simulated'  # Fake rendering is never marked playable.
    second = coordinator.start(draft_id, 30, reviewed=True)
    coordinator.future.result(timeout=15)
    with app.state.sessions() as session:
        project = session.get(VideoProject, session.get(RenderJob, second).project_id)
        assert project.snapshot['effects'] == ['cut'] * count
    assert [s.effect for s in coordinator.engine.plans[0].scenes] == ['fade'] * count
    assert [s.effect for s in coordinator.engine.plans[1].scenes] == ['cut'] * count


@pytest.mark.parametrize('effects', [[], ['movie=https://evil.invalid'], ['fade'] * 9])
def test_invalid_effects_cannot_render_and_review_remains_required(video, effects):
    coordinator, draft_id = video
    with pytest.raises(VideoError):
        coordinator.start(draft_id, 30, reviewed=True, effects=effects)
    with pytest.raises(VideoError):
        coordinator.start(draft_id, 30, reviewed=False)
    assert not coordinator.guard.locked()


def test_effect_filters_preserve_captions_audio_and_clip_protocols(tmp_path):
    scene = ScenePlan(1, '합성', '자막', clip=tmp_path/'clip.mp4', effect='fade')
    command = FFmpegAdapter.clip_command(Path('ffmpeg'), scene, tmp_path/'overlay.png', tmp_path/'a.wav', tmp_path/'out.mp4')
    filtered = FFmpegAdapter.apply_effect(command, scene)
    assert 'file' == filtered[filtered.index('-protocol_whitelist') + 1]
    assert 'fade=t=in' in filtered[filtered.index('-filter_complex') + 1]
    assert filtered[filtered.index('-map', filtered.index('-map') + 1) + 1] == '2:a'
    original = ['ffmpeg', '-vf', 'ass=scene.ass', 'out.mp4']
    filtered = FFmpegAdapter.apply_effect(original, scene)
    assert filtered[2].startswith('ass=scene.ass,fade=') and original[2] == 'ass=scene.ass'
    with pytest.raises(RenderError):
        FFmpegAdapter.apply_effect(command, ScenePlan(1, '', '', effect='arbitrary'))


def test_actual_ffmpeg_fade_mp4_and_decoded_frames(tmp_path, browser):
    """Two-second synthetic silent MP4, not speech/anchor quality verification."""
    import subprocess

    scene = ScenePlan(2, '합성 문장', '한국어 자막', effect='fade')
    output, metadata = FFmpegAdapter().render(RenderPlan('효과 검증', [scene], []), tmp_path,
                                             FakeTTS(), lambda _: None, Event())
    assert metadata['playable'] and metadata['video_codec'] == 'h264'
    assert metadata['audio_codec'] == 'aac'
    means = []
    binary, _, _ = FFmpegAdapter().check()
    for at in ['0', '1']:
        data = subprocess.run([str(binary), '-v', 'error', '-ss', at, '-i', str(output),
                               '-frames:v', '1', '-vf', 'scale=16:16,format=gray', '-f', 'rawvideo', '-'],
                              check=True, capture_output=True, timeout=30).stdout
        assert len(data) == 256
        means.append(sum(data)/len(data))
    assert means[0] < 2 and means[1] > means[0] + 5
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, HTMLResponse

    preview = FastAPI()
    preview.get("/sample.mp4")(lambda: FileResponse(output, media_type="video/mp4"))
    preview.get("/")(lambda: HTMLResponse('<video controls muted src="/sample.mp4"></video>'))
    with local_server(preview) as origin:
        context = browser.new_context()
        external = []
        def guard(route):
            if route.request.url.startswith(origin + "/"):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()
        context.route("**/*", guard)
        page = context.new_page()
        page.goto(origin)
        result = page.locator('video').evaluate("""async video=>{
            await video.play(); await new Promise(resolve=>video.requestVideoFrameCallback(resolve));
            video.pause(); return [video.videoWidth, video.videoHeight, video.duration, video.readyState];
        }""")
        assert result[:2] == [1080,1920] and abs(result[2]-2)<.25 and result[3] >= 2
        assert not external
        context.close()
    import os
    import shutil
    if os.environ.get('NEWSFLOW_CONTROL_EVIDENCE'):
        root = Path(os.environ['NEWSFLOW_CONTROL_EVIDENCE']); root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(output, root/'synthetic-fade-2s.mp4')


def test_categories_use_snapshots_once_and_preserve_missing_and_zero():
    rows = [SimpleNamespace(job_id=i, metric='views', value=value)
            for i, value in [(1,'80'), (1,'20'), (2,'50'), (3,'0')]]
    sources = {1: {'articles': [{'category': 'it'}, {'category': 'AI'}]},
               2: {'articles': [{'category': '경제'}, {'category': '사회'}]}}
    result = category_performance(rows, sources, 'youtube')
    assert [(r['name'], r['views'], r['videos']) for r in result] == [
        ('IT·과학', 100, 1), ('복합 주제', 50, 1), ('미분류', 0, 1)]
    assert sum(r['percent'] for r in result) == pytest.approx(100)
    assert category_performance([], {}, 'youtube') == []
    assert category_performance(rows, sources, 'tiktok') == []
