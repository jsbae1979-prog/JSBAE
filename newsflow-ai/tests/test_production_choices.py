"""Explicit production choices; injected AI/media only, no provider network calls."""

from copy import deepcopy
from threading import Event
from uuid import uuid4

import pytest
import test_api_news_pipeline
from conftest import csrf
from sqlalchemy import select
from test_api_news_pipeline import settled, start
from test_api_shorts_pipeline import context_for
from test_single_workspace import save_values, stored_values
from test_voice_engines import config

from newsflow.autopilot.contracts import AutopilotConflict, AutopilotError, BackendError
from newsflow.autopilot.production_options import freeze_options
from newsflow.autopilot.service import AutopilotCoordinator
from newsflow.db.models import AutopilotJob, ContentDraft, PublishDraft
from newsflow.gui.production_context import parse_context, validate_context
from newsflow.video.elevenlabs_tts import ElevenLabsKeys, save_settings
from newsflow.video.service import VideoError
from newsflow.video.voice_engines import provider_for

api_pipeline = test_api_news_pipeline.api_pipeline


def choices(review=True, video="off", **values):
    return {"version": 1, "script_review": review, "video_provider": video, **values}


@pytest.fixture(autouse=True)
def no_vendor_calls(monkeypatch):
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda *_a, **_k: pytest.fail("No vendor HTTP"))
    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: pytest.fail("No CLI or paid media"))
    monkeypatch.setattr("newsflow.video.tts.WindowsTTS.voice_details", lambda _: [])
    monkeypatch.setattr("newsflow.video.supertonic_tts.SupertonicTTS.voices", lambda _: [])


def test_checked_and_legacy_jobs_keep_script_and_final_review(api_pipeline):
    _coordinator, _, _, _, _, _ = api_pipeline
    job = settled(api_pipeline, start(api_pipeline, production_options=choices()))
    assert (job["status"], job["current_stage"]) == ("waiting_review", "script")
    assert job["review_pauses"] == ["script", "validate"]
    assert job["production_options"]["script_review"] is True
    assert AutopilotCoordinator._pauses(AutopilotJob(mode="guided", content_mode="real", stage_results={})) == {
        "select", "script", "validate"}


def test_skip_advances_to_existing_render_without_marking_reviewed(api_pipeline, monkeypatch):
    _coordinator, backend, provider, sessions, _, rss = api_pipeline
    seen = []

    def render(ctx, *_):
        seen.append(deepcopy(ctx))
        raise BackendError("Synthetic render boundary", retryable=False)

    monkeypatch.setattr(backend, "_render", render)
    job = settled(api_pipeline, start(api_pipeline, production_options=choices(False)))
    assert job["current_stage"] == "render" and seen
    assert job["review_pauses"] == ["validate"]
    assert provider.calls == ["search", "analysis", "script"] and rss.calls == []
    with sessions() as session:
        assert session.get(ContentDraft, job["content_draft_id"]).review_status == "review_required"
        assert session.scalar(select(PublishDraft)) is None


@pytest.mark.parametrize("fault", ["numbers", "structure", "source", "unsafe", "missing_sources"])
def test_skip_rechecks_actual_draft_and_stops_before_media(api_pipeline, monkeypatch, fault):
    _coordinator, backend, provider, sessions, _, _ = api_pipeline
    job = settled(api_pipeline, start(api_pipeline))
    with sessions.begin() as session:
        draft = session.get(ContentDraft, job["content_draft_id"])
        content, sources = deepcopy(draft.content), deepcopy(draft.sources)
        if fault == "numbers":
            content["summary"] += " 987654명이 참여했습니다."
        elif fault == "structure":
            content["scenes"] = []
        elif fault == "source":
            sources["articles"][0]["summary"] = "짧음"
        elif fault == "missing_sources":
            sources["articles"][0]["sources"] = []
        else:
            content["hook"] = "충격! 100% 확실"
        draft.content, draft.sources = content, sources
    ctx = context_for(api_pipeline, job["id"])
    ctx["production_options"] = choices(False)
    monkeypatch.setattr(backend.video, "start_preview", lambda *_a, **_k: pytest.fail("Unsafe render"))
    with pytest.raises(BackendError) as failure:
        backend._render(ctx, Event(), lambda *_: None, lambda *_: None)
    assert failure.value.retryable is False
    assert provider.calls == ["search", "analysis", "script"]


