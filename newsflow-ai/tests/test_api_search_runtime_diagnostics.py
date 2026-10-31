"""Production search keeps bounded diagnostics independently of cost uncertainty."""

import json
from decimal import Decimal

import pytest
from sqlalchemy import select
from test_api_search_check import KEY, MODELS, authenticate, response, rows, send_search, settings_values
from test_claude_search_diagnostics import RAW_MARKER, broken_response

from newsflow.db.models import AIUsage, ContentDraft, IntelligenceRun, NewsArticle
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.api_search import SearchRequest, SearchResponseError
from newsflow.intelligence.api_search_check import read_search_check
from newsflow.intelligence.api_settings import (
    APIBudgetService,
    APISettingsError,
    read_api_settings,
    save_api_settings,
)
from newsflow.intelligence.credentials import AnthropicKeyStore, FakeCipher
from newsflow.intelligence.provider import Options
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import _set

MODEL = MODELS["claude_api"]
OBSERVED_USAGE = {"input_tokens": 11651, "output_tokens": 3060,
                  "server_tool_use": {"web_search_requests": 1}}


@pytest.fixture(autouse=True)
def forbid_external_operations(monkeypatch):
    for name in ("NEWSFLOW_AI_API_KEY", "NEWSFLOW_ANTHROPIC_API_KEY", "NEWSFLOW_CLAUDE_API_KEY",
                 "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    def fail(*args, **kwargs):
        pytest.fail("real HTTP and CLI calls are prohibited")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", fail)
    monkeypatch.setattr("subprocess.Popen", fail)


@pytest.fixture
def state(tmp_path):
    engine = make_engine(tmp_path / "runtime-diagnostics.sqlite3")
    migrate(engine)
    sessions = session_factory(engine)
    store = AnthropicKeyStore(tmp_path / "secrets", FakeCipher())
    store.save(KEY)
    save_api_settings(
        sessions, "claude_api", model=MODEL, approved=True, search_enabled=True, search_approved=True,
        request_limit_usd="3.20", monthly_limit_usd="100", input_price_per_1m="3",
        output_price_per_1m="15", search_price_per_1k="10", billing_confirmed=True,
        account_remaining_usd="100",
    )
    value = {"sessions": sessions, "engine": engine, "store": store, "provider": "claude_api"}
    authenticate(value)  # Synthetic metadata in an isolated DB, no account authentication.
    yield value
    engine.dispose()


def production_service(state, document, monkeypatch):
    with state["sessions"].begin() as session:
        # Fixture proof only; production requests still use the unchanged real budget gates.
        _set(session, "api_claude_api_search_verified_at", state["authentication_at"])
    adapter = AnthropicProvider(state["store"].key)
    calls = []

    def transport(request, timeout, limit):
        body = json.loads(request.data)
        assert request.method == "POST" and timeout == 60
        assert body["model"] == MODEL and body["max_tokens"] == 3000
        assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search",
                                  "max_uses": 1, "allowed_callers": ["direct"]}]
        assert KEY not in request.data.decode()
        calls.append(body)
        return json.dumps(document).encode()

    monkeypatch.setattr(adapter, "_open", transport)
    monkeypatch.setattr(adapter, "analyze", lambda *a: pytest.fail("unexpected analysis"))
    monkeypatch.setattr(adapter, "complete", lambda *a: pytest.fail("unexpected script"))
    budget = APIBudgetService(state["sessions"])
    service = IntelligenceService(
        state["sessions"], api_key_stores={"claude_api": state["store"]},
        api_providers={"claude_api": adapter}, api_budget=budget,
    )
    return service, budget, calls


def search(service, on_run=None):
    return service.search_news(
        "claude_api", SearchRequest(category="it", period="24h", count=1), consent=True,
        options=Options(model=MODEL, max_tokens=3000, timeout=60), on_run=on_run,
    )


