"""First API verification controls use synthetic keys, temporary DBs and Fake HTTP."""

import json
import subprocess
import urllib.request

import pytest
from conftest import csrf
from sqlalchemy import select
from test_api_providers import anthropic_response, openai_response
from test_claude_connection_gui import Document

from newsflow.db.models import AppSetting
from newsflow.gui import production_routes, production_status
from newsflow.intelligence.api_settings import read_api_settings, save_api_settings
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, FakeCipher
from newsflow.intelligence.settings import write_studio_settings

KEY = "sk-synthetic-first-check-gui-0123456789"


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Verification tests must never call live APIs or CLIs")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    for name in ("NEWSFLOW_AI_API_KEY", "NEWSFLOW_ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for module in (production_routes, production_status):
        monkeypatch.setattr(module, "voice_choice_catalog", lambda: [
            {"name": "offline-silence", "label": "무음", "engine": "offline", "available": True},
        ])


@pytest.fixture(params=["openai", "claude_api"])
def prepared(request, app):
    provider = request.param
    model = "gpt-4.1-mini" if provider == "openai" else "claude-sonnet-4-6"
    factory = AIKeyStore if provider == "openai" else AnthropicKeyStore
    store = factory(app.state.config.data_dir, FakeCipher())
    store.save(KEY)
    app.state.api_keys[provider] = store
    app.state.autopilot_backend.intelligence.api_key_stores[provider] = store
    write_studio_settings(app.state.sessions, provider, model)
    save_api_settings(
        app.state.sessions, provider, model=model, approved=True, search_enabled=True,
        search_approved=True, request_limit_usd="10", monthly_limit_usd="20",
        input_price_per_1m="3", output_price_per_1m="15", search_price_per_1k="10",
        billing_confirmed=True, account_remaining_usd="20",
    )
    calls = []

    def metadata(req, timeout, limit):
        calls.append("metadata")
        return json.dumps({"object" if provider == "openai" else "type": "model", "id": model}).encode()

    def search(req, timeout, limit):
        calls.append("search")
        return json.dumps(openai_response() if provider == "openai" else anthropic_response()).encode()

    setattr(app.state, "openai_connection_transport" if provider == "openai" else "claude_connection_transport", metadata)
    app.state.api_search_check_transports = {provider: search}
    return provider, model, store, calls


def settings(app):
    with app.state.sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def test_explicit_controls_get_is_read_only_and_search_is_disabled_before_auth(client, app, prepared):
    provider, _, store, calls = prepared
    before = settings(app)
    encrypted = store.path.read_bytes()
    response = client.get("/simple-settings")
    assert response.status_code == 200
    doc = Document(response.text)
    for suffix in ("check", "check-search"):
        form = doc.find("form", action=f"/api-settings/{provider}/{suffix}")[0]
        consent = next(node for node in doc.find("input", name="consent") if form in node.ancestors)
        assert consent.attrs["type"] == "checkbox" and "checked" not in consent.attrs
        if suffix == "check-search":
            button = next(node for node in doc.find("button", type="submit") if form in node.ancestors)
            assert "disabled" in button.attrs
    assert "유료 웹 검색 1회 검증" in response.text
    assert "분석·대본·영상은 만들지 않습니다" in response.text
    assert "같은 인증 기록의 검증은 다시 전송하지 않습니다" in response.text
    assert not doc.find("input", name="max_cost_usd")
    assert not doc.find("input", name="request_limit_usd")
    assert "응답 후 확인되는 검색·토큰 비용" in response.text
    assert "이번 요청 비용은 사전에 확정되지 않습니다" in response.text
    assert "비용 상한을 보장하지 않습니다" in response.text
    assert calls == [] and settings(app) == before and encrypted == store.path.read_bytes()
    assert KEY not in response.text


def test_explicit_auth_then_search_prg_and_refresh_never_repeat(client, app, prepared):
    provider, model, store, calls = prepared
    token = csrf(client)
    encrypted = store.path.read_bytes()
    before = read_api_settings(app.state.sessions, provider)
    assert client.post(f"/api-settings/{provider}/check", data={
        "csrf_token": token, "consent": "true",
    }, follow_redirects=False).status_code == 303
    auth = read_api_settings(app.state.sessions, provider)
    assert auth.authentication_verified_at and not auth.search_verified_at
    form = {"csrf_token": token, "consent": "true", "model": model,
            "authentication_at": auth.authentication_verified_at}
    response = client.post(f"/api-settings/{provider}/check-search", data=form, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/simple-settings?saved=search-check#selected-ai"
    response = client.get(response.headers["location"])
    assert response.status_code == 200 and "검색 도구·출처·JSON·사용량 확인 완료" in response.text
    assert "기사 발행일·사실" in response.text and KEY not in response.text
    assert client.post(f"/api-settings/{provider}/check-search", data=form).status_code == 422
    client.get("/simple-settings")
    assert calls == ["metadata", "search"] and encrypted == store.path.read_bytes()
    after = read_api_settings(app.state.sessions, provider)
    assert after.approved_at == before.approved_at and after.search_approved_at == before.search_approved_at
    assert after.monthly_limit_usd == before.monthly_limit_usd and after.search_verified_at


def test_search_requires_origin_csrf_explicit_consent_and_current_model(client, app, prepared):
    provider, model, _, calls = prepared
    token = csrf(client)
    path = f"/api-settings/{provider}/check-search"
    assert client.post(path, data={"consent": "true"}).status_code == 403
    assert client.post(path, data={"csrf_token": token, "consent": "true"},
                       headers={"Origin": "https://foreign.invalid"}).status_code == 403
    assert client.post(path, data={"csrf_token": token}).status_code == 422
    assert client.post(path, data={"csrf_token": token, "consent": "true", "model": model,
                                   "authentication_at": "fabricated"}).status_code == 422
    assert client.post("/api-settings/claude_code/check-search", data={
        "csrf_token": token, "consent": "true",
    }).status_code == 422
    assert calls == [] and not read_api_settings(app.state.sessions, provider).search_verified_at