def test_higgsfield_stops_for_existing_scene_approvals_even_when_script_skipped(api_pipeline, monkeypatch):
    coordinator, backend, provider, _, _, _ = api_pipeline
    job = settled(api_pipeline, start(api_pipeline, production_options=choices(False, "higgsfield")))
    assert (job["status"], job["current_stage"]) == ("waiting_review", "script")
    assert job["production_options"]["video_provider"] == "higgsfield"
    monkeypatch.setattr(backend.video, "start_preview", lambda *_a, **_k: pytest.fail("No FFmpeg fallback"))
    coordinator.resume(job["id"], job["revision"])
    job = settled(api_pipeline, job["id"])
    assert job["status"] == "failed" and job["error_code"] == "ai_video_review" and not job["retryable"]
    assert provider.calls == ["search", "analysis", "script"]


def test_higgsfield_workspace_offers_scene_approvals_instead_of_basic_render(api_pipeline, app, client, monkeypatch):
    coordinator, _, _, _, _, _ = api_pipeline
    monkeypatch.setattr(app.state, "autopilot", coordinator)
    save_values(app, video_default_voice="offline-silence")
    job = settled(api_pipeline, start(api_pipeline, production_options=choices(False, "higgsfield")))
    page = client.get(f'/?task={job["id"]}')
    assert page.status_code == 200
    assert f'/video/ai?draft_id={job["content_draft_id"]}' in page.text
    assert 'action="/autopilot/jobs/' + job["id"] + '/resume"' not in page.text
    assert "장면별 승인 대기" in page.text and "기본 영상으로 대체하지 않습니다" in page.text


@pytest.mark.parametrize("voice", ["supertonic:F1", "elevenlabs"])
def test_ai_scene_composition_keeps_frozen_voice_or_blocks_unsupported_combination(api_pipeline, app, client, monkeypatch, voice):
    _, backend, _, _, _, _ = api_pipeline
    extra = {"external_tts_consent": True, "elevenlabs": config()} if voice == "elevenlabs" else {}
    job = settled(api_pipeline, start(api_pipeline, voice=voice, production_options=choices(False, "higgsfield", **extra)))
    save_values(app, video_default_voice="supertonic:F2")
    captured = []
    monkeypatch.setattr(backend.video, "_start", lambda *a, **k: captured.append((a, k)) or 123)
    if voice == "elevenlabs":
        with pytest.raises(VideoError, match="동시 합성은 지원하지 않습니다"):
            backend.video.start_ai(123, job["content_draft_id"], 30, [{}, {}, {}])
        assert captured == []
        monkeypatch.setattr(app.state.video_ai, "create_plan", lambda *_a: pytest.fail("Unsupported plan must not generate"))
        response = client.post("/video/ai/plans", data={"csrf_token": csrf(client),
            "draft_id": job["content_draft_id"], "duration": 30})
        assert response.status_code == 422 and "다른 음성으로 대체하지 않습니다" in response.text
    else:
        assert backend.video.start_ai(123, job["content_draft_id"], 30, [{}, {}, {}]) == 123
        assert captured[0][0][2] == "supertonic:F1"


def test_options_persist_across_coordinator_restart_and_default_changes(api_pipeline, app):
    coordinator, backend, provider, sessions, _, _ = api_pipeline
    identifier = start(api_pipeline, request_id=uuid4().hex, production_options=choices())
    first = settled(api_pipeline, identifier)
    coordinator.close()
    save_values(app,
                video_default_voice="elevenlabs", video_ai_provider="higgsfield")
    restored = AutopilotCoordinator(sessions, coordinator.root, backend)
    try:
        assert restored.snapshot(identifier)["production_options"] == first["production_options"]
        assert restored.snapshot(identifier)["voice"] == "supertonic:F1"
        assert restored.snapshot(identifier)["review_pauses"] == ["script", "validate"]
        with pytest.raises(AutopilotConflict):
            start((restored, *api_pipeline[1:]), request_id=identifier, production_options=choices(False))
        assert provider.calls == ["search", "analysis", "script"]
    finally:
        restored.close()


def test_elevenlabs_options_require_separate_consent_and_freeze_nonsecret_config():
    value = choices(False, external_tts_consent=True, elevenlabs=config())
    frozen = freeze_options(value, "elevenlabs")
    value["elevenlabs"]["voice_id"] = "changed"
    assert frozen["elevenlabs"]["voice_id"] == "syntheticVoice"
    assert not any("key" in key for key in frozen["elevenlabs"])
    with pytest.raises(AutopilotError):
        freeze_options(choices(False, elevenlabs=config()), "elevenlabs")


def test_local_mode_cannot_dispatch_elevenlabs(api_pipeline, monkeypatch):
    _, backend, _, _, _, _ = api_pipeline
    monkeypatch.setattr(backend.video, "voice_available", lambda v: v == "supertonic:F1")
    assert backend._voice({"voice": "supertonic:F1", "production_options": choices()}) == "supertonic:F1"
    with pytest.raises(BackendError):
        backend._voice({"voice": "elevenlabs", "production_options": choices()})
    assert backend.can_retry("render", {"voice": "elevenlabs"}) is False


