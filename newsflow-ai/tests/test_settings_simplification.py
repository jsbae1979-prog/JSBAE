"""Settings UX contracts with isolated data, synthetic secrets and no remote/CLI calls."""

import subprocess
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

import pytest
from conftest import csrf
from fastapi.testclient import TestClient
from sqlalchemy import select

from newsflow.config import Settings
from newsflow.db.models import APIRequestReservation, AppSetting, IntelligenceRun
from newsflow.gui import production_routes, production_status
from newsflow.intelligence.api_settings import read_api_settings, save_api_settings
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, FakeCipher
from newsflow.intelligence.settings import write_studio_settings
from newsflow.main import create_app


@dataclass
class Element:
    tag: str
    attrs: dict
    ancestors: tuple
    text: list[str] = field(default_factory=list)


class Document(HTMLParser):
    """A small structural reader; no browser behavior is simulated here."""

    def __init__(self, html):
        super().__init__()
        self.nodes = []
        self.stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, dict(attrs), tuple(self.stack))
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
                and all(node.attrs.get(key) == value for key, value in attrs.items())]


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Settings verification must not execute a CLI or vendor request")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    catalog = [
        {"name": "offline-silence", "label": "무음", "engine": "offline", "available": True},
        {"name": "supertonic:F1", "label": "Supertonic F1", "engine": "supertonic", "available": True},
        {"name": "elevenlabs", "label": "ElevenLabs", "engine": "elevenlabs", "available": False},
    ]
    for module in (production_routes, production_status):
        monkeypatch.setattr(module, "voice_choice_catalog", lambda: [dict(row) for row in catalog])


def values(app):
    with app.state.sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def save_values(app, **fields):
    with app.state.sessions.begin() as session:
        for key, value in fields.items():
            row = session.get(AppSetting, key)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=key, value=value))


def configured(app, provider):
    return save_api_settings(
        app.state.sessions, provider, model="gpt-4.1-mini" if provider == "openai" else "claude-sonnet-4-6",
        approved=True, search_enabled=True, search_approved=True, request_limit_usd="10",
        monthly_limit_usd="40", input_price_per_1m="3", output_price_per_1m="15", search_price_per_1k="10",
        billing_confirmed=True, account_remaining_usd="40",
    )


def synthetic_stores(app):
    stores = {"openai": AIKeyStore(app.state.config.data_dir, FakeCipher()),
              "claude_api": AnthropicKeyStore(app.state.config.data_dir, FakeCipher())}
    for provider, store in stores.items():
        store.save("sk-synthetic-settings-ux-key-" + provider)
    app.state.ai_keys = stores["openai"]
    app.state.api_keys = stores
    app.state.autopilot_backend.intelligence.api_key_stores = stores
    return stores


def test_three_sections_four_saved_statuses_and_seven_on_demand_diagnostics(client, app):
    write_studio_settings(app.state.sessions, "claude_api", "claude-sonnet-4-6")
    save_values(app, video_default_voice="supertonic:F1", autopilot_source="feeds")
    before = values(app)
    response = client.get("/simple-settings")
    dom = Document(response.text)
    for section in ("connections", "quality", "schedules"):
        assert dom.find("section", id=section)
    assert {node.attrs["data-summary-stage"] for node in dom.nodes if "data-summary-stage" in node.attrs} == {
        "search", "analysis", "voice", "video"}
    stages = [node for node in dom.nodes if "data-stage" in node.attrs]
    assert len(stages) == 7
    assert all(any(parent.tag == "dialog" and parent.attrs.get("id") == "settings-diagnostics"
                   for parent in node.ancestors) for node in stages)
    assert all(not any(parent.tag == "details" for parent in node.ancestors) for node in stages)
    assert "Claude API" in response.text and "Supertonic F1" in response.text and "FFmpeg" in response.text
    assert values(app) == before
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("provider,model", [
    ("openai", "gpt-4.1-mini"), ("claude_api", "claude-sonnet-4-6"),
    ("claude_code", "sonnet"), ("codex", "default"), ("offline", "offline"),
])
def test_only_saved_provider_is_exposed_on_initial_view(client, app, provider, model):
    write_studio_settings(app.state.sessions, provider, model)
    dom = Document(client.get("/simple-settings").text)
    panels = [node for node in dom.nodes if "data-ai-provider" in node.attrs]
    assert {node.attrs["data-ai-provider"] for node in panels} == {
        "openai", "claude_api", "claude_code", "codex", "offline"}
    assert [node.attrs["data-ai-provider"] for node in panels if "hidden" not in node.attrs] == [provider]
    with app.state.sessions() as session:
        assert not list(session.scalars(select(IntelligenceRun)))


