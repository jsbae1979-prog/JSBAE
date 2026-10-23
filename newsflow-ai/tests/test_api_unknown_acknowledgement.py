"""Acknowledging an old unknown is local-only; every execution uses Fake data."""

import json
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import csrf
from sqlalchemy import select
from test_api_settings import configured, reserve
from test_api_settings import sessions as sessions  # noqa: PLC0414 - export shared pytest fixture
from test_api_settings import store as store  # noqa: PLC0414 - export shared pytest fixture
from test_claude_connection_gui import Document

from newsflow.db.models import APIRequestReservation, AppSetting, AuditLog, NewsArticle, NewsSource
from newsflow.gui import production_routes, production_status
from newsflow.intelligence.api_providers import FakeAPIProvider
from newsflow.intelligence.api_settings import (
    APIBudgetService,
    APISettingsError,
    FakeAPIBudgetService,
    acknowledge_unknown_analysis,
)
from newsflow.intelligence.provider import Options, ProviderTimeoutError
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import _set, write_studio_settings


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No real API, OAuth, CLI, audio or rendering is allowed")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    for name in ("NEWSFLOW_AI_API_KEY", "NEWSFLOW_ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for module in (production_routes, production_status):
        monkeypatch.setattr(module, "voice_choice_catalog", lambda: [
            {"name": "offline-silence", "label": "무음", "engine": "offline", "available": True},
        ])


def original(sessions):
    with sessions() as session:
        return [{column.name: getattr(row, column.name) for column in row.__table__.columns}
                for row in session.scalars(select(APIRequestReservation).order_by(APIRequestReservation.id))]


def unknown(sessions, store, *, request_id="old:analysis", **changes):
    budget = FakeAPIBudgetService(sessions)
    record = reserve(budget, store, request_id, **changes)
    budget.finish(record.id, status="unknown")
    return record


def review(sessions, store, record):
    return next(row for row in FakeAPIBudgetService(sessions).readiness(
        "claude_api", store, "analysis")["unknown_analysis_reviews"] if row["id"] == record.id)


def acknowledge(sessions, store, record, **changes):
    options = {"reservation_id": record.id, "fingerprint": review(sessions, store, record)["fingerprint"],
               "consent": True, **changes}
    acknowledge_unknown_analysis(sessions, "claude_api", **options)


def test_ack_preserves_original_amount_failure_usage_and_settings_and_survives_restart(sessions, store):
    configured(sessions)
    record = unknown(sessions, store)
    with sessions.begin() as session:
        session.get(APIRequestReservation, record.id).reserved_usd = "9.165"
    before = original(sessions)
    with sessions() as session:
        settings = [(row.key, row.value) for row in session.scalars(select(AppSetting).order_by(AppSetting.key))]
    assert not FakeAPIBudgetService(sessions).readiness("claude_api", store, "analysis")["ready"]
    acknowledge(sessions, store, record)
    acknowledge(sessions, store, record)  # duplicate POST / refresh is idempotent
    assert original(sessions) == before
    with sessions() as session:
        assert [(row.key, row.value) for row in session.scalars(select(AppSetting).order_by(AppSetting.key))] == settings
        audit = list(session.scalars(select(AuditLog)))
        assert len(audit) == 1 and audit[0].event == "api_unknown_analysis_ack"
        assert audit[0].created_at and "9.165" not in audit[0].message
        assert len(audit[0].message) < 500
    restarted = FakeAPIBudgetService(sessions)
    status = restarted.readiness("claude_api", store, "analysis")
    assert status["ready"] and status["usage"]["unknown"] == 1
    assert status["usage"]["held_usd"] == "9.165" and status["usage"]["vendor_billing"] == "NOT VERIFIED"
    assert status["acknowledged_unknown_analyses"] == 1
    assert reserve(restarted, store, "new:analysis").reserved_usd == 0
    with pytest.raises(APISettingsError, match="이미 기록된 요청"):
        reserve(restarted, store, "old:analysis")


