"""Explicit Claude connection checks with synthetic keys and no vendor or CLI I/O."""

import json
import subprocess
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AppSetting, utcnow
from newsflow.gui import api_settings_routes, production_routes, production_status
from newsflow.intelligence.api_settings import read_api_settings
from newsflow.intelligence.credentials import AnthropicKeyStore, FakeCipher
from newsflow.intelligence.settings import _set, write_studio_settings

SYNTHETIC_KEY = "sk-synthetic-claude-connection-gui-0123456789"


@dataclass
class Node:
    tag: str
    attrs: dict
    ancestors: tuple
    text: list[str] = field(default_factory=list)


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes = []
        self.stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), tuple(self.stack))
        self.nodes.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        for node in self.stack:
            node.text.append(data)

    def find(self, tag=None, **attrs):
        return [node for node in self.nodes if (not tag or node.tag == tag)
                and all(node.attrs.get(name) == value for name, value in attrs.items())]


@pytest.fixture(autouse=True)
def isolated_without_network_or_cli(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Claude GUI tests must not execute a CLI or vendor HTTP request")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    monkeypatch.delenv("NEWSFLOW_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    for module in (production_routes, production_status):
        monkeypatch.setattr(module, "voice_choice_catalog", lambda: [
            {"name": "offline-silence", "label": "무음", "engine": "offline", "available": True},
        ])


@pytest.fixture
def claude_store(app):
    store = AnthropicKeyStore(app.state.config.data_dir, FakeCipher())
    app.state.api_keys["claude_api"] = store
    app.state.autopilot_backend.intelligence.api_key_stores["claude_api"] = store
    write_studio_settings(app.state.sessions, "claude_api", "claude-sonnet-4-6")
    return store


def values(app):
    with app.state.sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def result(*, ok=True, code="success", message="인증과 저장된 모델 접근을 확인했습니다."):
    return SimpleNamespace(ok=ok, code=code, message=message, checked_at="2026-10-17T00:00:00+00:00")


def claude_panel(document):
    return document.find("div", **{"data-api-connection": "claude_api"})[0]


def test_connection_action_is_explicit_outside_cost_dialog_with_official_dashboard(client, claude_store):
    document = Document(client.get("/simple-settings").text)
    form = document.find("form", action="/api-settings/claude_api/check")[0]
    assert not any(node.tag in {"dialog", "form"} for node in form.ancestors)
    # Connection checks are folded independently, outside the cost dialog.
    details = [node for node in form.ancestors if node.tag == "details"]
    assert len(details) == 1 and details[0].attrs["id"] == "claude_api-connection-settings"
    assert "open" not in details[0].attrs
    assert "data-settings-form" in form.attrs and "data-settings-watch" in form.attrs
    consent = next(node for node in document.find("input", name="consent") if form in node.ancestors)
    assert consent.attrs["type"] == "checkbox" and "checked" not in consent.attrs
    assert "required" in consent.attrs
    assert not any(node.attrs.get("name") in {"monthly_limit_usd", "request_limit_usd", "model"}
                   for node in document.nodes if form in node.ancestors)
    link = document.find("a", href="https://platform.claude.com/dashboard")[0]
    assert link.attrs["target"] == "_blank"
    assert {"noopener", "noreferrer"} <= set(link.attrs["rel"].split())
    assert "Claude" in "".join(link.text)


def test_key_status_uses_visible_label_as_well_as_color_without_claiming_authentication(client, claude_store):
    document = Document(client.get("/simple-settings").text)
    panel = claude_panel(document)
    missing = next(node for node in document.find("span")
                   if panel in node.ancestors and "API Key 미등록" in "".join(node.text))
    assert "status-chip--error" in missing.attrs["class"].split()
    claude_store.save(SYNTHETIC_KEY)
    response = client.get("/simple-settings")
    document = Document(response.text)
    panel = claude_panel(document)
    stored = next(node for node in document.find("span")
                  if panel in node.ancestors and "API Key 등록됨" in "".join(node.text))
    pending = next(node for node in document.find("span")
                   if panel in node.ancestors and "실제 연결 미확인" in "".join(node.text))
    assert "status-chip--success" in stored.attrs["class"].split()
    assert "status-chip--warning" in pending.attrs["class"].split()
    assert SYNTHETIC_KEY not in response.text


def test_authentication_success_and_failure_have_distinct_accessible_statuses(client, app, claude_store):
    claude_store.save(SYNTHETIC_KEY)
    with app.state.sessions.begin() as session:
        _set(session, "api_claude_api_authentication_verified_at", utcnow().isoformat())
        _set(session, "api_claude_api_verified_model", "claude-sonnet-4-6")
    response = client.get("/simple-settings")
    document = Document(response.text)
    panel = claude_panel(document)
    verified = next(node for node in document.find("span")
                    if panel in node.ancestors and "실제 인증 확인 기록 있음" in "".join(node.text))
    assert "status-chip--success" in verified.attrs["class"].split()
    assert "실제 웹 검색 미검증 · BLOCKED" in "".join(panel.text)
    with app.state.sessions.begin() as session:
        _set(session, "api_claude_api_authentication_verified_at", "")
        _set(session, "api_claude_api_connection_check_code", "auth_error")
        _set(session, "api_claude_api_connection_checked_at", utcnow().isoformat())
    response = client.get("/simple-settings")
    document = Document(response.text)
    panel = claude_panel(document)
    failures = [node for node in document.find("span") if panel in node.ancestors
                and "status-chip--error" in node.attrs.get("class", "").split()]
    assert failures and all("".join(node.text).strip() for node in failures)
    assert "실제 인증 확인 기록 있음" not in "".join(panel.text)
    assert "실제 웹 검색 미검증 · BLOCKED" in "".join(panel.text)
    assert SYNTHETIC_KEY not in response.text


def test_get_key_save_and_policy_save_never_start_connection_check(client, app, claude_store, monkeypatch):
    monkeypatch.setattr(api_settings_routes, "check_claude_connection",
                        lambda *args, **kwargs: pytest.fail("Only the explicit check POST may probe"))
    token = csrf(client)
    assert client.get("/simple-settings").status_code == 200
    assert client.post("/api-settings/claude_api/key", data={
        "csrf_token": token, "api_key": SYNTHETIC_KEY,
    }, follow_redirects=False).status_code == 303
    response = client.post("/api-settings/claude_api", data={
        "csrf_token": token, "model": "claude-sonnet-4-6",
        "request_limit_usd": "0", "monthly_limit_usd": "0",
        "input_price_per_1m": "", "output_price_per_1m": "", "search_price_per_1k": "",
    }, follow_redirects=False)
    assert response.status_code == 303
    settings = read_api_settings(app.state.sessions, "claude_api")
    assert settings.authentication_verified_at is None and settings.search_verified_at is None
    assert not settings.approved and not settings.search_approved
    assert SYNTHETIC_KEY not in json.dumps(values(app))


def test_check_uses_saved_model_without_budget_fields_and_preserves_other_state(
    client, app, claude_store, monkeypatch,
):
    claude_store.save(SYNTHETIC_KEY)
    token = csrf(client)
    before = values(app)
    encrypted = claude_store.path.read_bytes()
    transport = object()
    app.state.claude_connection_transport = transport
    calls = []

    def fake_check(sessions, store, *, consent=False, transport=None):
        calls.append((sessions, store, consent, transport, read_api_settings(sessions, "claude_api").model))
        return result()

    monkeypatch.setattr(api_settings_routes, "check_claude_connection", fake_check)
    response = client.post("/api-settings/claude_api/check", data={
        "csrf_token": token, "consent": "true", "model": "claude-untrusted-unsaved-model",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/simple-settings?saved=connection")
    assert calls == [(app.state.sessions, claude_store, True, transport, "claude-sonnet-4-6")]
    assert values(app) == before and claude_store.path.read_bytes() == encrypted
    settings = read_api_settings(app.state.sessions, "claude_api")
    assert not settings.approved and not settings.search_approved
    assert settings.monthly_limit_usd == 0 and settings.request_limit_usd == 0
    assert settings.search_verified_at is None and settings.request_succeeded_at is None
    with app.state.sessions() as session:
        assert not list(session.scalars(select(APIRequestReservation)))


def test_missing_consent_is_passed_as_false_and_failure_is_displayable(client, app, claude_store, monkeypatch):
    calls = []

    def fake_check(sessions, store, *, consent=False, **kwargs):
        calls.append(consent)
        return result(ok=False, code="consent_required", message="연결 확인에 동의해 주세요.")

    monkeypatch.setattr(api_settings_routes, "check_claude_connection", fake_check)
    before = values(app)
    response = client.post("/api-settings/claude_api/check", data={"csrf_token": csrf(client)},
                           follow_redirects=False)
    assert response.status_code == 422 and calls == [False]
    assert response.json()["detail"] == "연결 확인에 동의해 주세요."
    assert values(app) == before


@pytest.mark.parametrize("code,message", [
    ("authentication_failed", "API Key를 확인해 주세요."),
    ("permission_denied", "모델 접근 권한을 확인해 주세요."),
    ("rate_limited", "요청 한도에 도달했습니다. 잠시 후 직접 확인해 주세요."),
    ("timeout", "연결 확인 시간이 초과됐습니다. 자동 재시도하지 않습니다."),
])
def test_failed_check_returns_safe_actionable_error_without_secret_or_retry(
    client, claude_store, monkeypatch, code, message,
):
    claude_store.save(SYNTHETIC_KEY)
    calls = []

    def fake_check(*args, **kwargs):
        calls.append(True)
        return result(ok=False, code=code, message=message)

    monkeypatch.setattr(api_settings_routes, "check_claude_connection", fake_check)
    response = client.post("/api-settings/claude_api/check", data={
        "csrf_token": csrf(client), "consent": "true",
    }, follow_redirects=False)
    assert response.status_code == 422 and response.json()["detail"] == message
    assert calls == [True] and SYNTHETIC_KEY not in response.text


def test_check_keeps_csrf_origin_and_provider_validation_before_probe(client, claude_store, monkeypatch):
    monkeypatch.setattr(api_settings_routes, "check_claude_connection",
                        lambda *args, **kwargs: pytest.fail("Rejected requests must not probe"))
    token = csrf(client)
    assert client.post("/api-settings/claude_api/check", data={"consent": "true"}).status_code == 403
    assert client.post("/api-settings/claude_api/check", data={"csrf_token": token, "consent": "true"},
                       headers={"Origin": "https://foreign.example"}).status_code == 403
    for provider in ("openai", "claude_code", "unknown"):
        assert client.post(f"/api-settings/{provider}/check", data={
            "csrf_token": token, "consent": "true",
        }).status_code == 422
