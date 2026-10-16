"""Phase 5C real-content Autopilot: gated external AI, mandatory reviews, voice and audio-fit."""

from __future__ import annotations

from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.autopilot.backend import PipelineBackend
from newsflow.autopilot.contracts import AutopilotError, BackendError
from newsflow.db.models import (
    AIUsage,
    AppSetting,
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    NewsSource,
    PublishDraft,
    RenderJob,
    Scene,
    SubtitleTrack,
)
from newsflow.intelligence.credentials import AIKeyStore, FakeCipher
from newsflow.intelligence.provider import FakeProvider, OfflineProvider, ProviderRateLimitError
from newsflow.intelligence.service import IntelligenceService
from newsflow.intelligence.settings import external_ready, write_settings
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.service import PublishingService
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.tts import FakeTTS

KEY = "sk-synthetic-not-a-real-key-0123456789abcdef"
SCRIPT = {
    "title": "실제 뉴스 요약", "hook": "오늘의 보도입니다.", "summary": "보도된 내용의 요약입니다.", "closing": "원문을 확인하세요.",
    "scenes": [
        {"seconds": 10, "narration": "첫 번째 장면 내용입니다.", "caption": "첫 장면", "material": "카드"},
        {"seconds": 10, "narration": "두 번째 장면 내용입니다.", "caption": "둘째 장면", "material": "카드"},
        {"seconds": 10, "narration": "세 번째 장면 내용입니다.", "caption": "셋째 장면", "material": "카드"},
    ],
}


@pytest.fixture
def real(app):
    """Real-content job context on registered fixture RSS; AI stays offline unless a test opens the gate."""
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Fixture", url="https://example.com/rss", enabled=True))
    store = AIKeyStore(app.state.config.data_dir, FakeCipher())
    backend = PipelineBackend(
        app.state.sessions, app.state.config.data_dir, app.state.coordinator, app.state.video,
        intelligence=IntelligenceService(app.state.sessions, None, store),
        ai_gate=lambda: external_ready(app.state.sessions, store),
    )
    context = {"job_id": uuid4().hex, "source": "feeds", "mode": "easy", "duration": 30, "platform": "youtube",
               "content_mode": "real", "ai_mode": "offline", "voice": None}
    yield backend, context, store
    backend.close()
    app.state.coordinator.close()
    app.state.video.close()


def step(fixture, stage, cancel=None):
    backend, ctx, _store = fixture
    result = backend.execute(stage, dict(ctx), cancel or Event(), lambda *_: None, lambda key, value: ctx.__setitem__(key, value))
    ctx.update(result)
    return result


def open_gate(app, store):
    write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 100_000, 20)
    store.save(KEY)


class ScriptProvider(FakeProvider):
    """Offline-shaped analysis, fixed external-shaped script; counts calls like the fake."""

    def analyze(self, evidence, options):
        self.calls += 1
        return OfflineProvider().analyze(evidence, options)


def test_real_offline_flow_marks_real_rss_and_review_notes(real, app):
    _backend, ctx, _ = real
    collected = step(real, "collect")
    assert collected["synthetic_news"] is False and collected["added"] == 3
    selected = step(real, "select")
    assert selected["synthetic_news"] is False and "content_sufficient" in selected
    script = step(real, "script")
    assert script["ai_mode"] == "offline" and script["speech_fits"] is True
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, ctx["content_draft_id"])
        assert draft.review_status == "review_required" and isinstance(draft.review_notes, list)
        assert all(run.provider == "offline" for run in session.scalars(select(IntelligenceRun)))
        assert session.scalar(select(AIUsage)) is None


def test_external_ai_is_refused_until_settings_gate_opens(real, app, monkeypatch):
    backend, ctx, store = real
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    step(real, "collect")
    step(real, "select")
    ctx["ai_mode"] = "openai"
    forbidden = Mock(side_effect=AssertionError("external call"))
    monkeypatch.setattr("newsflow.intelligence.provider.OpenAIProvider.request", forbidden)
    with pytest.raises(BackendError) as failure:
        step(real, "script")
    assert failure.value.code == "ai_not_ready" and failure.value.retryable and not forbidden.called
    with app.state.sessions() as session:
        assert session.scalar(select(ContentDraft)) is None and session.scalar(select(IntelligenceRun)) is None
    open_gate(app, store)
    backend.intelligence.provider = ScriptProvider(SCRIPT, usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70})
    result = step(real, "script")
    assert result["ai_mode"] == "openai"
    with app.state.sessions() as session:
        assert [row.total_tokens for row in session.scalars(select(AIUsage))] == [70, 70]
        assert {run.provider for run in session.scalars(select(IntelligenceRun))} == {"openai"}
        assert session.get(ContentDraft, ctx["content_draft_id"]).review_status == "review_required"