def snapshot(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


@pytest.mark.parametrize("reason,stop_reason", [
    ("incomplete_response", "max_tokens"), ("incomplete_response", "pause_turn"),
    ("result_json", "end_turn"), ("source_binding", "end_turn"),
])
def test_production_failure_persists_cause_and_marks_over_bound_usage_unknown(
    state, monkeypatch, reason, stop_reason,
):
    document = (response("claude_api") if reason == "incomplete_response" else broken_response(reason))
    document.update(stop_reason=stop_reason, usage=OBSERVED_USAGE)
    service, budget, calls = production_service(state, document, monkeypatch)
    previous = budget.reserve(
        provider="claude_api", request_id="historical-search", kind="search", model=MODEL,
        max_input_tokens=1000, max_output_tokens=3000, max_search_calls=1, key_store=state["store"],
    )
    budget.finish(previous.id, status="failed",
                  usage={"prompt_tokens": 100, "completion_tokens": 50, "web_search_requests": 1})
    old_reservation = snapshot(rows(state["sessions"])[0])
    with state["sessions"].begin() as session:
        old_run = IntelligenceRun(kind="search", provider="claude_api", status="failed", options={},
                                  evidence={}, result={}, message="과거 응답 오류 · 원인 기록 없음")
        session.add(old_run)
        session.flush()
        old_run_id = old_run.id
    with state["sessions"]() as session:
        old_run_snapshot = snapshot(session.get(IntelligenceRun, old_run_id))
    before, encrypted = settings_values(state["sessions"]), state["store"].path.read_bytes()
    ids = []

    with pytest.raises(IntelligenceError) as error:
        search(service, ids.append)
    assert error.value.code == "ai_bad_response" and not error.value.retryable
    assert len(calls) == 1 and len(ids) == 1
    with state["sessions"]() as session:
        run = session.get(IntelligenceRun, ids[0])
        assert run.status == "failed"
        assert run.result == {"search_failure": {"failure_reason": reason, "stop_reason": stop_reason}}
        assert str(error.value) == run.message
        assert stop_reason in run.message
        assert snapshot(session.get(IntelligenceRun, old_run_id)) == old_run_snapshot
        for model in (NewsArticle, ContentDraft):
            assert list(session.scalars(select(model))) == []
        usage = list(session.scalars(select(AIUsage)))
        assert len(usage) == 1 and usage[0].kind == "search" and usage[0].status == "failed"
        assert usage[0].prompt_tokens == 11651 and usage[0].completion_tokens == 3060
    ledger = rows(state["sessions"])
    assert len(ledger) == 2
    assert snapshot(next(row for row in ledger if row.id == previous.id)) == old_reservation
    current = next(row for row in ledger if row.id != previous.id)
    assert current.status == "unknown" and current.test_only is False
    assert Decimal(current.reserved_usd) == Decimal('3.055000')
    assert Decimal(current.estimated_usd) == Decimal("0.090853")
    assert current.bounds == {'accounting': 'per_execution', 'search_calls': 1,
                              'prompt_tokens': 1000000, 'completion_tokens': 3000, 'request_limit_usd': '3.20'}
    assert current.usage == {"prompt_tokens": 11651, "completion_tokens": 3060, "search_calls": 1}
    # The same failed request can never be replayed after reconstructing the ledger.
    with pytest.raises(APISettingsError, match="이미 기록된 요청"):
        APIBudgetService(state["sessions"]).reserve(
            provider="claude_api", request_id=current.request_id, kind="search", model=MODEL,
            max_input_tokens=1000, max_output_tokens=3000, max_search_calls=1, key_store=state["store"],
        )
    assert len(calls) == 1
    assert len(rows(state["sessions"])) == 2
    assert settings_values(state["sessions"]) == before and state["store"].path.read_bytes() == encrypted
    stored = json.dumps({"settings": before, "result": run.result, "message": run.message})
    assert all(marker not in stored for marker in (KEY, RAW_MARKER, "DO_NOT_PERSIST_THIS"))


def test_first_search_parser_failure_with_complete_usage_is_not_unknown_only_for_token_size(state):
    document = broken_response("result_json")
    document["usage"] = OBSERVED_USAGE
    calls = []

    def transport(*args):
        calls.append(True)
        return json.dumps(document).encode()

    result = send_search(state, transport)
    assert result.code == "ai_bad_response" and not result.ok
    summary = read_search_check(state["sessions"], "claude_api")
    assert summary["failure_reason"] == "result_json" and summary["stop_reason"] == "end_turn"
    assert summary["message"] == result.message
    assert "sources" not in summary and "tool_ids" not in summary
    assert not read_api_settings(state["sessions"], "claude_api").search_verified_at
    reservation = rows(state["sessions"])[0]
    assert reservation.status == "failed" and Decimal(reservation.reserved_usd) == Decimal('3.145000')
    assert Decimal(reservation.estimated_usd) == Decimal("0.090853")
    assert send_search(state, transport).code == "blocked" and len(calls) == 1
    assert all(marker not in json.dumps(settings_values(state["sessions"])) for marker in (KEY, RAW_MARKER))


def test_missing_usage_keeps_parser_diagnostic_unknown_and_blocks_new_production_request(state, monkeypatch):
    document = broken_response("result_json")
    document.pop("usage")
    service, _, calls = production_service(state, document, monkeypatch)
    ids = []
    with pytest.raises(IntelligenceError):
        search(service, ids.append)
    ledger = rows(state["sessions"])
    assert len(calls) == len(ledger) == 1 and ledger[0].status == "unknown"
    assert ledger[0].estimated_usd is None and Decimal(ledger[0].reserved_usd) == Decimal('3.055000')
    with state["sessions"]() as session:
        run = session.get(IntelligenceRun, ids[0])
        assert run.result == {"search_failure": {"failure_reason": "result_json", "stop_reason": "end_turn"}}
    replacement = IntelligenceService(
        state["sessions"], api_key_stores=service.api_key_stores,
        api_providers=service.api_providers, api_budget=APIBudgetService(state["sessions"]),
    )
    with pytest.raises(IntelligenceError) as blocked:
        search(replacement)
    assert blocked.value.code == "ai_budget" and len(calls) == 1
    assert len(rows(state["sessions"])) == 1


@pytest.mark.parametrize("stop_reason,expected", [
    (None, None), ("max_tokens", "max_tokens"), ("pause_turn", "pause_turn"),
    ("stop_sequence", "stop_sequence"), ("tool_use", "tool_use"), ("refusal", "refusal"),
    (RAW_MARKER, "other"), ({"token": RAW_MARKER}, "other"), ([RAW_MARKER], "other"),
])
def test_adapter_persists_only_whitelisted_stop_reason(state, monkeypatch, stop_reason, expected):
    document = response("claude_api")
    document["stop_reason"] = stop_reason
    service, _, calls = production_service(state, document, monkeypatch)
    ids = []
    with pytest.raises(IntelligenceError):
        search(service, ids.append)
    with state["sessions"]() as session:
        run = session.get(IntelligenceRun, ids[0])
        expected_diagnostic = {"failure_reason": "incomplete_response"}
        if expected is not None:
            expected_diagnostic["stop_reason"] = expected
        assert run.result == {"search_failure": expected_diagnostic}
        assert RAW_MARKER not in json.dumps(run.result) + run.message
    assert len(calls) == 1 and rows(state["sessions"])[0].status == "failed"


def test_safe_copy_revalidates_exception_attributes_and_ignores_exception_text():
    failure = SearchResponseError("search_tool_error", tool_error_code="unavailable", stop_reason="end_turn")
    failure.tool_error_code = {"secret": RAW_MARKER}
    failure.stop_reason = RAW_MARKER
    failure.args = (RAW_MARKER,)
    safe = failure.safe_copy()
    assert safe.diagnostics() == {"failure_reason": "search_tool_error", "tool_error_code": "other",
                                  "stop_reason": "other"}
    assert RAW_MARKER not in str(safe) + json.dumps(safe.diagnostics())
    failure.failure_reason = {"secret": RAW_MARKER}
    assert failure.diagnostics() == {"failure_reason": "result_contract", "stop_reason": "other"}


def test_successful_production_search_keeps_source_contract_and_has_no_failure(state, monkeypatch):
    service, _, calls = production_service(state, response("claude_api"), monkeypatch)
    run_id = search(service)
    with state["sessions"]() as session:
        run = session.get(IntelligenceRun, run_id)
        assert run.status == "success" and "search_failure" not in run.result
        assert run.result["web_search_performed"] and not run.result["facts_verified"]
        assert not run.result["full_body_verified"]
        assert len(list(session.scalars(select(NewsArticle)))) == 1
        assert list(session.scalars(select(ContentDraft))) == []
    assert len(calls) == 1 and rows(state["sessions"])[0].status == "success"
