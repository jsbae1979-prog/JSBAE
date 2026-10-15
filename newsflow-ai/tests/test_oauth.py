"""Offline OAuth security boundaries; no real authorization or token transport."""

from __future__ import annotations

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import MetaData, Table, func, select, text

from newsflow.db.models import (
    AuditLog,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    OAuthConnection,
    PlatformAccount,
    PublishAttempt,
    PublishDraft,
    PublishEvidence,
    PublishJob,
    PublishValidation,
    RenderJob,
)
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.intelligence.provider import OfflineProvider, Options
from newsflow.intelligence.service import IntelligenceService
from newsflow.oauth.contracts import (
    FIXED_REDIRECT,
    YOUTUBE_UPLOAD_SCOPE,
    OAuthBlocked,
    OAuthError,
    OAuthPolicy,
)
from newsflow.oauth.providers import FakeOAuthProvider, InstagramOAuthAdapter, YouTubeOAuthAdapter
from newsflow.oauth.service import TokenLifecycleManager
from newsflow.oauth.session import OAuthCallbackValidator, OAuthSessionStore, pkce_s256
from newsflow.oauth.vault import FakeCredentialVault, VaultError
from newsflow.publishing.adapters import ExternalPublishingDisabled, InstagramAdapter, YouTubeAdapter
from newsflow.publishing.auth import TokenBundle


def callback(request, code="nf-synthetic-code-test"):
    return [("state", request.state.get_secret_value()), ("code", code)]


def consume(store, request, params=None, **kwargs):
    return OAuthCallbackValidator(store).consume(
        request.session_id,
        kwargs.pop("account_key", "youtube:1"),
        kwargs.pop("callback_uri", FIXED_REDIRECT),
        callback(request) if params is None else params,
        **kwargs,
    )


def test_pkce_s256_matches_rfc7636_vector():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_s256(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.mark.parametrize("verifier", ["a" * 42, "a" * 129, "a" * 42 + "/", "가" * 43])
def test_invalid_pkce_verifiers_are_rejected(verifier):
    with pytest.raises(OAuthError):
        pkce_s256(verifier)


@pytest.mark.parametrize("ttl", [0, -1, 301, 600])
def test_session_expiry_cannot_exceed_five_minutes(ttl):
    with pytest.raises(OAuthError):
        OAuthSessionStore(ttl)


@pytest.mark.parametrize(
    "account,redirect",
    [
        ("youtube:0", FIXED_REDIRECT),
        ("youtube:../1", FIXED_REDIRECT),
        ("unknown:1", FIXED_REDIRECT),
        ("instagram:1\n", FIXED_REDIRECT),
        ("youtube:1", "http://localhost:8765/oauth/callback"),
        ("youtube:1", "http://127.0.0.1:8766/oauth/callback"),
        ("youtube:1", FIXED_REDIRECT + "?state=unexpected"),
        ("youtube:1", FIXED_REDIRECT + "#fragment"),
    ],
)
def test_session_account_and_registered_redirect_are_exact(account, redirect):
    with pytest.raises(OAuthError):
        OAuthSessionStore().create(account, redirect_uri=redirect)


def test_sessions_use_distinct_state_and_s256_and_redact_repr():
    store = OAuthSessionStore()
    first, second = store.create("youtube:1"), store.create("youtube:1")
    assert first.session_id != second.session_id
    assert first.state.get_secret_value() != second.state.get_secret_value()
    assert first.code_challenge != second.code_challenge
    session, code = consume(store, first)
    verifier = session.verifier.get_secret_value()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    )
    assert first.code_challenge == expected and first.code_challenge_method == "S256"
    assert len(verifier) >= 43 and len(first.state.get_secret_value()) >= 43
    assert first.state.get_secret_value() not in repr(first)
    assert verifier not in repr(session)
    assert code.get_secret_value() not in repr((session, code))