def test_trial_job_never_uses_external_ai_even_if_requested(real, app):
    _backend, ctx, store = real
    open_gate(app, store)
    ctx.update({"source": "sample", "content_mode": "trial", "ai_mode": "openai"})
    step(real, "collect")
    step(real, "select")
    with pytest.raises(BackendError) as failure:
        step(real, "script")
    assert failure.value.code == "ai_consent" and not failure.value.retryable


@pytest.mark.parametrize("error,code,retryable", [
    (ProviderRateLimitError("x"), "ai_rate_limited", True), (TimeoutError("x"), "ai_timeout", True),
    ({"title": "bad"}, "ai_bad_response", True),
])
def test_external_ai_failures_map_to_actionable_codes(real, app, error, code, retryable):
    backend, ctx, store = real
    open_gate(app, store)
    step(real, "collect")
    step(real, "select")
    ctx["ai_mode"] = "openai"
    backend.intelligence.provider = FakeProvider(error)
    with pytest.raises(BackendError) as failure:
        step(real, "script")
    assert failure.value.code == code and failure.value.retryable is retryable
    assert backend.can_retry("script", ctx)
    with app.state.sessions() as session:
        assert session.scalar(select(IntelligenceRun).where(IntelligenceRun.status == "failed"))


def test_budget_exhaustion_blocks_before_provider_call(real, app):
    backend, ctx, store = real
    open_gate(app, store)
    write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 100, 20)  # below any max_tokens
    step(real, "collect")
    step(real, "select")
    ctx["ai_mode"] = "openai"
    provider = ScriptProvider(SCRIPT)
    backend.intelligence.provider = provider
    with pytest.raises(BackendError) as failure:
        step(real, "script")
    assert failure.value.code == "ai_budget" and provider.calls == 0 and not failure.value.retryable


def test_missing_installed_voice_fails_instead_of_substituting(real, app):
    _backend, ctx, _ = real
    for stage in ("collect", "select", "script"):
        step(real, stage)
    ctx["voice"] = "Korean Voice That Is Not Installed"
    app.state.video.tts = FakeTTS()  # lists only offline-silence
    with pytest.raises(BackendError) as failure:
        step(real, "render")
    assert failure.value.code == "voice_unavailable" and failure.value.retryable
    assert "render_job_id" not in ctx


def test_real_voice_uses_audio_fit_and_persists_scene_timing(real, app):
    _backend, ctx, _ = real
    for stage in ("collect", "select", "script"):
        step(real, stage)

    class KoreanTTS(FakeTTS):
        def voices(self):
            return ["offline-silence", "Fake Korean"]

        def synthesize(self, text, target, voice, seconds, speech=None):
            assert voice == "Fake Korean"
            super().synthesize(text, target, "offline-silence", seconds, speech)

    class FitRender(FakeRenderAdapter):
        def render(self, plan, work, tts, progress, cancel):
            assert plan.fit_audio and plan.voice == "Fake Korean" and plan.speech.pause_ms == 250
            path, meta = super().render(plan, work, tts, progress, cancel)
            meta.update({"playable": True, "audio": "voice", "audio_fit": True,
                         "scene_timings": [{"seconds": 12.0, "audio_seconds": 11.0}, {"seconds": 8.0, "audio_seconds": 7.0}, {"seconds": 10.0, "audio_seconds": 9.0}]})
            return path, meta

    app.state.video.tts, app.state.video.engine = KoreanTTS(), FitRender()
    ctx["voice"] = "Fake Korean"
    result = step(real, "render")
    assert result["audio"] == "voice" and result["audio_fit"] is True
    with app.state.sessions() as session:
        scenes = session.scalars(select(Scene).where(Scene.project_id == ctx["video_project_id"]).order_by(Scene.position)).all()
        assert [(s.start_ms, s.end_ms) for s in scenes] == [(0, 12000), (12000, 20000), (20000, 30000)]
        cues = session.scalar(select(SubtitleTrack).where(SubtitleTrack.project_id == ctx["video_project_id"])).cues
        assert cues[0]["end_ms"] == 11000 and cues[-1]["end_ms"] == 29000
        job = session.get(RenderJob, ctx["render_job_id"])
        assert job.status == "success"


