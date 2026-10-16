"""API settings/workspace contracts: Fake only; no CLI or vendor authentication."""

import json
import subprocess
import urllib.request
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import csrf
from sqlalchemy import func, select

from newsflow.db.models import AppSetting, AutopilotJob
from newsflow.gui import api_settings_routes, production_status
from newsflow.intelligence.api_settings import read_api_settings
from newsflow.intelligence.credentials import AnthropicKeyStore, FakeCipher
from newsflow.intelligence.settings import (
    read_settings,
    read_studio_settings,
    write_settings,
    write_studio_settings,
)


@pytest.fixture(autouse=True)
def isolated_no_external_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("API settings must not call any CLI or remote endpoint")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    monkeypatch.setattr(production_status, "voice_choice_catalog", lambda: [
        {"name": "offline-silence", "label": "무음", "engine": "offline", "available": True},
    ])


def values(app):
    with app.state.sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def config(token, **changes):
    return {"csrf_token": token, "model": "claude-sonnet-4-6", "approved": "true",
            "search_enabled": "true", "search_approved": "true", "request_limit_usd": "5",
            "monthly_limit_usd": "20", "input_price_per_1m": "3", "output_price_per_1m": "15",
            "search_price_per_1k": "10", **changes}


def test_integrated_settings_distinguish_configured_and_actual_connection(client, app):
    before = values(app)
    response = client.get("/simple-settings")
    assert response.status_code == 200
    assert 'value="claude_api"' in response.text and 'data-api-connection="openai"' in response.text
    assert "실제 연결 미확인" in response.text and "실제 요청 성공 미검증" in response.text
    assert "별도" in response.text and "BLOCKED" in response.text
    assert values(app) == before


def test_config_save_preserves_selection_rss_and_does_not_verify_api(client, app):
    write_studio_settings(app.state.sessions, "claude_code", "sonnet")
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key="autopilot_acquisition_policy", value="rss"))
    result = client.post("/api-settings/claude_api", data=config(csrf(client)), follow_redirects=False)
    assert result.status_code == 303 and result.headers["location"].startswith("/simple-settings")
    assert read_studio_settings(app.state.sessions)["provider"] == "claude_code"
    saved = read_api_settings(app.state.sessions, "claude_api")
    assert saved.search_enabled and saved.search_approved
    assert saved.authentication_verified_at is None and saved.search_verified_at is None
    assert values(app)["autopilot_acquisition_policy"] == "rss"
    assert "BLOCKED" in client.get("/simple-settings").text


def test_openai_configuration_reuses_existing_token_gate_without_changing_selected_ai(client, app):
    write_studio_settings(app.state.sessions, "claude_code", "sonnet")
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key="autopilot_acquisition_policy", value="rss"))
    page = client.get("/simple-settings")
    assert page.text.count('name="monthly_token_limit"') == 1
    assert page.text.count('name="timeout"') == 1
    response = client.post("/api-settings/openai", data=config(csrf(client), model="gpt-4.1-mini",
                           monthly_token_limit="250000", timeout="35"), follow_redirects=False)
    assert response.status_code == 303
    saved = read_settings(app.state.sessions)
    assert (saved.provider, saved.model, saved.approved, saved.monthly_token_limit, saved.timeout) == (
        "openai", "gpt-4.1-mini", True, 250000, 35)
    assert read_api_settings(app.state.sessions, "openai").search_approved
    assert read_studio_settings(app.state.sessions)["provider"] == "claude_code"
    assert values(app)["autopilot_acquisition_policy"] == "rss"


@pytest.mark.parametrize("changes", [{"monthly_token_limit": "0"}, {"monthly_token_limit": "-1"},
                                    {"monthly_token_limit": "50000001"}, {"timeout": "0"}, {"timeout": "61"}])
def test_invalid_legacy_openai_gate_changes_no_api_settings(client, app, changes):
    token = csrf(client)
    before = values(app)
    fields = config(token, model="gpt-4.1-mini", monthly_token_limit="100000", timeout="20")
    response = client.post("/api-settings/openai", data={**fields, **changes}, follow_redirects=False)
    assert response.status_code == 422
    assert values(app) == before


