"""Identity-bound credential lifecycle with preallocated durable ciphertext ownership.

The public production facade remains closed. The explicit synthetic facade exercises
the same reservation, verification, pointer CAS and recovery code using NF fixtures.
SQLite and the filesystem are not a distributed transaction: interruptions quarantine
the connection and cleanup only authentic, operation-owned, inactive ciphertext.
No recovery method retries a provider request or promotes unknown outcomes to success.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import (
    AuditLog,
    OAuthConnection,
    OAuthIdentityBinding,
    OAuthLifecycleOperation,
    PlatformAccount,
    utcnow,
)
from newsflow.publishing.auth import TokenBundle

from .activation import require_production_activation
from .contracts import OAuthBlocked, account_key_valid
from .production_vault import CredentialBoundaryError
from .vault import _synthetic

_REFERENCE = re.compile(r"[a-f0-9]{32}\Z")
_MODE = "synthetic_production"
_PENDING = ("reserved", "writing", "verified", "unknown", "error", "recovering_unknown", "cleanup_pending")
_AUDIT = "합성 운영 인증정보 작업; 실제 인증 및 게시 없음. 비밀값은 저장하거나 표시하지 않습니다."
_HISTORICAL_KEY = secrets.token_bytes(32)
_HISTORICAL_SEAL = object()


class ProductionOAuthCredentialLifecycle:
    """No settings, environment flag or forged approval can construct a real backend."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory

    @staticmethod
    def _deny() -> None:
        require_production_activation()
        # Replacing the activation check alone cannot expose a live lifecycle.
        raise OAuthBlocked()

    def store(self, *args: Any, **kwargs: Any) -> None:
        self._deny()

    def load(self, *args: Any, **kwargs: Any) -> None:
        self._deny()

    def replace(self, *args: Any, **kwargs: Any) -> None:
        self._deny()

    def refresh(self, *args: Any, **kwargs: Any) -> None:
        self._deny()

    def load_for_revalidation(self, *args: Any, **kwargs: Any) -> None:
        self._deny()

    def revoke(self, *args: Any, **kwargs: Any) -> None:
        self._deny()

    def recover(self, *args: Any, **kwargs: Any) -> None:
        self._deny()


@dataclass(frozen=True)
class LifecycleReservation:
    operation_id: str
    account_id: int
    account_key: str
    identity_digest: str
    revision: int
    old_reference: str | None = field(repr=False)
    new_reference: str | None = field(repr=False)
    claim_id: str = field(repr=False)


@dataclass(frozen=True)
class HistoricalCredential:
    """A sealed, short-lived refresh candidate; it proves no current identity.

    The opaque pointer and current grant hash were read from durable metadata and
    checked against authenticated ciphertext. Expired access is allowed only for
    explicit refresh followed by a new identity lookup. This is never API readiness
    or approval to publish. The object cannot be imported across a process restart;
    a fresh historical read is required in that process.
    """

    account_id: int
    account_key: str
    identity_digest: str = field(repr=False)
    channel_binding_digest: str = field(repr=False)
    revision: int
    reference: str = field(repr=False)
    grant_fingerprint: str = field(repr=False)
    bundle: TokenBundle = field(repr=False)
    issued_at: datetime
    expires_at: datetime
    purpose: str = "REVALIDATION_ONLY"
    _nonce: str = field(default="", repr=False)
    _signature: bytes = field(default=b"", repr=False)
    _seal: object = field(default=None, repr=False, compare=False)

    def _payload(self) -> bytes:
        return json.dumps([
            self.account_id, self.account_key, self.identity_digest, self.channel_binding_digest,
            self.revision, self.reference, self.grant_fingerprint,
            self.issued_at.isoformat(), self.expires_at.isoformat(), self.purpose, self._nonce,
        ], separators=(",", ":")).encode()

    def validate(self, account_id: int, *, expected_revision: int) -> None:
        from .identity import IDENTITY_LINK_SCOPES, grant_fingerprint

        try:
            if (
                type(account_id) is not int or self.account_id != account_id
                or self.account_key != f"youtube:{account_id}" or not account_key_valid(self.account_key)
                or type(expected_revision) is not int or self.revision != expected_revision
                or self._seal is not _HISTORICAL_SEAL or self.purpose != "REVALIDATION_ONLY"
                or not _REFERENCE.fullmatch(self.reference) or not _REFERENCE.fullmatch(self._nonce)
                or not all(re.fullmatch(r"[a-f0-9]{64}", value) for value in (
                    self.identity_digest, self.channel_binding_digest, self.grant_fingerprint,
                ))
                or self.issued_at > utcnow() or self.expires_at <= utcnow()
                or self.expires_at - self.issued_at != timedelta(minutes=5)
                or not isinstance(self._signature, bytes)
                or not hmac.compare_digest(self._signature, hmac.digest(_HISTORICAL_KEY, self._payload(), "sha256"))
            ):
                raise CredentialBoundaryError("account_mismatch")
            _synthetic(self.bundle, check_expiry=False)
            if (
                self.bundle.scopes != IDENTITY_LINK_SCOPES or self.bundle.refresh_token is None
                or not hmac.compare_digest(grant_fingerprint(self.bundle), self.grant_fingerprint)
            ):
                raise CredentialBoundaryError()
        except CredentialBoundaryError:
            raise
        except Exception:  # noqa: BLE001 - historical contents and tokens are never reflected
            raise CredentialBoundaryError() from None


