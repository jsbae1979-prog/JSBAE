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
from newsflow.intelligence.api_search import GeneratedSearch
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
    assert Decimal(ledger[0].reserved_usd) == 0
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
    assert Decimal(rows(state["sessions"])[0].reserved_usd) == 0


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
    assert all(Decimal(row.reserved_usd) == 0 for row in ledger)
    assert read_search_check(state["sessions"], "claude_api")["failure_reason"] == "source_evidence"


def test_claude_request_describes_exact_json_contract_without_extra_tools_or_calls(state):
    calls = []

    def send(request, timeout, limit):
        calls.append(request)
        body = json.loads(request.data)
        schema = json.loads(body["system"].split("return {\"articles\":[]} rather than inventing news: ")[1])
        assert schema == GeneratedSearch.model_json_schema()
        assert "one complete JSON object" in body["system"]
        assert "never citation placeholders" in body["system"]
        assert "output_config" not in body and "output_format" not in body
        assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search",
                                  "max_uses": 1, "allowed_callers": ["direct"]}]
        assert body["model"] == MODELS["claude_api"] and body["max_tokens"] == 9000
        assert timeout == 60 and KEY not in request.data.decode()
        return json.dumps(response("claude_api")).encode()

    assert send_search(state, send).ok and len(calls) == 1


@pytest.mark.parametrize("wrapper", ["plain", "json_fence", "unlabelled_fence", "split_with_citations"])
def test_complete_json_presentation_keeps_sources_usage_and_no_replay(state, wrapper):
    document = response("claude_api")
    text = document["content"][-1]["text"]
    if wrapper == "plain":
        text = " \n" + text + "\n "
    elif wrapper == "unlabelled_fence":
        text = "```\n" + text + "\n```"
    else:
        text = "```JSON\r\n" + text + "\r\n```"
    if wrapper == "split_with_citations":
        # Web-search citations are metadata on text blocks, not JSON delimiters.
        split = len(text) // 2
        document["content"][-1:] = [
            {"type": "text", "text": text[:split], "citations": [{
                "type": "web_search_result_location", "url": "https://www.bbc.com/untrusted-citation",
                "title": "Citation must not replace tool source", "cited_text": RAW_MARKER,
            }]},
            {"type": "text", "text": text[split:]},
        ]
        document["content"].insert(0, {"type": "text", "text": "Pre-search commentary " + RAW_MARKER})
    else:
        document["content"][-1]["text"] = text
    before = settings_values(state["sessions"])
    encrypted = state["store"].path.read_bytes()
    calls = []

    def send(*args):
        calls.append(True)
        return json.dumps(document).encode()

    assert send_search(state, send).ok
    summary = read_search_check(state["sessions"], "claude_api")
    assert summary["sources"] == [{"title": "검색 제목", "url": "https://www.bbc.com/korean/articles/source-contract"}]
    assert summary["source_review"] == "NOT VERIFIED"
    ledger = rows(state["sessions"])
    assert len(ledger) == 1 and ledger[0].status == "success"
    assert ledger[0].usage == {"prompt_tokens": 100, "completion_tokens": 50, "search_calls": 1}
    assert Decimal(ledger[0].reserved_usd) == 0
    assert send_search(state, send).code == "blocked" and len(calls) == 1
    after = settings_values(state["sessions"])
    proof_updates = {"api_claude_api_search_verified_at", "api_claude_api_request_succeeded_at"}
    assert all(after[name] == value for name, value in before.items() if name not in proof_updates)
    assert state["store"].path.read_bytes() == encrypted
    assert all(marker not in json.dumps(after) for marker in (KEY, RAW_MARKER, "DO_NOT_PERSIST_THIS"))


@pytest.mark.parametrize("shape", [
    "prose_prefix", "prose_suffix", "fence_with_prose", "two_objects", "two_fences",
    "truncated", "open_fence", "non_object", "malformed_outer", "wrong_fence_language",
])
def test_ambiguous_or_invalid_json_is_not_salvaged_and_keeps_reservation(state, shape):
    document = response("claude_api")
    text = document["content"][-1]["text"]
    transformed = {
        "prose_prefix": RAW_MARKER + "\n" + text,
        "prose_suffix": text + "\n" + RAW_MARKER,
        "fence_with_prose": RAW_MARKER + "\n```json\n" + text + "\n```",
        "two_objects": text + "\n" + text,
        "two_fences": "```json\n" + text + "\n```\n```json\n" + text + "\n```",
        "truncated": "```json\n" + text[:-1] + "\n```",
        "open_fence": "```json\n" + text,
        "non_object": "```json\n[" + text + "]\n```",
        "malformed_outer": '{"outer":' + text,  # Never salvage the nested valid object.
        "wrong_fence_language": "```python\n" + text + "\n```",
    }
    document["content"][-1]["text"] = transformed[shape]
    calls = []

    def send(*args):
        calls.append(True)
        return json.dumps(document).encode()

    result = send_search(state, send)
    assert result.code == "ai_bad_response"
    assert read_search_check(state["sessions"], "claude_api")["failure_reason"] == "result_json"
    assert not read_api_settings(state["sessions"], "claude_api").search_verified_at
    ledger = rows(state["sessions"])
    assert len(ledger) == 1 and ledger[0].status == "failed"
    assert Decimal(ledger[0].reserved_usd) == 0
    assert send_search(state, send).code == "blocked" and len(calls) == 1
    assert all(marker not in json.dumps(settings_values(state["sessions"])) for marker in (KEY, RAW_MARKER))


@pytest.mark.parametrize("change,reason", [
    ("url", "source_binding"), ("related_urls", "source_binding"), ("extra_field", "article_schema"),
])
def test_fenced_json_still_requires_article_schema_and_observed_sources(state, change, reason):
    document = response("claude_api")
    payload = json.loads(document["content"][-1]["text"])
    article = payload["articles"][0]
    if change == "url":
        article["url"] = "https://www.bbc.com/not-observed"
    elif change == "related_urls":
        article["related_urls"] = ["https://www.bbc.com/not-observed"]
    else:
        article["execute_command"] = RAW_MARKER
    document["content"][-1]["text"] = "```json\n" + json.dumps(payload) + "\n```"
    assert send_search(state, lambda *args: json.dumps(document).encode()).code == "ai_bad_response"
    assert read_search_check(state["sessions"], "claude_api")["failure_reason"] == reason
    assert rows(state["sessions"])[0].status == "failed"
    assert Decimal(rows(state["sessions"])[0].reserved_usd) == 0


def test_new_valid_format_does_not_replay_or_rewrite_an_old_failure(state):
    assert send_search(state, lambda *args: json.dumps(broken_response("result_json")).encode()).code == "ai_bad_response"
    previous = rows(state["sessions"])[0]
    snapshot = {column.name: getattr(previous, column.name) for column in previous.__table__.columns}
    document = response("claude_api")
    document["content"][-1]["text"] = "```json\n" + document["content"][-1]["text"] + "\n```"
    calls = []

    def send(*args):
        calls.append(True)
        return json.dumps(document).encode()

    assert send_search(state, send).code == "blocked" and not calls
    authenticate(state)  # Fake metadata in a temporary DB, not a live reauthentication.
    assert send_search(state, send).ok and len(calls) == 1
    ledger = rows(state["sessions"])
    preserved = next(row for row in ledger if row.id == previous.id)
    assert {column.name: getattr(preserved, column.name) for column in preserved.__table__.columns} == snapshot
    assert len(ledger) == 2 and sum(Decimal(row.reserved_usd) for row in ledger) == 0