def test_valid_callback_is_consumed_exactly_once():
    store = OAuthSessionStore()
    request = store.create("youtube:1", scopes=(YOUTUBE_UPLOAD_SCOPE,))
    session, code = consume(store, request)
    assert session.account_key == "youtube:1" and session.scopes == (YOUTUBE_UPLOAD_SCOPE,)
    assert code.get_secret_value() == "nf-synthetic-code-test"
    with pytest.raises(OAuthError) as error:
        consume(store, request)
    assert error.value.code == "reused"


def test_wrong_state_consumes_request_and_does_not_disclose_input():
    store = OAuthSessionStore()
    request = store.create("youtube:1")
    params = [("state", "X" * 43), ("code", "nf-synthetic-code-secret-value")]
    with pytest.raises(OAuthError) as error:
        consume(store, request, params)
    assert error.value.code == "state_mismatch"
    assert "nf-synthetic-code-secret-value" not in str(error.value)
    with pytest.raises(OAuthError) as replay:
        consume(store, request)
    assert replay.value.code == "reused"


@pytest.mark.parametrize(
    "extra",
    [
        [("state", "duplicated")],
        [("code", "nf-synthetic-code-duplicated")],
        [("error", "access_denied")],
        [("error_description", "PROVIDER-SECRET-MESSAGE")],
        [("unknown", "unexpected")],
    ],
)
def test_callback_duplicate_ambiguous_or_unknown_parameters_are_rejected(extra):
    store = OAuthSessionStore()
    request = store.create("youtube:1")
    with pytest.raises(OAuthError) as error:
        consume(store, request, callback(request) + extra)
    assert error.value.code == "callback_invalid"
    assert "PROVIDER-SECRET-MESSAGE" not in str(error.value)
    with pytest.raises(OAuthError):
        consume(store, request)


@pytest.mark.parametrize(
    "code", ["", "nf-synthetic-code-\nsecret", "nf-synthetic-code-\x00secret", "x" * 2049]
)
def test_callback_authorization_code_bounds_and_controls(code):
    store = OAuthSessionStore()
    request = store.create("youtube:1")
    with pytest.raises(OAuthError) as error:
        consume(store, request, callback(request, code))
    assert error.value.code == "callback_invalid" and "secret" not in str(error.value)


@pytest.mark.parametrize(
    "provider_error,expected", [("access_denied", "cancelled"), ("server_error", "provider_error")]
)
def test_callback_cancellation_is_distinct_from_provider_error(provider_error, expected):
    store = OAuthSessionStore()
    request = store.create("youtube:1")
    params = [
        ("state", request.state.get_secret_value()),
        ("error", provider_error),
        ("error_description", "UNTRUSTED-PROVIDER-SECRET"),
    ]
    with pytest.raises(OAuthError) as error:
        consume(store, request, params)
    assert error.value.code == expected
    assert "UNTRUSTED-PROVIDER-SECRET" not in str(error.value)


@pytest.mark.parametrize(
    "options,expected",
    [
        ({"account_key": "youtube:2"}, "account_mismatch"),
        ({"account_key": "instagram:1"}, "account_mismatch"),
        ({"callback_uri": "http://127.0.0.1:8766/oauth/callback"}, "redirect_mismatch"),
    ],
)
def test_callback_bound_to_original_account_and_redirect(options, expected):
    store = OAuthSessionStore()
    request = store.create("youtube:1")
    with pytest.raises(OAuthError) as error:
        consume(store, request, **options)
    assert error.value.code == expected
    with pytest.raises(OAuthError) as replay:
        consume(store, request)
    assert replay.value.code == "reused"


def test_callback_at_expiry_boundary_is_expired():
    start = datetime(2026, 10, 14, tzinfo=UTC)
    store = OAuthSessionStore(300)
    request = store.create("youtube:1", now=start)
    with pytest.raises(OAuthError) as error:
        consume(store, request, now=start + timedelta(seconds=300))
    assert error.value.code == "expired"


