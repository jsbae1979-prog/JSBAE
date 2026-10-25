"""Unified settings keep existing state and require deliberate connection actions."""

from conftest import csrf
from fastapi.testclient import TestClient
from sqlalchemy import select

from newsflow.config import Settings
from newsflow.db.models import AppSetting, IntelligenceRun
from newsflow.intelligence import claude_code, codex
from newsflow.intelligence.settings import read_settings, read_studio_settings, write_studio_settings
from newsflow.main import create_app


def test_settings_view_preserves_selection_and_never_checks_cli(client, app, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Viewing settings must not launch a connection check or inference")

    monkeypatch.setattr(claude_code.CLAUDE_LOGIN, "check", forbidden)
    monkeypatch.setattr(codex.CODEX_PROVIDER, "status", forbidden)
    monkeypatch.setattr(codex.CODEX_PROVIDER, "analyze", forbidden)
    write_studio_settings(app.state.sessions, "codex", "default")
    before = read_studio_settings(app.state.sessions)
    page = client.get("/simple-settings")
    assert page.status_code == 200
    assert read_studio_settings(app.state.sessions) == before
    for anchor in ("production", "connections", "quality", "schedules", "advanced"):
        assert f'id="{anchor}"' in page.text
    assert page.text.count('action="/production/preferences"') == 1
    assert 'action="/ai/preferences"' not in page.text
    assert 'value="codex" selected' in page.text
    assert "Claude Code · RSS 전용" in page.text and "웹 검색: BLOCKED" in page.text
    assert "Claude Code · 권장" not in page.text
    assert 'action="/ai/claude/status"' in page.text
    assert 'action="/ai/claude/login"' in page.text
    assert 'action="/ai/codex/status"' in page.text
    assert 'action="/ai/codex/login"' not in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"
    studio = client.get("/ai#claude-connection")
    assert studio.status_code == 200
    assert 'href="/simple-settings#connections"' in studio.text
    assert 'action="/ai/claude/status"' in page.text and 'action="/ai/codex/status"' in page.text
    assert 'action="/ai/codex/status"' not in studio.text
    assert 'action="/ai/preferences"' not in studio.text
    assert 'action="/ai/claude/login"' not in studio.text
    assert 'action="/ai/analyze"' in studio.text
    assert "이번 분석:" in studio.text and 'data-studio-provider-label' in studio.text
    assert 'name="provider"' in studio.text and 'name="model"' in studio.text


def test_unified_save_reuses_studio_source_and_survives_restart(tmp_path, fake, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Preferences are not execution or authentication consent")

    monkeypatch.setattr(claude_code.CLAUDE_LOGIN, "check", forbidden)
    monkeypatch.setattr(codex.CODEX_PROVIDER, "status", forbidden)
    config = Settings(data_dir=tmp_path / "settings-data")
    for restart in (False, True):
        app = create_app(config, fake)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            token = csrf(client)
            original = read_settings(app.state.sessions)
            if not restart:
                with app.state.sessions.begin() as session:
                    session.add(AppSetting(key="autopilot_ai", value="offline"))
                for provider, model in (("offline", "offline"), ("openai", "gpt-4o-mini"),
                                        ("claude_code", "opus"), ("codex", "default")):
                    response = client.post("/ai/preferences", data={"csrf_token": token,
                                           "provider": provider, "model": model, "return_to": "settings"},
                                           follow_redirects=False)
                    assert response.status_code == 303
                    assert response.headers["location"] == "/simple-settings?saved=true#connections"
                    assert read_studio_settings(app.state.sessions)["provider"] == provider
            saved = read_studio_settings(app.state.sessions)
            assert saved["provider"] == "codex" and saved["models"]["claude_code"] == "opus"
            assert read_settings(app.state.sessions) == original
            with app.state.sessions() as session:
                assert session.get(AppSetting, "autopilot_ai").value == "offline"
                assert not list(session.scalars(select(IntelligenceRun)))
                assert session.get(AppSetting, "studio_provider").value == "codex"
            page = client.get("/simple-settings")
            assert 'value="codex" selected' in page.text


def test_preferences_redirect_allowlist_and_security(client, app):
    token = csrf(client)
    before = read_studio_settings(app.state.sessions)
    values = {"provider": "claude_code", "model": "sonnet", "return_to": "settings"}
    assert client.post("/ai/preferences", data=values).status_code == 403
    assert client.post("/ai/preferences", data={**values, "csrf_token": token},
                       headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.post("/ai/preferences", data={**values, "csrf_token": token,
                       "return_to": "//attacker.invalid"}).status_code == 422
    assert read_studio_settings(app.state.sessions) == before
    legacy = client.post("/ai/preferences", data={"provider": "claude_code", "model": "sonnet",
                         "csrf_token": token}, follow_redirects=False)
    assert legacy.status_code == 303 and legacy.headers["location"] == "/ai?saved=true#claude-connection"
