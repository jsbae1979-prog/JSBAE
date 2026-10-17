"""OpenAI metadata checks use synthetic keys and a transport fake only."""

import io
import json
import urllib.error

import pytest
from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AppSetting
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.intelligence.api_connection import (
    ENDPOINTS,
    MAX_RESPONSE_BYTES,
    TIMEOUT_SECONDS,
    check_api_connection,
    invalidate_connection_check,
    read_connection_check,
)
from newsflow.intelligence.api_settings import APISettingsError, read_api_settings
from newsflow.intelligence.provider import NoRedirect
from newsflow.intelligence.settings import _set

KEY = "sk-synthetic-openai-metadata-0123456789"
MODEL = "gpt-4.1-mini"
PREFIX = "api_openai_"


class FakeKey:
    value = KEY

    def key(self):
        return self.value


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: pytest.fail("real network prohibited"))


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(tmp_path / "isolated.sqlite3")
    migrate(engine)
    yield session_factory(engine)
    engine.dispose()


def values(sessions):
    with sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def check(sessions, *, key=None, transport=None, consent=True):
    return check_api_connection(sessions, key or FakeKey(), provider="openai", consent=consent, transport=transport)


def model_response(*args):
    return json.dumps({"object": "model", "id": MODEL}).encode()


def test_openai_metadata_get_does_not_grant_search_or_change_other_provider(sessions):
    preserved = {"studio_provider": "claude_code", "studio_model_claude_api": "claude-sonnet-4-6",
                 "api_claude_api_verified_model": "claude-sonnet-4-6",
                 "api_claude_api_authentication_verified_at": "preserved",
                 "ai_approved_at": "preserved", PREFIX + "search_approved_at": "preserved",
                 PREFIX + "request_limit_usd": "1", PREFIX + "monthly_limit_usd": "20",
                 PREFIX + "account_remaining_usd": "10", PREFIX + "billing_confirmed_at": "preserved"}
    with sessions.begin() as session:
        for name, value in preserved.items():
            _set(session, name, value)
    calls = []

    def send(request, timeout, limit):
        calls.append(request)
        assert request.full_url == ENDPOINTS["openai"] + MODEL
        assert request.method == "GET" and request.data is None
        assert request.get_header("Authorization") == "Bearer " + KEY
        assert request.get_header("X-api-key") is None and request.get_header("Anthropic-version") is None
        assert timeout == TIMEOUT_SECONDS == 15 and limit == MAX_RESPONSE_BYTES
        return model_response()

    result = check(sessions, transport=send)
    assert result.ok and len(calls) == 1
    assert read_connection_check(sessions, "openai") == result
    settings = read_api_settings(sessions, "openai")
    assert settings.verified_model == MODEL and settings.authentication_verified_at == result.checked_at
    assert not settings.search_verified_at and not settings.request_succeeded_at
    after = values(sessions)
    assert all(after[name] == value for name, value in preserved.items())
    assert KEY not in json.dumps(after) and KEY not in repr(result)
    with sessions() as session:
        assert not list(session.scalars(select(APIRequestReservation)))


def test_openai_consent_is_required_before_key_read_or_state_change(sessions, monkeypatch):
    key = FakeKey()
    monkeypatch.setattr(key, "key", lambda: pytest.fail("key read without consent"))
    for consent in (False, None, 1, "true"):
        result = check(sessions, key=key, consent=consent)
        assert result.code == "consent_required" and "OpenAI" in result.message
    assert values(sessions) == {}


@pytest.mark.parametrize("status,code", [(401, "auth_error"), (403, "permission"), (404, "model_unavailable"),
                                       (429, "rate_limit"), (302, "unavailable"), (504, "timeout")])
def test_openai_failure_is_classified_without_retry_or_supplier_error_disclosure(sessions, status, code):
    calls = []
    with sessions.begin() as session:
        for name in ("authentication_verified_at", "search_verified_at", "request_succeeded_at", "verified_model"):
            _set(session, PREFIX + name, MODEL if name == "verified_model" else "old")

    def fail(*args):
        calls.append(True)
        raise urllib.error.HTTPError(ENDPOINTS["openai"] + KEY, status, KEY, {}, io.BytesIO(KEY.encode()))

    result = check(sessions, transport=fail)
    assert result.code == code and len(calls) == 1
    assert "Claude" not in result.message and KEY not in repr(result)
    assert not read_api_settings(sessions, "openai").verified_model
    assert not read_api_settings(sessions, "openai").search_verified_at
    assert KEY not in json.dumps(values(sessions))


@pytest.mark.parametrize("document", [{"type": "model", "id": MODEL}, {"object": "model", "id": "other"},
                                     {}, []])
def test_openai_response_requires_matching_object_and_model(sessions, document):
    result = check(sessions, transport=lambda *a: json.dumps(document).encode())
    assert result.code == "invalid_response"
    assert not read_api_settings(sessions, "openai").authentication_verified_at


@pytest.mark.parametrize("change", ["model", "key", "invalidation"])
def test_openai_late_response_cannot_validate_a_changed_configuration(sessions, change):
    key = FakeKey()

    def send(*args):
        if change == "key":
            key.value += "-replacement"
        else:
            with sessions.begin() as session:
                if change == "model":
                    _set(session, "studio_model_openai", "gpt-unknown")
                else:
                    invalidate_connection_check(session, "openai")
        return model_response()

    assert check(sessions, key=key, transport=send).code == "stale"
    assert not read_api_settings(sessions, "openai").authentication_verified_at


def test_openai_inflight_duplicate_does_not_send(sessions):
    nested = []

    def send(*args):
        nested.append(check(sessions))
        return model_response()

    assert check(sessions, transport=send).ok
    assert len(nested) == 1 and nested[0].code == "busy"


def test_unknown_provider_cannot_choose_an_endpoint(sessions):
    with pytest.raises(APISettingsError):
        check_api_connection(sessions, FakeKey(), provider="https://other.example", consent=True)
    assert values(sessions) == {}


def test_openai_default_transport_blocks_redirects_and_sends_one_metadata_get(sessions, monkeypatch):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            return io.BytesIO(model_response())

    def build(*handlers):
        assert len(handlers) == 1 and isinstance(handlers[0], NoRedirect)
        return Opener()

    monkeypatch.setattr("urllib.request.build_opener", build)
    assert check(sessions).ok
    assert len(calls) == 1 and calls[0].method == "GET"
