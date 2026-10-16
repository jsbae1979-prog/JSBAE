"""Unified voice defaults and truthful per-production media context; no real APIs."""

from __future__ import annotations

import json

import pytest
from conftest import csrf

from newsflow.db.models import AppSetting, ContentDraft, IntelligenceRun, NewsArticle
from newsflow.easy_setup import SetupError, save_voice_preferences, validate_voice_preferences
from newsflow.intelligence.service import IntelligenceService
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.supertonic_tts import SupertonicTTS
from newsflow.video.tts import FakeTTS, TTSError, WindowsTTS


@pytest.fixture
def local_voice_catalog(monkeypatch):
    monkeypatch.setattr("newsflow.easy_setup.voice_catalog", lambda: [{"name": "Heami", "culture": "ko-KR"}])
    monkeypatch.setattr("newsflow.gui.voice_routes.voice_catalog", lambda: [{"name": "Heami", "culture": "ko-KR"}])
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [{"name": "Heami", "culture": "ko-KR"}])
    monkeypatch.setattr(SupertonicTTS, "voices", lambda self: ["supertonic:F1"])
    checked = []
    monkeypatch.setattr("newsflow.video.supertonic_assets.verify_models", lambda root: checked.append(root))
    return checked


def test_supertonic_default_uses_existing_keys_and_explicit_integrity_check(app, local_voice_catalog):
    save_voice_preferences(app.state.sessions, "supertonic:F1", "-1", "400")
    assert len(local_voice_catalog) == 1
    with app.state.sessions() as session:
        assert session.get(AppSetting, "video_default_voice").value == "supertonic:F1"
        assert session.get(AppSetting, "video_default_rate").value == "-1"
        assert session.get(AppSetting, "video_default_pause_ms").value == "400"


def test_integrity_failure_preserves_existing_defaults(app, local_voice_catalog, monkeypatch):
    save_voice_preferences(app.state.sessions, "Heami", "0", "250")

    def invalid(root):
        raise TTSError("SYNTHETIC private runtime detail")

    monkeypatch.setattr("newsflow.video.supertonic_assets.verify_models", invalid)
    with pytest.raises(SetupError, match="무결성") as error:
        save_voice_preferences(app.state.sessions, "supertonic:F1", "1", "150")
    assert "SYNTHETIC" not in str(error.value)
    with app.state.sessions() as session:
        assert session.get(AppSetting, "video_default_voice").value == "Heami"
        assert session.get(AppSetting, "video_default_rate").value == "0"


def test_external_voice_selection_never_implies_paid_approval_or_network(app, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("selection must not construct an external client")

    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsTTS", forbidden)
    save_voice_preferences(app.state.sessions, "elevenlabs", "0", "250")
    with app.state.sessions() as session:
        assert session.get(AppSetting, "video_default_voice").value == "elevenlabs"
        assert session.get(AppSetting, "tts_el_enabled") is None
        assert session.get(AppSetting, "tts_el_monthly_limit") is None


@pytest.mark.parametrize("voice", ["supertonic:F1", "elevenlabs", "Missing Korean"])
def test_old_voice_page_retains_selected_engine_without_silence_fallback(client, app, local_voice_catalog, voice):
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key="video_default_voice", value=voice))
    html = client.get("/voices").text
    assert f'value="{voice}" selected' in html
    assert 'value="offline-silence" selected' not in html
    if voice == "Missing Korean":
        response = client.post("/voices", data={
            "csrf_token": csrf(client), "voice": voice, "rate": "1", "pause_ms": "250",
        })
        assert response.status_code == 422
    with app.state.sessions() as session:
        assert session.get(AppSetting, "video_default_voice").value == voice


def test_wizard_keeps_preexisting_non_sapi_voice_and_extended_rate(client, app, local_voice_catalog):
    values = {"source": "sample", "ai": "offline", "duration": "45", "platform": "youtube",
              "voice": "supertonic:F1", "font_size": "48", "subtitle_y": "1420", "rate": "-3", "pause_ms": "600"}
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key="easy_setup", value=json.dumps({
            "step": 5, "revision": 4, "completed": False, "values": values,
        })))
    html = client.get("/setup?step=5").text
    assert 'value="supertonic:F1" selected' in html
    assert 'value="-3" selected' in html and 'value="600" selected' in html


