"""Metadata-only GUI service and explicitly fake-only token lifecycle transactions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import AuditLog, OAuthConnection, PlatformAccount, utcnow
from newsflow.publishing.auth import TokenBundle

from .contracts import FIXED_REDIRECT, YOUTUBE_UPLOAD_SCOPE, OAuthBlocked, OAuthError
from .providers import FakeOAuthProvider, OAuthProvider
from .session import OAuthCallbackValidator, OAuthRequest, OAuthSessionStore
from .vault import CredentialVault, VaultError


def _ensure(session: Session, account_id: int) -> tuple[PlatformAccount, OAuthConnection]:
    account = session.get(PlatformAccount, account_id)
    if not account or account.platform not in {"youtube", "instagram"}:
        raise OAuthError("invalid_input")
    session.execute(
        insert(OAuthConnection).values(
            account_id=account_id, status="unprepared", mode="offline", revision=1,
            expires_at=None, error_code=None, updated_at=utcnow(),
        ).on_conflict_do_nothing(index_elements=["account_id"])
    )
    return account, session.get(OAuthConnection, account_id)


class AccountConnectionService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def _prepare(self, account_id: int, status: str) -> None:
        with self.sessions.begin() as session:
            _account, connection = _ensure(session, account_id)
            connection.status, connection.error_code = status, None
            connection.revision += 1
            connection.updated_at = utcnow()
            # This records intent only: no vault access, provider call, revocation or login.
            session.add(AuditLog(level="info", event="oauth_preparation", message=
                                 "로컬 계정 연결 준비" if status == "prepared" else "로컬 계정 해제 준비"))

    def prepare(self, account_id: int) -> None:
        self._prepare(account_id, "prepared")

    def disconnect_prepare(self, account_id: int) -> None:
        self._prepare(account_id, "disconnect_prepared")

    def blocked_start(self, account_id: int) -> None:
        raise OAuthBlocked()

    def cards(self) -> list[dict]:
        with self.sessions() as session:
            result = []
            for account in session.scalars(select(PlatformAccount).order_by(PlatformAccount.id.desc())):
                connection = session.get(OAuthConnection, account.id)
                result.append({
                    "id": account.id, "platform": account.platform, "label": account.label,
                    "account_type": account.account_type, "status": account.status,
                    "connection_status": connection.status if connection else "unprepared",
                    "mode": "FAKE" if connection and connection.mode == "fake" else "OFFLINE/BLOCKED",
                    "error_message": str(OAuthError(connection.error_code))
                    if connection and connection.error_code else "",
                    "expires_at": connection.expires_at if connection else None,
                    "permissions": (YOUTUBE_UPLOAD_SCOPE,) if account.platform == "youtube" else (),
                    "permissions_verified": account.platform == "youtube",
                    "can_connect": False, "token_exposed": False,
                })
            return result


class TokenLifecycleManager:
    """Explicit developer/test operations only; never reachable from the GUI."""

    def __init__(self, sessions: sessionmaker[Session], vault: CredentialVault, store: OAuthSessionStore) -> None:
        self.sessions, self.vault, self.store = sessions, vault, store
        self.validator = OAuthCallbackValidator(store)

    def _snapshot(self, account_id: int) -> dict:
        with self.sessions.begin() as session:
            account, connection = _ensure(session, account_id)
            if account.credential_ref and connection.mode != "fake":
                raise OAuthBlocked()
            return {
                "account_id": account.id, "key": f"{account.platform}:{account.id}",
                "reference": account.credential_ref, "revision": connection.revision,
                "status": connection.status, "mode": connection.mode,
                "expires_at": connection.expires_at,
            }

    def _error(self, snapshot: dict, code: str) -> None:
        safe = OAuthError(code)
        with self.sessions.begin() as session:
            # Uncorrelated/replayed callbacks must not alter another account or invalidate
            # a healthy existing connection. They only produce a fixed, secret-free audit.
            if code in {"reused", "account_mismatch", "redirect_mismatch", "state_mismatch", "callback_invalid"}:
                session.add(AuditLog(level="warning", event="oauth_callback_rejected", message=str(safe)))
                return
            changed = session.execute(
                update(OAuthConnection).where(
                    OAuthConnection.account_id == snapshot["account_id"],
                    OAuthConnection.revision == snapshot["revision"],
                ).values(
                    status=code if code in {"expired", "cancelled"} else "error",
                    error_code=safe.code, revision=OAuthConnection.revision + 1, updated_at=utcnow(),
                )
            )
            if changed.rowcount:
                session.add(AuditLog(level="warning", event="oauth_fake_error", message=str(safe)))

    @staticmethod
    def _fake(provider: OAuthProvider) -> None:
        if not isinstance(provider, FakeOAuthProvider) or provider.mode != "fake":
            raise OAuthBlocked()

    def _save(self, snapshot: dict, bundle: TokenBundle, scopes: tuple[str, ...]) -> None:
        if bundle.expires_at <= datetime.now(UTC):
            raise OAuthError("expired")
        if set(bundle.scopes) != set(scopes):
            raise OAuthError("scope_mismatch")
        new_reference = self.vault.store(snapshot["key"], bundle)
        try:
            with self.sessions.begin() as session:
                changed = session.execute(
                    update(OAuthConnection).where(
                        OAuthConnection.account_id == snapshot["account_id"],
                        OAuthConnection.revision == snapshot["revision"],
                    ).values(
                        status="fake_connected", mode="fake", expires_at=bundle.expires_at,
                        error_code=None, revision=OAuthConnection.revision + 1, updated_at=utcnow(),
                    )
                )
                if changed.rowcount != 1:
                    raise OAuthError("revision_conflict")
                account = session.get(PlatformAccount, snapshot["account_id"])
                if account.credential_ref != snapshot["reference"]:
                    raise OAuthError("revision_conflict")
                account.credential_ref, account.scopes = new_reference, list(bundle.scopes)
                account.status, account.api_ready, account.connected_at = "not_connected", False, None
                session.add(AuditLog(level="info", event="oauth_fake_connected", message=
                                     "합성 인증정보 교체 완료; 실제 계정 연결 아님"))
        except Exception:
            try:
                self.vault.delete(snapshot["key"], new_reference)
            except VaultError:
                pass
            raise
        if snapshot["reference"]:
            try:
                self.vault.delete(snapshot["key"], snapshot["reference"])
            except VaultError:
                self._error({**snapshot, "revision": snapshot["revision"] + 1}, "credential_error")
                raise OAuthError("credential_error") from None

    def complete_fake(
        self, account_id: int, request: OAuthRequest, params: Sequence[tuple[str, str]],
        provider: OAuthProvider, *, callback_uri: str = FIXED_REDIRECT, now: datetime | None = None,
    ) -> None:
        self._fake(provider)
        snapshot = self._snapshot(account_id)
        try:
            session, code = self.validator.consume(
                request.session_id, snapshot["key"], callback_uri, params, now=now,
            )
            expected_scopes = (YOUTUBE_UPLOAD_SCOPE,) if snapshot["key"].startswith("youtube:") else ()
            if set(session.scopes) != set(expected_scopes):
                raise OAuthError("scope_mismatch")
            self._save(snapshot, provider.exchange(code, session), session.scopes)
        except OAuthError as exc:
            self._error(snapshot, exc.code)
            raise
        except Exception:  # noqa: BLE001 - fail closed without reflecting secrets or provider errors
            self._error(snapshot, "credential_error")
            raise OAuthError("credential_error") from None

    def refresh_fake(self, account_id: int, provider: OAuthProvider) -> None:
        self._fake(provider)
        snapshot = self._snapshot(account_id)
        if snapshot["mode"] != "fake" or snapshot["status"] not in {"fake_connected", "expired"}:
            raise OAuthError("credential_error")
        try:
            old = self.vault.load(snapshot["key"], snapshot["reference"], allow_expired=True)
            self._save(snapshot, provider.refresh(old), old.scopes)
        except OAuthError as exc:
            self._error(snapshot, exc.code)
            raise
        except Exception:  # noqa: BLE001 - fail closed without reflecting secrets or provider errors
            self._error(snapshot, "credential_error")
            raise OAuthError("credential_error") from None

    def token_for_fake(self, account_id: int) -> TokenBundle:
        snapshot = self._snapshot(account_id)
        if snapshot["mode"] != "fake" or snapshot["status"] != "fake_connected":
            raise OAuthError("expired" if snapshot["status"] == "expired" else "credential_error")
        try:
            return self.vault.load(snapshot["key"], snapshot["reference"])
        except Exception:  # noqa: BLE001 - fail closed without reflecting secrets or provider errors
            code = "expired" if snapshot["expires_at"] and snapshot["expires_at"] <= utcnow() else "credential_error"
            self._error(snapshot, code)
            raise OAuthError(code) from None

    def disconnect_fake(self, account_id: int, provider: OAuthProvider) -> None:
        self._fake(provider)
        snapshot = self._snapshot(account_id)
        if snapshot["mode"] != "fake" or not snapshot["reference"]:
            raise OAuthError("credential_error")
        self.store.invalidate(snapshot["key"])
        try:
            bundle = self.vault.load(snapshot["key"], snapshot["reference"], allow_expired=True)
            with self.sessions.begin() as session:
                changed = session.execute(
                    update(OAuthConnection).where(
                        OAuthConnection.account_id == account_id,
                        OAuthConnection.revision == snapshot["revision"],
                    ).values(
                        status="revoked", error_code=None, expires_at=None,
                        revision=OAuthConnection.revision + 1, updated_at=utcnow(),
                    )
                )
                if changed.rowcount != 1:
                    raise OAuthError("revision_conflict")
                account = session.get(PlatformAccount, account_id)
                account.credential_ref, account.scopes = None, []
                account.status, account.api_ready, account.connected_at = "not_connected", False, None
                session.add(AuditLog(level="info", event="oauth_fake_revoked", message=
                                     "합성 인증정보 해제; 실제 서비스 회수 요청 없음"))
            provider.revoke(bundle)
            self.vault.delete(snapshot["key"], snapshot["reference"])
        except OAuthError:
            raise
        except Exception:  # noqa: BLE001 - fail closed without reflecting secrets or provider errors
            self._error({**snapshot, "revision": snapshot["revision"] + 1}, "credential_error")
            raise OAuthError("credential_error") from None
