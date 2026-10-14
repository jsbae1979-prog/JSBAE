"""A disabled production credential boundary and a synthetic recovery kernel.

The Phase 4B-1 DPAPI vault stays synthetic-only and is not a production backend.
Filesystem writes and SQLite commits are separate: the journal makes interruption
fail closed, not a claim of a distributed atomic transaction. A process killed
after a ciphertext file is written but before its opaque reference is journaled
can leave an orphan encrypted file; no token is activated in that window.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import (
    AuditLog,
    OAuthConnection,
    OAuthCredentialRotation,
    PlatformAccount,
    utcnow,
)
from newsflow.publishing.auth import TokenBundle

from .activation import require_production_activation
from .contracts import YOUTUBE_UPLOAD_SCOPE, OAuthBlocked, account_key_valid
from .vault import CredentialVault, _synthetic

_REFERENCE = re.compile(r"[a-f0-9]{32}\Z")
_IDENTITY = re.compile(r"nf-synthetic-identity-[A-Za-z0-9_-]{1,200}\Z")
_SAFE_MESSAGES = {
    "account_mismatch": "인증정보의 대상 계정 또는 계정 식별자가 일치하지 않습니다.",
    "revision_conflict": "다른 인증정보 작업이 진행 중이거나 상태가 변경되었습니다.",
    "credential_error": "인증정보 보관 작업이 실패했습니다. 비밀값은 표시되지 않습니다.",
    "outcome_unknown": "인증정보 작업 결과를 확인할 수 없습니다. 자동 재시도는 차단됩니다.",
}


class CredentialBoundaryError(Exception):
    """Fixed messages only: never relay provider/backend exceptions or secret values."""

    def __init__(self, code: str = "credential_error") -> None:
        self.code = code if code in _SAFE_MESSAGES else "credential_error"
        super().__init__(_SAFE_MESSAGES[self.code])


class ProductionCredentialBackend(Protocol):
    """Future approved current-user backend, separate from the synthetic DPAPI vault.

    A future implementation must bind authenticated provider identity to ciphertext,
    reject account mismatch, use current-user protection and support atomic file
    publication. There is deliberately no real-token implementation in this phase.
    """

    def store(self, account_key: str, identity_digest: str, bundle: TokenBundle) -> str: ...
    def load(self, account_key: str, identity_digest: str, reference: str) -> TokenBundle: ...
    def delete(self, account_key: str, identity_digest: str, reference: str) -> None: ...


class ProductionCredentialBoundary:
    """Real credential entry points are closed before even constructing a backend."""

    def __init__(self, backend_factory: Callable[[], ProductionCredentialBackend]) -> None:
        self._backend_factory = backend_factory

    @staticmethod
    def _deny() -> None:
        require_production_activation()
        # A replacement gate alone does not silently create a real-token backend.
        raise OAuthBlocked()

    def store(self, account_key: str, identity_digest: str, bundle: TokenBundle) -> str:
        self._deny()

    def load(self, account_key: str, identity_digest: str, reference: str) -> TokenBundle:
        self._deny()

    def replace(
        self, account_key: str, identity_digest: str, reference: str, bundle: TokenBundle,
        *, expected_revision: int,
    ) -> str:
        self._deny()

    def delete(self, account_key: str, identity_digest: str, reference: str) -> None:
        self._deny()

    def recover(self) -> None:
        self._deny()


def recover_credential_rotations(sessions: sessionmaker[Session]) -> int:
    """Restart quarantine only: never construct a vault or make a provider request.

    Pending exchange/refresh outcomes are unknown even if an old reference remains.
    Ciphertext cleanup is deliberately a separate explicit operation.
    """
    with sessions.begin() as session:
        journals = list(session.scalars(update(OAuthCredentialRotation).where(
            OAuthCredentialRotation.status.in_(("pending", "writing", "recovering_uncommitted")),
        ).values(status="unknown", updated_at=utcnow()).returning(OAuthCredentialRotation)))
        for journal in journals:
            account = session.get(PlatformAccount, journal.account_id)
            changed = session.execute(update(OAuthConnection).where(
                OAuthConnection.account_id == journal.account_id,
                OAuthConnection.revision == journal.expected_revision + 1,
                OAuthConnection.status == "credential_pending",
            ).values(
                status="credential_unknown", error_code="credential_error",
                revision=OAuthConnection.revision + 1, updated_at=utcnow(),
            ))
            if changed.rowcount and account and f"{account.platform}:{account.id}" == journal.account_key:
                account.status, account.api_ready, account.connected_at = "not_connected", False, None
            session.add(AuditLog(level="warning", event="credential_restart_quarantined",
                                 message=_SAFE_MESSAGES["outcome_unknown"]))
        return len(journals)


@dataclass(frozen=True)
class SyntheticAccountIdentity:
    """An explicitly fake receipt, not proof of a real provider account identity."""

    account_key: str
    subject: SecretStr = field(repr=False)

    def digest(self, expected_key: str) -> str:
        if (
            not account_key_valid(expected_key)
            or self.account_key != expected_key
            or not isinstance(self.subject, SecretStr)
            or not _IDENTITY.fullmatch(self.subject.get_secret_value())
        ):
            raise CredentialBoundaryError("account_mismatch")
        return hashlib.sha256(
            ("NewsFlowAI:synthetic-identity:" + expected_key + ":" + self.subject.get_secret_value()).encode()
        ).hexdigest()


@dataclass(frozen=True)
class CredentialReservation:
    operation_id: str
    account_id: int
    account_key: str
    identity_digest: str
    revision: int
    old_reference: str | None = field(repr=False)


class SyntheticCredentialBoundaryKernel:
    """Test-only durable rotation/recovery; rejects any non-NF credential values.

    Calls are explicit; neither restart nor recovery performs a provider request.
    A pending or unknown operation prevents reading credentials. Successful fake
    connection metadata never marks the platform account connected or API-ready.
    The checkpoint hook only simulates process termination in offline tests.
    """

    def __init__(
        self, sessions: sessionmaker[Session], vault: CredentialVault,
        *, checkpoint: Callable[[str], None] | None = None,
    ) -> None:
        self.sessions, self.vault = sessions, vault
        self._checkpoint = checkpoint or (lambda _stage: None)

    @staticmethod
    def _reference(value: str) -> str:
        if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
            raise CredentialBoundaryError()
        return value

    @staticmethod
    def _bundle(bundle: TokenBundle) -> None:
        try:
            _synthetic(bundle)
        except Exception:  # noqa: BLE001 - redact credential validation errors
            raise CredentialBoundaryError() from None

    @staticmethod
    def _account(session: Session, account_id: int) -> tuple[PlatformAccount, OAuthConnection]:
        if type(account_id) is not int or not 1 <= account_id < 2**63:
            raise CredentialBoundaryError("account_mismatch")
        account = session.get(PlatformAccount, account_id)
        if not account or not account_key_valid(f"{account.platform}:{account.id}"):
            raise CredentialBoundaryError("account_mismatch")
        session.execute(insert(OAuthConnection).values(
            account_id=account.id, status="unprepared", mode="offline", revision=1,
            error_code=None, expires_at=None, updated_at=utcnow(),
        ).on_conflict_do_nothing(index_elements=["account_id"]))
        return account, session.get(OAuthConnection, account.id)

    @staticmethod
    def _identity(
        session: Session, account: PlatformAccount, identity: SyntheticAccountIdentity,
    ) -> tuple[str, str]:
        key = f"{account.platform}:{account.id}"
        if not isinstance(identity, SyntheticAccountIdentity):
            raise CredentialBoundaryError("account_mismatch")
        digest = identity.digest(key)
        # Bind the first receipt permanently, including after delete or a failure.
        prior = session.scalar(select(OAuthCredentialRotation).where(
            OAuthCredentialRotation.account_id == account.id,
        ).order_by(OAuthCredentialRotation.created_at, OAuthCredentialRotation.id).limit(1))
        if prior and (
            prior.account_key != key or not hmac.compare_digest(prior.identity_digest, digest)
        ):
            raise CredentialBoundaryError("account_mismatch")
        return key, digest

    def reserve(
        self, account_id: int, identity: SyntheticAccountIdentity,
        *, operation: str, expected_revision: int,
    ) -> CredentialReservation:
        """Reserve before a refresh/exchange; caller must never retry an unknown result."""
        try:
            return self._reserve(account_id, identity, operation=operation, expected_revision=expected_revision)
        except CredentialBoundaryError:
            raise
        except Exception:  # noqa: BLE001 - sanitize transaction/concurrency backend failures
            raise CredentialBoundaryError() from None

    def _reserve(
        self, account_id: int, identity: SyntheticAccountIdentity,
        *, operation: str, expected_revision: int,
    ) -> CredentialReservation:
        if operation not in {"store", "replace", "delete"} or type(expected_revision) is not int:
            raise CredentialBoundaryError()
        with self.sessions.begin() as session:
            account, connection = self._account(session, account_id)
            key, digest = self._identity(session, account, identity)
            if connection.revision != expected_revision:
                raise CredentialBoundaryError("revision_conflict")
            if connection.status in {"credential_pending", "credential_unknown"}:
                raise CredentialBoundaryError("outcome_unknown")
            if operation == "store":
                if account.credential_ref:
                    raise CredentialBoundaryError("revision_conflict")
            elif (
                not account.credential_ref or connection.mode != "synthetic_boundary"
                or connection.status != "fake_connected"
            ):
                raise CredentialBoundaryError("revision_conflict")
            if account.credential_ref:
                self._reference(account.credential_ref)
            changed = session.execute(update(OAuthConnection).where(
                OAuthConnection.account_id == account_id,
                OAuthConnection.revision == expected_revision,
            ).values(
                status="credential_pending", mode="synthetic_boundary",
                revision=expected_revision + 1, expires_at=None, error_code=None, updated_at=utcnow(),
            ))
            if changed.rowcount != 1:
                raise CredentialBoundaryError("revision_conflict")
            operation_id = uuid4().hex
            session.add(OAuthCredentialRotation(
                id=operation_id, account_id=account.id, account_key=key, identity_digest=digest,
                operation=operation, expected_revision=expected_revision,
                old_reference=account.credential_ref, new_reference=None, status="pending",
            ))
            account.status, account.api_ready, account.connected_at = "not_connected", False, None
            return CredentialReservation(
                operation_id, account.id, key, digest, expected_revision + 1, account.credential_ref,
            )

    @staticmethod
    def _journal(
        session: Session, reservation: CredentialReservation, *, allowed: tuple[str, ...] = ("pending",),
    ) -> OAuthCredentialRotation:
        journal = session.get(OAuthCredentialRotation, reservation.operation_id)
        if (
            not journal or journal.account_id != reservation.account_id
            or journal.account_key != reservation.account_key
            or journal.identity_digest != reservation.identity_digest
            or journal.expected_revision + 1 != reservation.revision
            or journal.old_reference != reservation.old_reference
            or journal.status not in allowed
        ):
            raise CredentialBoundaryError("revision_conflict")
        return journal

    def mark_unknown(self, reservation: CredentialReservation) -> None:
        """Durably block reuse after an ambiguous exchange/refresh; no automatic retry."""
        with self.sessions.begin() as session:
            journal = self._journal(session, reservation)
            changed = session.execute(update(OAuthConnection).where(
                OAuthConnection.account_id == reservation.account_id,
                OAuthConnection.revision == reservation.revision,
                OAuthConnection.status == "credential_pending",
            ).values(status="credential_unknown", revision=reservation.revision + 1, updated_at=utcnow()))
            if changed.rowcount != 1:
                raise CredentialBoundaryError("revision_conflict")
            journal.status, journal.updated_at = "unknown", utcnow()
            session.add(AuditLog(level="warning", event="credential_outcome_unknown",
                                 message=_SAFE_MESSAGES["outcome_unknown"]))

    def _failed(self, reservation: CredentialReservation, new_reference: str | None) -> None:
        with self.sessions() as session:
            journal = session.get(OAuthCredentialRotation, reservation.operation_id)
            if not journal or journal.status != "writing":
                return
        cleanup_ok = True
        if new_reference:
            try:
                self.vault.delete(reservation.account_key, new_reference)
            except Exception:  # noqa: BLE001 - no backend exception or token is logged
                cleanup_ok = False
        with self.sessions.begin() as session:
            journal = session.get(OAuthCredentialRotation, reservation.operation_id)
            if not journal or journal.status != "writing":
                return
            connection = session.get(OAuthConnection, reservation.account_id)
            if connection.revision == reservation.revision and connection.status == "credential_pending":
                connection.status = "credential_unknown"
                connection.error_code = "credential_error"
                connection.revision += 1
                connection.updated_at = utcnow()
            journal.status = "failed" if cleanup_ok else "failed_cleanup_pending"
            journal.updated_at = utcnow()
            session.add(AuditLog(level="warning", event="credential_boundary_failed",
                                 message=_SAFE_MESSAGES["credential_error"]))

    def complete(self, reservation: CredentialReservation, bundle: TokenBundle | None = None) -> str | None:
        """Commit a reserved synthetic result; revision and opaque reference change together."""
        new_reference = None
        claimed = False
        try:
            if not isinstance(reservation, CredentialReservation):
                raise CredentialBoundaryError()
            with self.sessions.begin() as session:
                journal = self._journal(session, reservation)
                operation = journal.operation
                expected_scopes = (YOUTUBE_UPLOAD_SCOPE,) if reservation.account_key.startswith("youtube:") else ()
                changed = session.execute(update(OAuthCredentialRotation).where(
                    OAuthCredentialRotation.id == reservation.operation_id,
                    OAuthCredentialRotation.status == "pending",
                ).values(status="writing", updated_at=utcnow()))
                if changed.rowcount != 1:
                    raise CredentialBoundaryError("revision_conflict")
            claimed = True
            if operation == "delete":
                if bundle is not None:
                    raise CredentialBoundaryError()
            else:
                self._bundle(bundle)
                if len(bundle.scopes) != len(expected_scopes) or set(bundle.scopes) != set(expected_scopes):
                    raise CredentialBoundaryError()
            self._checkpoint("reserved")
            if operation != "delete":
                new_reference = self._reference(self.vault.store(reservation.account_key, bundle))
                if new_reference == reservation.old_reference:
                    # A backend violating immutable reference publication must not delete the old file.
                    new_reference = None
                    raise CredentialBoundaryError()
                self._checkpoint("ciphertext_written")
                with self.sessions.begin() as session:
                    journal = self._journal(session, reservation, allowed=("writing",))
                    journal.new_reference, journal.updated_at = new_reference, utcnow()
                self._checkpoint("reference_journaled")
                stored = self.vault.load(reservation.account_key, new_reference)
                self._bundle(stored)
                if (
                    not hmac.compare_digest(stored.access_token.get_secret_value(), bundle.access_token.get_secret_value())
                    or stored.refresh_token != bundle.refresh_token or stored.expires_at != bundle.expires_at
                    or stored.scopes != bundle.scopes
                ):
                    raise CredentialBoundaryError()
            with self.sessions.begin() as session:
                journal = self._journal(session, reservation, allowed=("writing",))
                account, connection = self._account(session, reservation.account_id)
                if (
                    f"{account.platform}:{account.id}" != reservation.account_key
                    or account.credential_ref != reservation.old_reference
                    or connection.status != "credential_pending"
                    or connection.revision != reservation.revision
                ):
                    raise CredentialBoundaryError("revision_conflict")
                connection.status = "revoked" if operation == "delete" else "fake_connected"
                connection.expires_at = None if operation == "delete" else bundle.expires_at
                connection.revision += 1
                connection.updated_at = utcnow()
                account.credential_ref = new_reference
                account.scopes = [] if operation == "delete" else list(bundle.scopes)
                account.status, account.api_ready, account.connected_at = "not_connected", False, None
                journal.status, journal.updated_at = "committed", utcnow()
                session.add(AuditLog(level="info", event="synthetic_credential_committed",
                                     message="합성 인증정보 참조 변경; 실제 계정 연결 없음"))
            self._checkpoint("database_committed")
            self._cleanup_committed(reservation.operation_id)
            return new_reference
        except CredentialBoundaryError:
            if claimed:
                self._failed(reservation, new_reference)
            raise
        except Exception:  # noqa: BLE001 - redact failures; BaseException leaves a restart-recoverable journal
            if claimed:
                self._failed(reservation, new_reference)
            raise CredentialBoundaryError() from None

    def _cleanup_committed(self, operation_id: str) -> None:
        with self.sessions() as session:
            journal = session.get(OAuthCredentialRotation, operation_id)
            if not journal or journal.status not in {"committed", "committed_cleanup_pending"}:
                raise CredentialBoundaryError("revision_conflict")
            old, key = journal.old_reference, journal.account_key
        if old:
            try:
                self.vault.delete(key, old)
            except Exception:  # noqa: BLE001 - fixed error and blocked credentials on cleanup failure
                with self.sessions.begin() as session:
                    journal = session.get(OAuthCredentialRotation, operation_id)
                    journal.status, journal.updated_at = "committed_cleanup_pending", utcnow()
                    account = session.get(PlatformAccount, journal.account_id)
                    if account and account.credential_ref == journal.new_reference:
                        session.execute(update(OAuthConnection).where(
                            OAuthConnection.account_id == journal.account_id,
                            OAuthConnection.revision == journal.expected_revision + 2,
                            OAuthConnection.status.in_(("fake_connected", "revoked")),
                        ).values(status="credential_unknown", error_code="credential_error",
                                 revision=OAuthConnection.revision + 1, updated_at=utcnow()))
                raise CredentialBoundaryError() from None
        with self.sessions.begin() as session:
            journal = session.get(OAuthCredentialRotation, operation_id)
            journal.status, journal.updated_at = "cleaned", utcnow()

    def store(
        self, account_id: int, identity: SyntheticAccountIdentity, bundle: TokenBundle,
        *, expected_revision: int,
    ) -> str:
        self._bundle(bundle)
        reservation = self.reserve(account_id, identity, operation="store", expected_revision=expected_revision)
        return self.complete(reservation, bundle)

    def replace(
        self, account_id: int, identity: SyntheticAccountIdentity, bundle: TokenBundle,
        *, expected_revision: int,
    ) -> str:
        self._bundle(bundle)
        reservation = self.reserve(account_id, identity, operation="replace", expected_revision=expected_revision)
        return self.complete(reservation, bundle)

    def delete(
        self, account_id: int, identity: SyntheticAccountIdentity, *, expected_revision: int,
    ) -> None:
        reservation = self.reserve(account_id, identity, operation="delete", expected_revision=expected_revision)
        self.complete(reservation)

    def load(self, account_id: int, identity: SyntheticAccountIdentity) -> TokenBundle:
        try:
            with self.sessions.begin() as session:
                account, connection = self._account(session, account_id)
                key, _digest = self._identity(session, account, identity)
                if connection.mode != "synthetic_boundary" or connection.status != "fake_connected":
                    raise CredentialBoundaryError("outcome_unknown")
                reference = self._reference(account.credential_ref)
                revision = connection.revision
            value = self.vault.load(key, reference)
            self._bundle(value)
            with self.sessions() as session:
                account = session.get(PlatformAccount, account_id)
                connection = session.get(OAuthConnection, account_id)
                if (
                    not account or not connection or f"{account.platform}:{account.id}" != key
                    or account.credential_ref != reference or connection.revision != revision
                    or connection.mode != "synthetic_boundary" or connection.status != "fake_connected"
                ):
                    raise CredentialBoundaryError("revision_conflict")
                self._identity(session, account, identity)
            return value
        except CredentialBoundaryError:
            raise
        except Exception:  # noqa: BLE001 - redact corrupted/missing/expired backend errors
            if "revision" in locals():
                with self.sessions.begin() as session:
                    session.execute(update(OAuthConnection).where(
                        OAuthConnection.account_id == account_id, OAuthConnection.revision == revision,
                    ).values(status="credential_unknown", error_code="credential_error",
                             revision=revision + 1, updated_at=utcnow()))
            raise CredentialBoundaryError() from None

    def recover(self) -> int:
        """Inspect durable interrupted work. Never call a provider or retry token rotation."""
        with self.sessions() as session:
            pending = list(session.scalars(select(OAuthCredentialRotation).where(
                OAuthCredentialRotation.status.in_((
                    "pending", "writing", "unknown", "committed", "committed_cleanup_pending",
                    "failed_cleanup_pending",
                )),
            ).order_by(OAuthCredentialRotation.created_at)))
        self._checkpoint("recovery_snapshot")
        recovered = 0
        for item in pending:
            if item.status in {"committed", "committed_cleanup_pending"}:
                with self.sessions() as session:
                    current = session.get(OAuthCredentialRotation, item.id)
                    if not current or current.status not in {"committed", "committed_cleanup_pending"}:
                        continue
                self._cleanup_committed(item.id)
                recovered += 1
                continue
            with self.sessions.begin() as session:
                # Claim the latest journal before touching ciphertext. A worker that
                # already committed/cleaned fails this CAS; a still-writing worker
                # loses permission to commit once this claim is durable.
                changed = session.execute(update(OAuthCredentialRotation).where(
                    OAuthCredentialRotation.id == item.id,
                    OAuthCredentialRotation.status == item.status,
                    OAuthCredentialRotation.new_reference == item.new_reference,
                    OAuthCredentialRotation.old_reference == item.old_reference,
                ).values(status="recovering_uncommitted", updated_at=utcnow()))
                if changed.rowcount != 1:
                    continue
                account = session.get(PlatformAccount, item.account_id)
                if (
                    not account or f"{account.platform}:{account.id}" != item.account_key
                    or (item.new_reference is not None and account.credential_ref == item.new_reference)
                ):
                    # Inconsistent/current pointers require explicit review, not deletion.
                    journal = session.get(OAuthCredentialRotation, item.id)
                    journal.status, journal.updated_at = "recovery_conflict", utcnow()
                    recovered += 1
                    continue
                session.execute(update(OAuthConnection).where(
                    OAuthConnection.account_id == item.account_id,
                    OAuthConnection.mode == "synthetic_boundary",
                    OAuthConnection.revision == item.expected_revision + 1,
                    OAuthConnection.status == "credential_pending",
                ).values(status="credential_unknown", error_code="credential_error",
                         revision=OAuthConnection.revision + 1, updated_at=utcnow()))
            self._checkpoint("recovery_claimed")
            # Remove only the uncommitted new file. Preserve old ciphertext but block reads;
            # an external refresh might already have invalidated it before interruption.
            cleanup_ok = True
            if item.new_reference:
                try:
                    self.vault.delete(item.account_key, item.new_reference)
                except Exception:  # noqa: BLE001 - unknown/corrupt files are not declared clean
                    cleanup_ok = False
            with self.sessions.begin() as session:
                session.execute(update(OAuthCredentialRotation).where(
                    OAuthCredentialRotation.id == item.id,
                    OAuthCredentialRotation.status == "recovering_uncommitted",
                ).values(status="recovered_unknown" if cleanup_ok else "failed_cleanup_pending",
                         updated_at=utcnow()))
            recovered += 1
        return recovered
