"""Production defaults are atomic and status evidence never causes external requests."""

from types import SimpleNamespace

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import AppSetting, IntelligenceRun, utcnow
from newsflow.easy_setup import SetupError
from newsflow.gui import production_routes, production_status
from newsflow.intelligence import claude_code, codex
from newsflow.intelligence.settings import (
    read_settings,
    read_studio_settings,
    write_settings,
    write_studio_settings,
)
from newsflow.video.elevenlabs_tts import ElevenLabsTTS
from newsflow.video.engine import FFmpegAdapter, RenderError


@pytest.fixture(autouse=True)
def local_catalog(monkeypatch):
    entries = [{"name": "offline-silence", "label": "무음", "engine": "offline", "available": True},
               {"name": "supertonic:F1", "label": "Supertonic F1", "engine": "supertonic", "available": True},
               {"name": "elevenlabs", "label": "ElevenLabs", "engine": "elevenlabs", "available": False}]
    monkeypatch.setattr(production_status, "voice_choice_catalog", lambda: [dict(item) for item in entries])
    monkeypatch.setattr(production_routes, "voice_choice_catalog", lambda: [dict(item) for item in entries])


def all_settings(app):
    with app.state.sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def payload(token, **changes):
    return {"csrf_token": token, "provider": "claude_code", "model": "sonnet", "source": "feeds",
            "duration": "45", "platform": "youtube", "voice": "offline-silence", "rate": "0",
            "pause_ms": "250", "video_provider": "off", **changes}


@pytest.mark.parametrize("provider,state,expected", [
    ("codex", "usage_blocked", "limited"), ("codex", "isolation_blocked", "unavailable"),
    ("codex", "version_check", "unavailable"), ("codex", "version_unsupported", "unavailable"),
    ("codex", "failed", "unavailable"), ("claude_code", "auth_error", "unavailable"),
    ("claude_code", "timeout", "check"), ("claude_code", "version_check", "unavailable"),
    ("claude_code", "approval_required", "limited"),
])
def test_cli_adapter_states_keep_blocked_reason_and_auth_distinction(provider, state, expected):
    result = production_status._cli_status(provider, {"state": state, "installed": True,
                                                     "authenticated": True, "ready": False, "message": "PRIVATE"})
    assert result["status_code"] == expected
    assert "PRIVATE" not in str(result)  # use adapter's fixed message, never a raw cached error
    assert "자동 제작의 직접 실행은 미지원" in result["availability"]
    if state == "approval_required":
        assert "구독 로그인 확인됨" not in result["authentication"]
        assert "과금 자동 전환 차단" in result["authentication"]


def test_status_page_does_not_authenticate_generate_or_verify_models(client, app, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only status must never execute external or expensive checks")

    monkeypatch.setattr(claude_code.CLAUDE_LOGIN, "check", forbidden)
    monkeypatch.setattr(codex.CODEX_PROVIDER, "status", forbidden)
    monkeypatch.setattr(ElevenLabsTTS, "subscription", forbidden)
    monkeypatch.setattr(FFmpegAdapter, "check", forbidden)
    monkeypatch.setattr(production_routes, "validate_voice_preferences", forbidden)
    write_studio_settings(app.state.sessions, "claude_code", "opus")
    before = all_settings(app)
    response = client.get("/simple-settings")
    assert response.status_code == 200
    assert all_settings(app) == before
    context = production_status.production_context(SimpleNamespace(app=app))
    assert len(context["pipeline_stages"]) == 7
    assert context["production_config"]["provider"] == "claude_code"
    assert [item["provider"] for item in context["pipeline_stages"][1:3]] == ["offline", "offline"]
    assert "선택은 보존" in context["pipeline_stages"][1]["availability"]
    assert context["provider_statuses"]["claude_code"]["checked_at"] is None
    assert context["provider_statuses"]["supertonic"]["status_code"] == "check"
    assert 'data-ai-provider="openai" hidden' in response.text
    assert "웹 검색 BLOCKED" in response.text and "확인 기록 없음" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_historical_success_and_cached_auth_are_distinct(app):
    moment = utcnow()
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key="ai_last_check", value='{"checked_at":'))
        session.add(AppSetting(key="autopilot_source", value="feeds"))
        session.add(IntelligenceRun(kind="script", status="success", provider="codex", options={}, evidence={},
                                    result={}, message="Saved success", finished_at=moment))
    write_studio_settings(app.state.sessions, "codex", "default")
    context = production_status.production_context(SimpleNamespace(app=app))
    codex_status = context["provider_statuses"]["codex"]
    assert codex_status["checked_at"] is None and codex_status["status_code"] == "check"
    assert codex_status["last_success_at"] == moment
    assert context["pipeline_stages"][1]["last_success_at"] is None
    assert context["pipeline_stages"][2]["last_success_at"] == moment
    assert context["provider_statuses"]["openai"]["checked_at"] is None


