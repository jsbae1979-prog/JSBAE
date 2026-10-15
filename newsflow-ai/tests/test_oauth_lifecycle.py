"""Operational lifecycle tests use local fake identity and NF synthetic tokens only."""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Barrier, Event, Thread
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from newsflow.db.models import (
    AuditLog,
    OAuthConnection,
    OAuthIdentityBinding,
    OAuthLifecycleOperation,
    PlatformAccount,
)
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.oauth.contracts import OAuthBlocked
from newsflow.oauth.identity import (
    IDENTITY_LINK_SCOPES,
    SyntheticLoopbackIdentityTransport,
    SyntheticYouTubeIdentityAdapter,
)
from newsflow.oauth.lifecycle import (
    ProductionOAuthCredentialLifecycle,
    SyntheticOAuthCredentialLifecycle,
    expire_production_credentials,
    recover_production_lifecycle,
)
from newsflow.oauth.production_dpapi import (
    FakeProductionCipherProtector,
    ProductionVaultError,
    SyntheticProductionCredentialVault,
)
from newsflow.oauth.production_vault import CredentialBoundaryError
from newsflow.publishing.auth import TokenBundle


class IdentityFixtureServer:
    """Numeric loopback GET fixture, never a real Google identity lookup."""

    def __init__(self):
        owner = self
        self.channels = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *args):
                return

            def do_GET(self):
                access = self.headers.get("Authorization", "").removeprefix("Bearer ")
                channel = owner.channels.get(access)
                body = json.dumps({
                    "kind": "youtube#channelListResponse", "pageInfo": {"totalResults": 1},
                    "items": [{"id": channel, "kind": "youtube#channel"}],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.thread = Thread(target=lambda: self.http.serve_forever(poll_interval=0.02), daemon=True)
        self.thread.start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)


def bundle(suffix="first"):
    return TokenBundle(
        access_token=SecretStr("nf-synthetic-access-" + suffix),
        refresh_token=SecretStr("nf-synthetic-refresh-" + suffix),
        expires_at=datetime.now(UTC) + timedelta(hours=1), scopes=IDENTITY_LINK_SCOPES,
    )


@pytest.fixture
def environment(tmp_path):
    engine = make_engine(tmp_path / "공백 한글" / "synthetic.sqlite")
    migrate(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        session.add_all([
            PlatformAccount(id=1, platform="youtube", label="합성 채널 1", account_type="channel"),
            PlatformAccount(id=2, platform="youtube", label="합성 채널 2", account_type="channel"),
        ])
    vault = SyntheticProductionCredentialVault(
        (tmp_path / "운영 합성 vault").absolute(),
        protector=FakeProductionCipherProtector(b"t" * 32), owner_sid="NF-TEST-SID-first-user",
    )
    server = IdentityFixtureServer()
    adapter = SyntheticYouTubeIdentityAdapter(
        SyntheticLoopbackIdentityTransport(f"http://127.0.0.1:{server.http.server_port}"),
        client_id="nf-synthetic-lifecycle.apps.googleusercontent.com",
    )

    def verify(value, account=1, channel=None):
        key = f"youtube:{account}"
        channel = channel or "UC" + str(account) * 22
        server.channels[value.access_token.get_secret_value()] = channel
        adapter.register_synthetic_grant(key, value)
        return adapter.lookup(key, value, expected_channel=channel)

    kernel = SyntheticOAuthCredentialLifecycle(sessions, vault)
    yield sessions, vault, kernel, verify, engine, tmp_path
    server.close()
    engine.dispose()


def revision(sessions, account=1):
    with sessions() as session:
        row = session.get(OAuthConnection, account)
        return row.revision if row else 1


def metadata(sessions, account=1):
    with sessions() as session:
        account_row = session.get(PlatformAccount, account)
        row = session.get(OAuthConnection, account)
        return account_row.credential_ref, row.status, row.revision, account_row.api_ready, account_row.status


@pytest.mark.parametrize("operation", ["store", "load", "replace", "refresh", "revoke", "recover"])
def test_production_lifecycle_hardblock_before_factory(operation, monkeypatch):
    factory = Mock(side_effect=AssertionError("real factory must not run"))
    monkeypatch.setenv("NEWSFLOW_OAUTH_ENABLED", "true")
    monkeypatch.setenv("NEWSFLOW_OAUTH_USER_APPROVED", "true")
    boundary = ProductionOAuthCredentialLifecycle(factory)
    with pytest.raises(OAuthBlocked):
        getattr(boundary, operation)(approved=True, production=True)
    factory.assert_not_called()


def test_replacing_activation_check_alone_never_constructs_production(monkeypatch):
    from newsflow.oauth import lifecycle

    factory = Mock()
    monkeypatch.setattr(lifecycle, "require_production_activation", lambda: None)
    with pytest.raises(OAuthBlocked):
        ProductionOAuthCredentialLifecycle(factory).store()
    factory.assert_not_called()


def test_store_rotate_reopen_revoke_separates_secrets_from_pointer(environment):
    sessions, vault, kernel, verify, engine, _path = environment
    first = bundle()
    first_identity = verify(first)
    old = kernel.store(1, first_identity, first, expected_revision=1)
    assert metadata(sessions) == (old, "fake_connected", 3, False, "not_connected")
    second = bundle("rotated")
    receipt = verify(second)
    new = kernel.replace(1, receipt, second, expected_revision=3)
    assert old != new and not vault.reference_exists(old)
    reopened = SyntheticOAuthCredentialLifecycle(sessions, vault)
    assert reopened.load(1, receipt).access_token == second.access_token
    with engine.connect() as connection:
        dump = repr(connection.execute(text("SELECT * FROM oauth_lifecycle_operations")).all())
        dump += repr(connection.execute(text("SELECT * FROM oauth_identity_bindings")).all())
    assert "nf-synthetic-access" not in dump and "nf-synthetic-refresh" not in dump
    kernel.revoke(1, receipt, expected_revision=5)
    assert metadata(sessions) == (None, "revoked", 7, False, "not_connected")
    assert not vault.reference_exists(new)


def test_reference_is_committed_before_any_ciphertext_write(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    reservation = kernel.reserve(1, receipt, operation="store", expected_revision=1)
    with sessions() as session:
        row = session.get(OAuthLifecycleOperation, reservation.operation_id)
        assert row.new_reference == reservation.new_reference
        assert row.status == "reserved" and row.account_key == "youtube:1"
    assert not vault.reference_exists(reservation.new_reference)
    kernel.complete(reservation, value, identity=receipt)
    evidence = vault.inventory()[0]
    assert evidence.reference == reservation.new_reference and evidence.operation_id == reservation.operation_id


@pytest.mark.parametrize("field", ["access_token", "refresh_token"])
def test_real_format_tokens_rejected_before_reservation(environment, field):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    setattr(value, field, SecretStr("EXAMPLE-real-service-token-never-used"))
    with pytest.raises(CredentialBoundaryError) as caught:
        kernel.store(1, receipt, value, expected_revision=1)
    assert "EXAMPLE" not in str(caught.value) and not vault.inventory()
    with sessions() as session:
        assert session.scalar(select(OAuthLifecycleOperation)) is None
        assert session.scalar(select(OAuthIdentityBinding)) is None


def test_cross_account_receipt_and_ciphertext_isolation(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    one, two = bundle(), bundle("second-account")
    receipt1, receipt2 = verify(one), verify(two, account=2)
    first = kernel.store(1, receipt1, one, expected_revision=1)
    second = kernel.store(2, receipt2, two, expected_revision=1)
    with pytest.raises(CredentialBoundaryError):
        kernel.load(1, receipt2)
    with pytest.raises(ProductionVaultError):
        vault.load("youtube:2", receipt2.digest("youtube:2"), first)
    with sessions.begin() as session:
        session.get(PlatformAccount, 1).credential_ref = second
    with pytest.raises(CredentialBoundaryError):
        kernel.load(1, receipt1)
    assert metadata(sessions)[1] == "error"
    assert kernel.load(2, receipt2).access_token == two.access_token
    assert vault.reference_exists(first) and vault.reference_exists(second)


def test_old_still_valid_receipt_cannot_read_a_rotated_grant(environment):
    sessions, _vault, kernel, verify, _engine, _path = environment
    old = bundle()
    original_receipt = verify(old)
    kernel.store(1, original_receipt, old, expected_revision=1)
    from newsflow.oauth.identity import _issue_receipt

    new = bundle("new-grant-another-adapter")
    fresh = _issue_receipt("youtube:1", original_receipt.client_id, original_receipt.channel_id, new, now=None)
    kernel.replace(1, fresh, new, expected_revision=3)
    with pytest.raises(CredentialBoundaryError):
        kernel.load(1, original_receipt)
    assert metadata(sessions)[1] == "error"


@pytest.mark.parametrize("mutation", ["access", "refresh", "scope"])
def test_backend_grant_or_scope_substitution_is_blocked_before_return(environment, mutation, monkeypatch):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    kernel.store(1, receipt, value, expected_revision=1)
    returned = value.model_copy(deep=True)
    if mutation == "scope":
        returned.scopes = returned.scopes[:1]
    elif mutation == "access":
        returned.access_token = SecretStr("nf-synthetic-access-substituted")
    else:
        returned.refresh_token = SecretStr("nf-synthetic-refresh-substituted")
    monkeypatch.setattr(vault, "load", lambda *_args, **_kwargs: returned)
    with pytest.raises(CredentialBoundaryError):
        kernel.load(1, receipt)
    assert metadata(sessions)[1] == "error"


@pytest.mark.parametrize("field,value", [
    ("account_key", "youtube:2"),
    ("client_id", "nf-synthetic-other.apps.googleusercontent.com"),
    ("channel_id", "UC" + "9" * 22),
    ("synthetic", False),
])
def test_forged_identity_receipt_never_changes_healthy_connection(environment, field, value):
    sessions, _vault, kernel, verify, _engine, _path = environment
    original = bundle()
    receipt = verify(original)
    reference = kernel.store(1, receipt, original, expected_revision=1)
    with pytest.raises(CredentialBoundaryError):
        kernel.reserve(1, replace(receipt, **{field: value}), operation="replace", expected_revision=3)
    assert metadata(sessions)[0:2] == (reference, "fake_connected")


def test_permanent_channel_binding_survives_revoke(environment):
    sessions, _vault, kernel, verify, _engine, _path = environment
    first = bundle()
    receipt = verify(first)
    kernel.store(1, receipt, first, expected_revision=1)
    kernel.revoke(1, receipt, expected_revision=3)
    # A separately issued, legitimate fake receipt for a different client is still a mismatch.
    from newsflow.oauth.identity import _issue_receipt

    another = bundle("different-client")
    wrong = _issue_receipt("youtube:1", "nf-synthetic-other.apps.googleusercontent.com",
                           "UC" + "1" * 22, another, now=None)
    with pytest.raises(CredentialBoundaryError):
        kernel.store(1, wrong, another, expected_revision=5)
    assert metadata(sessions)[1] == "revoked"


def test_same_client_channel_cannot_bind_another_local_account_after_restart(environment):
    sessions, _vault, kernel, verify, _engine, _path = environment
    first = bundle()
    receipt = verify(first)
    kernel.store(1, receipt, first, expected_revision=1)
    from newsflow.oauth.identity import _issue_receipt

    second = bundle("same-channel-another-account")
    cross_account = _issue_receipt("youtube:2", receipt.client_id, receipt.channel_id, second, now=None)
    restarted = SyntheticOAuthCredentialLifecycle(sessions, kernel.vault)
    with pytest.raises(CredentialBoundaryError):
        restarted.store(2, cross_account, second, expected_revision=1)
    assert kernel.load(1, receipt).access_token == first.access_token
    with sessions() as session:
        assert session.get(OAuthIdentityBinding, 2) is None
        assert session.get(PlatformAccount, 2).credential_ref is None


def test_concurrent_revision_cas_has_single_reservation(environment):
    sessions, _vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    kernel.store(1, receipt, value, expected_revision=1)
    barrier = Barrier(2)

    def reserve():
        barrier.wait()
        try:
            return kernel.reserve(1, receipt, operation="replace", expected_revision=3)
        except CredentialBoundaryError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        reservations = list(pool.map(lambda _index: reserve(), range(2)))
    assert sum(item is not None for item in reservations) == 1
    assert metadata(sessions)[1] == "credential_pending"
    with sessions() as session:
        assert len(list(session.scalars(select(OAuthLifecycleOperation)))) == 2


@pytest.mark.parametrize("stage", [
    "reference_reserved", "write_claimed", "ciphertext_written", "ciphertext_verified", "database_committed",
    "old_ciphertext_cleaned",
])
def test_crash_restart_preallocated_reference_cleans_without_unknown_success(environment, stage):
    sessions, vault, _kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)

    class ProcessKilled(BaseException):
        pass

    def crash(current):
        if current == stage:
            raise ProcessKilled()

    kernel = SyntheticOAuthCredentialLifecycle(sessions, vault, checkpoint=crash)
    with pytest.raises(ProcessKilled):
        kernel.store(1, receipt, value, expected_revision=1)
    restarted = SyntheticOAuthCredentialLifecycle(sessions, vault)
    restarted.recover()
    if stage in {"database_committed", "old_ciphertext_cleaned"}:
        assert restarted.load(1, receipt).access_token == value.access_token
        assert restarted.scan_orphans() == {"owned_inactive": 0, "active": 1, "unowned": 0}
    else:
        assert metadata(sessions)[1] == "credential_unknown"
        with pytest.raises(CredentialBoundaryError):
            restarted.load(1, receipt)
        assert not vault.inventory()


def test_refresh_unknown_preserves_old_ciphertext_but_never_reuses_tokens(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    old = kernel.store(1, receipt, value, expected_revision=1)
    reservation = kernel.reserve(1, receipt, operation="replace", expected_revision=3)
    kernel.mark_unknown(reservation)
    with pytest.raises(CredentialBoundaryError):
        kernel.load(1, receipt, allow_expired=True)
    with pytest.raises(CredentialBoundaryError):
        kernel.reserve(1, receipt, operation="replace", expected_revision=5)
    assert kernel.recover() == 1
    assert vault.reference_exists(old) and metadata(sessions)[1] == "credential_unknown"


def test_startup_quarantine_is_database_only_and_idempotent(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    reservation = kernel.reserve(1, verify(value), operation="store", expected_revision=1)
    vault.inventory = Mock(side_effect=AssertionError("startup must never touch vault"))
    assert recover_production_lifecycle(sessions) == 1
    assert recover_production_lifecycle(sessions) == 0
    assert metadata(sessions)[1] == "credential_unknown"
    vault.inventory.assert_not_called()
    with sessions() as session:
        assert session.get(OAuthLifecycleOperation, reservation.operation_id).new_reference == reservation.new_reference


def test_late_writer_loses_claim_and_orphan_sweep_deletes_only_owned_file(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    reservation = kernel.reserve(1, receipt, operation="store", expected_revision=1)
    ready, release = Event(), Event()

    def pause(stage):
        if stage == "write_claimed":
            ready.set()
            assert release.wait(5)

    writer = SyntheticOAuthCredentialLifecycle(sessions, vault, checkpoint=pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer.complete, reservation, value, identity=receipt)
        assert ready.wait(5)
        assert kernel.recover() == 1
        release.set()
        with pytest.raises(CredentialBoundaryError):
            future.result(timeout=5)
    assert kernel.scan_orphans() == {"owned_inactive": 1, "active": 0, "unowned": 0}
    assert kernel.cleanup_orphans() == 1
    assert kernel.cleanup_orphans() == 0
    assert not vault.inventory() and metadata(sessions)[1] == "credential_unknown"


def test_stale_recovery_snapshot_never_deletes_late_committed_pointer(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    reservation = kernel.reserve(1, receipt, operation="store", expected_revision=1)
    ready, release = Event(), Event()

    def pause(stage):
        if stage == "ciphertext_verified":
            ready.set()
            assert release.wait(5)

    writer = SyntheticOAuthCredentialLifecycle(sessions, vault, checkpoint=pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer.complete, reservation, value, identity=receipt)
        assert ready.wait(5)

        def finish(stage):
            if stage == "recovery_snapshot":
                release.set()
                future.result(timeout=5)

        recovering = SyntheticOAuthCredentialLifecycle(sessions, vault, checkpoint=finish)
        assert recovering.recover() == 0
    assert kernel.load(1, receipt).access_token == value.access_token
    assert vault.reference_exists(reservation.new_reference)


def test_two_recovery_workers_only_one_claims_uncommitted_file(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    reservation = kernel.reserve(1, receipt, operation="store", expected_revision=1)
    vault.write_reserved("youtube:1", receipt.digest("youtube:1"), reservation.new_reference, value,
                         operation_id=reservation.operation_id)
    barrier = Barrier(2)

    def wait_snapshot(stage):
        if stage == "recovery_snapshot":
            barrier.wait()

    def recover():
        return SyntheticOAuthCredentialLifecycle(sessions, vault, checkpoint=wait_snapshot).recover()

    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(lambda _index: recover(), range(2)))
    assert sum(counts) == 1 and not vault.reference_exists(reservation.new_reference)
    assert metadata(sessions)[1] == "credential_unknown"


def test_foreign_and_unjournaled_ciphertext_never_deleted_by_orphan_sweep(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    healthy = kernel.store(1, receipt, value, expected_revision=1)
    unused = vault.store("youtube:1", receipt.digest("youtube:1"), bundle("unowned"))
    assert kernel.scan_orphans() == {"owned_inactive": 0, "active": 1, "unowned": 1}
    assert kernel.cleanup_orphans() == 0
    assert vault.reference_exists(healthy) and vault.reference_exists(unused)
    assert metadata(sessions)[1] == "fake_connected"


def test_tampered_ciphertext_stays_unresolved_and_is_not_deleted(environment):
    sessions, vault, kernel, verify, _engine, path = environment
    value = bundle()
    receipt = verify(value)
    reservation = kernel.reserve(1, receipt, operation="store", expected_revision=1)
    vault.write_reserved("youtube:1", receipt.digest("youtube:1"), reservation.new_reference, value,
                         operation_id=reservation.operation_id)
    target = path / "운영 합성 vault" / (reservation.new_reference + ".pcred")
    encoded = target.read_bytes()
    target.write_bytes(encoded[:-1] + bytes([encoded[-1] ^ 1]))
    assert kernel.recover() == 1
    assert target.exists() and metadata(sessions)[1] == "credential_unknown"
    with sessions() as session:
        assert session.get(OAuthLifecycleOperation, reservation.operation_id).status == "cleanup_pending"


def test_wrong_operation_owned_ciphertext_is_preserved(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    reservation = kernel.reserve(1, receipt, operation="store", expected_revision=1)
    vault.write_reserved("youtube:1", receipt.digest("youtube:1"), reservation.new_reference, value,
                         operation_id="f" * 32)
    assert kernel.recover() == 1
    assert vault.reference_exists(reservation.new_reference)
    with sessions() as session:
        assert session.get(OAuthLifecycleOperation, reservation.operation_id).status == "cleanup_pending"


@pytest.mark.parametrize("published", [False, True])
def test_crash_left_authenticated_temporary_ciphertext_is_owned_and_cleaned(environment, published):
    sessions, vault, kernel, verify, _engine, path = environment
    value = bundle()
    receipt = verify(value)
    reservation = kernel.reserve(1, receipt, operation="store", expected_revision=1)
    vault.write_reserved("youtube:1", receipt.digest("youtube:1"), reservation.new_reference, value,
                         operation_id=reservation.operation_id)
    root = path / "운영 합성 vault"
    final = root / (reservation.new_reference + ".pcred")
    pending = root / ("." + reservation.new_reference + "." + "e" * 32 + ".pending")
    if published:
        os.link(final, pending)
    else:
        final.rename(pending)
    assert len(vault.pending_inventory()) == 1
    assert kernel.recover() == 1
    assert not pending.exists() and not final.exists()
    assert metadata(sessions)[1] == "credential_unknown"


def test_committed_owned_temporary_link_cleanup_preserves_current_ciphertext(environment):
    sessions, _vault, kernel, verify, _engine, path = environment
    value = bundle()
    receipt = verify(value)
    reference = kernel.store(1, receipt, value, expected_revision=1)
    root = path / "운영 합성 vault"
    final = root / (reference + ".pcred")
    pending = root / ("." + reference + "." + "e" * 32 + ".pending")
    os.link(final, pending)
    with sessions.begin() as session:
        row = session.scalar(select(OAuthLifecycleOperation).where(OAuthLifecycleOperation.new_reference == reference))
        row.status = "committed"
    assert kernel.recover() == 1
    assert final.exists() and not pending.exists()
    assert kernel.load(1, receipt).access_token == value.access_token


def test_cleanup_never_deletes_another_accounts_active_reference(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    one, two = bundle(), bundle("another-account")
    identity1, identity2 = verify(one), verify(two, account=2)
    first = kernel.store(1, identity1, one, expected_revision=1)
    second = kernel.store(2, identity2, two, expected_revision=1)
    reservation = kernel.reserve(1, identity1, operation="replace", expected_revision=3)
    kernel.mark_unknown(reservation)
    # A duplicate owned reference is rejected by SQLite before any cleanup.
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.get(OAuthLifecycleOperation, reservation.operation_id).new_reference = second
    # A second account falsely selecting this operation's ciphertext also blocks cleanup.
    vault.write_reserved("youtube:1", identity1.digest("youtube:1"), reservation.new_reference, one,
                         operation_id=reservation.operation_id)
    with sessions.begin() as session:
        session.get(PlatformAccount, 2).credential_ref = reservation.new_reference
    kernel.recover()
    assert vault.reference_exists(first) and vault.reference_exists(second)
    assert vault.reference_exists(reservation.new_reference)
    with sessions.begin() as session:
        session.get(PlatformAccount, 2).credential_ref = second
    assert kernel.load(2, identity2).access_token == two.access_token


def test_backend_permission_failure_is_redacted_and_quarantined(environment, monkeypatch):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    monkeypatch.setattr(vault, "write_reserved", Mock(side_effect=PermissionError("nf-synthetic-access-LEAK")))
    with pytest.raises(CredentialBoundaryError) as raised:
        kernel.store(1, receipt, value, expected_revision=1)
    assert "LEAK" not in str(raised.value) and metadata(sessions)[1] == "credential_unknown"
    with sessions() as session:
        audit = " ".join(session.scalars(select(AuditLog.message)))
        assert "nf-synthetic" not in audit and "LEAK" not in audit


def test_metadata_expiration_no_vault_access(environment):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    kernel.store(1, receipt, value, expected_revision=1)
    with sessions.begin() as session:
        session.get(OAuthConnection, 1).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    vault.load = Mock(side_effect=AssertionError("metadata expiry must not read vault"))
    assert expire_production_credentials(sessions) == 1
    assert expire_production_credentials(sessions) == 0
    assert metadata(sessions)[1] == "expired"
    vault.load.assert_not_called()


def test_known_provider_error_does_not_become_connected_after_recovery(environment):
    sessions, _vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    reservation = kernel.reserve(1, receipt, operation="store", expected_revision=1)
    kernel.mark_error(reservation)
    assert metadata(sessions)[1] == "error"
    assert kernel.recover() == 1
    assert metadata(sessions)[1] == "error"
    with pytest.raises(CredentialBoundaryError):
        kernel.load(1, receipt)


def test_additive_migration_0007_preserves_prior_journal_and_account(environment):
    sessions, _vault, _kernel, _verify, engine, _path = environment
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "src/newsflow/db/migrations"))
    with sessions.begin() as session:
        session.add(OAuthConnection(account_id=1, status="fake_connected", mode="fake", revision=17))
        session.get(PlatformAccount, 1).credential_ref = "a" * 32
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0006")
    migrate(engine)
    with sessions() as session:
        assert session.get(PlatformAccount, 1).credential_ref == "a" * 32
        assert session.get(OAuthConnection, 1).revision == 17
        assert session.scalar(select(OAuthIdentityBinding)) is None
        assert session.scalar(select(OAuthLifecycleOperation)) is None
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0009"


@pytest.mark.skipif(sys.platform != "win32", reason="Actual current-user DPAPI requires Windows")
def test_native_dpapi_lifecycle_crash_reopen_preserves_account_isolation(environment):
    sessions, _fake_vault, _kernel, verify, _engine, path = environment
    root = (path / "Windows 합성 운영 보관소").absolute()
    vault = SyntheticProductionCredentialVault(root)
    kernel = SyntheticOAuthCredentialLifecycle(sessions, vault)
    value = bundle("native")
    receipt = verify(value)
    first = kernel.store(1, receipt, value, expected_revision=1)
    reopened = SyntheticOAuthCredentialLifecycle(sessions, SyntheticProductionCredentialVault(root))
    assert reopened.load(1, receipt).access_token == value.access_token
    assert b"nf-synthetic-access" not in (root / (first + ".pcred")).read_bytes()
    with pytest.raises(ProductionVaultError):
        vault.load("youtube:2", receipt.digest("youtube:1"), first)
    replaced = bundle("native-rotation")
    receipt2 = verify(replaced)

    class ProcessKilled(BaseException):
        pass

    def crash(stage):
        if stage == "ciphertext_written":
            raise ProcessKilled()

    writer = SyntheticOAuthCredentialLifecycle(sessions, vault, checkpoint=crash)
    with pytest.raises(ProcessKilled):
        writer.replace(1, receipt2, replaced, expected_revision=3)
    restarted = SyntheticOAuthCredentialLifecycle(sessions, SyntheticProductionCredentialVault(root))
    assert restarted.recover() == 1
    assert vault.reference_exists(first) and metadata(sessions)[1] == "credential_unknown"
    assert restarted.scan_orphans() == {"owned_inactive": 0, "active": 1, "unowned": 0}


def test_historical_candidate_is_not_identity_and_consumes_revision_once(environment):
    sessions, _vault, kernel, verify, _engine, _path = environment
    value = bundle()
    receipt = verify(value)
    kernel.store(1, receipt, value, expected_revision=1)
    historical = kernel.load_for_revalidation(1, expected_revision=3)
    assert historical.purpose == "REVALIDATION_ONLY"
    assert "nf-synthetic" not in repr(historical)
    assert not hasattr(historical, "digest")
    assert historical.bundle == value
    historical.validate(1, expected_revision=3)
    reservation = kernel.reserve_for_revalidation(historical)
    assert reservation.old_reference == historical.reference
    with pytest.raises(CredentialBoundaryError):
        kernel.reserve_for_revalidation(historical)
    with pytest.raises(CredentialBoundaryError):
        kernel.load_for_revalidation(1, expected_revision=4)
    kernel.mark_unknown(reservation)
    assert metadata(sessions)[1] == "credential_unknown"


@pytest.mark.parametrize("field", ["account_id", "reference", "revision", "purpose", "grant_fingerprint", "bundle"])
def test_historical_candidate_field_substitution_cannot_reserve(environment, field):
    _sessions, _vault, kernel, verify, _engine, _path = environment
    value = bundle()
    kernel.store(1, verify(value), value, expected_revision=1)
    historical = kernel.load_for_revalidation(1, expected_revision=3)
    changes = {"account_id": 2, "reference": "a" * 32, "revision": 2,
               "purpose": "READY", "grant_fingerprint": "e" * 64, "bundle": bundle("foreign")}
    with pytest.raises(CredentialBoundaryError):
        kernel.reserve_for_revalidation(replace(historical, **{field: changes[field]}))
    assert kernel.load_for_revalidation(1, expected_revision=3).reference == historical.reference


@pytest.mark.parametrize("status", ["credential_pending", "credential_unknown", "error", "revoked"])
def test_historical_load_forbids_uncertain_failed_or_revoked_state_without_vault_read(environment, status):
    sessions, vault, kernel, verify, _engine, _path = environment
    value = bundle()
    kernel.store(1, verify(value), value, expected_revision=1)
    with sessions.begin() as session:
        session.get(OAuthConnection, 1).status = status
    vault.load = Mock(side_effect=AssertionError("blocked state must not decrypt"))
    with pytest.raises(CredentialBoundaryError):
        kernel.load_for_revalidation(1, expected_revision=3)
    vault.load.assert_not_called()


def test_historical_grant_hash_tamper_quarantines_without_readiness(environment):
    sessions, _vault, kernel, verify, _engine, _path = environment
    value = bundle()
    kernel.store(1, verify(value), value, expected_revision=1)
    with sessions.begin() as session:
        session.get(OAuthIdentityBinding, 1).grant_fingerprint = "a" * 64
    with pytest.raises(CredentialBoundaryError):
        kernel.load_for_revalidation(1, expected_revision=3)
    assert metadata(sessions)[1] == "error"


def test_historical_candidate_expiry_rejects_after_five_minutes(environment, monkeypatch):
    from newsflow.oauth import lifecycle

    _sessions, _vault, kernel, verify, _engine, _path = environment
    value = bundle()
    kernel.store(1, verify(value), value, expected_revision=1)
    historical = kernel.load_for_revalidation(1, expected_revision=3)
    monkeypatch.setattr(lifecycle, "utcnow", lambda: historical.expires_at)
    with pytest.raises(CredentialBoundaryError):
        kernel.reserve_for_revalidation(historical)
