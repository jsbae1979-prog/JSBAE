"""Production remains blocked; journal/DPAPI exercises use synthetic credentials only."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import select, text

from newsflow.db.models import AuditLog, OAuthConnection, OAuthCredentialRotation, PlatformAccount
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.oauth.contracts import YOUTUBE_UPLOAD_SCOPE, OAuthBlocked
from newsflow.oauth.production_vault import (
    CredentialBoundaryError,
    ProductionCredentialBoundary,
    SyntheticAccountIdentity,
    SyntheticCredentialBoundaryKernel,
    recover_credential_rotations,
)
from newsflow.oauth.vault import FakeCredentialVault, VaultError, WindowsCredentialVault
from newsflow.publishing.auth import TokenBundle


def bundle(suffix="first", *, scopes=(YOUTUBE_UPLOAD_SCOPE,)):
    return TokenBundle(
        access_token=SecretStr("nf-synthetic-access-" + suffix),
        refresh_token=SecretStr("nf-synthetic-refresh-" + suffix),
        expires_at=datetime.now(UTC) + timedelta(hours=1), scopes=scopes,
    )


def identity(account=1, *, platform="youtube", suffix="first"):
    return SyntheticAccountIdentity(
        f"{platform}:{account}", SecretStr("nf-synthetic-identity-" + suffix),
    )


@pytest.fixture
def boundary(tmp_path):
    engine = make_engine(tmp_path / "공백 경로" / "synthetic.sqlite")
    migrate(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        session.add_all([
            PlatformAccount(id=1, platform="youtube", label="합성 계정1", account_type="channel"),
            PlatformAccount(id=2, platform="youtube", label="합성 계정2", account_type="channel"),
            PlatformAccount(id=3, platform="instagram", label="합성 계정3", account_type="business"),
        ])
    vault = FakeCredentialVault()
    kernel = SyntheticCredentialBoundaryKernel(sessions, vault)
    yield sessions, vault, kernel, engine
    engine.dispose()


def revision(sessions, account=1):
    with sessions() as session:
        connection = session.get(OAuthConnection, account)
        return connection.revision if connection else 1


def metadata(sessions, account=1):
    with sessions() as session:
        row = session.get(PlatformAccount, account)
        connection = session.get(OAuthConnection, account)
        return row.credential_ref, connection.status, row.api_ready, row.status


@pytest.mark.parametrize("operation", ["store", "load", "replace", "delete", "recover"])
def test_production_boundary_denies_before_backend_construction(operation, monkeypatch):
    factory = Mock(side_effect=AssertionError("must not construct a production backend"))
    boundary = ProductionCredentialBoundary(factory)
    monkeypatch.setenv("NEWSFLOW_OAUTH_ENABLED", "true")
    monkeypatch.setenv("NEWSFLOW_OAUTH_USER_APPROVED", "true")
    values = {
        "store": ("youtube:1", "a" * 64, bundle()),
        "load": ("youtube:1", "a" * 64, "b" * 32),
        "replace": ("youtube:1", "a" * 64, "b" * 32, bundle()),
        "delete": ("youtube:1", "a" * 64, "b" * 32),
        "recover": (),
    }
    with pytest.raises(OAuthBlocked):
        getattr(boundary, operation)(*values[operation], **({"expected_revision": 1} if operation == "replace" else {}))
    factory.assert_not_called()


def test_altered_gate_cannot_silently_enable_real_backend(monkeypatch):
    from newsflow.oauth import production_vault

    factory = Mock()
    monkeypatch.setattr(production_vault, "require_production_activation", lambda: None)
    with pytest.raises(OAuthBlocked):
        ProductionCredentialBoundary(factory).store("youtube:1", "a" * 64, bundle())
    factory.assert_not_called()


def test_store_rotate_delete_keeps_refs_separate_from_secrets(boundary):
    sessions, vault, kernel, engine = boundary
    first = kernel.store(1, identity(), bundle(), expected_revision=1)
    assert len(first) == 32 and metadata(sessions) == (first, "fake_connected", False, "not_connected")
    second = kernel.replace(1, identity(), bundle("rotated"), expected_revision=revision(sessions))
    assert second != first and kernel.load(1, identity()).access_token.get_secret_value().endswith("rotated")
    with pytest.raises(VaultError):
        vault.load("youtube:1", first)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT * FROM oauth_credential_rotations")).all()
        serialized = repr(rows)
    assert "nf-synthetic-access" not in serialized and "nf-synthetic-refresh" not in serialized
    assert "nf-synthetic-identity" not in serialized
    kernel.delete(1, identity(), expected_revision=revision(sessions))
    assert metadata(sessions) == (None, "revoked", False, "not_connected")
    with pytest.raises(VaultError):
        vault.load("youtube:1", second)


@pytest.mark.parametrize("field", ["access_token", "refresh_token"])
def test_real_format_values_rejected_before_journal_or_backend(boundary, field):
    sessions, vault, kernel, _engine = boundary
    value = bundle()
    setattr(value, field, SecretStr("EXAMPLE-real-format-never-stored"))
    with pytest.raises(CredentialBoundaryError) as raised:
        kernel.store(1, identity(), value, expected_revision=1)
    assert "EXAMPLE" not in str(raised.value)
    assert not vault._bundles
    with sessions() as session:
        assert session.scalar(select(OAuthCredentialRotation)) is None


@pytest.mark.parametrize("wrong", [identity(2), identity(platform="instagram"), identity(suffix="different")])
def test_account_and_identity_mismatch_preserves_healthy_connection(boundary, wrong):
    sessions, _vault, kernel, _engine = boundary
    reference = kernel.store(1, identity(), bundle(), expected_revision=1)
    with pytest.raises(CredentialBoundaryError, match="계정"):
        kernel.replace(1, wrong, bundle("wrong"), expected_revision=revision(sessions))
    assert metadata(sessions)[0:2] == (reference, "fake_connected")
    assert kernel.load(1, identity()).access_token.get_secret_value().endswith("first")


def test_identity_receipt_repr_and_non_synthetic_subject_rejection(boundary):
    sessions, vault, kernel, _engine = boundary
    receipt = identity()
    assert receipt.subject.get_secret_value() not in repr(receipt)
    invalid = SyntheticAccountIdentity("youtube:1", SecretStr("unverified-real-provider-subject"))
    with pytest.raises(CredentialBoundaryError):
        kernel.store(1, invalid, bundle(), expected_revision=1)
    assert not vault._bundles
    assert revision(sessions) == 1


def test_multiple_accounts_and_platforms_are_isolated(boundary):
    sessions, vault, kernel, _engine = boundary
    one = kernel.store(1, identity(), bundle(), expected_revision=1)
    two = kernel.store(2, identity(2), bundle("two"), expected_revision=1)
    three = kernel.store(3, identity(3, platform="instagram"), bundle("three", scopes=()), expected_revision=1)
    assert len({one, two, three}) == 3
    for key in ("youtube:2", "instagram:1"):
        with pytest.raises(VaultError):
            vault.load(key, one)
    kernel.delete(1, identity(), expected_revision=revision(sessions))
    assert kernel.load(2, identity(2)).access_token.get_secret_value().endswith("two")
    assert kernel.load(3, identity(3, platform="instagram")).access_token.get_secret_value().endswith("three")


def test_revision_cas_prevents_concurrent_reservations(boundary):
    sessions, _vault, kernel, _engine = boundary
    kernel.store(1, identity(), bundle(), expected_revision=1)
    expected = revision(sessions)
    barrier = Barrier(2)

    def reserve():
        barrier.wait()
        try:
            return kernel.reserve(1, identity(), operation="replace", expected_revision=expected)
        except CredentialBoundaryError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: reserve(), range(2)))
    assert sum(item is not None for item in results) == 1
    assert metadata(sessions)[1] == "credential_pending"


def test_unknown_refresh_does_not_retry_or_return_old_token(boundary):
    sessions, _vault, kernel, _engine = boundary
    old = kernel.store(1, identity(), bundle(), expected_revision=1)
    reservation = kernel.reserve(1, identity(), operation="replace", expected_revision=revision(sessions))
    kernel.mark_unknown(reservation)
    assert metadata(sessions)[0:2] == (old, "credential_unknown")
    with pytest.raises(CredentialBoundaryError):
        kernel.load(1, identity())
    with pytest.raises(CredentialBoundaryError):
        kernel.replace(1, identity(), bundle("retry"), expected_revision=revision(sessions))


class ProcessKilled(BaseException):
    """Simulate a process kill; normal exception cleanup does not run."""


@pytest.mark.parametrize("stage", ["reserved", "ciphertext_written", "reference_journaled", "database_committed"])
def test_interruption_and_explicit_recovery_fail_closed(boundary, stage):
    sessions, vault, _kernel, _engine = boundary

    def crash(current):
        if current == stage:
            raise ProcessKilled()

    kernel = SyntheticCredentialBoundaryKernel(sessions, vault, checkpoint=crash)
    with pytest.raises(ProcessKilled):
        kernel.store(1, identity(), bundle(), expected_revision=1)
    restarted = SyntheticCredentialBoundaryKernel(sessions, vault)
    assert restarted.recover() == 1
    if stage == "database_committed":
        assert restarted.load(1, identity()).access_token.get_secret_value().endswith("first")
    else:
        assert metadata(sessions)[1] == "credential_unknown"
        with pytest.raises(CredentialBoundaryError):
            restarted.load(1, identity())
        # The encrypted-file/reference orphan window is documented, not falsely declared cleaned.
        assert len(vault._bundles) == (1 if stage == "ciphertext_written" else 0)


def test_restart_metadata_recovery_never_accesses_vault(boundary):
    sessions, vault, kernel, _engine = boundary
    kernel.reserve(1, identity(), operation="store", expected_revision=1)
    vault.store = Mock(side_effect=AssertionError("restart must not construct/access credentials"))
    vault.load = vault.delete = vault.store
    assert recover_credential_rotations(sessions) == 1
    assert recover_credential_rotations(sessions) == 0
    assert metadata(sessions)[1] == "credential_unknown"
    vault.store.assert_not_called()


def test_recovery_snapshot_cannot_delete_a_late_committed_current_reference(boundary):
    sessions, vault, kernel, _engine = boundary
    reservation = kernel.reserve(1, identity(), operation="store", expected_revision=1)
    ready, release = Event(), Event()

    def pause_write(stage):
        if stage == "reference_journaled":
            ready.set()
            assert release.wait(5)

    writer = SyntheticCredentialBoundaryKernel(sessions, vault, checkpoint=pause_write)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer.complete, reservation, bundle())
        assert ready.wait(5)

        def finish_after_snapshot(stage):
            if stage == "recovery_snapshot":
                release.set()
                future.result(timeout=5)

        recovering = SyntheticCredentialBoundaryKernel(sessions, vault, checkpoint=finish_after_snapshot)
        assert recovering.recover() == 0
    assert metadata(sessions)[1] == "fake_connected"
    assert kernel.load(1, identity()).access_token.get_secret_value().endswith("first")
    with sessions() as session:
        assert session.get(OAuthCredentialRotation, reservation.operation_id).status == "cleaned"


def test_recovery_claim_prevents_a_paused_worker_from_committing_removed_ciphertext(boundary):
    sessions, vault, kernel, _engine = boundary
    reservation = kernel.reserve(1, identity(), operation="store", expected_revision=1)
    ready, release = Event(), Event()

    def pause_write(stage):
        if stage == "reference_journaled":
            ready.set()
            assert release.wait(5)

    writer = SyntheticCredentialBoundaryKernel(sessions, vault, checkpoint=pause_write)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer.complete, reservation, bundle())
        assert ready.wait(5)

        def resume_after_claim(stage):
            if stage == "recovery_claimed":
                release.set()
                with pytest.raises(CredentialBoundaryError):
                    future.result(timeout=5)

        recovering = SyntheticCredentialBoundaryKernel(sessions, vault, checkpoint=resume_after_claim)
        assert recovering.recover() == 1
    assert metadata(sessions)[0:2] == (None, "credential_unknown")
    assert not vault._bundles


def test_recovery_does_not_quarantine_a_newer_account_revision(boundary):
    sessions, _vault, kernel, _engine = boundary
    kernel.reserve(1, identity(), operation="store", expected_revision=1)
    with sessions.begin() as session:
        connection = session.get(OAuthConnection, 1)
        connection.revision = 10
        connection.status = "prepared"
    assert kernel.recover() == 1
    assert revision(sessions) == 10 and metadata(sessions)[1] == "prepared"


def test_database_cas_failure_removes_uncommitted_ciphertext(boundary):
    sessions, vault, _kernel, _engine = boundary

    def conflict(stage):
        if stage == "reference_journaled":
            with sessions.begin() as session:
                session.get(OAuthConnection, 1).revision += 1

    kernel = SyntheticCredentialBoundaryKernel(sessions, vault, checkpoint=conflict)
    with pytest.raises(CredentialBoundaryError):
        kernel.store(1, identity(), bundle(), expected_revision=1)
    assert not vault._bundles
    assert metadata(sessions)[0] is None
    with sessions() as session:
        assert session.scalar(select(OAuthCredentialRotation)).status == "failed"


def test_old_cleanup_failure_preserves_new_and_recovery_deletes_only_old(boundary):
    sessions, vault, kernel, _engine = boundary
    old = kernel.store(1, identity(), bundle(), expected_revision=1)
    original = vault.delete

    def fail_old(key, reference):
        if reference == old:
            raise RuntimeError("nf-synthetic-secret-in-backend-error")
        original(key, reference)

    vault.delete = fail_old
    with pytest.raises(CredentialBoundaryError) as raised:
        kernel.replace(1, identity(), bundle("new"), expected_revision=revision(sessions))
    assert "secret" not in str(raised.value)
    new = metadata(sessions)[0]
    assert new != old and vault.load("youtube:1", new).access_token.get_secret_value().endswith("new")
    assert metadata(sessions)[1] == "credential_unknown"
    vault.delete = original
    assert kernel.recover() == 1
    with pytest.raises(VaultError):
        vault.load("youtube:1", old)
    assert vault.load("youtube:1", new)
    assert metadata(sessions)[1] == "credential_unknown"  # cleanup does not authorize an unknown connection


def test_late_old_cleanup_failure_cannot_overwrite_newer_connection(boundary):
    sessions, vault, kernel, _engine = boundary
    kernel.store(1, identity(), bundle(), expected_revision=1)

    def fail_and_advance(_key, _reference):
        with sessions.begin() as session:
            connection = session.get(OAuthConnection, 1)
            connection.revision += 1
            connection.status = "prepared"
        raise RuntimeError("private-provider-error")

    vault.delete = fail_and_advance
    with pytest.raises(CredentialBoundaryError):
        kernel.replace(1, identity(), bundle("new"), expected_revision=revision(sessions))
    assert metadata(sessions)[1] == "prepared"


def test_stale_load_cannot_return_token_after_concurrent_rotation(boundary):
    sessions, vault, kernel, _engine = boundary
    kernel.store(1, identity(), bundle(), expected_revision=1)
    original = vault.load

    def load_then_rotate(key, reference, *, allow_expired=False):
        value = original(key, reference, allow_expired=allow_expired)
        vault.load = original
        kernel.replace(1, identity(), bundle("new"), expected_revision=revision(sessions))
        return value

    vault.load = load_then_rotate
    with pytest.raises(CredentialBoundaryError) as raised:
        kernel.load(1, identity())
    assert raised.value.code == "revision_conflict"
    assert kernel.load(1, identity()).access_token.get_secret_value().endswith("new")


def test_same_reservation_completion_cannot_be_replayed(boundary):
    sessions, vault, kernel, _engine = boundary
    reservation = kernel.reserve(1, identity(), operation="store", expected_revision=1)
    reference = kernel.complete(reservation, bundle())
    with pytest.raises(CredentialBoundaryError):
        kernel.complete(reservation, bundle("replay"))
    assert len(vault._bundles) == 1 and metadata(sessions)[0] == reference


def test_backend_cannot_bind_another_accounts_reference(boundary):
    sessions, vault, kernel, _engine = boundary
    foreign = kernel.store(2, identity(2), bundle("other-account"), expected_revision=1)
    vault.store = lambda _key, _bundle: foreign
    with pytest.raises(CredentialBoundaryError):
        kernel.store(1, identity(), bundle(), expected_revision=1)
    assert metadata(sessions)[0] is None
    assert vault.load("youtube:2", foreign).access_token.get_secret_value().endswith("other-account")


def test_backend_cannot_overwrite_or_delete_the_old_reference(boundary):
    sessions, vault, kernel, _engine = boundary
    old = kernel.store(1, identity(), bundle(), expected_revision=1)
    vault.store = lambda _key, _bundle: old
    with pytest.raises(CredentialBoundaryError):
        kernel.replace(1, identity(), bundle("replacement"), expected_revision=revision(sessions))
    assert vault.load("youtube:1", old).access_token.get_secret_value().endswith("first")


def test_lost_ciphertext_quarantines_only_matching_revision(boundary):
    sessions, vault, kernel, _engine = boundary
    reference = kernel.store(1, identity(), bundle(), expected_revision=1)
    vault.delete("youtube:1", reference)
    with pytest.raises(CredentialBoundaryError):
        kernel.load(1, identity())
    assert metadata(sessions)[1] == "credential_unknown"


def test_scopes_cannot_expand_during_synthetic_rotation(boundary):
    sessions, _vault, kernel, _engine = boundary
    kernel.store(1, identity(), bundle(), expected_revision=1)
    with pytest.raises(CredentialBoundaryError):
        kernel.replace(1, identity(), bundle("expanded", scopes=(YOUTUBE_UPLOAD_SCOPE, "extra")),
                       expected_revision=revision(sessions))


def test_audit_messages_do_not_contain_credentials_or_subjects(boundary):
    sessions, _vault, kernel, _engine = boundary
    kernel.store(1, identity(), bundle(), expected_revision=1)
    reservation = kernel.reserve(1, identity(), operation="replace", expected_revision=revision(sessions))
    kernel.mark_unknown(reservation)
    with sessions() as session:
        messages = " ".join(row.message for row in session.scalars(select(AuditLog)))
    assert "nf-synthetic" not in messages


def test_additive_0006_preserves_existing_phase4b1_fake_credential_metadata(boundary):
    sessions, vault, _kernel, engine = boundary
    reference = vault.store("youtube:1", bundle())
    with sessions.begin() as session:
        account = session.get(PlatformAccount, 1)
        account.credential_ref, account.scopes = reference, [YOUTUBE_UPLOAD_SCOPE]
        session.add(OAuthConnection(
            account_id=1, status="fake_connected", mode="fake", revision=8,
            expires_at=datetime.now(UTC) + timedelta(hours=1), error_code=None,
        ))
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "src/newsflow/db/migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0005")
    migrate(engine)
    with sessions() as session:
        account = session.get(PlatformAccount, 1)
        connection = session.get(OAuthConnection, 1)
        assert account.credential_ref == reference and account.scopes == [YOUTUBE_UPLOAD_SCOPE]
        assert (connection.status, connection.mode, connection.revision) == ("fake_connected", "fake", 8)
        assert session.scalar(select(OAuthCredentialRotation)) is None
    assert vault.load("youtube:1", reference).access_token.get_secret_value().endswith("first")


@pytest.mark.skipif(sys.platform != "win32", reason="Native current-user DPAPI requires Windows")
def test_native_windows_synthetic_boundary_rotation_reopen_and_account_isolation(boundary, tmp_path):
    sessions, _fake, _kernel, _engine = boundary
    root = tmp_path / "한글 공백" / "합성 보관소"
    vault = WindowsCredentialVault(root)
    kernel = SyntheticCredentialBoundaryKernel(sessions, vault)
    first = kernel.store(1, identity(), bundle(), expected_revision=1)
    second = kernel.replace(1, identity(), bundle("native"), expected_revision=revision(sessions))
    reopened = SyntheticCredentialBoundaryKernel(sessions, WindowsCredentialVault(root))
    assert reopened.load(1, identity()).access_token.get_secret_value().endswith("native")
    assert not (root / (first + ".bin")).exists()
    assert b"nf-synthetic-access" not in (root / (second + ".bin")).read_bytes()
    with pytest.raises(VaultError):
        WindowsCredentialVault(root).load("youtube:2", second)
    reopened.delete(1, identity(), expected_revision=revision(sessions))
    assert not list(root.iterdir())