def test_per_production_voice_and_duration_survive_changed_global_defaults(client, app, local_voice_catalog):
    with app.state.sessions.begin() as session:
        session.add(NewsArticle(title="합성 제작 문맥", summary="테스트용 기사", publisher="합성 출처", source_id=1,
                                url="https://example.com/flow", canonical_url="https://example.com/flow"))
    service = IntelligenceService(app.state.sessions)
    identifier = service.generate(service.analyze([1]), 45)
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, identifier)
        run = session.get(IntelligenceRun, draft.run_id)
        run.options = {**run.options, "production_context": {
            "source": "sample", "initial_duration": 45, "initial_provider": "offline",
            "initial_model": "offline", "initial_voice": "supertonic:F1",
        }}
    save_voice_preferences(app.state.sessions, "Heami", "0", "250")
    html = client.get(f"/video?draft_id={identifier}").text
    assert 'value="45" selected' in html and 'value="supertonic:F1" selected' in html
    assert "홈에서 선택: 45초" in html
    assert 'value="Heami" selected' not in html

    class SelectedFakeVoice(FakeTTS):
        def voices(self):
            return ["supertonic:F1"]

        def synthesize(self, text, target, voice, seconds, speech=None):
            assert voice == "supertonic:F1"
            return super().synthesize(text, target, "offline-silence", seconds, speech)

    app.state.video.tts = SelectedFakeVoice()
    app.state.video.engine = FakeRenderAdapter()
    response = client.post("/video/render", data={
        "csrf_token": csrf(client), "draft_id": identifier, "duration": 45,
        "voice": "supertonic:F1", "reviewed": "true",
    }, follow_redirects=False)
    assert response.status_code == 303
    app.state.video.future.result(timeout=15)
    html = client.get(response.headers["location"]).text
    assert "영상 작업 구성: 45초 · supertonic · supertonic:F1" in html
    assert "실제 MP4가 아니며" in html


def test_voice_validation_rejects_unknown_model_without_writes(local_voice_catalog):
    with pytest.raises(SetupError):
        validate_voice_preferences("supertonic:arbitrary", "0", "250")


def test_higgsfield_context_opens_explicit_plan_without_local_render_fallback(client, app, local_voice_catalog):
    with app.state.sessions.begin() as session:
        session.add(NewsArticle(title="합성 장면 계획", summary="테스트용 기사", publisher="합성 출처", source_id=1,
                                url="https://example.com/scene", canonical_url="https://example.com/scene"))
    service = IntelligenceService(app.state.sessions)
    identifier = service.generate(service.analyze([1]), 45)
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, identifier)
        run = session.get(IntelligenceRun, draft.run_id)
        run.options = {**run.options, "production_context": {
            "source": "feeds", "initial_duration": 45, "initial_provider": "offline",
            "initial_model": "offline", "initial_voice": "supertonic:F1", "initial_video": "higgsfield",
        }}
    html = client.get(f"/video?draft_id={identifier}").text
    assert 'id="video-selected-higgsfield"' in html and 'action="/video/render"' not in html
    assert f'/video/ai?draft_id={identifier}' in html and "45초 Higgsfield" in html
    plan = client.get(f"/video/ai?draft_id={identifier}").text
    assert 'name="duration" value="45" checked' in plan
    created = client.post("/video/ai/plans", data={
        "csrf_token": csrf(client), "draft_id": identifier, "duration": 45,
    }, follow_redirects=False)
    assert created.status_code == 303
    screen = client.get(created.headers["location"]).text
    assert 'id="compose-voice-context"' in screen
    assert "최초 선택한 음성 supertonic:F1와 현재 합성 음성이 다릅니다" in screen
    assert "현재 합성 음성: <strong>offline-silence</strong>" in screen
    assert 'name="approved" value="true"' in screen
