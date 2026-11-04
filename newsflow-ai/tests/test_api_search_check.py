"""First-search verification uses the real ledger with synthetic HTTP responses."""

import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AppSetting, ContentDraft, IntelligenceRun, NewsArticle
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.intelligence.api_connection import check_api_connection
from newsflow.intelligence.api_search_check import check_api_search, read_search_check
from newsflow.intelligence.api_settings import (
    FIRST_SEARCH_OUTPUT_TOKENS,
    APIBudgetService,
    APISettingsError,
    api_readiness,
    first_search_readiness,
    invalidate_api_verification,
    read_api_settings,
    save_api_settings,
)
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, FakeCipher
from newsflow.intelligence.settings import _set

KEY = "sk-synthetic-first-search-test-0123456789"
URL = "https://www.bbc.com/korean/articles/source-contract"
MODELS = {"openai": "gpt-4.1-mini", "claude_api": "claude-sonnet-4-6"}
UPPER = {'openai': Decimal('3.287728'), 'claude_api': Decimal('3.145000')}


@pytest.fixture(autouse=True)
def forbid_external_operations(monkeypatch):
    for name in ("NEWSFLOW_AI_API_KEY", "NEWSFLOW_ANTHROPIC_API_KEY", "NEWSFLOW_CLAUDE_API_KEY",
                 "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    def fail(*args, **kwargs):
        pytest.fail("real HTTP and CLI calls are prohibited")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", fail)
    monkeypatch.setattr("subprocess.Popen", fail)


@pytest.fixture(params=["openai", "claude_api"])
def state(request, tmp_path):
    provider = request.param
    engine = make_engine(tmp_path / "isolated.sqlite3")
    migrate(engine)
    sessions = session_factory(engine)
    store = (AIKeyStore if provider == "openai" else AnthropicKeyStore)(tmp_path / "secrets", FakeCipher())
    store.save(KEY)
    save_api_settings(
        sessions, provider, model=MODELS[provider], approved=True, search_enabled=True, search_approved=True,
        request_limit_usd="10", monthly_limit_usd="100", input_price_per_1m="3", output_price_per_1m="15",
        search_price_per_1k="10", billing_confirmed=True, account_remaining_usd="100",
    )
    value = {"sessions": sessions, "engine": engine, "store": store, "provider": provider}
    authenticate(value)
    yield value
    engine.dispose()


def authenticate(state):
    provider = state["provider"]
    response = {"id": MODELS[provider], "object" if provider == "openai" else "type": "model"}
    result = check_api_connection(state["sessions"], state["store"], provider=provider, consent=True,
                                  transport=lambda *a: json.dumps(response).encode())
    assert result.ok
    state["authentication_at"] = result.checked_at


def response(provider):
    article = {"title": "합성 제목", "url": URL, "publisher": "BBC", "published_at": None,
               "summary": "실제 뉴스가 아닌 계약 응답입니다.", "key_facts": ["합성 근거"],
               "related_urls": [], "uncertainties": ["사실 검증 없음"]}
    text = json.dumps({"articles": [article]})
    if provider == "openai":
        return {"status": "completed", "output": [
            {"type": "web_search_call", "id": "ws_1", "status": "completed",
             "action": {"type": "search", "sources": [{"url": URL, "title": "검색 제목"}]}},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ], "usage": {"input_tokens": 120, "output_tokens": 30}}
    return {"stop_reason": "end_turn", "content": [
        {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "뉴스"}},
        {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [
            {"type": "web_search_result", "url": URL, "title": "검색 제목",
             "page_age": "2026-10-16", "encrypted_content": "DO_NOT_PERSIST_THIS"},
        ]}, {"type": "text", "text": text},
    ], "usage": {"input_tokens": 100, "output_tokens": 50, "server_tool_use": {"web_search_requests": 1}}}


def send_search(state, transport, *, consent=True):
    return check_api_search(state["sessions"], state["store"], provider=state["provider"],
                            model=MODELS[state["provider"]], authentication_at=state["authentication_at"],
                            consent=consent, max_cost_usd="10", transport=transport)