def recover_production_lifecycle(sessions: sessionmaker[Session]) -> int:
    """Startup performs metadata quarantine only: no vault, network or browser access."""
    with sessions.begin() as session:
        changed = list(session.scalars(update(OAuthLifecycleOperation).where(
            OAuthLifecycleOperation.status.in_(("reserved", "writing", "verified", "recovering_unknown")),
        ).values(status="unknown", claim_id=None, updated_at=utcnow()).returning(OAuthLifecycleOperation)))
        for operation in changed:
            session.execute(update(OAuthConnection).where(
                OAuthConnection.account_id == operation.account_id,
                OAuthConnection.mode == _MODE,
                OAuthConnection.status == "credential_pending",
                OAuthConnection.revision == operation.expected_revision + 1,
            ).values(status="credential_unknown", error_code="credential_error",
                     revision=OAuthConnection.revision + 1, updated_at=utcnow()))
            account = session.get(PlatformAccount, operation.account_id)
            if account and f"{account.platform}:{account.id}" == operation.account_key:
                account.status, account.api_ready, account.connected_at = "not_connected", False, None
            session.add(AuditLog(level="warning", event="oauth_lifecycle_restart_quarantine", message=_AUDIT))
        return len(changed)


def expire_production_credentials(sessions: sessionmaker[Session]) -> int:
    """Expire connection metadata without constructing a vault or consulting a provider."""
    with sessions.begin() as session:
        changed = session.execute(update(OAuthConnection).where(
            OAuthConnection.mode == _MODE, OAuthConnection.status == "fake_connected",
            OAuthConnection.expires_at <= utcnow(),
        ).values(status="expired", error_code="expired",
                 revision=OAuthConnection.revision + 1, updated_at=utcnow()))
        return changed.rowcount


