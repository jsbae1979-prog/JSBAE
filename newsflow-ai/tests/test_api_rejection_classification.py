"""Explicit request rejection is not an uncertain inference. Fake/local only."""
import copy
import json
import urllib.request

import pytest
import test_api_settings as api_fixtures
from sqlalchemy import select
from test_api_settings import configured, reserve

from newsflow.db.models import APIRequestReservation, IntelligenceRun, utcnow
from newsflow.intelligence.api_settings import APISettingsError, FakeAPIBudgetService

sessions = api_fixtures.sessions
store = api_fixtures.store


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No external request permitted")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)


def evidence(sessions, *, kind="analysis", **details):
    diagnostic = {"failure_reason": "request_rejected", "http_status": 400,
                  "error_type": "invalid_request_error"}
    diagnostic.update(details)
    with sessions.begin() as session:
        run = IntelligenceRun(kind=kind, status="failed", provider="claude_api",
                              options={"model": "claude-sonnet-4-6"}, evidence={},
                              result={f"{kind}_failure": diagnostic}, message="safe failure",
                              finished_at=utcnow())
        session.add(run)
        session.flush()
        return run.id


def journal(sessions):
    with sessions() as session:
        return [{c.name: copy.deepcopy(getattr(row, c.name)) for c in row.__table__.columns}
                for row in session.scalars(select(APIRequestReservation).order_by(APIRequestReservation.id))]


@pytest.mark.parametrize("kind", ["analysis", "script"])
def test_explicit_rejection_finishes_failed_without_inventing_usage(sessions, store, kind):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    run_id = evidence(sessions, kind=kind)
    result = reserve(budget, store, request_id=f"intelligence:{run_id}", kind=kind)
    budget.finish(result.id, status="failed")
    row = journal(sessions)[0]
    assert row["status"] == "failed"
    assert row["estimated_usd"] is None  # Missing billing data is never a zero-cost claim.
    assert row["usage"] == {"search_calls": 0}
    assert budget.readiness("claude_api", store, "script")["ready"]
    with pytest.raises(APISettingsError, match="이미 기록된 요청"):
        reserve(budget, store, request_id=f"intelligence:{run_id}", kind=kind)


def test_legacy_unknown_preserved_but_new_request_allowed_after_restart(sessions, store):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    run_id = evidence(sessions)
    result = reserve(budget, store, request_id=f"intelligence:{run_id}")
    budget.finish(result.id, status="unknown")  # Reproduce historical journal classification.
    with sessions.begin() as session:
        session.get(APIRequestReservation, result.id).reserved_usd = "9.165"
    before = journal(sessions)
    restarted = FakeAPIBudgetService(sessions)
    for kind in ("analysis", "script", "search"):
        assert restarted.readiness("claude_api", store, kind)["ready"]
    assert journal(sessions) == before
    reserve(restarted, store, request_id="feed-card:123", kind="script")
    assert next(row for row in journal(sessions) if row["id"] == result.id) == before[0]
    with pytest.raises(APISettingsError, match="이미 기록된 요청"):
        reserve(restarted, store, request_id=f"intelligence:{run_id}")


@pytest.mark.parametrize("details", [
    {"http_status": 408}, {"http_status": 429}, {"http_status": 500},
    {"http_status": "400"}, {"error_type": "other"},
    {"failure_reason": "response_envelope"}, {"failure_reason": "result_json"},
])
def test_ambiguous_or_non_allowlisted_response_stays_blocked(sessions, store, details):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    run_id = evidence(sessions, **details)
    row = reserve(budget, store, request_id=f"intelligence:{run_id}")
    budget.finish(row.id, status="failed")
    assert journal(sessions)[0]["status"] == "unknown"
    assert not budget.readiness("claude_api", store, "script")["ready"]
    with pytest.raises(APISettingsError, match="결과 불명"):
        reserve(budget, store, request_id="new:2")


@pytest.mark.parametrize("field,value", [
    ("model", "other"), ("provider", "openai"), ("kind", "script"),
    ("status", "success"), ("finished_at", None), ("result", {}),
])
def test_mismatched_or_incomplete_evidence_cannot_release_gate(sessions, store, field, value):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    run_id = evidence(sessions)
    row = reserve(budget, store, request_id=f"intelligence:{run_id}")
    with sessions.begin() as session:
        run = session.get(IntelligenceRun, run_id)
        if field == "model":
            run.options = {"model": value}
        else:
            setattr(run, field, value)
    budget.finish(row.id, status="failed")
    assert journal(sessions)[0]["status"] == "unknown"
    assert not budget.readiness("claude_api", store, "script")["ready"]


def test_rejection_does_not_exempt_other_timeout_or_pending_request(sessions, store):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    run_id = evidence(sessions)
    rejected = reserve(budget, store, request_id=f"intelligence:{run_id}")
    budget.finish(rejected.id, status="unknown")
    timed_out = reserve(budget, store, request_id="unrelated:timeout")
    assert not budget.readiness("claude_api", store, "script")["ready"]
    budget.finish(timed_out.id, status="unknown")
    assert not budget.readiness("claude_api", store, "script")["ready"]
    with pytest.raises(APISettingsError, match="결과 불명"):
        reserve(budget, store, request_id="new:card", kind="script")


def test_partial_positive_usage_is_not_explicit_pre_execution_rejection(sessions, store):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    run_id = evidence(sessions)
    row = reserve(budget, store, request_id=f"intelligence:{run_id}")
    budget.finish(row.id, status="failed", usage={"prompt_tokens": 10})
    assert journal(sessions)[0]["status"] == "unknown"
    assert not budget.readiness("claude_api", store, "script")["ready"]


def test_rejection_does_not_grant_approval_or_erase_monthly_usage(sessions, store):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    run_id = evidence(sessions)
    row = reserve(budget, store, request_id=f"intelligence:{run_id}")
    budget.finish(row.id, status="unknown")
    configured(sessions, approved=False)
    with pytest.raises(APISettingsError):
        reserve(budget, store, request_id="unapproved:1")
    configured(sessions, monthly_limit_usd="1")
    with sessions.begin() as session:
        session.get(APIRequestReservation, row.id).estimated_usd = "2"
    before = journal(sessions)
    with pytest.raises(APISettingsError, match="월별"):
        reserve(budget, store, request_id="over:limit")
    assert journal(sessions) == before
    assert "sk-" not in json.dumps(before, default=str)