def test_silent_voice_keeps_script_timing_and_queue_labels_silent(real, app):
    backend, ctx, _ = real
    for stage in ("collect", "select", "script"):
        step(real, stage)
    app.state.video.tts, app.state.video.engine = FakeTTS(), FakeRenderAdapter()
    ctx["voice"] = "offline-silence"
    render_id = app.state.video.start_preview(ctx["content_draft_id"], 30, voice="offline-silence")
    app.state.video.future.result(timeout=10)
    inspector = FakeMediaInspector()
    with app.state.sessions.begin() as session:
        job = session.get(RenderJob, render_id)
        job.status, job.metadata_json = "success", {**inspector.metadata, "audio": "silent"}
    ctx["render_job_id"] = render_id
    backend.inspector = inspector
    backend.publishing = PublishingService(app.state.sessions, backend.video.outputs, inspector)
    step(real, "render")
    checked = step(real, "validate")
    assert checked["audio"] == "silent" and checked["watch_quality"] == "NOT VERIFIED"
    step(real, "queue")
    with app.state.sessions() as session:
        draft = session.scalar(select(PublishDraft))
        assert "무음 검토영상" in draft.description and "실제 보도 아님" not in draft.description
        assert draft.state == "blocked" and not draft.content_reviewed


def test_coordinator_real_mode_pauses_on_script_and_final_video(client, app):
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Fixture", url="https://example.com/rss", enabled=True))
    app.state.video.tts, app.state.video.engine = FakeTTS(), FakeRenderAdapter()
    response = client.post("/autopilot/start", data={"csrf_token": csrf(client), "source": "feeds", "mode": "easy", "ai": "offline"}, follow_redirects=False)
    assert response.status_code == 303
    app.state.autopilot.future.result(timeout=20)
    job_id = response.headers["location"].rsplit("/", 1)[1]
    snapshot = app.state.autopilot.snapshot(job_id)
    assert (snapshot["content_mode"], snapshot["ai_mode"], snapshot["status"], snapshot["current_stage"]) == ("real", "offline", "waiting_review", "script")
    assert snapshot["review_pauses"] == ["script", "validate"]
    page = client.get(f"/autopilot/jobs/{job_id}").text
    assert "원문과 비교하기" in page and 'id="review-notes"' in page and "실제 콘텐츠" in page
    with app.state.sessions() as session:
        job = session.get(AutopilotJob, job_id)
        assert job.content_mode == "real" and job.voice is None


def test_start_validation_rejects_inconsistent_modes(app):
    coordinator = app.state.autopilot
    with pytest.raises(AutopilotError):
        coordinator.start(source="sample", content_mode="real")
    with pytest.raises(AutopilotError):
        coordinator.start(source="sample", ai_mode="openai")
    with pytest.raises(AutopilotError):
        coordinator.start(source="feeds", voice="x" * 201)


def test_simple_settings_rejects_external_ai_with_sample_news(client, app):
    response = client.post("/simple-settings", data={"csrf_token": csrf(client), "duration": "30", "platform": "youtube", "source": "sample", "mode": "easy", "ai": "openai"})
    assert response.status_code == 422
    with app.state.sessions() as session:
        assert session.get(AppSetting, "autopilot_ai") is None
    ok = client.post("/simple-settings", data={"csrf_token": csrf(client), "duration": "30", "platform": "youtube", "source": "feeds", "mode": "easy", "ai": "openai"})
    assert ok.status_code == 200
    assert "외부 AI 대본" in client.get("/").text


def test_gui_start_page_shows_readiness_and_disables_unready_external_ai(client, app, monkeypatch):
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    app.state.ai_keys = AIKeyStore(app.state.config.data_dir, FakeCipher())
    page = client.get("/autopilot/start").text
    assert "준비 안 됨" in page and 'value="openai"' in page and "disabled" in page
    assert "RSS 출처 0개 사용 중" in page
