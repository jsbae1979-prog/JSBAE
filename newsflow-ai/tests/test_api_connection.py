"""Metadata-only Claude verification. Every HTTP operation uses a local fake."""

import io
import json
import urllib.error

import pytest
from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AppSetting, utcnow
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.intelligence.api_connection import (
    CHECK_MESSAGES,
    ENDPOINT,
    MAX_RESPONSE_BYTES,
    TIMEOUT_SECONDS,
    check_claude_connection,
    invalidate_connection_check,
    read_connection_check,
)
from newsflow.intelligence.api_settings import api_readiness, read_api_settings
from newsflow.intelligence.credentials import AnthropicKeyStore, CredentialError, FakeCipher
from newsflow.intelligence.provider import NoRedirect, ProviderResponseError
from newsflow.intelligence.settings import _set

KEY = "sk-synthetic-connection-test-0123456789"
MODEL = "claude-sonnet-4-6"
PREFIX = "api_claude_api_"
PROOF_KEYS = ("authentication_verified_at", "search_verified_at", "request_succeeded_at", "verified_model")


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.delenv("NEWSFLOW_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: pytest.fail("real network prohibited"))


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(tmp_path / "isolated.sqlite3")
    migrate(engine)
    yield session_factory(engine)
    engine.dispose()


@pytest.fixture
def store(tmp_path):
    result = AnthropicKeyStore(tmp_path / "secrets", FakeCipher())
    result.save(KEY)
    return result


def values(sessions):
    with sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def set_values(sessions, settings):
    with sessions.begin() as session:
        for name, value in settings.items():
            _set(session, name, value)


def seed_proof(sessions):
    stamp = utcnow().isoformat()
    set_values(sessions, {PREFIX + name: MODEL if name == "verified_model" else stamp for name in PROOF_KEYS})


def transport(payload=None, *, error=None, callback=None):
    calls = []

    def send(request, timeout, limit):
        calls.append((request, timeout, limit))
        if callback:
            callback()
        if error is not None:
            raise error
        return json.dumps(payload if payload is not None else {"type": "model", "id": MODEL}).encode()

    return send, calls


def test_model_metadata_get_verifies_without_budget_inference_or_search(sessions, store):
    before_key = store.path.read_bytes()
    send, calls = transport()
    result = check_claude_connection(sessions, store, consent=True, transport=send)
    assert result.ok and result.code == "success" and result.checked_at
    assert read_connection_check(sessions) == result
    request, timeout, limit = calls[0]
    assert len(calls) == 1
    assert request.full_url == ENDPOINT + MODEL and request.method == "GET" and request.data is None
    assert request.get_header("X-api-key") == KEY
    assert request.get_header("Anthropic-version") == "2023-06-01"
    assert timeout == TIMEOUT_SECONDS == 15 and limit == MAX_RESPONSE_BYTES
    settings = read_api_settings(sessions, "claude_api")
    assert settings.authentication_verified_at == result.checked_at and settings.verified_model == MODEL
    assert not settings.search_verified_at and not settings.request_succeeded_at
    assert not settings.approved and not settings.search_approved and settings.monthly_limit_usd == 0
    status = api_readiness(sessions, "claude_api", store)
    assert status["authentication_verified"] and not status["ready"] and not status["request_succeeded"]
    with sessions() as session:
        assert not list(session.scalars(select(APIRequestReservation)))
    assert store.path.read_bytes() == before_key
    assert KEY not in repr(result) and KEY not in json.dumps(values(sessions))


def test_consent_is_explicit_and_without_it_no_key_database_or_network_is_touched(sessions, store, monkeypatch):
    monkeypatch.setattr(store, "key", lambda: pytest.fail("no key read without consent"))
    for consent in (False, None, "true", 1):
        result = check_claude_connection(sessions, store, consent=consent)
        assert result.code == "consent_required" and not result.ok
    assert values(sessions) == {}


def test_success_preserves_existing_search_proof_and_independent_settings(sessions, store):
    seed_proof(sessions)
    set_values(sessions, {PREFIX + "approved_at": "approval-kept", PREFIX + "monthly_limit_usd": "75",
                          PREFIX + "billing_confirmed_at": "billing-kept", PREFIX + "account_remaining_usd": "25",
                          "studio_provider": "claude_code", "api_openai_verified_model": "gpt-4.1-mini"})
    before = values(sessions)
    send, _ = transport()
    assert check_claude_connection(sessions, store, consent=True, transport=send).ok
    after = values(sessions)
    for name, value in before.items():
        if name != PREFIX + "authentication_verified_at":
            assert after[name] == value


@pytest.mark.parametrize("status,code", [(401, "auth_error"), (403, "permission"),
                                       (404, "model_unavailable"), (429, "rate_limit"),
                                       (408, "timeout"), (504, "timeout"), (500, "unavailable"),
                                       (302, "unavailable")])
def test_http_error_single_attempt_sanitized_and_old_proof_cleared(sessions, store, status, code):
    seed_proof(sessions)
    set_values(sessions, {PREFIX + "monthly_limit_usd": "75", PREFIX + "approved_at": "keep-approval",
                          PREFIX + "billing_confirmed_at": "keep-billing", PREFIX + "account_remaining_usd": "25"})
    error = urllib.error.HTTPError(ENDPOINT + KEY, status, KEY, {"Retry-After": "1"}, io.BytesIO(KEY.encode()))
    send, calls = transport(error=error)
    result = check_claude_connection(sessions, store, consent=True, transport=send)
    assert result.code == code and result.message == CHECK_MESSAGES[code] and not result.ok
    assert len(calls) == 1 and KEY not in repr(result)
    saved = values(sessions)
    assert all(saved[PREFIX + key] == "" for key in PROOF_KEYS)
    assert saved[PREFIX + "monthly_limit_usd"] == "75" and saved[PREFIX + "approved_at"] == "keep-approval"
    assert saved[PREFIX + "billing_confirmed_at"] == "keep-billing"
    assert saved[PREFIX + "account_remaining_usd"] == "25" and KEY not in json.dumps(saved)


@pytest.mark.parametrize("error,code", [(TimeoutError(KEY), "timeout"),
                                       (urllib.error.URLError(TimeoutError(KEY)), "timeout"),
                                       (urllib.error.URLError(KEY), "network"), (OSError(KEY), "network"),
                                       (RuntimeError(KEY), "unavailable"),
                                       (ProviderResponseError(KEY), "invalid_response")])
def test_transport_errors_never_retry_or_expose_error_text(sessions, store, error, code):
    send, calls = transport(error=error)
    result = check_claude_connection(sessions, store, consent=True, transport=send)
    assert result.code == code and len(calls) == 1 and KEY not in repr(result)


@pytest.mark.parametrize("payload", [{}, [], {"type": "message", "id": MODEL},
                                    {"type": "model", "id": "claude-other-alias-target"},
                                    {"type": "model", "id": KEY}])
def test_rejects_invalid_json_shape_or_a_different_resolved_model(sessions, store, payload):
    send, _ = transport(payload)
    result = check_claude_connection(sessions, store, consent=True, transport=send)
    assert result.code == "invalid_response" and not read_api_settings(sessions, "claude_api").verified_model
    assert KEY not in json.dumps(values(sessions))


@pytest.mark.parametrize("raw", [b"not-json", b"\xff", b"x" * (MAX_RESPONSE_BYTES + 1)],
                         ids=["not-json", "invalid-encoding", "oversized"])
def test_invalid_or_oversized_bytes_are_not_saved(sessions, store, raw):
    result = check_claude_connection(sessions, store, consent=True, transport=lambda *args: raw)
    assert result.code == "invalid_response"


@pytest.mark.parametrize("model", ["https://attacker.example/key", "../messages", "claude-unknown"])
def test_unsupported_model_has_no_network_and_is_preserved(sessions, store, model):
    set_values(sessions, {"studio_model_claude_api": model})
    result = check_claude_connection(sessions, store, consent=True)
    assert result.code == "unsupported_model"
    assert values(sessions)["studio_model_claude_api"] == model


def test_missing_or_unreadable_key_has_safe_result_without_network(sessions, store, monkeypatch):
    assert check_claude_connection(sessions, None, consent=True).code == "key_missing"

    def fail():
        raise CredentialError(KEY)

    monkeypatch.setattr(store, "key", fail)
    result = check_claude_connection(sessions, store, consent=True)
    assert result.code == "key_error" and KEY not in repr(result)


@pytest.mark.parametrize("change", ["key", "model", "invalidation"])
def test_late_result_cannot_verify_changed_credentials_or_model(sessions, store, change):
    def modify():
        if change == "key":
            store.save(KEY + "-replacement")
        elif change == "model":
            set_values(sessions, {"studio_model_claude_api": "claude-unknown"})
        else:
            with sessions.begin() as session:
                invalidate_connection_check(session, "claude_api")

    send, calls = transport(callback=modify)
    result = check_claude_connection(sessions, store, consent=True, transport=send)
    assert result.code == "stale" and len(calls) == 1
    assert not read_api_settings(sessions, "claude_api").authentication_verified_at


def test_second_inflight_click_is_blocked_without_transmission(sessions, store):
    nested = []

    def duplicate():
        nested.append(check_claude_connection(sessions, store, consent=True))

    send, calls = transport(callback=duplicate)
    assert check_claude_connection(sessions, store, consent=True, transport=send).ok
    assert len(calls) == 1 and nested[0].code == "busy"


def test_late_failure_does_not_clear_a_newer_verification(sessions, store):
    def newer():
        with sessions.begin() as session:
            invalidate_connection_check(session, "claude_api")
            _set(session, PREFIX + "authentication_verified_at", "newer-proof")
            _set(session, PREFIX + "verified_model", MODEL)

    send, _ = transport(error=TimeoutError(KEY), callback=newer)
    assert check_claude_connection(sessions, store, consent=True, transport=send).code == "stale"
    assert values(sessions)[PREFIX + "authentication_verified_at"] == "newer-proof"


def test_default_transport_reuses_no_redirect_and_does_not_send_messages(sessions, store, monkeypatch):
    requests = []

    class Response(io.BytesIO):
        pass

    class Opener:
        def open(self, request, timeout):
            requests.append((request, timeout))
            return Response(json.dumps({"type": "model", "id": MODEL}).encode())

    def build(*handlers):
        assert len(handlers) == 1 and isinstance(handlers[0], NoRedirect)
        return Opener()

    monkeypatch.setattr("urllib.request.build_opener", build)
    assert check_claude_connection(sessions, store, consent=True).ok
    assert len(requests) == 1 and requests[0][0].get_method() == "GET"


def test_read_check_state_is_local_and_unknown_database_values_are_not_echoed(sessions, monkeypatch):
    set_values(sessions, {PREFIX + "connection_check_code": KEY, PREFIX + "connection_checked_at": KEY})
    result = read_connection_check(sessions)
    assert result.code == "not_checked" and result.checked_at is None and KEY not in repr(result)