def test_unified_save_uses_existing_keys_and_preserves_approvals(client, app, monkeypatch):
    write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 10000, 20)
    previous_ai = read_settings(app.state.sessions)
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key="video_ai_approved_at", value="2026-10-16T00:00:00+00:00"))
        session.add(AppSetting(key="video_ai_monthly_limit", value="20"))
        session.add(AppSetting(key="autopilot_ai", value="offline"))
    validated = []
    monkeypatch.setattr(production_routes, "validate_voice_preferences", lambda *args: validated.append(args))
    response = client.post("/production/preferences", data=payload(csrf(client), voice="supertonic:F1",
                           video_provider="higgsfield"), follow_redirects=False)
    assert response.status_code == 303
    values = all_settings(app)
    assert values["studio_provider"] == "claude_code" and values["autopilot_duration"] == "45"
    assert values["video_default_voice"] == "supertonic:F1" and values["video_ai_provider"] == "higgsfield"
    assert validated == [("supertonic:F1", "0", "250")]
    assert read_settings(app.state.sessions) == previous_ai
    assert values["autopilot_ai"] == "offline" and values["video_ai_monthly_limit"] == "20"
    assert values["video_ai_approved_at"] == "2026-10-16T00:00:00+00:00"
    assert read_studio_settings(app.state.sessions)["model"] == "sonnet"


def test_validation_failure_and_csrf_preserve_every_setting(client, app, monkeypatch):
    def fail(*args):
        raise SetupError("모델 검증 실패")

    monkeypatch.setattr(production_routes, "validate_voice_preferences", fail)
    token = csrf(client)
    before = all_settings(app)
    assert client.post("/production/preferences", data=payload("wrong")).status_code == 403
    assert client.post("/production/preferences", data=payload(token),
                       headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.post("/production/preferences", data=payload(token, voice="supertonic:F1")).status_code == 422
    assert client.post("/production/preferences", data=payload(token, model="invalid model")).status_code == 422
    assert all_settings(app) == before


def test_local_check_is_explicit_cached_and_not_generation(client, app, monkeypatch):
    calls = []

    def check(*args):
        calls.append(1)
        if len(calls) == 1:
            raise RenderError("PRIVATE")

    monkeypatch.setattr(FFmpegAdapter, "check", check)
    token = csrf(client)
    assert client.post("/production/check-local", data={"engine": "ffmpeg"}).status_code == 403
    assert client.post("/production/check-local", data={"csrf_token": token, "engine": "openai"}).status_code == 422
    assert client.post("/production/check-local", data={"csrf_token": token, "engine": "ffmpeg"}).status_code == 200
    assert app.state.production_checks["ffmpeg"]["ok"] is False
    failed = production_status.production_context(SimpleNamespace(app=app))["provider_statuses"]["ffmpeg"]
    assert failed["status_code"] == "unavailable" and failed["checked_at"] is not None
    assert "PRIVATE" not in str(failed)
    assert client.get("/simple-settings").status_code == 200 and len(calls) == 1
    assert client.post("/production/check-local", data={"csrf_token": token, "engine": "ffmpeg"}).status_code == 200
    assert app.state.production_checks["ffmpeg"]["ok"] is True
    assert len(calls) == 2
