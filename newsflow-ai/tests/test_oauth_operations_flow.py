"""Full synthetic local HTTP OAuth flow; no real login, service or upload calls."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from oauth_operations_server import FAKE_CHANNEL, FakeGoogleOAuthHTTPServer, FakeGoogleResponse
from pydantic import SecretStr
from sqlalchemy import select, text

from newsflow.db.models import AuditLog, OAuthConnection, OAuthLifecycleOperation, PlatformAccount
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.oauth.callback import CallbackError, SyntheticLoopbackCallback
from newsflow.oauth.contracts import YOUTUBE_UPLOAD_SCOPE, OAuthBlocked
from newsflow.oauth.fake_flow import ProductionOAuthFlow, SyntheticOAuthFlow, SyntheticTokenExchangeClient
from newsflow.oauth.identity import (
    IDENTITY_LINK_SCOPES,
    IdentityError,
    SyntheticLoopbackIdentityTransport,
    SyntheticYouTubeIdentityAdapter,
)
from newsflow.oauth.lifecycle import SyntheticOAuthCredentialLifecycle, recover_production_lifecycle
from newsflow.oauth.production import ProtocolError
from newsflow.oauth.production_dpapi import FakeProductionCipherProtector, SyntheticProductionCredentialVault
from newsflow.oauth.production_vault import CredentialBoundaryError
from newsflow.oauth.session import pkce_s256

CLIENT = "nf-synthetic-desktop.apps.googleusercontent.com"


@pytest.fixture
def full_flow(tmp_path: Path):
    engine = make_engine(tmp_path / "공백 한글 데이터" / "fixture.sqlite")
    migrate(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        session.add_all([
            PlatformAccount(id=1, platform="youtube", label="합성 채널 1", account_type="channel"),
            PlatformAccount(id=2, platform="youtube", label="합성 채널 2", account_type="channel"),
        ])
    vault_root = tmp_path / "합성 운영 vault"
    vault = SyntheticProductionCredentialVault(
        vault_root.absolute(), protector=FakeProductionCipherProtector(b"f" * 32),
        owner_sid="NF-TEST-SID-flow",
    )
    server = FakeGoogleOAuthHTTPServer()
    server.start()
    client = SyntheticTokenExchangeClient(server.base_url, client_id=CLIENT,
                                          client_secret=SecretStr("nf-synthetic-client-secret"))
    identity = SyntheticYouTubeIdentityAdapter(SyntheticLoopbackIdentityTransport(server.base_url), client_id=CLIENT)
    lifecycle = SyntheticOAuthCredentialLifecycle(sessions, vault)
    flow = SyntheticOAuthFlow(client, identity, lifecycle)
    try:
        yield flow, server, sessions, vault, vault_root, engine
    finally:
        server.close()
        engine.dispose()


def callback(client, *, account="youtube:1", server=None):
    with SyntheticLoopbackCallback() as listener:
        launch = listener.start(account, scopes=IDENTITY_LINK_SCOPES)
        assert client.dispatch_authorization(launch) == 200
        result = listener.wait(timeout_seconds=2)
        result.assert_valid(account)
        assert listener.evidence()["synthetic_callbacks_accepted"] == 1
    return result


def connect(full_flow):
    flow, _server, _sessions, _vault, _root, _engine = full_flow
    return flow.connect(1, callback(flow.client), expected_channel=FAKE_CHANNEL, expected_revision=1)


def metadata(sessions, account=1):
    with sessions() as session:
        row = session.get(PlatformAccount, account)
        connection = session.get(OAuthConnection, account)
        return {
            "reference": row.credential_ref,
            "account_status": row.status, "api_ready": row.api_ready,
            "connection_status": connection.status if connection else "unprepared",
            "revision": connection.revision if connection else 1,
        }


def test_full_http_callback_exchange_identity_ciphertext_restart(full_flow, capsys):
    _flow, server, sessions, vault, root, engine = full_flow
    completed = connect(full_flow)
    assert metadata(sessions) == {
        "reference": completed.reference, "account_status": "not_connected", "api_ready": False,
        "connection_status": "fake_connected", "revision": 3,
    }
    assert completed.mode == "SYNTHETIC_ONLY" and repr(completed) == "SyntheticConnectionResult(mode='SYNTHETIC_ONLY')"
    token_request = next(request for request in server.requests if request.path == "/token")
    assert token_request.values["redirect_uri"][0].startswith("http://127.0.0.1:")
    assert ":8765/" not in token_request.values["redirect_uri"][0]
    authorize = next(request for request in server.requests if request.path == "/authorize")
    assert pkce_s256(token_request.values["code_verifier"][0]) == authorize.values["code_challenge"][0]
    assert token_request.values["redirect_uri"] == authorize.values["redirect_uri"]
    reopened_vault = SyntheticProductionCredentialVault(
        root.absolute(), protector=FakeProductionCipherProtector(b"f" * 32), owner_sid="NF-TEST-SID-flow",
    )
    reopened = SyntheticOAuthCredentialLifecycle(sessions, reopened_vault)
    assert reopened.load(1, completed.identity) == completed.bundle
    ciphertext = (root / (completed.reference + ".pcred")).read_bytes()
    captured = capsys.readouterr()
    with engine.connect() as connection:
        dump = repr(connection.execute(text("SELECT * FROM oauth_lifecycle_operations")).all())
    with sessions() as session:
        audit = repr(list(session.scalars(select(AuditLog.message))))
    for secret in (completed.bundle.access_token.get_secret_value(), completed.bundle.refresh_token.get_secret_value()):
        assert secret.encode() not in ciphertext
        assert secret not in dump + audit + captured.out + captured.err + repr(completed)
    assert len(vault.inventory()) == 1
    assert server.evidence() == {
        "mode": "SYNTHETIC_FAKE_GOOGLE_SERVER", "authorization_requests": 1,
        "token_requests": 1, "identity_requests": 1, "revoke_requests": 0,
        "real_oauth_requests": 0, "real_sns_upload_requests": 0,
    }


@pytest.mark.parametrize("field", ["account", "verifier", "redirect"])
def test_callback_seal_blocks_cross_binding_before_token_post(full_flow, field):
    flow, server, sessions, _vault, _root, _engine = full_flow
    consumed = callback(flow.client)
    changes = {
        "account": {"account_key": "youtube:2"},
        "verifier": {"verifier": SecretStr("f" * 64), "code_challenge": pkce_s256("f" * 64)},
        "redirect": {"redirect_uri": "http://127.0.0.1:12345/oauth/callback"},
    }[field]
    with pytest.raises(CallbackError):
        flow.connect(1, replace(consumed, **changes), expected_channel=FAKE_CHANNEL, expected_revision=1)
    assert server.evidence()["token_requests"] == 0
    assert metadata(sessions)["reference"] is None


def test_consumed_callback_cannot_exchange_twice(full_flow):
    flow, server, sessions, _vault, _root, _engine = full_flow
    consumed = callback(flow.client)
    flow.connect(1, consumed, expected_channel=FAKE_CHANNEL, expected_revision=1)
    with pytest.raises(ProtocolError) as error:
        flow.client.exchange("youtube:1", consumed)
    assert error.value.code == "reused"
    assert server.evidence()["token_requests"] == 1
    assert metadata(sessions)["account_status"] == "not_connected"


@pytest.mark.parametrize("changes", [
    {"scope": YOUTUBE_UPLOAD_SCOPE}, {"access_token": "not-a-real-service-token-test-value"},
    {"refresh_token": None}, {"expires_in": True},
], ids=["reduced-scope", "real-format", "no-refresh", "boolean-expiry"])
def test_invalid_exchange_response_never_creates_a_connection(full_flow, changes):
    flow, server, sessions, vault, _root, _engine = full_flow
    server.token_responses.append(FakeGoogleResponse(changes=changes))
    consumed = callback(flow.client)
    with pytest.raises(ProtocolError):
        flow.connect(1, consumed, expected_channel=FAKE_CHANNEL, expected_revision=1)
    with pytest.raises(ProtocolError):
        flow.client.exchange("youtube:1", consumed)
    assert server.evidence()["token_requests"] == 1
    assert server.evidence()["identity_requests"] == 0
    assert metadata(sessions)["reference"] is None
    assert vault.inventory() == ()


def test_exchange_timeout_keeps_callback_consumed_without_retry(full_flow):
    flow, server, sessions, vault, _root, _engine = full_flow
    consumed = callback(flow.client)
    flow.client.timeout_seconds = 0.05
    server.token_responses.append(FakeGoogleResponse(delay=0.2))
    with pytest.raises(ProtocolError) as error:
        flow.connect(1, consumed, expected_channel=FAKE_CHANNEL, expected_revision=1)
    assert error.value.outcome_unknown
    with pytest.raises(ProtocolError):
        flow.client.exchange("youtube:1", consumed)
    assert metadata(sessions)["reference"] is None and vault.inventory() == ()
    assert server.evidence()["token_requests"] == 1


@pytest.mark.parametrize("case", ["wrong-channel", "unauthorized", "timeout"])
def test_identity_failure_blocks_credential_pointer(full_flow, case):
    flow, server, sessions, vault, _root, _engine = full_flow
    expected = "UC" + "b" * 22 if case == "wrong-channel" else FAKE_CHANNEL
    if case == "unauthorized":
        server.identity_responses.append(FakeGoogleResponse(status=401))
    elif case == "timeout":
        flow.identity.transport.timeout_seconds = 0.05
        server.identity_responses.append(FakeGoogleResponse(delay=0.2))
    with pytest.raises(IdentityError):
        flow.connect(1, callback(flow.client), expected_channel=expected, expected_revision=1)
    assert metadata(sessions)["reference"] is None and vault.inventory() == ()
    assert flow.identity.readiness("youtube:1") == "BLOCKED"
    assert server.evidence()["identity_requests"] == 1


def test_refresh_journal_rotation_rechecks_identity_then_revoke(full_flow):
    flow, server, sessions, vault, _root, _engine = full_flow
    first = connect(full_flow)
    first_digest = first.identity.digest("youtube:1")
    replacement = flow.refresh(1, first.bundle, first.identity, expected_channel=FAKE_CHANNEL, expected_revision=3)
    assert replacement.reference != first.reference
    assert replacement.identity.digest("youtube:1") == first_digest
    assert not vault.reference_exists(first.reference)
    assert flow.lifecycle.load(1, replacement.identity) == replacement.bundle
    with pytest.raises(IdentityError):
        first.identity.validate_bundle("youtube:1", first.bundle)
    assert metadata(sessions)["revision"] == 5
    flow.revoke(1, replacement.bundle, replacement.identity, expected_revision=5)
    assert metadata(sessions) == {
        "reference": None, "account_status": "not_connected", "api_ready": False,
        "connection_status": "revoked", "revision": 7,
    }
    assert vault.inventory() == ()
    assert server.evidence()["token_requests"] == 2
    assert server.evidence()["identity_requests"] == 2
    assert server.evidence()["revoke_requests"] == 1


@pytest.mark.parametrize("case", ["timeout", "scope-reduction", "identity-permission"])
def test_refresh_failure_quarantines_before_call_and_restart_never_succeeds(full_flow, case):
    flow, server, sessions, vault, _root, _engine = full_flow
    first = connect(full_flow)
    if case == "timeout":
        flow.client.timeout_seconds = 0.05
        server.token_responses.append(FakeGoogleResponse(delay=0.2))
    elif case == "scope-reduction":
        server.token_responses.append(FakeGoogleResponse(changes={"scope": YOUTUBE_UPLOAD_SCOPE}))
    else:
        server.identity_responses.append(FakeGoogleResponse(status=403))
    with pytest.raises((ProtocolError, IdentityError)):
        flow.refresh(1, first.bundle, first.identity, expected_channel=FAKE_CHANNEL, expected_revision=3)
    state = metadata(sessions)
    assert state["connection_status"] == ("error" if case == "identity-permission" else "credential_unknown")
    assert state["reference"] == first.reference and state["account_status"] == "not_connected"
    assert state["api_ready"] is False and vault.reference_exists(first.reference)
    before = len(server.requests)
    recover_production_lifecycle(sessions)
    with pytest.raises(CredentialBoundaryError):
        flow.lifecycle.load(1, first.identity)
    with pytest.raises((CredentialBoundaryError, IdentityError)):
        flow.refresh(1, first.bundle, first.identity, expected_channel=FAKE_CHANNEL,
                     expected_revision=metadata(sessions)["revision"])
    assert len(server.requests) == before
    with sessions() as session:
        operation = session.scalar(select(OAuthLifecycleOperation).where(OAuthLifecycleOperation.operation == "replace"))
        assert operation.status in {"unknown", "error"}


def test_wrong_account_refresh_cannot_reserve_or_post(full_flow):
    flow, server, sessions, _vault, _root, _engine = full_flow
    completed = connect(full_flow)
    before = len(server.requests)
    with pytest.raises(IdentityError):
        flow.refresh(2, completed.bundle, completed.identity, expected_channel=FAKE_CHANNEL, expected_revision=1)
    assert len(server.requests) == before
    assert metadata(sessions, 2)["reference"] is None
    assert flow.lifecycle.load(1, completed.identity) == completed.bundle


def test_fake_authorization_cannot_redirect_to_external_login(full_flow):
    flow, server, sessions, _vault, _root, _engine = full_flow
    server.authorize_responses.append(FakeGoogleResponse(status=302, location="https://accounts.google.com/o/oauth2/auth"))
    with SyntheticLoopbackCallback() as listener:
        launch = listener.start("youtube:1", scopes=IDENTITY_LINK_SCOPES)
        with pytest.raises(ProtocolError) as error:
            flow.client.dispatch_authorization(launch)
        assert error.value.code == "redirect_mismatch"
        assert listener.evidence()["synthetic_callbacks_accepted"] == 0
    assert server.evidence()["token_requests"] == 0
    assert metadata(sessions)["reference"] is None


def test_cancelled_fake_login_never_exchanges_code(full_flow):
    flow, server, sessions, _vault, _root, _engine = full_flow
    server.authorize_responses.append(FakeGoogleResponse(status=302, changes={"error": "access_denied"}))
    with SyntheticLoopbackCallback() as listener:
        launch = listener.start("youtube:1", scopes=IDENTITY_LINK_SCOPES)
        assert flow.client.dispatch_authorization(launch) == 400
        with pytest.raises(CallbackError) as error:
            listener.wait(timeout_seconds=1)
        assert error.value.code == "cancelled"
    assert server.evidence()["token_requests"] == 0
    assert metadata(sessions)["reference"] is None


@pytest.mark.parametrize("method", ["prepare", "complete", "refresh", "revoke"])
def test_real_flow_blocks_factory_even_after_environment_or_gate_forgery(monkeypatch, method):
    factory = Mock(side_effect=AssertionError("production factory must not run"))
    monkeypatch.setenv("NEWSFLOW_OAUTH_ENABLED", "true")
    monkeypatch.setenv("NEWSFLOW_OAUTH_USER_APPROVED", "true")
    from newsflow.oauth import fake_flow

    monkeypatch.setattr(fake_flow, "require_production_activation", lambda: None)
    with pytest.raises(OAuthBlocked):
        getattr(ProductionOAuthFlow(factory), method)(approved=True, production=True)
    factory.assert_not_called()


def reopened_flow(full_flow):
    _old, server, sessions, vault, _root, _engine = full_flow
    client = SyntheticTokenExchangeClient(server.base_url, client_id=CLIENT,
                                          client_secret=SecretStr("nf-synthetic-client-secret"))
    identity = SyntheticYouTubeIdentityAdapter(SyntheticLoopbackIdentityTransport(server.base_url), client_id=CLIENT)
    return SyntheticOAuthFlow(client, identity, SyntheticOAuthCredentialLifecycle(sessions, vault))


def test_expired_grant_refresh_requires_new_identity_and_atomic_revision(full_flow, monkeypatch):
    from newsflow.oauth import lifecycle

    completed = connect(full_flow)
    _flow, server, sessions, vault, _root, _engine = full_flow
    monkeypatch.setattr(lifecycle, "utcnow", lambda: completed.bundle.expires_at)
    assert lifecycle.expire_production_credentials(sessions) == 1
    assert metadata(sessions)["connection_status"] == "expired"
    assert metadata(sessions)["revision"] == 4
    # A new process has no old VerifiedIdentity receipt or token registry.
    restarted = reopened_flow(full_flow)
    # Return a grant valid beyond the simulated access-token expiration.
    server.token_responses.append(FakeGoogleResponse(changes={"expires_in": 7200}))
    replacement = restarted.refresh_for_revalidation(1, expected_channel=FAKE_CHANNEL, expected_revision=4)
    assert replacement.reference != completed.reference
    assert not vault.reference_exists(completed.reference)
    assert restarted.lifecycle.load(1, replacement.identity) == replacement.bundle
    assert metadata(sessions)["revision"] == 6
    assert metadata(sessions)["api_ready"] is False
    assert server.evidence()["identity_requests"] == 2
    assert server.evidence()["token_requests"] == 2


def test_revalidation_restores_after_receipt_key_and_client_state_restart(full_flow, monkeypatch):
    from newsflow.oauth import identity

    completed = connect(full_flow)
    _flow, server, sessions, _vault, _root, engine = full_flow
    engine.dispose()
    monkeypatch.setattr(identity, "_RECEIPT_KEY", b"new-process-receipt-signing-key-32")
    with pytest.raises(IdentityError):
        completed.identity.validate_bundle("youtube:1", completed.bundle)
    restarted = reopened_flow(full_flow)
    assert restarted.identity.readiness("youtube:1") == "BLOCKED"
    result = restarted.refresh_for_revalidation(1, expected_channel=FAKE_CHANNEL, expected_revision=3)
    assert restarted.lifecycle.load(1, result.identity) == result.bundle
    assert metadata(sessions)["revision"] == 5 and metadata(sessions)["api_ready"] is False
    assert server.evidence()["token_requests"] == 2


@pytest.mark.parametrize("case", ["wrong-channel", "wrong-client", "wrong-account", "stale-revision"])
def test_historical_refresh_cross_binding_rejected_before_http(full_flow, case):
    connect(full_flow)
    flow, server, sessions, _vault, _root, _engine = full_flow
    account, revision, channel = 1, 3, FAKE_CHANNEL
    if case == "wrong-channel":
        channel = "UC" + "b" * 22
    elif case == "wrong-client":
        other = "nf-synthetic-other.apps.googleusercontent.com"
        flow = SyntheticOAuthFlow(
            SyntheticTokenExchangeClient(server.base_url, client_id=other,
                                         client_secret=SecretStr("nf-synthetic-client-secret")),
            SyntheticYouTubeIdentityAdapter(SyntheticLoopbackIdentityTransport(server.base_url), client_id=other),
            flow.lifecycle,
        )
    elif case == "wrong-account":
        account, revision = 2, 1
    else:
        revision = 2
    before = len(server.requests)
    with pytest.raises((ProtocolError, CredentialBoundaryError)):
        flow.refresh_for_revalidation(account, expected_channel=channel, expected_revision=revision)
    assert len(server.requests) == before
    assert metadata(sessions)["revision"] == 3


@pytest.mark.parametrize("case", ["timeout", "identity-denied"])
def test_historical_refresh_failure_blocks_explicit_retry_after_restart(full_flow, case):
    connect(full_flow)
    flow, server, sessions, _vault, _root, _engine = full_flow
    restarted = reopened_flow(full_flow)
    if case == "timeout":
        restarted.client.timeout_seconds = 0.05
        server.token_responses.append(FakeGoogleResponse(delay=0.2))
    else:
        server.identity_responses.append(FakeGoogleResponse(status=403))
    with pytest.raises((ProtocolError, IdentityError)):
        restarted.refresh_for_revalidation(1, expected_channel=FAKE_CHANNEL, expected_revision=3)
    assert restarted.identity.readiness("youtube:1") == "BLOCKED"
    before = len(server.requests)
    revision = metadata(sessions)["revision"]
    with pytest.raises(CredentialBoundaryError):
        reopened_flow(full_flow).refresh_for_revalidation(1, expected_channel=FAKE_CHANNEL, expected_revision=revision)
    assert len(server.requests) == before and metadata(sessions)["api_ready"] is False
    assert flow.lifecycle.scan_orphans()["active"] == 1