@pytest.mark.parametrize("kind", ["search", "script"])
def test_ack_does_not_allow_search_or_script(sessions, store, kind):
    configured(sessions)
    record = unknown(sessions, store)
    acknowledge(sessions, store, record)
    budget = FakeAPIBudgetService(sessions)
    assert not budget.readiness("claude_api", store, kind)["ready"]
    with pytest.raises(APISettingsError, match="결과 불명"):
        reserve(budget, store, "new:" + kind, kind=kind, max_search_calls=int(kind == "search"))
    assert len(original(sessions)) == 1


@pytest.mark.parametrize("consent", [False, None, 1])
def test_no_implicit_acknowledgement(sessions, store, consent):
    configured(sessions)
    record = unknown(sessions, store)
    with pytest.raises(APISettingsError, match="명시적"):
        acknowledge(sessions, store, record, consent=consent)
    assert not review(sessions, store, record)["acknowledged"]


def test_provider_scope_current_model_and_record_fingerprint_are_enforced(sessions, store):
    configured(sessions)
    record = unknown(sessions, store)
    fingerprint = review(sessions, store, record)["fingerprint"]
    for provider in ("openai", "claude_code"):
        with pytest.raises(APISettingsError):
            acknowledge_unknown_analysis(sessions, provider, reservation_id=record.id,
                                         fingerprint=fingerprint, consent=True)
    with sessions.begin() as session:
        session.get(APIRequestReservation, record.id).reserved_usd = "3.055"
    with pytest.raises(APISettingsError, match="변경"):
        acknowledge_unknown_analysis(sessions, "claude_api", reservation_id=record.id,
                                     fingerprint=fingerprint, consent=True)
    acknowledge(sessions, store, record)
    with sessions.begin() as session:
        _set(session, "studio_model_claude_api", "claude-haiku-4-5-20251001")
    assert not FakeAPIBudgetService(sessions).readiness("claude_api", store, "analysis")["ready"]


@pytest.mark.parametrize("state", ["reserved", "failed", "success"])
def test_only_finished_unknown_analysis_can_be_acknowledged(sessions, store, state):
    configured(sessions)
    record = unknown(sessions, store)
    fingerprint = review(sessions, store, record)["fingerprint"]
    with sessions.begin() as session:
        session.get(APIRequestReservation, record.id).status = state
    with pytest.raises(APISettingsError, match="변경"):
        acknowledge_unknown_analysis(sessions, "claude_api", reservation_id=record.id,
                                     fingerprint=fingerprint, consent=True)


@pytest.mark.parametrize("change,reason", [
    ({"api_claude_api_approved_at": ""}, "사용 승인"),
    ({"api_claude_api_monthly_limit_usd": "0"}, "월별"),
    ({"api_claude_api_output_price_per_1m": "0"}, "단가"),
])
def test_ack_keeps_other_budget_gates(sessions, store, change, reason):
    configured(sessions)
    record = unknown(sessions, store)
    acknowledge(sessions, store, record)
    with sessions.begin() as session:
        for name, value in change.items():
            _set(session, name, value)
    with pytest.raises(APISettingsError, match=reason):
        reserve(FakeAPIBudgetService(sessions), store, "new:analysis")


def test_ack_does_not_bypass_authentication_or_another_unknown_or_active_request(sessions, store):
    configured(sessions)
    record = unknown(sessions, store)
    acknowledge(sessions, store, record)
    with pytest.raises(APISettingsError, match="실제 API 연결 미확인"):
        reserve(APIBudgetService(sessions), store, "new:analysis")
    second = reserve(FakeAPIBudgetService(sessions), store, "second:analysis")
    with pytest.raises(APISettingsError, match="결과 불명"):
        reserve(FakeAPIBudgetService(sessions), store, "third:analysis")
    FakeAPIBudgetService(sessions).finish(second.id, status="unknown")
    with pytest.raises(APISettingsError, match="결과 불명"):
        reserve(FakeAPIBudgetService(sessions), store, "third:analysis")