def test_claude_api_configuration_does_not_change_existing_openai_gate(client, app):
    write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 123456, 37)
    before = read_settings(app.state.sessions)
    response = client.post("/api-settings/claude_api", data=config(csrf(client)), follow_redirects=False)
    assert response.status_code == 303 and read_settings(app.state.sessions) == before


def test_new_key_never_echoed_or_stored_in_sqlite_and_clear_preserves_other_provider(client, app):
    store = AnthropicKeyStore(app.state.config.data_dir, FakeCipher())
    app.state.api_keys["claude_api"] = store
    app.state.autopilot_backend.intelligence.api_key_stores["claude_api"] = store
    token = csrf(client)
    secret = "sk-synthetic-ui-secret-never-a-real-api-key"
    result = client.post("/api-settings/claude_api/key", data={"csrf_token": token, "api_key": secret})
    assert result.status_code == 200 and secret not in result.text
    assert secret not in json.dumps(values(app)) and secret.encode() not in store.path.read_bytes()
    bad = client.post("/api-settings/claude_api/key", data={"csrf_token": token, "api_key": secret * 20})
    assert bad.status_code == 422 and secret not in bad.text
    assert store.key() == secret
    client.post("/api-settings/claude_api/key/clear", data={"csrf_token": token})
    assert not store.status()["stored"]
    assert not app.state.ai_keys.status()["stored"]


@pytest.mark.parametrize("provider", ["openai", "claude_api"])
@pytest.mark.parametrize("policy", ["ai_web", "hybrid"])
def test_unverified_api_search_stays_in_workspace_without_rss_fallback(client, app, provider, policy):
    write_studio_settings(app.state.sessions, provider,
                          "gpt-4.1-mini" if provider == "openai" else "claude-sonnet-4-6")
    before = values(app)
    response = client.post("/autopilot/quick-start", data={"csrf_token": csrf(client), "source": "feeds",
                           "duration": 30, "workspace": "true", "acquisition_policy": policy},
                           follow_redirects=False)
    assert response.status_code == 303 and parse_qs(urlsplit(response.headers["location"]).query)["guide"] == ["search"]
    page = client.get(response.headers["location"])
    assert "AI 웹 뉴스 조사 BLOCKED" in page.text and "RSS로 자동 전환하지 않았습니다" in page.text
    assert 'action="/autopilot/confirm-start"' not in page.text
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AutopilotJob)) == 0
    assert values(app) == before


def test_api_forms_retain_csrf_origin_and_safe_provider_validation(client, app):
    token = csrf(client)
    assert client.post("/api-settings/claude_api", data=config("")).status_code == 403
    assert client.post("/api-settings/claude_api", data=config(token),
                       headers={"Origin": "https://foreign.example"}).status_code == 403
    assert client.post("/api-settings/claude_code", data=config(token)).status_code == 422


@pytest.mark.parametrize("duration", [30, 45, 60])
def test_fake_ready_api_consent_names_three_stages_and_preserves_duration(client, app, monkeypatch, duration):
    """Inject readiness only for presentation; no request is dispatched."""
    write_studio_settings(app.state.sessions, "claude_api", "claude-sonnet-4-6")
    original = api_settings_routes.connection_status

    def ready(request, provider, capability="search"):
        return {**original(request, provider, capability), "ready": True, "reasons": [], "test_only": True}

    monkeypatch.setattr("newsflow.gui.autopilot_routes.connection_status", ready)
    response = client.post("/autopilot/quick-start", data={"csrf_token": csrf(client), "source": "feeds",
                           "duration": duration, "workspace": "true", "acquisition_policy": "ai_web"},
                           follow_redirects=False)
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["guide"] == ["consent"]
    flow = json.loads(unescape(query["flow"][0]))
    assert flow["initial_duration"] == duration and flow["initial_provider"] == "claude_api"
    page = client.get(response.headers["location"])
    assert "검색·분석·대본 3단계" in page.text and "별도의 API 과금" in page.text
    assert "본인 Claude 또는 ChatGPT 구독" not in page.text
    assert app.state.autopilot.future is None