def settings_values(sessions):
    with sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def rows(sessions):
    with sessions() as session:
        return list(session.scalars(select(APIRequestReservation)))


def test_first_search_validates_evidence_without_import_or_other_setting_changes(state, monkeypatch):
    sessions, store, provider = state["sessions"], state["store"], state["provider"]
    other = "claude_api" if provider == "openai" else "openai"
    with sessions.begin() as session:
        _set(session, f"api_{other}_search_verified_at", "other-provider-preserved")
        _set(session, "studio_provider", "claude_code")
        _set(session, "production_acquisition_policy", "rss")
    before, encrypted = settings_values(sessions), store.path.read_bytes()
    assert not api_readiness(sessions, provider, store)["ready"]
    assert first_search_readiness(sessions, provider, store)["ready"]
    with pytest.raises(APISettingsError, match="웹 검색 미검증"):
        APIBudgetService(sessions).reserve(provider=provider, request_id="production-search", kind="search",
                                           model=MODELS[provider], max_input_tokens=1000, max_output_tokens=1000,
                                           max_search_calls=1, key_store=store)
    observed, calls = [], []
    from newsflow.intelligence.api_search_check import validate_search_result

    def validate(result):
        observed.append(result)
        return validate_search_result(result)

    monkeypatch.setattr("newsflow.intelligence.api_search_check.validate_search_result", validate)

    def send(request, timeout, limit):
        calls.append(request)
        body = json.loads(request.data)
        assert timeout == 60 and request.method == "POST"
        assert body["model"] == MODELS[provider]
        if provider == "openai":
            assert body["max_tool_calls"] == 1 and body["max_output_tokens"] == FIRST_SEARCH_OUTPUT_TOKENS
        else:
            assert body["tools"][0]["max_uses"] == 1 and body["max_tokens"] == FIRST_SEARCH_OUTPUT_TOKENS
        return json.dumps(response(provider)).encode()

    assert send_search(state, send).ok and len(calls) == 1
    assert observed[0].articles[0].published_at is None
    assert not observed[0].articles[0].full_body_verified
    assert api_readiness(sessions, provider, store)["ready"]
    summary = read_search_check(sessions, provider)
    assert summary["source_review"] == "NOT VERIFIED" and summary["sources"][0]["url"] == URL
    assert summary["tool_ids"] and summary["reservation_id"]
    ledger = rows(sessions)
    assert len(ledger) == 1 and ledger[0].status == "success"
    assert ledger[0].test_only is False and Decimal(ledger[0].reserved_usd) == UPPER[provider]
    assert ledger[0].bounds == {'accounting': 'per_execution', 'search_calls': 1,
        'prompt_tokens': 1047576 if provider == 'openai' else 1000000,
        'completion_tokens': FIRST_SEARCH_OUTPUT_TOKENS, 'request_limit_usd': '10'}
    assert Decimal(ledger[0].estimated_usd) > 0
    assert ledger[0].usage["search_calls"] == 1
    after = settings_values(sessions)
    proof_updates = {f"api_{provider}_search_verified_at", f"api_{provider}_request_succeeded_at"}
    assert all(after[name] == value for name, value in before.items() if name not in proof_updates)
    assert store.path.read_bytes() == encrypted
    assert KEY not in json.dumps(after) and "DO_NOT_PERSIST_THIS" not in json.dumps(after)
    with sessions() as session:
        for model in (NewsArticle, ContentDraft, IntelligenceRun):
            assert not list(session.scalars(select(model)))


def test_local_status_and_unchecked_consent_never_decrypt_or_reserve(state, monkeypatch):
    sessions, store, provider = state["sessions"], state["store"], state["provider"]
    before = settings_values(sessions)
    monkeypatch.setattr(store, "key", lambda: pytest.fail("key read without consent"))
    assert first_search_readiness(sessions, provider, store)["ready"]
    assert read_search_check(sessions, provider) == {}
    for consent in (False, None, "true", 1):
        assert send_search(state, lambda *a: pytest.fail("missing consent"), consent=consent).code == "consent_required"
    assert rows(sessions) == [] and settings_values(sessions) == before