def test_naive_callback_clock_is_invalid_and_request_is_consumed():
    store = OAuthSessionStore()
    request = store.create("youtube:1")
    with pytest.raises(OAuthError) as error:
        consume(store, request, now=datetime(2026, 10, 14))
    assert error.value.code == "invalid_input"
    with pytest.raises(OAuthError) as replay:
        consume(store, request)
    assert replay.value.code == "reused"


def test_restart_does_not_restore_sensitive_pending_sessions():
    request = OAuthSessionStore().create("youtube:1")
    with pytest.raises(OAuthError) as error:
        consume(OAuthSessionStore(), request)
    assert error.value.code == "reused"


def test_concurrent_callbacks_reserve_only_one_request():
    store = OAuthSessionStore()
    request = store.create("youtube:1")
    barrier = Barrier(2)

    def process():
        barrier.wait(timeout=5)
        try:
            consume(store, request)
        except OAuthError as error:
            return error.code
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: process(), range(2)))
    assert sorted(results) == ["accepted", "reused"]


@pytest.mark.parametrize("provider", [YouTubeOAuthAdapter, InstagramOAuthAdapter])
@pytest.mark.parametrize("enabled,approved", [(False, False), (False, True), (True, False), (True, True)])
def test_real_oauth_never_enabled_by_flags_or_approval(provider, enabled, approved):
    assert not OAuthPolicy(enabled, approved).allows_real
    adapter = provider(feature_enabled=enabled, user_approved=approved)
    with patch("urllib.request.OpenerDirector.open") as network:
        for operation in ("begin", "exchange", "refresh", "revoke"):
            with pytest.raises(OAuthBlocked):
                getattr(adapter, operation)("synthetic-placeholder")
        network.assert_not_called()
    for publisher in (InstagramAdapter(), YouTubeAdapter()):
        with pytest.raises(ExternalPublishingDisabled):
            publisher.publish({}, "synthetic", approved=True)


@pytest.mark.parametrize("account,scopes", [("youtube:1", (YOUTUBE_UPLOAD_SCOPE,)), ("instagram:1", ())])
def test_fake_provider_explicitly_synthetic_and_minimum_scope(account, scopes):
    provider, store = FakeOAuthProvider(), OAuthSessionStore()
    request = provider.begin(account, store)
    session, code = consume(store, request, account_key=account)
    bundle = provider.exchange(code, session)
    assert bundle.access_token.get_secret_value().startswith("nf-synthetic-access-")
    assert bundle.refresh_token.get_secret_value().startswith("nf-synthetic-refresh-")
    assert bundle.scopes == scopes
    assert bundle.expires_at > datetime.now(UTC)
    assert bundle.access_token.get_secret_value() not in repr(bundle)
    with pytest.raises(OAuthError) as error:
        provider.exchange(code, session)
    assert error.value.code == "reused" and provider.calls["exchange"] == 1