def test_elevenlabs_keeps_job_voice_model_after_saved_settings_change(api_pipeline, app, monkeypatch):
    _, backend, _, _, _, _ = api_pipeline
    original = config()
    job = settled(api_pipeline, start(api_pipeline, voice="elevenlabs",
        production_options=choices(external_tts_consent=True, elevenlabs=original)))
    save_settings(app.state.sessions, **{**original, "voice_id": "changedVoice", "model": "eleven_v3"})
    save_values(app, video_default_voice="supertonic:F2")
    context = context_for(api_pipeline, job["id"])
    assert backend._voice(context) == "elevenlabs"
    selected = []
    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsTTS",
                        lambda root, config, consent: selected.append((config, consent)))
    provider_for("elevenlabs", app.state.sessions, backend.video.root, external_consent=True,
                 elevenlabs_config=context["production_options"]["elevenlabs"])
    assert selected == [(original, True)]


@pytest.mark.parametrize("unknown", [False, True])
def test_skip_never_continues_after_failed_or_unknown_api(api_pipeline, monkeypatch, unknown):
    from newsflow.intelligence.provider import ProviderAuthError, ProviderTimeoutError

    _, backend, provider, _, _, _ = api_pipeline
    monkeypatch.setattr(backend, "_render", lambda *_: pytest.fail("Failed API must not render"))
    def fail(*_):
        provider.calls.append("script")
        raise ProviderTimeoutError() if unknown else ProviderAuthError()
    monkeypatch.setattr(provider, "complete", fail)
    job = settled(api_pipeline, start(api_pipeline, production_options=choices(False)))
    assert job["status"] == "failed" and not job["retryable"]
    assert provider.calls == ["search", "analysis", "script"]


def test_form_default_context_and_separate_tts_consent(client, app, monkeypatch):
    import json
    from urllib.parse import urlsplit

    save_values(app, video_default_voice="offline-silence", autopilot_acquisition_policy="rss")
    before = stored_values(app)
    page = client.get("/create")
    assert 'name="script_review" value="true" form="quick-production" checked' in page.text
    assert 'id="quick-voice-method"' in page.text and 'id="quick-video-method"' in page.text
    captured = []
    monkeypatch.setattr(app.state.autopilot, "start", lambda **k: captured.append(k) or "a" * 32)
    # Local selection explicitly overrides an AI-video global without rewriting settings.
    response = client.post("/autopilot/quick-start", data={"csrf_token": csrf(client), "source": "sample",
        "duration": "30", "workspace": "true", "production_options_version": "1", "voice_method": "local",
        "video_method": "off"}, follow_redirects=False)
    assert response.status_code == 303 and captured[0]["production_options"]["script_review"] is False
    assert captured[0]["voice"] == "offline-silence" and stored_values(app) == before
    value = {"source": "feeds", "initial_duration": 30, "initial_provider": "offline", "initial_model": "offline",
             "initial_voice": "elevenlabs", "initial_video": "off", "production_options_version": 1,
             "script_review": False, "acquisition_policy": "rss", "request_id": uuid4().hex}
    assert parse_context(json.dumps(value))["script_review"] is False
    response = client.post("/autopilot/confirm-start", data={"csrf_token": csrf(client), "flow": json.dumps(value),
        "consent": "true"}, follow_redirects=False)
    assert response.status_code == 422 and len(captured) == 1
    save_settings(app.state.sessions, **config())
    monkeypatch.setattr(ElevenLabsKeys, "status", lambda _: {"configured": True})
    # Only source presence is needed; no collection is dispatched by this route mock.
    from newsflow.db.models import NewsSource
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Synthetic", url="https://example.com/fixture", enabled=True))
    response = client.post("/autopilot/confirm-start", data={"csrf_token": csrf(client), "flow": json.dumps(value),
        "consent": "true", "external_tts_consent": "true"}, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert captured[-1]["voice"] == "elevenlabs"
    assert captured[-1]["production_options"]["external_tts_consent"] is True
    assert captured[-1]["production_options"]["elevenlabs"] == config()
    assert urlsplit(response.headers["location"]).path.endswith("a" * 32)
    assert client.post("/autopilot/quick-start", data={"source": "sample", "duration": 30}).status_code == 403


@pytest.mark.parametrize("review", ["false", 0, None])
def test_forged_context_review_type_rejected(review):
    with pytest.raises(ValueError):
        validate_context({"source": "feeds", "initial_duration": 30, "initial_voice": "offline-silence",
                          "initial_provider": "offline", "initial_model": "offline",
                          "initial_video": "off",
                          "production_options_version": 1, "script_review": review})
