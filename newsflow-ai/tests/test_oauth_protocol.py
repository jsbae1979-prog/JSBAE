"""Synthetic loopback HTTP protocol tests, never evidence of real OAuth success."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from oauth_protocol_fixtures import installed_document
from oauth_protocol_server import FakeResponse, synthetic_response

from newsflow.oauth.contracts import FIXED_REDIRECT, YOUTUBE_UPLOAD_SCOPE, OAuthBlocked, OAuthError
from newsflow.oauth.production import (
    DesktopClientConfig,
    GoogleHTTPSOAuthTransport,
    GoogleOAuthProtocol,
    ProtocolError,
    SyntheticLoopbackTransport,
)
from newsflow.oauth.session import OAuthSessionStore, pkce_s256


def callback(launch, code="nf-synthetic-code-initial"):
    return [("state", launch.request.state.get_secret_value()), ("code", code)]


def complete(protocol, launch=None, account="youtube:1", code="nf-synthetic-code-initial", **kwargs):
    launch = launch or protocol.begin(account)
    return protocol.complete(
        launch.request.session_id, account, FIXED_REDIRECT, callback(launch, code), **kwargs,
    )


@pytest.mark.parametrize(
    "auth_uri",
    ["https://accounts.google.com/o/oauth2/auth", "https://accounts.google.com/o/oauth2/v2/auth"],
)
def test_desktop_client_accepts_official_installed_app_export_and_pins_callback(auth_uri):
    config = DesktopClientConfig.from_installed_json(installed_document(auth_uri=auth_uri))
    assert config.redirect_uri == FIXED_REDIRECT
    assert "nf-synthetic-client-secret" not in repr(config)


@pytest.mark.parametrize(
    "document",
    [
        {"web": installed_document()["installed"]},
        installed_document(client_id=""),
        installed_document(client_id="example.invalid"),
        installed_document(client_secret=""),
        installed_document(auth_uri="http://accounts.google.com/o/oauth2/v2/auth"),
        installed_document(auth_uri="https://attacker.invalid/oauth"),
        installed_document(token_uri="https://attacker.invalid/token"),
        installed_document(redirect_uris=["https://attacker.invalid/callback"]),
        installed_document(redirect_uris=["http://127.0.0.1:8766/oauth/callback"]),
        installed_document(redirect_uris=["http://localhost.evil.invalid"]),
    ],
    ids=["web", "no-client", "bad-client", "no-secret", "http-auth", "foreign-auth",
         "foreign-token", "remote-redirect", "other-port", "lookalike-loopback"],
)
def test_desktop_client_rejects_untrusted_or_non_desktop_config(document):
    with pytest.raises((ProtocolError, OAuthError)):
        DesktopClientConfig.from_installed_json(document)


@pytest.mark.parametrize(
    "redirect", ["http://localhost:8765/oauth/callback", FIXED_REDIRECT + "?unexpected=1", FIXED_REDIRECT + "#fragment"],
    ids=["hostname-alias", "query", "fragment"],
)
def test_effective_callback_cannot_be_changed_by_client_config(redirect):
    with pytest.raises((ProtocolError, OAuthError)):
        DesktopClientConfig.from_installed_json(installed_document(), redirect_uri=redirect)


def test_authorization_request_has_s256_state_minimal_scope_and_offline_grant(protocol, server):
    launch = protocol.begin("youtube:1")
    url = launch.authorization_url.get_secret_value()
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}" == server.base_url
    assert parsed.path == "/authorize"
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["nf-synthetic-desktop.apps.googleusercontent.com"]
    assert query["redirect_uri"] == [FIXED_REDIRECT]
    assert query["scope"] == [YOUTUBE_UPLOAD_SCOPE]
    assert query["state"] == [launch.request.state.get_secret_value()]
    assert query["code_challenge"] == [launch.request.code_challenge]
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert "client_secret" not in query
    assert launch.request.state.get_secret_value() not in repr(launch)
    assert server.requests == []


def test_code_exchange_posts_pkce_bound_form_once_and_never_sends_state(protocol, server):
    launch = protocol.begin("youtube:1")
    bundle = complete(protocol, launch)
    assert len(server.requests) == 1
    request = server.requests[0]
    assert request.method == "POST" and request.path == "/token"
    assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert request.form["grant_type"] == ["authorization_code"]
    assert request.form["code"] == ["nf-synthetic-code-initial"]
    assert request.form["client_id"] == ["nf-synthetic-desktop.apps.googleusercontent.com"]
    assert request.form["client_secret"] == ["nf-synthetic-client-secret"]
    assert request.form["redirect_uri"] == [FIXED_REDIRECT]
    assert pkce_s256(request.form["code_verifier"][0]) == launch.request.code_challenge
    assert "state" not in request.form and "authorization" not in request.headers
    assert bundle.scopes == (YOUTUBE_UPLOAD_SCOPE,)
    assert bundle.expires_at.tzinfo is not None
    assert bundle.access_token.get_secret_value() == "nf-synthetic-access-initial"
    assert bundle.refresh_token.get_secret_value() == "nf-synthetic-refresh-initial"
    assert bundle.access_token.get_secret_value() not in repr(bundle)
    with pytest.raises(OAuthError) as replay:
        complete(protocol, launch)
    assert replay.value.code == "reused" and len(server.requests) == 1


@pytest.mark.parametrize(
    "case,expected",
    [("state", "state_mismatch"), ("duplicate", "callback_invalid"),
     ("cancel", "cancelled"), ("account", "account_mismatch"), ("redirect", "redirect_mismatch")],
)
def test_invalid_callback_consumes_request_before_any_http_exchange(protocol, server, case, expected):
    launch = protocol.begin("youtube:1")
    params = callback(launch)
    account, uri = "youtube:1", FIXED_REDIRECT
    if case == "state":
        params[0] = ("state", "X" * 43)
    elif case == "duplicate":
        params.append(("code", "nf-synthetic-code-duplicate"))
    elif case == "cancel":
        params = [params[0], ("error", "access_denied")]
    elif case == "account":
        account = "youtube:2"
    else:
        uri = "http://127.0.0.1:8766/oauth/callback"
    with pytest.raises(OAuthError) as error:
        protocol.complete(launch.request.session_id, account, uri, params)
    assert error.value.code == expected and server.requests == []
    with pytest.raises(OAuthError) as replay:
        complete(protocol, launch)
    assert replay.value.code == "reused" and server.requests == []


def test_expired_callback_never_reaches_transport(config, server):
    now = datetime(2026, 10, 14, tzinfo=UTC)
    protocol = GoogleOAuthProtocol(
        config, SyntheticLoopbackTransport(server.base_url), synthetic=True, sessions=OAuthSessionStore(1),
    )
    launch = protocol.begin("youtube:1", now=now)
    with pytest.raises(OAuthError) as error:
        complete(protocol, launch, now=now + timedelta(seconds=2))
    assert error.value.code == "expired" and server.requests == []


def test_new_request_cancels_previous_pending_request_for_same_account(protocol, server):
    previous = protocol.begin("youtube:1")
    replacement = protocol.begin("youtube:1")
    with pytest.raises(OAuthError) as error:
        complete(protocol, previous)
    assert error.value.code == "reused" and server.requests == []
    complete(protocol, replacement)
    assert len(server.requests) == 1


def test_cancellation_invalidates_pending_request_without_revocation_network(protocol, server):
    launch = protocol.begin("youtube:1")
    protocol.cancel("youtube:1")
    with pytest.raises(OAuthError) as error:
        complete(protocol, launch)
    assert error.value.code == "reused" and server.requests == []


def test_connection_retry_budget_is_account_bound_and_bounded(protocol, server):
    for _ in range(3):
        protocol.begin("youtube:1")
    with pytest.raises(ProtocolError) as error:
        protocol.begin("youtube:1")
    assert error.value.code == "rate_limited"
    assert protocol.begin("youtube:2").request.session_id
    assert server.requests == []


@pytest.mark.parametrize(
    "changes",
    [
        {"access_token": "not-synthetic-service-token"},
        {"access_token": ""},
        {"access_token": ["nf-synthetic-access-array"]},
        {"refresh_token": "not-synthetic-refresh-token"},
        {"token_type": "Basic"},
        {"expires_in": 0},
        {"expires_in": -1},
        {"expires_in": True},
        {"expires_in": "3600"},
        {"expires_in": 3.5},
        {"expires_in": 86401},
    ],
    ids=["foreign-access", "empty-access", "array-access", "foreign-refresh", "token-type",
         "zero-expiry", "negative-expiry", "bool-expiry", "string-expiry", "float-expiry", "long-expiry"],
)
def test_invalid_token_response_is_not_returned_or_retried(protocol, server, changes):
    launch = protocol.begin("youtube:1")
    server.queue(FakeResponse(payload=synthetic_response(**changes)))
    with pytest.raises(ProtocolError) as error:
        complete(protocol, launch)
    assert error.value.code == "response_invalid"
    assert error.value.outcome_unknown and len(server.requests) == 1
    with pytest.raises(OAuthError) as replay:
        complete(protocol, launch)
    assert replay.value.code == "reused" and len(server.requests) == 1


@pytest.mark.parametrize(
    "scope",
    ["", "openid", YOUTUBE_UPLOAD_SCOPE + " openid", [YOUTUBE_UPLOAD_SCOPE]],
    ids=["empty", "wrong", "extra", "non-string"],
)
def test_unexpected_scope_never_becomes_a_validated_grant(protocol, server, scope):
    server.queue(FakeResponse(payload=synthetic_response(scope=scope)))
    with pytest.raises(ProtocolError) as error:
        complete(protocol)
    assert error.value.code in {"scope_mismatch", "response_invalid"}
    assert len(server.requests) == 1


@pytest.mark.parametrize("missing", ["access_token", "token_type", "expires_in", "scope"])
def test_required_code_exchange_response_fields_are_validated(protocol, server, missing):
    payload = synthetic_response()
    del payload[missing]
    server.queue(FakeResponse(payload=payload))
    with pytest.raises(ProtocolError) as error:
        complete(protocol)
    assert error.value.code in {"response_invalid", "scope_mismatch"}
    assert len(server.requests) == 1


def test_access_only_grant_is_explicit_and_cannot_be_refreshed(protocol, server):
    payload = synthetic_response()
    del payload["refresh_token"]
    server.queue(FakeResponse(payload=payload))
    bundle = complete(protocol)
    assert bundle.refresh_token is None
    with pytest.raises(OAuthError):
        protocol.refresh("youtube:1", bundle)
    assert len(server.requests) == 1


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", b'{"access_token": "nf-synthetic-access-first", "access_token": "nf-synthetic-access-second"}'],
    ids=["malformed-json", "array-json", "duplicate-key"],
)
def test_non_object_or_ambiguous_token_response_is_unknown_and_not_retried(protocol, server, body):
    server.queue(FakeResponse(body=body))
    with pytest.raises(ProtocolError) as error:
        complete(protocol)
    assert error.value.code == "response_invalid" and error.value.outcome_unknown
    assert len(server.requests) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_token_redirects_are_never_followed(protocol, server, status):
    server.queue(FakeResponse(status=status, headers={"Location": "https://accounts.google.com/forbidden"}))
    with pytest.raises(ProtocolError):
        complete(protocol)
    assert len(server.requests) == 1


@pytest.mark.parametrize(
    "status,error_code,unknown",
    [(400, "provider_error", False), (401, "provider_error", False),
     (429, "rate_limited", False), (500, "outcome_unknown", True), (503, "outcome_unknown", True)],
)
def test_http_failure_classification_and_sensitive_error_redaction(protocol, server, status, error_code, unknown):
    server.queue(FakeResponse(status=status, payload={"error": "invalid_grant", "error_description": "UNTRUSTED-SECRET"}))
    with pytest.raises(ProtocolError) as error:
        complete(protocol)
    assert error.value.code == error_code and error.value.outcome_unknown is unknown
    assert "UNTRUSTED-SECRET" not in str(error.value) and len(server.requests) == 1


def test_network_timeout_is_unknown_and_authorization_code_is_not_reused(config, server):
    protocol = GoogleOAuthProtocol(
        config, SyntheticLoopbackTransport(server.base_url, timeout_seconds=0.05), synthetic=True,
    )
    launch = protocol.begin("youtube:1")
    server.queue(FakeResponse(payload=synthetic_response(), delay=0.2))
    with pytest.raises(ProtocolError) as error:
        complete(protocol, launch)
    assert error.value.code == "outcome_unknown" and error.value.outcome_unknown
    with pytest.raises(OAuthError) as replay:
        complete(protocol, launch)
    assert replay.value.code == "reused" and len(server.requests) == 1


def test_refresh_uses_form_and_preserves_previous_refresh_when_response_omits_it(protocol, server):
    initial = complete(protocol)
    response = synthetic_response(access_token="nf-synthetic-access-refreshed")
    del response["refresh_token"]
    del response["scope"]
    server.queue(FakeResponse(payload=response))
    refreshed = protocol.refresh("youtube:1", initial)
    assert refreshed.refresh_token == initial.refresh_token and refreshed.scopes == initial.scopes
    form = server.requests[-1].form
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == [initial.refresh_token.get_secret_value()]
    assert "code" not in form and "state" not in form and "code_verifier" not in form
    assert "authorization" not in server.requests[-1].headers


def test_refresh_rotation_invalidates_old_bundle_and_is_bound_to_account(protocol, server):
    initial = complete(protocol)
    response = synthetic_response(
        access_token="nf-synthetic-access-rotated", refresh_token="nf-synthetic-refresh-rotated",
    )
    server.queue(FakeResponse(payload=response))
    refreshed = protocol.refresh("youtube:1", initial)
    assert refreshed.refresh_token != initial.refresh_token
    with pytest.raises(OAuthError):
        protocol.refresh("youtube:1", initial)
    with pytest.raises(OAuthError) as mismatch:
        protocol.refresh("youtube:2", refreshed)
    assert mismatch.value.code == "account_mismatch" and len(server.requests) == 2


def test_refresh_timeout_is_unknown_without_automatic_retry(config, server):
    protocol = GoogleOAuthProtocol(
        config, SyntheticLoopbackTransport(server.base_url, timeout_seconds=0.05), synthetic=True,
    )
    initial = complete(protocol)
    server.queue(FakeResponse(payload=synthetic_response(), delay=0.2))
    with pytest.raises(ProtocolError) as error:
        protocol.refresh("youtube:1", initial)
    assert error.value.code == "outcome_unknown" and error.value.outcome_unknown
    with pytest.raises(OAuthError):
        protocol.refresh("youtube:1", initial)
    assert len(server.requests) == 2


def test_revocation_uses_owned_refresh_and_never_sends_external_upload(protocol, server):
    bundle = complete(protocol)
    with pytest.raises(OAuthError) as mismatch:
        protocol.revoke("youtube:2", bundle)
    assert mismatch.value.code == "account_mismatch" and len(server.requests) == 1
    protocol.revoke("youtube:1", bundle)
    assert server.requests[-1].path == "/revoke"
    assert server.requests[-1].form == {"token": [bundle.refresh_token.get_secret_value()]}
    assert [r.path for r in server.requests] == ["/token", "/revoke"]


def test_revocation_failure_is_unknown_not_false_success(protocol, server):
    bundle = complete(protocol)
    server.queue(FakeResponse(status=503, payload={"error": "server_error"}))
    with pytest.raises(ProtocolError) as error:
        protocol.revoke("youtube:1", bundle)
    assert error.value.code == "outcome_unknown" and error.value.outcome_unknown
    assert len(server.requests) == 2


def test_synthetic_account_identity_is_never_inferred_from_upload_permission(protocol):
    bundle = complete(protocol)
    assert protocol.identity_status("youtube:1", bundle) == "UNVERIFIED"
    with pytest.raises(ProtocolError) as error:
        protocol.bind_synthetic_identity("youtube:1", bundle, "nf-synthetic-identity-expected", "nf-synthetic-identity-wrong")
    assert error.value.code == "identity_mismatch"
    assert protocol.identity_status("youtube:1", bundle) == "UNVERIFIED"
    protocol.bind_synthetic_identity("youtube:1", bundle, "nf-synthetic-identity-expected", "nf-synthetic-identity-expected")
    assert protocol.identity_status("youtube:1", bundle) == "SYNTHETIC_VERIFIED"
    with pytest.raises(OAuthError):
        protocol.identity_status("youtube:2", bundle)


def test_different_accounts_keep_distinct_grants_and_never_cross_refresh(protocol, server):
    first = complete(protocol, account="youtube:1")
    server.queue(FakeResponse(payload=synthetic_response(
        access_token="nf-synthetic-access-second", refresh_token="nf-synthetic-refresh-second",
    )))
    second = complete(protocol, account="youtube:2", code="nf-synthetic-code-second")
    assert hashlib.sha256(first.access_token.get_secret_value().encode()).digest() != hashlib.sha256(
        second.access_token.get_secret_value().encode(),
    ).digest()
    with pytest.raises(OAuthError) as error:
        protocol.refresh("youtube:1", second)
    assert error.value.code == "account_mismatch" and len(server.requests) == 2


@pytest.mark.parametrize(
    "url",
    ["https://oauth2.googleapis.com", "http://localhost:8766", "http://127.0.0.2:8766",
     "http://127.0.0.1:8765", "http://user:password@127.0.0.1:8766",
     "http://127.0.0.1:8766/token", "http://127.0.0.1:8766?query=1", "http://127.0.0.1:8766#fragment"],
    ids=["official-server", "hostname", "other-loopback", "application-port", "credentials", "path", "query", "fragment"],
)
def test_synthetic_transport_cannot_target_external_or_ambiguous_endpoints(url):
    with pytest.raises(ProtocolError) as error:
        SyntheticLoopbackTransport(url)
    assert error.value.code == "transport_invalid"


@pytest.mark.parametrize("operation", ["begin", "browser", "complete", "refresh", "revoke"])
def test_default_production_activation_is_hard_blocked_before_browser_or_transport(
    config, server, monkeypatch, operation,
):
    browser_calls = []
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: browser_calls.append(args))
    monkeypatch.setenv("NEWSFLOW_OAUTH_ENABLED", "true")
    monkeypatch.setenv("NEWSFLOW_OAUTH_USER_APPROVED", "true")
    monkeypatch.setenv("NEWSFLOW_PRODUCTION_ACTIVATION", "true")
    synthetic = GoogleOAuthProtocol(config, SyntheticLoopbackTransport(server.base_url), synthetic=True)
    bundle = complete(synthetic)
    baseline = len(server.requests)
    blocked = GoogleOAuthProtocol(config, GoogleHTTPSOAuthTransport())
    with pytest.raises(OAuthBlocked):
        if operation in {"begin", "browser"}:
            blocked.begin("youtube:1", open_browser=operation == "browser")
        elif operation == "complete":
            blocked.complete("a" * 32, "youtube:1", FIXED_REDIRECT, [])
        elif operation == "refresh":
            blocked.refresh("youtube:1", bundle)
        else:
            blocked.revoke("youtube:1", bundle)
    assert browser_calls == [] and len(server.requests) == baseline


def test_fake_protocol_results_do_not_change_real_safety_counters(protocol, server):
    from newsflow.oauth.providers import oauth_safety_status

    complete(protocol)
    status = oauth_safety_status()
    assert len(server.requests) == 1
    assert all(value == 0 for key, value in status.items() if key.startswith("real_"))
    assert status["mode"] == "OFFLINE/BLOCKED"