class SyntheticOAuthCredentialLifecycle:
    """An explicit fake-grant facade; recognisable synthetic values are mandatory.

    Receipts are produced by the identity adapter and sealed to account, client,
    channel, granted scopes and token fingerprint. They are not user assertions.
    Each rotated grant needs a fresh verified identity receipt before completion.
    """

    def __init__(
        self, sessions: sessionmaker[Session], vault: Any,
        *, checkpoint: Callable[[str], None] | None = None,
    ) -> None:
        # Import lazily so the blocked public facade needs no crypto construction.
        from .production_dpapi import SyntheticProductionCredentialVault

        if not isinstance(vault, SyntheticProductionCredentialVault):
            raise CredentialBoundaryError()
        self.sessions, self.vault = sessions, vault
        self._checkpoint = checkpoint or (lambda _stage: None)

    @staticmethod
    def _reference(value: str | None) -> str:
        if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
            raise CredentialBoundaryError()
        return value

    @staticmethod
    def _bundle(value: TokenBundle, *, check_expiry: bool = True) -> None:
        try:
            _synthetic(value, check_expiry=check_expiry)
        except Exception:  # noqa: BLE001 - redact validation details and credential values
            raise CredentialBoundaryError() from None

    @staticmethod
    def _receipt(identity: Any, key: str, bundle: TokenBundle | None = None) -> str:
        from .identity import VerifiedIdentity

        if not isinstance(identity, VerifiedIdentity) or identity.synthetic is not True:
            raise CredentialBoundaryError("account_mismatch")
        try:
            digest = identity.digest(key)
            if bundle is not None:
                identity.validate_bundle(key, bundle)
        except Exception:  # noqa: BLE001 - identity mismatch must not print account or tokens
            raise CredentialBoundaryError("account_mismatch") from None
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise CredentialBoundaryError("account_mismatch")
        return digest

    @staticmethod
    def _account(session: Session, account_id: int) -> tuple[PlatformAccount, OAuthConnection]:
        if type(account_id) is not int or not 1 <= account_id < 2**63:
            raise CredentialBoundaryError("account_mismatch")
        account = session.get(PlatformAccount, account_id)
        if not account or account.platform != "youtube" or not account_key_valid(f"youtube:{account.id}"):
            raise CredentialBoundaryError("account_mismatch")
        session.execute(insert(OAuthConnection).values(
            account_id=account_id, status="unprepared", mode="offline", revision=1,
            error_code=None, expires_at=None, updated_at=utcnow(),
        ).on_conflict_do_nothing(index_elements=["account_id"]))
        return account, session.get(OAuthConnection, account_id)

    @staticmethod
    def _binding(
        session: Session, account: PlatformAccount, digest: str, *, create: bool,
        channel_binding_digest: str | None = None,
    ) -> None:
        key = f"{account.platform}:{account.id}"
        binding = session.get(OAuthIdentityBinding, account.id)
        if binding is None and create:
            if not isinstance(channel_binding_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", channel_binding_digest):
                raise CredentialBoundaryError("account_mismatch")
            session.add(OAuthIdentityBinding(account_id=account.id, account_key=key,
                                             identity_digest=digest, channel_binding_digest=channel_binding_digest,
                                             mode="synthetic"))
        elif not binding or binding.account_key != key or binding.mode != "synthetic" or not hmac.compare_digest(
            binding.identity_digest, digest,
        ):
            raise CredentialBoundaryError("account_mismatch")

    @staticmethod
    def _operation(
        session: Session, reservation: LifecycleReservation, *, allowed: tuple[str, ...],
    ) -> OAuthLifecycleOperation:
        operation = session.get(OAuthLifecycleOperation, reservation.operation_id)
        if (
            not operation or operation.account_id != reservation.account_id
            or operation.account_key != reservation.account_key
            or operation.identity_digest != reservation.identity_digest
            or operation.expected_revision + 1 != reservation.revision
            or operation.old_reference != reservation.old_reference
            or operation.new_reference != reservation.new_reference
            or operation.claim_id != reservation.claim_id or operation.status not in allowed
        ):
            raise CredentialBoundaryError("revision_conflict")
        return operation

    def reserve(
        self, account_id: int, identity: Any, *, operation: str, expected_revision: int,
    ) -> LifecycleReservation:
        """Journal new reference before first ciphertext write; no external call occurs."""
        return self._reserve(account_id, identity, operation=operation, expected_revision=expected_revision)

    def reserve_for_revalidation(self, historical: HistoricalCredential) -> LifecycleReservation:
        """Reserve one explicit historical refresh; pending/unknown outcomes forbid reuse."""
        if type(historical) is not HistoricalCredential:
            raise CredentialBoundaryError()
        historical.validate(historical.account_id, expected_revision=historical.revision)
        return self._reserve(historical.account_id, historical, operation="replace",
                             expected_revision=historical.revision, historical=True)

    def _reserve(
        self, account_id: int, identity: Any, *, operation: str, expected_revision: int,
        historical: bool = False,
    ) -> LifecycleReservation:
        if operation not in {"store", "replace", "revoke"} or type(expected_revision) is not int:
            raise CredentialBoundaryError()
        try:
            with self.sessions.begin() as session:
                account, connection = self._account(session, account_id)
                key = f"youtube:{account.id}"
                if historical:
                    if type(identity) is not HistoricalCredential or operation != "replace":
                        raise CredentialBoundaryError()
                    identity.validate(account_id, expected_revision=expected_revision)
                    binding = session.get(OAuthIdentityBinding, account_id)
                    if (
                        connection.mode != _MODE or connection.status not in {"fake_connected", "expired"}
                        or account.credential_ref != identity.reference
                        or tuple(account.scopes) != identity.bundle.scopes
                        or not binding or binding.grant_fingerprint != identity.grant_fingerprint
                        or binding.channel_binding_digest != identity.channel_binding_digest
                    ):
                        raise CredentialBoundaryError("revision_conflict")
                    digest, channel_digest = identity.identity_digest, identity.channel_binding_digest
                else:
                    digest = self._receipt(identity, key)
                    channel_digest = hashlib.sha256(
                        ("NewsFlowAI:channel-binding:" + identity.client_id + ":" + identity.channel_id).encode()
                    ).hexdigest()
                if connection.revision != expected_revision:
                    raise CredentialBoundaryError("revision_conflict")
                if connection.status in {"credential_pending", "credential_unknown"}:
                    raise CredentialBoundaryError("outcome_unknown")
                if operation == "store":
                    if account.credential_ref:
                        raise CredentialBoundaryError("revision_conflict")
                elif not account.credential_ref or connection.mode != _MODE or connection.status not in {
                    "fake_connected", "expired", "error",
                }:
                    raise CredentialBoundaryError("revision_conflict")
                if account.credential_ref:
                    self._reference(account.credential_ref)
                self._binding(session, account, digest, create=operation == "store", channel_binding_digest=channel_digest)
                changed = session.execute(update(OAuthConnection).where(
                    OAuthConnection.account_id == account.id,
                    OAuthConnection.revision == expected_revision,
                ).values(status="credential_pending", mode=_MODE, expires_at=None, error_code=None,
                         revision=expected_revision + 1, updated_at=utcnow()))
                if changed.rowcount != 1:
                    raise CredentialBoundaryError("revision_conflict")
                operation_id, claim_id = uuid4().hex, uuid4().hex
                # Reference allocation creates no file and does not access credentials.
                reference = None if operation == "revoke" else self._reference(self.vault.reserve_reference())
                if reference == account.credential_ref and reference is not None:
                    raise CredentialBoundaryError()
                session.add(OAuthLifecycleOperation(
                    id=operation_id, account_id=account.id, account_key=key, identity_digest=digest,
                    operation=operation, expected_revision=expected_revision,
                    old_reference=account.credential_ref, new_reference=reference,
                    status="reserved", claim_id=claim_id,
                ))
                account.status, account.api_ready, account.connected_at = "not_connected", False, None
                result = LifecycleReservation(operation_id, account.id, key, digest, expected_revision + 1,
                                              account.credential_ref, reference, claim_id)
            self._checkpoint("reference_reserved")
            return result
        except CredentialBoundaryError:
            raise
        except Exception:  # noqa: BLE001 - sanitize database/concurrency failures
            raise CredentialBoundaryError() from None

    def mark_unknown(self, reservation: LifecycleReservation) -> None:
        self._finish_failure(reservation, unknown=True)

    def mark_error(self, reservation: LifecycleReservation) -> None:
        self._finish_failure(reservation, unknown=False)

    def _finish_failure(self, reservation: LifecycleReservation, *, unknown: bool) -> None:
        with self.sessions.begin() as session:
            operation = self._operation(session, reservation, allowed=("reserved", "writing", "verified"))
            changed = session.execute(update(OAuthConnection).where(
                OAuthConnection.account_id == reservation.account_id,
                OAuthConnection.mode == _MODE,
                OAuthConnection.revision == reservation.revision,
                OAuthConnection.status == "credential_pending",
            ).values(status="credential_unknown" if unknown else "error", error_code="credential_error",
                     revision=OAuthConnection.revision + 1, updated_at=utcnow()))
            if changed.rowcount != 1:
                raise CredentialBoundaryError("revision_conflict")
            operation.status, operation.claim_id, operation.updated_at = (
                "unknown" if unknown else "error", None, utcnow(),
            )
            session.add(AuditLog(level="warning", event="oauth_lifecycle_outcome_unknown" if unknown
                                 else "oauth_lifecycle_failed", message=_AUDIT))

    def complete(
        self, reservation: LifecycleReservation, bundle: TokenBundle | None = None, *, identity: Any,
    ) -> str | None:
        """Write, read-verify, then switch the SQLite pointer with revision CAS."""
        claimed = False
        try:
            if not isinstance(reservation, LifecycleReservation):
                raise CredentialBoundaryError()
            if self._receipt(identity, reservation.account_key, bundle) != reservation.identity_digest:
                raise CredentialBoundaryError("account_mismatch")
            with self.sessions.begin() as session:
                operation = self._operation(session, reservation, allowed=("reserved",))
                deleting = operation.operation == "revoke"
                if deleting != (bundle is None):
                    raise CredentialBoundaryError()
                if not deleting:
                    self._bundle(bundle)
                operation.status, operation.updated_at = "writing", utcnow()
            claimed = True
            self._checkpoint("write_claimed")
            if not deleting:
                self.vault.write_reserved(reservation.account_key, reservation.identity_digest,
                                          reservation.new_reference, bundle,
                                          operation_id=reservation.operation_id)
                self._checkpoint("ciphertext_written")
                stored = self.vault.load(reservation.account_key, reservation.identity_digest,
                                         reservation.new_reference)
                self._bundle(stored)
                self._receipt(identity, reservation.account_key, stored)
                if (
                    not hmac.compare_digest(stored.access_token.get_secret_value(), bundle.access_token.get_secret_value())
                    or stored.refresh_token != bundle.refresh_token or stored.scopes != bundle.scopes
                    or stored.expires_at != bundle.expires_at
                ):
                    raise CredentialBoundaryError()
            with self.sessions.begin() as session:
                operation = self._operation(session, reservation, allowed=("writing",))
                operation.status, operation.updated_at = "verified", utcnow()
            self._checkpoint("ciphertext_verified")
            with self.sessions.begin() as session:
                operation = self._operation(session, reservation, allowed=("verified",))
                account, _connection = self._account(session, reservation.account_id)
                self._binding(session, account, reservation.identity_digest, create=False)
                if account.credential_ref != reservation.old_reference:
                    raise CredentialBoundaryError("revision_conflict")
                changed = session.execute(update(OAuthConnection).where(
                    OAuthConnection.account_id == account.id,
                    OAuthConnection.mode == _MODE,
                    OAuthConnection.revision == reservation.revision,
                    OAuthConnection.status == "credential_pending",
                ).values(status="revoked" if deleting else "fake_connected", error_code=None,
                         expires_at=None if deleting else bundle.expires_at,
                         revision=OAuthConnection.revision + 1, updated_at=utcnow()))
                if changed.rowcount != 1:
                    raise CredentialBoundaryError("revision_conflict")
                account.credential_ref = reservation.new_reference
                account.scopes = [] if deleting else list(bundle.scopes)
                account.status, account.api_ready, account.connected_at = "not_connected", False, None
                binding = session.get(OAuthIdentityBinding, account.id)
                if deleting:
                    binding.grant_fingerprint = None
                else:
                    from .identity import grant_fingerprint

                    binding.grant_fingerprint = grant_fingerprint(bundle)
                operation.status, operation.claim_id, operation.updated_at = "committed", None, utcnow()
                session.add(AuditLog(level="info", event="oauth_synthetic_pointer_committed", message=_AUDIT))
            self._checkpoint("database_committed")
            self._cleanup_committed(reservation.operation_id)
            return reservation.new_reference
        except CredentialBoundaryError:
            if claimed:
                self._best_effort_quarantine(reservation)
            raise
        except Exception:  # noqa: BLE001 - BaseException leaves a deliberate crash-recoverable journal
            if claimed:
                self._best_effort_quarantine(reservation)
            raise CredentialBoundaryError() from None

    def _best_effort_quarantine(self, reservation: LifecycleReservation) -> None:
        try:
            self.mark_unknown(reservation)
        except CredentialBoundaryError:
            # CAS loss/committed work must not be overwritten by an outdated writer.
            return
        except Exception:  # noqa: BLE001 - retain durable pending metadata if DB itself is unavailable
            return

    def store(self, account_id: int, identity: Any, bundle: TokenBundle, *, expected_revision: int) -> str:
        self._bundle(bundle)
        self._receipt(identity, f"youtube:{account_id}", bundle)
        reservation = self.reserve(account_id, identity, operation="store", expected_revision=expected_revision)
        return self.complete(reservation, bundle, identity=identity)

    def replace(self, account_id: int, identity: Any, bundle: TokenBundle, *, expected_revision: int) -> str:
        self._bundle(bundle)
        self._receipt(identity, f"youtube:{account_id}", bundle)
        reservation = self.reserve(account_id, identity, operation="replace", expected_revision=expected_revision)
        return self.complete(reservation, bundle, identity=identity)

    def revoke(self, account_id: int, identity: Any, *, expected_revision: int) -> None:
        """Local synthetic revoke only; this never calls a provider revocation endpoint."""
        reservation = self.reserve(account_id, identity, operation="revoke", expected_revision=expected_revision)
        self.complete(reservation, identity=identity)

    def load_for_revalidation(self, account_id: int, *, expected_revision: int) -> HistoricalCredential:
        """Explicit restart/expiry read using durable trust, never fresh identity approval.

        The caller must reserve this exact revision before attempting a refresh and
        obtain a fresh verified identity for the resulting grant before committing.
        Unknown or failed operations cannot use this entry point as a retry route.
        """
        from .identity import IDENTITY_LINK_SCOPES, grant_fingerprint

        revision = None
        try:
            with self.sessions.begin() as session:
                account, connection = self._account(session, account_id)
                key, revision = f"youtube:{account.id}", connection.revision
                binding = session.get(OAuthIdentityBinding, account_id)
                if (
                    type(expected_revision) is not int or revision != expected_revision
                    or connection.mode != _MODE or connection.status not in {"fake_connected", "expired"}
                    or not binding or binding.account_key != key or binding.mode != "synthetic"
                    or not binding.grant_fingerprint
                    or tuple(account.scopes) != IDENTITY_LINK_SCOPES
                ):
                    raise CredentialBoundaryError("outcome_unknown")
                reference = self._reference(account.credential_ref)
                digest, channel_digest, fingerprint = (
                    binding.identity_digest, binding.channel_binding_digest, binding.grant_fingerprint,
                )
                expires_at = connection.expires_at
            value = self.vault.load(key, digest, reference, allow_expired=True)
            self._bundle(value, check_expiry=False)
            if (
                value.scopes != IDENTITY_LINK_SCOPES or value.refresh_token is None
                or value.expires_at != expires_at
                or not hmac.compare_digest(grant_fingerprint(value), fingerprint)
            ):
                raise ValueError
            with self.sessions() as session:
                account, connection = session.get(PlatformAccount, account_id), session.get(OAuthConnection, account_id)
                binding = session.get(OAuthIdentityBinding, account_id)
                if (
                    not account or not connection or not binding or f"youtube:{account.id}" != key
                    or account.credential_ref != reference or tuple(account.scopes) != IDENTITY_LINK_SCOPES
                    or connection.revision != revision or connection.mode != _MODE
                    or connection.status not in {"fake_connected", "expired"} or connection.expires_at != expires_at
                    or binding.account_key != key or binding.mode != "synthetic"
                    or binding.identity_digest != digest or binding.channel_binding_digest != channel_digest
                    or binding.grant_fingerprint != fingerprint
                ):
                    raise CredentialBoundaryError("revision_conflict")
            instant = utcnow()
            values = {"account_id": account_id, "account_key": key, "identity_digest": digest,
                          "channel_binding_digest": channel_digest, "revision": revision, "reference": reference,
                          "grant_fingerprint": fingerprint, "bundle": value.model_copy(deep=True),
                          "issued_at": instant, "expires_at": instant + timedelta(minutes=5),
                          "_nonce": uuid4().hex, "_seal": _HISTORICAL_SEAL}
            unsigned = HistoricalCredential(**values)
            result = HistoricalCredential(**values, _signature=hmac.digest(_HISTORICAL_KEY, unsigned._payload(), "sha256"))
            result.validate(account_id, expected_revision=revision)
            return result
        except CredentialBoundaryError:
            raise
        except Exception:  # noqa: BLE001 - expired synthetic grants and corrupted files never leak
            if revision is not None:
                with self.sessions.begin() as session:
                    session.execute(update(OAuthConnection).where(
                        OAuthConnection.account_id == account_id,
                        OAuthConnection.mode == _MODE, OAuthConnection.revision == revision,
                        OAuthConnection.status.in_(("fake_connected", "expired")),
                    ).values(status="error", error_code="credential_error",
                             revision=revision + 1, updated_at=utcnow()))
            raise CredentialBoundaryError() from None

    def load(self, account_id: int, identity: Any, *, allow_expired: bool = False) -> TokenBundle:
        revision = None
        try:
            with self.sessions.begin() as session:
                account, connection = self._account(session, account_id)
                key, digest = f"youtube:{account.id}", self._receipt(identity, f"youtube:{account.id}")
                self._binding(session, account, digest, create=False)
                allowed = {"fake_connected", "expired"} if allow_expired else {"fake_connected"}
                if connection.mode != _MODE or connection.status not in allowed:
                    raise CredentialBoundaryError("outcome_unknown")
                reference, revision = self._reference(account.credential_ref), connection.revision
            value = self.vault.load(key, digest, reference, allow_expired=True)
            self._bundle(value, check_expiry=False)
            if value.expires_at <= utcnow() and not allow_expired:
                with self.sessions.begin() as session:
                    session.execute(update(OAuthConnection).where(
                        OAuthConnection.account_id == account_id,
                        OAuthConnection.mode == _MODE, OAuthConnection.revision == revision,
                    ).values(status="expired", error_code="expired", revision=revision + 1, updated_at=utcnow()))
                raise CredentialBoundaryError()
            try:
                self._receipt(identity, key, value)
            except CredentialBoundaryError:
                with self.sessions.begin() as session:
                    session.execute(update(OAuthConnection).where(
                        OAuthConnection.account_id == account_id,
                        OAuthConnection.mode == _MODE, OAuthConnection.revision == revision,
                    ).values(status="error", error_code="credential_error",
                             revision=revision + 1, updated_at=utcnow()))
                raise
            with self.sessions() as session:
                account, connection = session.get(PlatformAccount, account_id), session.get(OAuthConnection, account_id)
                if (
                    not account or not connection or account.credential_ref != reference
                    or f"youtube:{account.id}" != key or connection.mode != _MODE
                    or connection.status not in allowed or connection.revision != revision
                ):
                    raise CredentialBoundaryError("revision_conflict")
                self._binding(session, account, digest, create=False)
            return value
        except CredentialBoundaryError:
            raise
        except Exception:  # noqa: BLE001 - missing/corrupt backend is never a successful connection
            if revision is not None:
                with self.sessions.begin() as session:
                    session.execute(update(OAuthConnection).where(
                        OAuthConnection.account_id == account_id,
                        OAuthConnection.mode == _MODE, OAuthConnection.revision == revision,
                    ).values(status="error", error_code="credential_error",
                             revision=revision + 1, updated_at=utcnow()))
            raise CredentialBoundaryError() from None

    def _ciphertext_delete(
        self, session: Session, operation: OAuthLifecycleOperation, reference: str | None,
        *, original_operation: str,
    ) -> None:
        if reference is None:
            return
        self._reference(reference)
        # This transaction acquires the SQLite write lock before filesystem cleanup.
        # No concurrent lifecycle transaction can change a pointer until commit.
        if session.scalar(select(PlatformAccount.id).where(PlatformAccount.credential_ref == reference)):
            raise CredentialBoundaryError("revision_conflict")
        self._pending_delete(session, operation, reference, original_operation=original_operation, allow_active=False)
        evidence = next((item for item in self.vault.inventory() if item.reference == reference), None)
        if evidence is None:
            if self.vault.reference_exists(reference):
                # Corrupt/foreign ciphertext never becomes an implicitly absent file.
                raise CredentialBoundaryError()
            return
        if (
            evidence.account_key != operation.account_key or evidence.identity_digest != operation.identity_digest
            or evidence.operation_id != original_operation
        ):
            raise CredentialBoundaryError("account_mismatch")
        self.vault.cleanup_orphan(reference, operation.account_key, operation.identity_digest,
                                  expected_file_digest=evidence.file_digest,
                                  expected_operation_id=original_operation)

    def _pending_delete(
        self, session: Session, operation: OAuthLifecycleOperation, reference: str | None,
        *, original_operation: str, allow_active: bool,
    ) -> None:
        """Delete only authenticated writer-owned temporary files, preserving final files."""
        if reference is None:
            return
        active_accounts = list(session.scalars(select(PlatformAccount.id).where(
            PlatformAccount.credential_ref == reference,
        )))
        if active_accounts and (not allow_active or active_accounts != [operation.account_id]):
            raise CredentialBoundaryError("revision_conflict")
        for evidence in self.vault.pending_inventory():
            if evidence.reference != reference:
                continue
            if (
                evidence.account_key != operation.account_key or evidence.identity_digest != operation.identity_digest
                or evidence.operation_id != original_operation or evidence.pending_filename is None
            ):
                raise CredentialBoundaryError("account_mismatch")
            self.vault.cleanup_pending(evidence.pending_filename, operation.account_key, operation.identity_digest,
                                       evidence.file_digest, original_operation)

    def _cleanup_committed(self, operation_id: str) -> None:
        claim = uuid4().hex
        try:
            with self.sessions.begin() as session:
                changed = session.execute(update(OAuthLifecycleOperation).where(
                    OAuthLifecycleOperation.id == operation_id,
                    OAuthLifecycleOperation.status.in_(("committed", "committed_cleanup_pending", "cleaning")),
                ).values(status="cleaning", claim_id=claim, updated_at=utcnow()))
                if changed.rowcount != 1:
                    raise CredentialBoundaryError("revision_conflict")
                operation = session.get(OAuthLifecycleOperation, operation_id)
                account = session.get(PlatformAccount, operation.account_id)
                if not account or f"youtube:{account.id}" != operation.account_key:
                    raise CredentialBoundaryError("account_mismatch")
                self._binding(session, account, operation.identity_digest, create=False)
                self._pending_delete(session, operation, operation.new_reference,
                                     original_operation=operation.id, allow_active=True)
                if operation.old_reference:
                    prior = session.scalar(select(OAuthLifecycleOperation).where(
                        OAuthLifecycleOperation.account_id == operation.account_id,
                        OAuthLifecycleOperation.account_key == operation.account_key,
                        OAuthLifecycleOperation.identity_digest == operation.identity_digest,
                        OAuthLifecycleOperation.new_reference == operation.old_reference,
                        OAuthLifecycleOperation.status.in_(("committed", "cleaned", "committed_cleanup_pending", "cleaning")),
                    ))
                    if not prior:
                        raise CredentialBoundaryError("account_mismatch")
                    self._ciphertext_delete(session, operation, operation.old_reference, original_operation=prior.id)
                self._checkpoint("old_ciphertext_cleaned")
                operation.status, operation.claim_id, operation.updated_at = "cleaned", None, utcnow()
        except Exception:  # noqa: BLE001 - cleanup cannot replace a committed pointer or reveal backend values
            with self.sessions.begin() as session:
                operation = session.get(OAuthLifecycleOperation, operation_id)
                if operation and operation.status in {"committed", "committed_cleanup_pending", "cleaning"}:
                    operation.status, operation.claim_id, operation.updated_at = "committed_cleanup_pending", None, utcnow()
                    session.execute(update(OAuthConnection).where(
                        OAuthConnection.account_id == operation.account_id,
                        OAuthConnection.mode == _MODE,
                        OAuthConnection.revision == operation.expected_revision + 2,
                        OAuthConnection.status.in_(("fake_connected", "revoked")),
                    ).values(status="credential_unknown", error_code="credential_error",
                             revision=OAuthConnection.revision + 1, updated_at=utcnow()))
            raise CredentialBoundaryError() from None

    def recover(self) -> int:
        """Explicit ciphertext recovery; ambiguous operations stay blocked after cleanup."""
        with self.sessions() as session:
            snapshots = list(session.scalars(select(OAuthLifecycleOperation).where(
                OAuthLifecycleOperation.status.in_((*_PENDING, "committed", "committed_cleanup_pending", "cleaning")),
            ).order_by(OAuthLifecycleOperation.created_at)))
        self._checkpoint("recovery_snapshot")
        recovered = 0
        for snapshot in snapshots:
            if snapshot.status in {"committed", "committed_cleanup_pending", "cleaning"}:
                try:
                    self._cleanup_committed(snapshot.id)
                except CredentialBoundaryError:
                    continue
                recovered += 1
                continue
            claim = uuid4().hex
            with self.sessions.begin() as session:
                changed = session.execute(update(OAuthLifecycleOperation).where(
                    OAuthLifecycleOperation.id == snapshot.id,
                    OAuthLifecycleOperation.status == snapshot.status,
                    OAuthLifecycleOperation.claim_id == snapshot.claim_id,
                    OAuthLifecycleOperation.new_reference == snapshot.new_reference,
                    OAuthLifecycleOperation.old_reference == snapshot.old_reference,
                ).values(status="recovering_unknown", claim_id=claim, updated_at=utcnow()))
                if changed.rowcount != 1:
                    continue
                session.execute(update(OAuthConnection).where(
                    OAuthConnection.account_id == snapshot.account_id,
                    OAuthConnection.mode == _MODE,
                    OAuthConnection.status == "credential_pending",
                    OAuthConnection.revision == snapshot.expected_revision + 1,
                ).values(status="credential_unknown", error_code="credential_error",
                         revision=OAuthConnection.revision + 1, updated_at=utcnow()))
            self._checkpoint("recovery_claimed")
            try:
                with self.sessions.begin() as session:
                    # The claim is matched again under the write lock before deleting.
                    changed = session.execute(update(OAuthLifecycleOperation).where(
                        OAuthLifecycleOperation.id == snapshot.id,
                        OAuthLifecycleOperation.status == "recovering_unknown",
                        OAuthLifecycleOperation.claim_id == claim,
                    ).values(updated_at=utcnow()))
                    if changed.rowcount != 1:
                        continue
                    current = session.get(OAuthLifecycleOperation, snapshot.id)
                    account = session.get(PlatformAccount, current.account_id)
                    if not account or f"youtube:{account.id}" != current.account_key:
                        raise CredentialBoundaryError("account_mismatch")
                    self._binding(session, account, current.identity_digest, create=False)
                    self._ciphertext_delete(session, current, current.new_reference, original_operation=current.id)
                    self._checkpoint("recovery_ciphertext_cleaned")
                    current.status, current.claim_id, current.updated_at = "recovered_unknown", None, utcnow()
            except Exception:  # noqa: BLE001 - foreign/tampered files remain untouched and unresolved
                with self.sessions.begin() as session:
                    session.execute(update(OAuthLifecycleOperation).where(
                        OAuthLifecycleOperation.id == snapshot.id,
                        OAuthLifecycleOperation.status == "recovering_unknown",
                        OAuthLifecycleOperation.claim_id == claim,
                    ).values(status="cleanup_pending", claim_id=None, updated_at=utcnow()))
            recovered += 1
        return recovered

    def scan_orphans(self) -> dict[str, int]:
        """Report counts only. Inventory does not delete unknown or current ciphertext."""
        counts = {"owned_inactive": 0, "active": 0, "unowned": 0}
        with self.sessions() as session:
            active = set(session.scalars(select(PlatformAccount.credential_ref).where(
                PlatformAccount.credential_ref.is_not(None),
            )))
            operations = {item.id: item for item in session.scalars(select(OAuthLifecycleOperation))}
        for item in (*self.vault.inventory(), *self.vault.pending_inventory()):
            operation = operations.get(item.operation_id)
            if item.reference in active:
                counts["active"] += 1
            elif (
                operation and item.reference == operation.new_reference
                and operation.account_key == item.account_key and operation.identity_digest == item.identity_digest
            ):
                counts["owned_inactive"] += 1
            else:
                counts["unowned"] += 1
        return counts

    def cleanup_orphans(self) -> int:
        """Revisit operation-owned late writes after a recovery already quarantined them.

        A writer can die or lose its claim after recovery observes an absent file.
        Only a previously recovered/blocked operation is eligible; arbitrary vault
        inventory, active pointers and healthy committed rotations are excluded.
        """
        with self.sessions() as session:
            snapshots = list(session.scalars(select(OAuthLifecycleOperation).where(
                OAuthLifecycleOperation.status == "recovered_unknown",
                OAuthLifecycleOperation.new_reference.is_not(None),
            )))
        cleaned = 0
        for snapshot in snapshots:
            try:
                with self.sessions.begin() as session:
                    changed = session.execute(update(OAuthLifecycleOperation).where(
                        OAuthLifecycleOperation.id == snapshot.id,
                        OAuthLifecycleOperation.status == "recovered_unknown",
                        OAuthLifecycleOperation.new_reference == snapshot.new_reference,
                    ).values(updated_at=utcnow()))
                    if changed.rowcount != 1:
                        continue
                    current = session.get(OAuthLifecycleOperation, snapshot.id)
                    account = session.get(PlatformAccount, current.account_id)
                    if not account or f"youtube:{account.id}" != current.account_key:
                        raise CredentialBoundaryError("account_mismatch")
                    self._binding(session, account, current.identity_digest, create=False)
                    existed = self.vault.reference_exists(current.new_reference) or any(
                        item.reference == current.new_reference for item in self.vault.pending_inventory()
                    )
                    self._ciphertext_delete(session, current, current.new_reference, original_operation=current.id)
                    if existed:
                        cleaned += 1
            except Exception:  # noqa: BLE001 - corrupt/unowned files are left for explicit review
                with self.sessions.begin() as session:
                    session.add(AuditLog(level="warning", event="oauth_orphan_cleanup_blocked", message=_AUDIT))
                continue
        return cleaned