def test_fake_provider_rejects_real_looking_codes_and_tokens():
    provider, store = FakeOAuthProvider(), OAuthSessionStore()
    request = provider.begin("youtube:1", store)
    session, _ = consume(store, request)
    with pytest.raises(OAuthBlocked):
        provider.exchange(SecretStr("UNSAFE-REAL-CODE"), session)
    bundle = TokenBundle(
        access_token="UNSAFE-REAL-ACCESS",
        refresh_token="UNSAFE-REAL-REFRESH",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    for operation in ("refresh", "revoke"):
        with pytest.raises(OAuthBlocked):
            getattr(provider, operation)(bundle)
    assert provider.calls == {"begin": 1, "exchange": 0, "refresh": 0, "revoke": 0}


class TrackingVault(FakeCredentialVault):
    def __init__(self):
        super().__init__()
        self.created, self.deleted = [], []

    def store(self, account_key, bundle):
        reference = super().store(account_key, bundle)
        self.created.append(reference)
        return reference

    def delete(self, account_key, reference):
        super().delete(account_key, reference)
        self.deleted.append(reference)


@pytest.fixture
def lifecycle(app):
    with app.state.sessions.begin() as session:
        session.add_all(
            [
                PlatformAccount(platform="youtube", label="합성 채널", account_type="youtube_channel"),
                PlatformAccount(
                    platform="instagram", label="합성 계정", account_type="professional_business"
                ),
            ]
        )
    store, vault = OAuthSessionStore(), TrackingVault()
    manager = TokenLifecycleManager(app.state.sessions, vault, store)
    return manager, store, vault


def connect_fake(lifecycle, account_id=1, platform="youtube", provider=None):
    manager, store, _vault = lifecycle
    provider = provider or FakeOAuthProvider()
    request = provider.begin(f"{platform}:{account_id}", store)
    manager.complete_fake(
        account_id, request, callback(request, "nf-synthetic-code-" + request.session_id), provider
    )
    return provider


@pytest.mark.parametrize("account_id,platform", [(1, "youtube"), (2, "instagram")])
def test_fake_connection_does_not_change_real_publishing_readiness(lifecycle, app, account_id, platform):
    manager, _store, _vault = lifecycle
    provider = connect_fake(lifecycle, account_id, platform)
    bundle = manager.token_for_fake(account_id)
    access, refresh = bundle.access_token.get_secret_value(), bundle.refresh_token.get_secret_value()
    with app.state.sessions() as session:
        account = session.get(PlatformAccount, account_id)
        connection = session.get(OAuthConnection, account_id)
        assert connection.status == "fake_connected" and connection.mode == "fake"
        assert account.status == "not_connected" and not account.api_ready and account.connected_at is None
        assert (
            account.credential_ref and access != account.credential_ref and refresh != account.credential_ref
        )
        assert connection.expires_at == bundle.expires_at
        logs = " ".join(session.scalars(select(AuditLog.message)))
        assert access not in logs and refresh not in logs
        assert session.scalar(select(PublishJob)) is None
    with app.state.engine.connect() as connection:
        dump = "\n".join(connection.connection.driver_connection.iterdump())
    assert access not in dump and refresh not in dump
    assert provider.calls["exchange"] == 1


@pytest.mark.parametrize("outcome", ["error", "cancelled", "expired"])
def test_fake_exchange_error_cancel_and_expiry_are_distinct(lifecycle, app, outcome):
    with pytest.raises(OAuthError) as error:
        connect_fake(lifecycle, provider=FakeOAuthProvider(outcome))
    expected = "provider_error" if outcome == "error" else outcome
    assert error.value.code == expected
    with app.state.sessions() as session:
        connection = session.get(OAuthConnection, 1)
        assert connection.status == ("error" if outcome == "error" else outcome)
        assert connection.error_code == expected
        account = session.get(PlatformAccount, 1)
        assert account.credential_ref is None and not account.api_ready


def test_failed_connection_can_recover_with_fresh_synthetic_request(lifecycle, app):
    with pytest.raises(OAuthError):
        connect_fake(lifecycle, provider=FakeOAuthProvider("error"))
    connect_fake(lifecycle)
    manager, *_ = lifecycle
    assert manager.token_for_fake(1).access_token.get_secret_value().startswith("nf-synthetic-access-")
    with app.state.sessions() as session:
        connection = session.get(OAuthConnection, 1)
        assert connection.status == "fake_connected" and connection.error_code is None


def test_callback_for_other_account_cannot_replace_existing_credentials(lifecycle, app):
    manager, store, _vault = lifecycle
    connect_fake(lifecycle)
    original = manager.token_for_fake(1).access_token.get_secret_value()
    provider = FakeOAuthProvider()
    request = provider.begin("youtube:1", store)
    with pytest.raises(OAuthError) as error:
        manager.complete_fake(2, request, callback(request), provider)
    assert error.value.code == "account_mismatch" and provider.calls["exchange"] == 0
    assert manager.token_for_fake(1).access_token.get_secret_value() == original
    with app.state.sessions() as session:
        assert session.get(PlatformAccount, 2).credential_ref is None


def test_provider_exception_is_redacted_and_request_not_reused(lifecycle, app):
    manager, store, _vault = lifecycle

    class BrokenProvider(FakeOAuthProvider):
        def exchange(self, code, session):
            raise RuntimeError("SECRET-CODE-TOKEN-IN-PROVIDER-ERROR")

    provider = BrokenProvider()
    request = provider.begin("youtube:1", store)
    with pytest.raises(OAuthError) as error:
        manager.complete_fake(1, request, callback(request), provider)
    assert error.value.code == "credential_error" and "SECRET" not in str(error.value)
    with app.state.sessions() as session:
        assert "SECRET" not in " ".join(session.scalars(select(AuditLog.message)))
    with pytest.raises(OAuthError) as replay:
        consume(store, request)
    assert replay.value.code == "reused"


def test_fake_provider_cannot_grant_unrequested_scope(lifecycle, app):
    class BroaderScopes(FakeOAuthProvider):
        def exchange(self, code, session):
            result = super().exchange(code, session)
            return result.model_copy(update={"scopes": (*result.scopes, "unexpected-permission")})

    with pytest.raises(OAuthError) as error:
        connect_fake(lifecycle, provider=BroaderScopes())
    assert error.value.code == "scope_mismatch"
    with app.state.sessions() as session:
        assert session.get(PlatformAccount, 1).credential_ref is None
        assert session.get(OAuthConnection, 1).status == "error"
    assert not lifecycle[2].created


def test_forged_session_scope_is_blocked_before_fake_exchange(lifecycle, app):
    manager, store, vault = lifecycle
    request = store.create("youtube:1", scopes=("unexpected-permission",))
    provider = FakeOAuthProvider()
    with pytest.raises(OAuthError) as error:
        manager.complete_fake(1, request, callback(request), provider)
    assert error.value.code == "scope_mismatch"
    assert provider.calls["exchange"] == 0 and not vault.created
    with app.state.sessions() as session:
        assert session.get(PlatformAccount, 1).credential_ref is None
        assert session.get(OAuthConnection, 1).error_code == "scope_mismatch"


def test_duplicate_callback_does_not_invalidate_healthy_fake_credentials(lifecycle, app):
    manager, store, _vault = lifecycle
    provider = FakeOAuthProvider()
    request = provider.begin("youtube:1", store)
    params = callback(request, "nf-synthetic-code-successful-request")
    manager.complete_fake(1, request, params, provider)
    token = manager.token_for_fake(1).access_token.get_secret_value()
    with app.state.sessions() as session:
        reference = session.get(PlatformAccount, 1).credential_ref
        revision = session.get(OAuthConnection, 1).revision
    with pytest.raises(OAuthError) as error:
        manager.complete_fake(1, request, params, provider)
    assert error.value.code == "reused" and provider.calls["exchange"] == 1
    assert manager.token_for_fake(1).access_token.get_secret_value() == token
    with app.state.sessions() as session:
        connection = session.get(OAuthConnection, 1)
        assert connection.status == "fake_connected" and connection.revision == revision
        assert connection.error_code is None
        assert session.get(PlatformAccount, 1).credential_ref == reference
        rejected = list(session.scalars(select(AuditLog).where(AuditLog.event == "oauth_callback_rejected")))
        assert len(rejected) == 1 and rejected[0].message == str(OAuthError("reused"))
        assert token not in rejected[0].message
        assert request.state.get_secret_value() not in rejected[0].message
        assert params[1][1] not in rejected[0].message


def test_cross_account_callback_rejection_preserves_both_healthy_accounts(lifecycle, app):
    manager, store, _vault = lifecycle
    connect_fake(lifecycle)
    connect_fake(lifecycle, 2, "instagram")
    tokens = {
        identifier: manager.token_for_fake(identifier).access_token.get_secret_value()
        for identifier in (1, 2)
    }
    with app.state.sessions() as session:
        snapshots = {
            identifier: (
                session.get(PlatformAccount, identifier).credential_ref,
                session.get(OAuthConnection, identifier).revision,
            )
            for identifier in (1, 2)
        }
    provider = FakeOAuthProvider()
    request = provider.begin("youtube:1", store)
    with pytest.raises(OAuthError) as error:
        manager.complete_fake(2, request, callback(request), provider)
    assert error.value.code == "account_mismatch" and provider.calls["exchange"] == 0
    for identifier, token in tokens.items():
        assert manager.token_for_fake(identifier).access_token.get_secret_value() == token
    with app.state.sessions() as session:
        for identifier, (reference, revision) in snapshots.items():
            connection = session.get(OAuthConnection, identifier)
            assert connection.status == "fake_connected" and connection.revision == revision
            assert connection.error_code is None
            assert session.get(PlatformAccount, identifier).credential_ref == reference
        rejected = list(session.scalars(select(AuditLog).where(AuditLog.event == "oauth_callback_rejected")))
        assert len(rejected) == 1 and rejected[0].message == str(OAuthError("account_mismatch"))
        assert not any(token in rejected[0].message for token in tokens.values())
        assert request.state.get_secret_value() not in rejected[0].message


def test_refresh_rotates_pointer_then_invalidates_old_reference(lifecycle, app):
    manager, _store, vault = lifecycle
    provider = connect_fake(lifecycle)
    old_token = manager.token_for_fake(1).access_token.get_secret_value()
    with app.state.sessions() as session:
        old_reference = session.get(PlatformAccount, 1).credential_ref
        old_revision = session.get(OAuthConnection, 1).revision
    manager.refresh_fake(1, provider)
    with app.state.sessions() as session:
        new_reference = session.get(PlatformAccount, 1).credential_ref
        assert new_reference != old_reference
        assert session.get(OAuthConnection, 1).revision == old_revision + 1
    assert manager.token_for_fake(1).access_token.get_secret_value() != old_token
    with pytest.raises(VaultError):
        vault.load("youtube:1", old_reference)
    assert old_reference in vault.deleted and new_reference not in vault.deleted


def test_expired_fake_metadata_allows_explicit_refresh_recovery(lifecycle, app):
    manager, *_ = lifecycle
    provider = connect_fake(lifecycle)
    with app.state.sessions.begin() as session:
        session.get(OAuthConnection, 1).status = "expired"
    with pytest.raises(OAuthError) as error:
        manager.token_for_fake(1)
    assert error.value.code == "expired"
    manager.refresh_fake(1, provider)
    assert manager.token_for_fake(1).expires_at > datetime.now(UTC)


def test_refresh_failure_keeps_old_pointer_but_blocks_use_until_reconnected(lifecycle, app):
    manager, _store, vault = lifecycle
    connect_fake(lifecycle)
    with app.state.sessions() as session:
        old_reference = session.get(PlatformAccount, 1).credential_ref
    with pytest.raises(OAuthError) as error:
        manager.refresh_fake(1, FakeOAuthProvider("error"))
    assert error.value.code == "provider_error"
    with app.state.sessions() as session:
        assert session.get(PlatformAccount, 1).credential_ref == old_reference
        assert session.get(OAuthConnection, 1).status == "error"
    with pytest.raises(OAuthError):
        manager.token_for_fake(1)
    connect_fake(lifecycle)
    assert manager.token_for_fake(1).expires_at > datetime.now(UTC)
    with pytest.raises(VaultError):
        vault.load("youtube:1", old_reference)


def test_account_credentials_are_isolated_during_rotation_and_disconnect(lifecycle, app):
    manager, _store, vault = lifecycle
    provider = connect_fake(lifecycle)
    connect_fake(lifecycle, 2, "instagram", provider)
    second_token = manager.token_for_fake(2).access_token.get_secret_value()
    with app.state.sessions() as session:
        second_reference = session.get(PlatformAccount, 2).credential_ref
    with pytest.raises(VaultError):
        vault.load("youtube:1", second_reference)
    manager.refresh_fake(1, provider)
    manager.disconnect_fake(1, provider)
    assert manager.token_for_fake(2).access_token.get_secret_value() == second_token
    assert vault.load("instagram:2", second_reference).access_token.get_secret_value() == second_token


def test_disconnect_clears_reference_and_invalidates_pending_callbacks(lifecycle, app):
    manager, store, vault = lifecycle
    provider = connect_fake(lifecycle)
    pending = provider.begin("youtube:1", store)
    with app.state.sessions() as session:
        old_reference = session.get(PlatformAccount, 1).credential_ref
    manager.disconnect_fake(1, provider)
    with app.state.sessions() as session:
        account = session.get(PlatformAccount, 1)
        assert account.credential_ref is None and account.scopes == []
        assert account.status == "not_connected" and not account.api_ready
        assert session.get(OAuthConnection, 1).status == "revoked"
    with pytest.raises(VaultError):
        vault.load("youtube:1", old_reference)
    with pytest.raises(OAuthError):
        manager.token_for_fake(1)
    with pytest.raises(OAuthError) as error:
        consume(store, pending)
    assert error.value.code == "reused" and provider.calls["revoke"] == 1


def test_concurrent_refresh_cannot_replace_newer_rotation_or_leak_orphan(lifecycle, app):
    manager, _store, vault = lifecycle
    connect_fake(lifecycle)
    entered, released = Event(), Event()

    class WaitingProvider(FakeOAuthProvider):
        def refresh(self, bundle):
            entered.set()
            assert released.wait(5)
            return super().refresh(bundle)

    with ThreadPoolExecutor(max_workers=1) as executor:
        stale = executor.submit(manager.refresh_fake, 1, WaitingProvider())
        try:
            assert entered.wait(3)
            manager.refresh_fake(1, FakeOAuthProvider())
            newest = manager.token_for_fake(1).access_token.get_secret_value()
        finally:
            released.set()
        with pytest.raises(OAuthError) as error:
            stale.result(timeout=5)
    assert error.value.code == "revision_conflict"
    assert manager.token_for_fake(1).access_token.get_secret_value() == newest
    with app.state.sessions() as session:
        current_reference = session.get(PlatformAccount, 1).credential_ref
        assert session.get(OAuthConnection, 1).status == "fake_connected"
    assert set(vault.created) - set(vault.deleted) == {current_reference}


@pytest.mark.parametrize("adapter", [YouTubeOAuthAdapter, InstagramOAuthAdapter])
def test_lifecycle_manager_rejects_real_provider_even_after_fake_connection(lifecycle, adapter):
    manager, store, _vault = lifecycle
    connect_fake(lifecycle)
    request = store.create("youtube:1")
    provider = adapter(feature_enabled=True, user_approved=True)
    with patch("urllib.request.OpenerDirector.open") as network:
        for operation, args in (
            (manager.complete_fake, (1, request, callback(request), provider)),
            (manager.refresh_fake, (1, provider)),
            (manager.disconnect_fake, (1, provider)),
        ):
            with pytest.raises(OAuthBlocked):
                operation(*args)
        network.assert_not_called()


def test_restart_with_missing_fake_vault_fails_closed(lifecycle, app):
    _manager, store, _vault = lifecycle
    connect_fake(lifecycle)
    fresh = TokenLifecycleManager(app.state.sessions, FakeCredentialVault(), store)
    with pytest.raises(OAuthError) as error:
        fresh.token_for_fake(1)
    assert error.value.code == "credential_error"
    with app.state.sessions() as session:
        assert session.get(OAuthConnection, 1).status == "error"
        assert not session.get(PlatformAccount, 1).api_ready


def test_additive_0005_migration_preserves_phase4a_forensic_records(tmp_path):
    engine = make_engine(tmp_path / "기존 게시 DB" / "newsflow.db")
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "src/newsflow/db/migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0004")
    sessions = session_factory(engine)
    with sessions.begin() as session:
        source = NewsSource(name="기존 합성 출처", url="https://example.com/legacy-feed")
        session.add(source)
        session.flush()
        session.add(
            NewsArticle(
                source_id=source.id,
                publisher="합성 출처",
                title="기존 합성 기사",
                url="https://example.com/legacy-article",
                canonical_url="https://example.com/legacy-article",
            )
        )
        session.add(
            PlatformAccount(platform="youtube", label="기존 준비 계정", account_type="youtube_channel")
        )
    ai = IntelligenceService(sessions)
    analysis_id = ai.analyze([1])
    with sessions.begin() as session:
        # Seed the actual historical schema, without columns introduced in 0008/0009.
        analysis = session.get(IntelligenceRun, analysis_id)
        legacy_content = Table("content_drafts", MetaData(), autoload_with=session.connection())
        content_id = session.execute(legacy_content.insert().values(
            run_id=analysis_id, duration=30, revision=1, review_status="review_required",
            content=OfflineProvider().complete(analysis.evidence, 30, Options()), sources=analysis.evidence,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )).inserted_primary_key[0]
        content = session.execute(legacy_content.select().where(legacy_content.c.id == content_id)).one()
        legacy_projects = Table("video_projects", MetaData(), autoload_with=session.connection())
        project_id = session.execute(legacy_projects.insert().values(
            draft_id=content_id, title="기존 합성 영상", duration=30,
            snapshot=content.content, sources=content.sources, created_at=datetime.now(UTC),
        )).inserted_primary_key[0]
        render = RenderJob(project_id=project_id, status="success", output_name="video-" + "1" * 32 + ".mp4")
        session.add(render)
        session.flush()
        legacy_drafts = Table("publish_drafts", MetaData(), autoload_with=session.connection())
        draft_id = session.execute(legacy_drafts.insert().values(
            render_job_id=render.id,
            platform="youtube",
            title="기존 게시 초안",
            description="기존 설명",
            hashtags=["합성"],
            account_id=1,
            sources=content.sources,
            media_sha256="a" * 64,
            state="blocked",
            content_reviewed=True,
            sources_confirmed=True,
            copyright_confirmed=True,
            ai_disclosure="disclose", revision=1,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )).inserted_primary_key[0]
        session.add(
            PublishValidation(
                draft_id=draft_id,
                draft_revision=1,
                status="blocked",
                results=[{"key": "api_readiness", "status": "fail", "reason": "기존 미연결"}],
                media_sha256="a" * 64,
            )
        )
        job = PublishJob(
            draft_id=draft_id,
            platform="youtube",
            status="unknown",
            message="기존 결과 불명",
            idempotency_key="b" * 64,
        )
        session.add(job)
        session.flush()
        session.add(PublishAttempt(job_id=job.id, status="unknown", message="기존 시도"))
        session.add(PublishEvidence(draft_id=draft_id, kind="simulation", payload={"real_api_calls": 0}))
    migrate(engine)
    migrate(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011"
    with sessions() as session:
        assert session.get(PlatformAccount, 1).label == "기존 준비 계정"
        assert (
            session.get(PublishDraft, 1).sources["articles"][0]["sources"][0]["url"]
            == "https://example.com/legacy-article"
        )
        assert session.get(PublishValidation, 1).results[0]["reason"] == "기존 미연결"
        assert session.get(PublishJob, 1).status == "unknown"
        assert session.get(PublishAttempt, 1).message == "기존 시도"
        assert session.get(PublishEvidence, 1).payload == {"real_api_calls": 0}
        assert session.scalar(select(func.count()).select_from(OAuthConnection)) == 0
    engine.dispose()
