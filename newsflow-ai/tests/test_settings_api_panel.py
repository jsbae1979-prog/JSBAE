"""Selected API settings remain clear, accessible and approval-gated without I/O."""

from dataclasses import replace
from decimal import Decimal
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

from newsflow.gui.routes import templates
from newsflow.intelligence.api_settings import APISettings


class Panel(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.containers = []
        self.inputs = []
        self.dialogs = []
        self.forms = []
        self.details = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        parents = tuple(self.containers)
        if tag in {"dialog", "details", "form"}:
            getattr(self, {"dialog": "dialogs", "details": "details", "form": "forms"}[tag]).append(
                (values, parents)
            )
            self.containers.append(tag)
        if tag == "input":
            self.inputs.append((values, parents))

    def handle_endtag(self, tag):
        if tag in {"dialog", "details", "form"}:
            assert self.containers.pop() == tag

    def field(self, name):
        matches = [item for item in self.inputs if item[0].get("name") == name]
        assert len(matches) == 1, name
        return matches[0]


def render_panel(provider="openai", *, settings=None, token_limit=0, **changes):
    config = settings or APISettings(provider, "gpt-4.1-mini" if provider == "openai" else "claude-sonnet-4-6")
    api = {
        "settings": config, "authentication_verified": False, "request_succeeded": False,
        "key": {"configured": False, "stored": False, "environment": False, "storage_supported": True},
        "usage": {"unknown": 0, "pending": 0, "held_usd": "0", "calls": 0, "estimated_usd": "0", "test_calls": 0},
        **changes,
    }
    html = templates.env.get_template("api_connection.html").render(
        key=provider, api_connections={provider: api}, csrf_field=lambda: "CSRF-FIELD",
        legacy_api_settings=SimpleNamespace(request_token_limit=token_limit, timeout=30),
    )
    html += templates.env.get_template("api_budget.html").render(
        key=provider, api=api, api_label="OpenAI API" if provider == "openai" else "Claude API",
        csrf_field=lambda: "CSRF-FIELD",
        legacy_api_settings=SimpleNamespace(request_token_limit=token_limit, timeout=30))
    return html, Panel(html)


@pytest.mark.parametrize("provider", ["openai", "claude_api"])
def test_key_registration_is_direct_and_costs_use_one_accessible_dialog(provider):
    html, panel = render_panel(provider)
    field, parents = panel.field("api_key")
    assert parents == ("details", "form") and field["type"] == "password" and "value" not in field
    assert field["id"] in html and field["aria-describedby"] in html
    assert len(panel.dialogs) == 1 and panel.dialogs[0][0]["aria-labelledby"] in html
    assert panel.dialogs[0][0]["id"] == f"api-costs-{provider}" and "data-settings-close" in html
    assert all("form" not in parents for _, parents in panel.forms)
    assert all("data-settings-form" in attrs and "data-settings-watch" in attrs for attrs, _ in panel.forms)
    assert len(panel.details) == 3
    key_details = next(attrs for attrs, _ in panel.details if attrs.get("id") == provider + "-key-settings")
    assert "open" in key_details
    assert "실제 연결 미확인" in html and "실제 웹 검색 미검증 · BLOCKED" in html


@pytest.mark.parametrize("provider", ["openai", "claude_api"])
def test_mandatory_approvals_and_budget_are_visible_in_dialog_and_not_prechecked(provider):
    html, panel = render_panel(provider)
    for name in ("approved", "search_enabled", "search_approved", "request_limit_usd"):
        field, parents = panel.field(name)
        assert parents == ("dialog", "form") and "checked" not in field
    assert not any(field.get("name") == "monthly_limit_usd" for field, _ in panel.inputs)
    assert not any(field.get("name") in {"billing_confirmed", "account_remaining_usd"} for field, _ in panel.inputs)
    assert "보수적 예상 비용이 1회 한도 안에 있을 때만 승인" in html
    assert "details" in panel.field("input_price_per_1m")[1]
    assert "details" in panel.field("search_price_per_1k")[1]


def test_existing_approvals_remain_independent_without_manual_balance_fields():
    settings = APISettings("claude_api", "claude-sonnet-4-6", approved_at="saved",
                           search_enabled=True, search_approved_at=None, billing_confirmed_at="saved")
    _, panel = render_panel("claude_api", settings=settings)
    assert "checked" in panel.field("approved")[0]
    assert "checked" in panel.field("search_enabled")[0]
    assert "checked" not in panel.field("search_approved")[0]
    assert not any(field.get("name") in {"billing_confirmed", "account_remaining_usd"} for field, _ in panel.inputs)


@pytest.mark.parametrize("token_limit", [0, 150000])
def test_required_openai_token_limit_stays_visible_until_configured(token_limit):
    _, panel = render_panel(token_limit=token_limit)
    field, parents = panel.field("request_token_limit")
    assert field["value"] == str(token_limit) and "required" in field
    assert ("details" in parents) is (token_limit > 0)
    assert "details" in panel.field("timeout")[1]


def test_unknown_reservation_is_prominent_outside_dialog():
    usage = {"unknown": 1, "pending": 0, "held_usd": "7.50", "calls": 2, "estimated_usd": "0", "test_calls": 0}
    html, _ = render_panel(usage=usage)
    before_dialog = html.split("<dialog", 1)[0]
    assert 'role="alert"' in before_dialog and "결과 불명 1건" in before_dialog
    assert "새 API 호출이 차단" in before_dialog and "기존 기록은 유지" in before_dialog
    assert "7.50" not in html and "보존된 예약" not in html


def test_missing_rates_are_explained_and_saved_zero_is_not_dropped():
    html, panel = render_panel()
    assert "단가 입력이 필요합니다" in html and "open" in next(attrs for attrs, _ in panel.details if attrs.get("id") == "openai-price-settings")
    config = APISettings("openai", "gpt-4.1-mini", input_price_per_1m=Decimal(0),
                         output_price_per_1m=Decimal(2), search_price_per_1k=Decimal(10))
    html, panel = render_panel(settings=config)
    assert "단가 입력이 필요합니다" not in html and "open" not in next(attrs for attrs, _ in panel.details if attrs.get("id") == "openai-price-settings")
    assert panel.field("input_price_per_1m")[0]["value"] == "0"


def test_key_registration_or_old_search_record_never_implies_current_verification():
    settings = APISettings("openai", "gpt-4.1-mini", search_verified_at="old", verified_model="old-model")
    key = {"configured": True, "stored": True, "environment": False, "storage_supported": True}
    html, _ = render_panel(settings=settings, key=key)
    assert "API Key 등록됨" in html and "실제 연결 미확인" in html
    assert "실제 웹 검색 미검증 · BLOCKED" in html
    html, _ = render_panel(settings=replace(settings, verified_model=settings.model),
                           authentication_verified=True, key=key)
    assert "실제 인증 확인 기록 있음" in html and "실제 웹 검색 성공 기록 있음" in html
