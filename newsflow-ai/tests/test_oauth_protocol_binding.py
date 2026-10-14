"""Independent adversarial grant-binding checks against the synthetic HTTP server."""

from datetime import UTC, datetime, timedelta

import pytest
from oauth_protocol_server import FakeResponse, synthetic_response
from pydantic import SecretStr
from test_oauth_protocol import complete

from newsflow.oauth.contracts import OAuthError
from newsflow.oauth.production import ProtocolError


def two_grants(protocol, server):
    first = complete(protocol, account="youtube:1")
    server.queue(FakeResponse(payload=synthetic_response(
        access_token="nf-synthetic-access-account-two",
        refresh_token="nf-synthetic-refresh-account-two",
    )))
    second = complete(protocol, account="youtube:2", code="nf-synthetic-code-account-two")
    return first, second


@pytest.mark.parametrize("mutation", ["foreign-refresh", "expiry-extension", "scope-extension"])
@pytest.mark.parametrize("operation", ["refresh", "revoke", "identity", "bind-identity"])
def test_every_grant_consumer_rejects_mutated_issue_before_http(protocol, server, mutation, operation):
    first, second = two_grants(protocol, server)
    forged = first.model_copy(deep=True)
    if mutation == "foreign-refresh":
        forged.refresh_token = second.refresh_token
    elif mutation == "expiry-extension":
        forged.expires_at += timedelta(days=1)
    else:
        forged.scopes = (*forged.scopes, "openid")
    baseline = len(server.requests)
    with pytest.raises(OAuthError):
        if operation == "identity":
            protocol.identity_status("youtube:1", forged)
        elif operation == "bind-identity":
            protocol.bind_synthetic_identity(
                "youtube:1", forged, "nf-synthetic-identity-one", "nf-synthetic-identity-one",
            )
        else:
            getattr(protocol, operation)("youtube:1", forged)
    assert len(server.requests) == baseline
    assert protocol.identity_status("youtube:1", first) == "UNVERIFIED"
    assert protocol.identity_status("youtube:2", second) == "UNVERIFIED"


def test_replacing_refresh_with_none_does_not_preserve_original_identity_receipt(protocol, server):
    first = complete(protocol)
    protocol.bind_synthetic_identity(
        "youtube:1", first, "nf-synthetic-identity-one", "nf-synthetic-identity-one",
    )
    forged = first.model_copy(update={"refresh_token": None})
    with pytest.raises(OAuthError):
        protocol.identity_status("youtube:1", forged)
    assert protocol.identity_status("youtube:1", first) == "SYNTHETIC_VERIFIED"
    assert len(server.requests) == 1


@pytest.mark.parametrize("failure", ["server-error", "timeout", "malformed-success"])
def test_unknown_refresh_removes_identity_usability_and_blocks_retries(protocol, server, failure):
    first = complete(protocol)
    protocol.bind_synthetic_identity(
        "youtube:1", first, "nf-synthetic-identity-one", "nf-synthetic-identity-one",
    )
    assert protocol.identity_status("youtube:1", first) == "SYNTHETIC_VERIFIED"
    if failure == "server-error":
        server.queue(FakeResponse(status=503, payload={"error": "temporarily_unavailable"}))
    elif failure == "timeout":
        protocol.transport.timeout_seconds = 0.05
        server.queue(FakeResponse(payload=synthetic_response(), delay=0.2))
    else:
        server.queue(FakeResponse(payload=synthetic_response(access_token="non-synthetic-invalid-example")))
    with pytest.raises(ProtocolError) as error:
        protocol.refresh("youtube:1", first)
    assert error.value.outcome_unknown
    assert len(server.requests) == 2
    for operation in ("identity", "bind", "refresh"):
        with pytest.raises(OAuthError):
            if operation == "identity":
                protocol.identity_status("youtube:1", first)
            elif operation == "bind":
                protocol.bind_synthetic_identity(
                    "youtube:1", first, "nf-synthetic-identity-one", "nf-synthetic-identity-one",
                )
            else:
                protocol.refresh("youtube:1", first)
    assert len(server.requests) == 2
    assert all(request.path == "/token" for request in server.requests)
    assert protocol.evidence()["real_oauth_requests"] == 0
    assert protocol.evidence()["real_sns_upload_requests"] == 0


def test_known_refresh_rejection_never_retains_a_verified_identity(protocol, server):
    first = complete(protocol)
    protocol.bind_synthetic_identity(
        "youtube:1", first, "nf-synthetic-identity-one", "nf-synthetic-identity-one",
    )
    server.queue(FakeResponse(status=400, payload={"error": "invalid_grant"}))
    with pytest.raises(OAuthError):
        protocol.refresh("youtube:1", first)
    with pytest.raises(OAuthError):
        protocol.identity_status("youtube:1", first)
    assert len(server.requests) == 2


def test_refresh_lifetime_expiry_blocks_new_http_attempt(protocol, server):
    now = datetime(2026, 10, 14, tzinfo=UTC)
    server.queue(FakeResponse(payload=synthetic_response(refresh_token_expires_in=1)))
    launch = protocol.begin("youtube:1", now=now)
    first = complete(protocol, launch=launch, now=now)
    with pytest.raises(OAuthError) as error:
        protocol.refresh("youtube:1", first, now=now + timedelta(seconds=2))
    assert error.value.code == "expired"
    assert len(server.requests) == 1


def test_read_identity_from_forged_access_does_not_affect_other_account(protocol, server):
    first, second = two_grants(protocol, server)
    forged = first.model_copy(update={"access_token": SecretStr(second.access_token.get_secret_value())})
    with pytest.raises(OAuthError):
        protocol.identity_status("youtube:1", forged)
    assert protocol.identity_status("youtube:2", second) == "UNVERIFIED"
    assert len(server.requests) == 2