def test_atomic_acknowledgement_and_concurrent_new_requests(sessions, store):
    configured(sessions)
    record = unknown(sessions, store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: acknowledge(sessions, store, record), range(2)))
    with sessions() as session:
        assert len(list(session.scalars(select(AuditLog)))) == 1

    def attempt(number):
        try:
            return reserve(FakeAPIBudgetService(sessions), store, f"new:{number}")
        except APISettingsError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(result is not None for result in results) == 1


def test_fake_analysis_needs_execution_consent_and_failed_new_request_is_not_retried(sessions, store):
    configured(sessions)
    old = unknown(sessions, store)
    acknowledge(sessions, store, old)
    adapter = FakeAPIProvider("claude_api")
    service = IntelligenceService(sessions, api_key_stores={"claude_api": store},
                                  api_providers={"claude_api": adapter}, api_budget=FakeAPIBudgetService(sessions))
    with sessions.begin() as session:
        source = NewsSource(name="합성 출처", url="https://example.com/rss", enabled=False)
        session.add(source)
        session.flush()
        article = NewsArticle(source_id=source.id, title="지역 정책 합성 자료", summary="합성 RSS 요약입니다.",
                              publisher="합성 출처", url="https://example.com/a", canonical_url="https://example.com/a")
        session.add(article)
        session.flush()
        identifier = article.id
    options = Options(model="claude-sonnet-4-6")
    with pytest.raises(IntelligenceError, match="명시적 동의"):
        service.analyze([identifier], "claude_api", False, options)
    assert adapter.calls == []
    analysis_id = service.analyze([identifier], "claude_api", True, options)
    assert analysis_id and adapter.calls == ["analysis"]
    adapter.result = ProviderTimeoutError()
    with pytest.raises(IntelligenceError):
        service.analyze([identifier], "claude_api", True, options)
    assert adapter.calls == ["analysis", "analysis"]
    with pytest.raises(IntelligenceError, match="결과 불명"):
        service.analyze([identifier], "claude_api", True, options)
    assert adapter.calls == ["analysis", "analysis"]


def test_gui_get_csrf_origin_consent_and_idempotent_ack_only(client, app, store):
    sessions = app.state.sessions
    configured(sessions)
    write_studio_settings(sessions, "claude_api", "claude-sonnet-4-6")
    app.state.api_keys["claude_api"] = store
    app.state.autopilot_backend.intelligence.api_key_stores["claude_api"] = store
    record = unknown(sessions, store)
    before = original(sessions)
    encrypted = store.path.read_bytes()
    page = client.get("/simple-settings")
    assert page.status_code == 200 and not review(sessions, store, record)["acknowledged"]
    path = "/api-settings/claude_api/acknowledge-unknown-analysis"
    document = Document(page.text)
    form = document.find("form", action=path)[0]
    fields = {node.attrs["name"]: node for node in document.find("input") if form in node.ancestors
              and node.attrs.get("name")}
    assert "checked" not in fields["consent"].attrs and "required" in fields["consent"].attrs
    payload = {name: node.attrs.get("value", "") for name, node in fields.items()}
    payload["consent"] = "true"
    assert client.post(path, data={**payload, "csrf_token": "wrong"}).status_code == 403
    assert client.post(path, data=payload, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    assert client.post(path, data={**payload, "consent": "false"}).status_code == 422
    assert client.post(path, data={**payload, "fingerprint": "0" * 64}).status_code == 422
    payload["csrf_token"] = csrf(client)
    for _ in range(2):
        response = client.post(path, data=payload, follow_redirects=False)
        assert response.status_code == 303
    result = client.get(response.headers["location"])
    assert result.status_code == 200 and "실제 분석은 실행하지 않았습니다" in result.text
    assert "새 기사 분석만 차단 예외" in result.text and "검색·대본의 결과 불명 차단은 유지" in result.text
    assert path not in result.text
    assert original(sessions) == before and store.path.read_bytes() == encrypted
    with sessions() as session:
        entries = list(session.scalars(select(AuditLog).where(AuditLog.event == "api_unknown_analysis_ack")))
        assert len(entries) == 1 and store.key() not in entries[0].message
        assert json.loads(entries[0].message)["scope"] == "new_analysis_only"