@pytest.mark.parametrize("provider", ["openai", "claude_api"])
def test_key_entry_is_direct_and_cost_approvals_are_not_prechecked_or_hidden_in_advanced(client, app, provider):
    write_studio_settings(app.state.sessions, provider,
                          "gpt-4.1-mini" if provider == "openai" else "claude-sonnet-4-6")
    # Fake cipher is only for this isolated DB, allowing the same key UI on non-Windows test hosts.
    stores = synthetic_stores(app)
    stores[provider].clear()
    dom = Document(client.get("/simple-settings").text)
    key_form = dom.find("form", action=f"/api-settings/{provider}/key")[0]
    assert not any(parent.tag in {"details", "dialog"} for parent in key_form.ancestors)
    key_input = next(node for node in dom.find("input", name="api_key") if key_form in node.ancestors)
    assert key_input.attrs["type"] == "password" and "value" not in key_input.attrs
    assert any(parent.tag == "label" for parent in key_input.ancestors)
    cost_form = dom.find("form", action=f"/api-settings/{provider}")[0]
    assert any(parent.tag == "dialog" for parent in cost_form.ancestors)
    for name in ("approved", "search_enabled", "search_approved", "billing_confirmed"):
        control = next(node for node in dom.find("input", name=name) if cost_form in node.ancestors)
        assert "checked" not in control.attrs
        assert not any(parent.tag == "details" for parent in control.ancestors)
    assert dom.find("input", name="monthly_limit_usd")


def test_voice_change_preserves_other_providers_keys_approvals_and_unknown_reservation(client, app, monkeypatch):
    stores = synthetic_stores(app)
    for provider in stores:
        configured(app, provider)
    write_studio_settings(app.state.sessions, "claude_code", "opus")
    write_studio_settings(app.state.sessions, "codex", "default")
    save_values(app, video_ai_approved_at="2026-10-16T00:00:00+00:00", video_ai_monthly_limit="100",
                autopilot_acquisition_policy="rss", video_default_voice="offline-silence")
    with app.state.sessions.begin() as session:
        session.add(APIRequestReservation(id="synthetic-unknown", request_id="synthetic-unknown-1",
                    provider="claude_api", kind="search", model="claude-sonnet-4-6", status="unknown",
                    reserved_usd="4.20", bounds={}, prices={}, usage={}, test_only=True))
    before = values(app)
    api_before = {provider: read_api_settings(app.state.sessions, provider) for provider in stores}
    key_bytes = {provider: store.path.read_bytes() for provider, store in stores.items()}
    validated = []
    monkeypatch.setattr(production_routes, "validate_voice_preferences", lambda *args: validated.append(args))
    response = client.post("/production/preferences", data={
        "csrf_token": csrf(client), "provider": "codex", "model": "default", "source": "feeds",
        "duration": "45", "platform": "youtube", "voice": "supertonic:F1", "rate": "0",
        "pause_ms": "250", "video_provider": "off", "acquisition_policy": "rss", "category": "it", "period": "24h",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert validated == [("supertonic:F1", "0", "250")]
    after = values(app)
    editable = {"studio_provider", "studio_model_codex", "autopilot_source", "autopilot_duration", "autopilot_platform",
                "autopilot_acquisition_policy", "autopilot_category", "autopilot_period", "video_default_voice",
                "video_default_rate", "video_default_pause_ms", "video_ai_provider"}
    assert {key: value for key, value in before.items() if key not in editable} == {
        key: value for key, value in after.items() if key not in editable}
    assert after["video_default_voice"] == "supertonic:F1" and after["studio_model_claude_code"] == "opus"
    assert {provider: read_api_settings(app.state.sessions, provider) for provider in stores} == api_before
    assert {provider: store.path.read_bytes() for provider, store in stores.items()} == key_bytes
    with app.state.sessions() as session:
        reservation = session.get(APIRequestReservation, "synthetic-unknown")
        assert (reservation.status, reservation.reserved_usd) == ("unknown", "4.20")
    status = app.state.autopilot_backend.intelligence.api_readiness("claude_api")
    assert not status["ready"] and status["usage"]["unknown"] == 1


def test_restart_keeps_saved_voice_policy_and_independent_api_approvals(tmp_path, fake, monkeypatch):
    config = Settings(data_dir=tmp_path / "settings-restart")
    first = create_app(config, fake)
    stores = synthetic_stores(first)
    for provider in stores:
        configured(first, provider)
    save_values(first, studio_provider="claude_api", video_default_voice="supertonic:F1",
                autopilot_acquisition_policy="rss")
    before = values(first)
    key_bytes = {provider: store.path.read_bytes() for provider, store in stores.items()}
    with TestClient(first, base_url="http://127.0.0.1") as client:
        assert client.get("/simple-settings").status_code == 200
    second = create_app(config, fake)
    with TestClient(second, base_url="http://127.0.0.1") as client:
        page = client.get("/simple-settings")
        assert page.status_code == 200 and 'value="supertonic:F1"' in page.text
        assert values(second) == before
        assert {provider: store.path.read_bytes() for provider, store in stores.items()} == key_bytes
        assert not second.state.autopilot_backend.intelligence.api_readiness("claude_api")["ready"]


def test_advanced_links_and_legacy_anchors_remain_available(client):
    dom = Document(client.get("/simple-settings").text)
    for anchor in ("production", "connections", "quality", "schedules", "advanced", "selected-ai",
                   "selected-voice", "selected-video", "pipeline-status"):
        assert dom.find(id=anchor)
    links = {node.attrs.get("href") for node in dom.find("a")}
    assert {"/", "/sources", "/ai", "/video", "/schedules", "/operations", "/settings",
            "/ai-settings", "/video-ai-settings", "/video/tts"} <= links
