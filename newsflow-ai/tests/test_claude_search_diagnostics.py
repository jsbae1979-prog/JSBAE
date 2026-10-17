"""Synthetic Claude failures retain safe diagnostics without changing cost policy."""

import json
from decimal import Decimal

import pytest
from test_api_search_check import (
    KEY,
    MODELS,
    authenticate,
    response,
    rows,
    send_search,
    settings_values,
)

from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.intelligence.api_search_check import MESSAGES, read_search_check
from newsflow.intelligence.api_settings import read_api_settings, save_api_settings
from newsflow.intelligence.credentials import AnthropicKeyStore, FakeCipher

RAW_MARKER = "private-provider-content-do-not-persist"


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
    engine = make_engine(tmp_path / "diagnostics.sqlite3")
    migrate(engine)
    sessions = session_factory(engine)
    store = AnthropicKeyStore(tmp_path / "secrets", FakeCipher())
    store.save(KEY)
    save_api_settings(
        sessions, "claude_api", model=MODELS["claude_api"], approved=True,
        search_enabled=True, search_approved=True, request_limit_usd="3.10",
        monthly_limit_usd="100", input_price_per_1m="3", output_price_per_1m="15",
        search_price_per_1k="10", billing_confirmed=True, account_remaining_usd="100",
    )
    value = {"sessions": sessions, "engine": engine, "store": store, "provider": "claude_api"}
    authenticate(value)
    yield value
    engine.dispose()


def broken_response(reason):
    document = response("claude_api")
    tool_result = document["content"][1]
    if reason == "search_tool_error":
        tool_result["content"] = {"type": "web_search_tool_result_error", "error_code": "unavailable"}
    elif reason == "tool_pairing":
        tool_result["tool_use_id"] = "unpaired-tool"
    elif reason == "source_evidence":
        tool_result["content"] = []
    elif reason == "result_json":
        document["content"][-1]["text"] = RAW_MARKER
    elif reason == "article_schema":
        document["content"][-1]["text"] = '{"articles": []}'
    elif reason == "source_binding":
        payload = json.loads(document["content"][-1]["text"])
        payload["articles"][0]["url"] = "https://www.bbc.com/korean/articles/not-observed"
        document["content"][-1]["text"] = json.dumps(payload)
    elif reason == "article_count":
        payload = json.loads(document["content"][-1]["text"])
        payload["articles"].append(dict(payload["articles"][0]))
        document["content"][-1]["text"] = json.dumps(payload)
    else:
        raise AssertionError(reason)
    return document


@pytest.mark.parametrize("reason", [
    "search_tool_error", "tool_pairing", "source_evidence", "result_json",
    "article_schema", "source_binding", "article_count",
])
def test_same_recorded_envelope_can_have_distinct_safe_failures(state, reason):
    document = broken_response(reason)
    # These all match the retained live response shape; shape alone cannot prove a cause.
    assert document["stop_reason"] == "end_turn"
    assert [block["type"] for block in document["content"]] == [
        "server_tool_use", "web_search_tool_result", "text",
    ]
    before = settings_values(state["sessions"])
    encrypted = state["store"].path.read_bytes()
    calls = []

    def send(*args):
        calls.append(True)
        return json.dumps(document).encode()

    result = send_search(state, send)
    assert not result.ok and result.code == "ai_bad_response"
    assert result.message != MESSAGES["ai_bad_response"]
    summary = read_search_check(state["sessions"], "claude_api")
    assert summary["failure_reason"] == reason
    assert summary["message"] == result.message
    assert "sources" not in summary and "tool_ids" not in summary
    assert not read_api_settings(state["sessions"], "claude_api").search_verified_at
    ledger = rows(state["sessions"])
    assert len(ledger) == 1 and ledger[0].status == "failed"
    assert Decimal(ledger[0].reserved_usd) == Decimal("3.055")
    assert ledger[0].usage == {"prompt_tokens": 100, "completion_tokens": 50, "search_calls": 1}
    assert Decimal(ledger[0].estimated_usd) > 0
    assert send_search(state, send).code == "blocked" and len(calls) == 1
    after = settings_values(state["sessions"])
    assert all(after[name] == value for name, value in before.items())
    assert state["store"].path.read_bytes() == encrypted
    persisted = json.dumps(after)
    assert all(marker not in persisted for marker in (KEY, RAW_MARKER, "DO_NOT_PERSIST_THIS"))


@pytest.mark.parametrize("error_code", [RAW_MARKER, {"message": RAW_MARKER}])
def test_arbitrary_tool_error_details_are_never_persisted(state, error_code):
    document = broken_response("search_tool_error")
    document["content"][1]["content"]["error_code"] = error_code
    document["content"][1]["content"]["message"] = RAW_MARKER
    result = send_search(state, lambda *args: json.dumps(document).encode())
    summary = read_search_check(state["sessions"], "claude_api")
    assert result.code == "ai_bad_response" and summary["failure_reason"] == "search_tool_error"
    assert summary["tool_error_code"] == "other"
    assert RAW_MARKER not in result.message
    assert RAW_MARKER not in json.dumps(settings_values(state["sessions"]))
    assert Decimal(rows(state["sessions"])[0].reserved_usd) == Decimal("3.055")


def test_success_keeps_existing_proof_contract_without_failure_diagnostics(state):
    result = send_search(state, lambda *args: json.dumps(response("claude_api")).encode())
    summary = read_search_check(state["sessions"], "claude_api")
    assert result.ok and result.code == "success"
    assert summary["source_review"] == "NOT VERIFIED"
    assert summary["sources"] and summary["tool_ids"]
    assert "failure_reason" not in summary and "tool_error_code" not in summary
    assert rows(state["sessions"])[0].status == "success"
    assert read_api_settings(state["sessions"], "claude_api").search_verified_at


def test_later_failure_does_not_rewrite_existing_request_record(state):
    first = broken_response("result_json")
    assert send_search(state, lambda *args: json.dumps(first).encode()).code == "ai_bad_response"
    previous = rows(state["sessions"])[0]
    snapshot = {column.name: getattr(previous, column.name) for column in previous.__table__.columns}
    authenticate(state)  # Fake metadata only; a distinct authorization generation in this temporary DB.
    second = broken_response("source_evidence")
    assert send_search(state, lambda *args: json.dumps(second).encode()).code == "ai_bad_response"
    ledger = rows(state["sessions"])
    assert len(ledger) == 2
    preserved = next(row for row in ledger if row.id == previous.id)
    assert {column.name: getattr(preserved, column.name) for column in preserved.__table__.columns} == snapshot
    assert all(Decimal(row.reserved_usd) == Decimal("3.055") for row in ledger)
    assert read_search_check(state["sessions"], "claude_api")["failure_reason"] == "source_evidence"
