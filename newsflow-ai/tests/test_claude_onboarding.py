"""Connection setup must never imply inference or paid-call approval."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import csrf
from fastapi.testclient import TestClient

from newsflow.config import Settings
from newsflow.intelligence import claude_code as cli
from newsflow.intelligence.provider import Options
from newsflow.intelligence.settings import read_settings, read_studio_settings, write_studio_settings
from newsflow.main import create_app
from newsflow.video.tts import WindowsTTS


@pytest.mark.parametrize("logged,method,code,expected", [
    (True, "claude.ai", 0, "ready"), (False, "none", 1, "login_required"),
    (True, "api_key", 0, "approval_required"), (True, "third_party", 0, "approval_required"),
    (True, "oauth_token", 0, "approval_required"), (False, "none", 2, "auth_error"),
])
def test_auth_classification_and_redaction(monkeypatch, logged, method, code, expected):
    monkeypatch.setattr(cli, "cli_path", lambda: Path("claude.exe"))
    payload = {"loggedIn": logged, "authMethod": method, "email": "PRIVATE", "token": "PRIVATE"}
    replies = iter([SimpleNamespace(returncode=0, stdout=b"2.1.301 (Claude Code)"),
                    SimpleNamespace(returncode=code, stdout=json.dumps(payload).encode())])
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: next(replies))
    result = cli.ClaudeCodeProvider.status()
    assert result["state"] == expected
    assert result["authenticated"] is (expected in ("ready", "approval_required"))
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("kind,expected", [
    ("missing", "not_installed"), ("old", "version_check"), ("bad", "check_failed"),
    ("timeout", "timeout"), ("oserror", "check_failed"),
])
def test_detection_failures(monkeypatch, kind, expected):
    monkeypatch.setattr(cli, "cli_path", lambda: None if kind == "missing" else Path("claude.exe"))

    def run(args, **kwargs):
        if kind == "timeout":
            raise subprocess.TimeoutExpired(args, 10)
        if kind == "oserror":
            raise OSError("PRIVATE")
        if "--version" in args:
            return SimpleNamespace(returncode=0, stdout=b"2.1.1" if kind == "old" else b"2.1.301")
        return SimpleNamespace(returncode=0, stdout=b'{"loggedIn":"true"}')

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.ClaudeCodeProvider.status()["state"] == expected


def test_billing_auth_never_starts_inference(monkeypatch):
    monkeypatch.setattr(cli.ClaudeCodeProvider, "status", lambda *args: cli.connection_state("approval_required"))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: pytest.fail("inference launched"))
    with pytest.raises(cli.ProviderBillingApprovalError):
        cli.ClaudeCodeProvider().complete({}, 30, Options())


def test_login_consent_duplicate_and_final_status(monkeypatch):
    login = cli.ClaudeLogin()
    state = {"value": "login_required"}
    monkeypatch.setattr(cli.ClaudeCodeProvider, "status", lambda *args: cli.connection_state(state["value"]))
    monkeypatch.setattr(cli, "cli_path", lambda: Path("claude.exe"))
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt", environ={"CLAUDE_CONFIG_DIR": "custom"}))
    monkeypatch.setattr(cli.subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    process = SimpleNamespace(code=None)
    process.poll = lambda: process.code
    calls = []

    def launch(args, **kwargs):
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr(cli.subprocess, "Popen", launch)
    with pytest.raises(ValueError):
        login.start()
    assert not calls
    assert login.start(consent=True)["state"] == "login_started"
    assert login.start(consent=True)["state"] == "login_running"
    assert login.check()["state"] == "login_running"
    assert len(calls) == 1 and calls[0][0] == ["claude.exe", "auth", "login"]
    assert "stdout" not in calls[0][1] and "stderr" not in calls[0][1]
    assert calls[0][1]["shell"] is False
    process.code = 0
    assert login.check()["state"] == "login_required"  # exit alone is not success
    login.process = process
    process.code = 1
    assert login.check()["state"] == "login_cancelled"
    state["value"] = "ready"
    assert login.start(consent=True)["state"] == "ready"
    state["value"] = "approval_required"
    assert login.start(consent=True)["state"] == "approval_required"
    assert len(calls) == 1


def test_login_launch_error_and_busy(monkeypatch):
    login = cli.ClaudeLogin()
    login.lock.acquire()
    assert login.start(consent=True)["state"] == "checking"
    assert login.check()["state"] == "checking"
    login.lock.release()
    monkeypatch.setattr(cli.ClaudeCodeProvider, "status", lambda *args: cli.connection_state("login_required"))
    monkeypatch.setattr(cli, "cli_path", lambda: Path("claude.exe"))
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(cli.subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)

    def fail(*args, **kwargs):
        raise OSError("PRIVATE")

    monkeypatch.setattr(cli.subprocess, "Popen", fail)
    result = login.start(consent=True)
    assert result["state"] == "login_failed" and "PRIVATE" not in str(result)


def test_preserve_config_context_without_api_credentials(monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "custom")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "PRIVATE")
    assert cli.cli_env()["CLAUDE_CONFIG_DIR"] == "custom"
    assert "ANTHROPIC_API_KEY" not in cli.cli_env()


def test_preferences_reload_restart_and_separate_approval(tmp_path, fake, monkeypatch):
    # Unified readiness also lists local SAPI voices. Keep that unrelated worker synthetic;
    # the global process prohibition below must still catch every accidental Claude launch.
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [])
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: pytest.fail("CLI launched by settings"))
    monkeypatch.setattr(cli.ClaudeCodeProvider, "status", lambda *args: pytest.fail("automatic status query"))
    config = Settings(data_dir=tmp_path / "persistent")
    for restart in (False, True):
        app = create_app(config, fake)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            token = csrf(client)
            original = read_settings(app.state.sessions)
            if not restart:
                for provider, model in (("openai", "gpt-4o-mini"), ("offline", "offline"),
                                        ("claude_code", "opus")):
                    response = client.post("/ai/preferences", data={"csrf_token": token,
                                           "provider": provider, "model": model})
                    assert response.status_code == 200
                    assert read_studio_settings(app.state.sessions)["provider"] == provider
                invalid = client.post("/ai/preferences", data={"csrf_token": token,
                                      "provider": "claude_code", "model": "gpt-4o-mini"})
                assert invalid.status_code == 422
            saved = read_studio_settings(app.state.sessions)
            assert saved["provider"] == "claude_code" and saved["model"] == "opus"
            assert saved["models"]["openai"] == "gpt-4o-mini"
            page = client.get("/ai")
            assert 'value="claude_code" selected' in page.text and 'value="opus"' in page.text
            assert read_settings(app.state.sessions) == original
            assert "content-security-policy" in page.headers


@pytest.mark.parametrize("path", ["/ai/claude/status", "/ai/claude/login", "/ai/preferences"])
def test_setup_csrf_and_origin(client, path):
    assert client.post(path, data={}).status_code == 403
    assert client.post(path, data={"csrf_token": csrf(client)},
                       headers={"Origin": "https://attacker.invalid"}).status_code == 403


def test_explicit_status_login_and_disable(client, app, monkeypatch):
    checks = []
    starts = []
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [])
    monkeypatch.setattr(cli.CLAUDE_LOGIN, "check", lambda: checks.append(1) or cli.connection_state("ready"))
    monkeypatch.setattr(cli.CLAUDE_LOGIN, "start", lambda **k: starts.append(k) or cli.connection_state("ready"))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected CLI"))
    token = csrf(client)
    assert client.get("/ai").status_code == 200 and not checks
    assert client.post("/ai/claude/login", data={"csrf_token": token}).status_code == 422
    assert not starts
    assert client.post("/ai/claude/status", data={"csrf_token": token}).json()["ready"]
    assert len(checks) == 1
    assert client.post("/ai/claude/login", data={"csrf_token": token, "consent": "true"}).status_code == 200
    assert starts == [{"consent": True}]
    write_studio_settings(app.state.sessions, "claude_code", "sonnet")
    response = client.post("/ai/preferences", data={"csrf_token": token, "provider": "offline", "model": "offline"})
    assert response.status_code == 200
    assert read_studio_settings(app.state.sessions)["provider"] == "offline"