def test_same_authentication_cannot_resubmit_after_process_restart(state):
    calls = []

    def send(*args):
        calls.append(True)
        return json.dumps(response(state["provider"])).encode()

    assert send_search(state, send).ok
    state["engine"].dispose()
    state["sessions"] = session_factory(state["engine"])
    assert send_search(state, send).code == "blocked"
    assert not first_search_readiness(state["sessions"], state["provider"], state["store"])["ready"]
    assert len(calls) == 1 and len(rows(state["sessions"])) == 1


def test_unknown_outcome_survives_reauthentication_and_blocks_new_attempt(state):
    calls = []

    def timeout(*args):
        calls.append(True)
        raise TimeoutError(KEY)

    result = send_search(state, timeout)
    assert result.code == "unknown" and KEY not in repr(result)
    ledger = rows(state["sessions"])
    assert ledger[0].status == "unknown" and Decimal(ledger[0].reserved_usd) == UPPER[state['provider']]
    authenticate(state)
    assert send_search(state, timeout).code == "blocked"
    assert len(calls) == 1 and len(rows(state["sessions"])) == 1


@pytest.mark.parametrize("problem", ["empty", "invalid_json", "missing_usage", "malformed_usage", "secret_echo"])
def test_bad_search_or_usage_never_creates_proof_or_releases_reservation(state, problem):
    document = response(state["provider"])
    if problem == "empty":
        if state["provider"] == "openai":
            document["output"][0]["action"]["sources"] = []
        else:
            document["content"][1]["content"] = []
    elif problem == "missing_usage":
        document.pop("usage")
    elif problem == "malformed_usage":
        document["usage"]["output_tokens"] = "unknown"
    elif problem == "secret_echo":
        document["secret"] = KEY
    calls = []

    def send(*args):
        calls.append(True)
        return b"not-json" if problem == "invalid_json" else json.dumps(document).encode()

    result = send_search(state, send)
    assert not result.ok and len(calls) == 1
    assert not read_api_settings(state["sessions"], state["provider"]).search_verified_at
    ledger = rows(state["sessions"])
    assert len(ledger) == 1 and Decimal(ledger[0].reserved_usd) == UPPER[state['provider']]
    if problem in {"missing_usage", "malformed_usage"}:
        assert ledger[0].status == "unknown" and result.code == "unknown"
    assert send_search(state, send).code == "blocked" and len(calls) == 1
    assert KEY not in json.dumps(settings_values(state["sessions"]))


@pytest.mark.parametrize("change", ["model", "key", "authentication"])
def test_late_search_cannot_verify_changed_model_key_or_authentication(state, change):
    provider, sessions = state["provider"], state["sessions"]

    def send(*args):
        if change == "authentication":
            authenticate(state)
        else:
            if change == "key":
                state["store"].save(KEY + "-replacement")
            else:
                with sessions.begin() as session:
                    _set(session, "studio_model_" + provider, "changed-model")
            invalidate_api_verification(sessions, provider)
        return json.dumps(response(provider)).encode()

    assert send_search(state, send).code == "stale"
    assert not read_api_settings(sessions, provider).search_verified_at
    assert read_search_check(sessions, provider) == {}
    assert len(rows(sessions)) == 1 and Decimal(rows(sessions)[0].reserved_usd) == UPPER[provider]


def test_reported_output_above_requested_tokens_blocks_proof_and_preserves_unknown(state):
    document = response(state["provider"])
    document["usage"]["output_tokens"] = FIRST_SEARCH_OUTPUT_TOKENS + 1
    calls = []

    def send(*args):
        calls.append(True)
        return json.dumps(document).encode()

    assert send_search(state, send).code == 'unknown' and len(calls) == 1
    ledger = rows(state["sessions"])
    assert len(ledger) == 1 and ledger[0].status == "unknown"
    assert ledger[0].usage["completion_tokens"] == FIRST_SEARCH_OUTPUT_TOKENS + 1
    assert Decimal(ledger[0].reserved_usd) == UPPER[state['provider']] and Decimal(ledger[0].estimated_usd) > 0
    assert not read_api_settings(state["sessions"], state["provider"]).search_verified_at
    assert send_search(state, send).code == "blocked" and len(calls) == 1
