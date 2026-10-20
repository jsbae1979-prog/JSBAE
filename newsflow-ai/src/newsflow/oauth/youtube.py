"""User-approved YouTube desktop connection using the existing OAuth/DPAPI kernels.

Construction and status reads never contact Google. Only explicit connection and
upload actions can exchange or refresh credentials. Failed or interrupted operations
are durable and are never replayed automatically.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import timedelta
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import select, update

from newsflow.db.models import (
    AppSetting,
    AuditLog,
    OAuthConnection,
    OAuthIdentityBinding,
    OAuthLifecycleOperation,
    PlatformAccount,
    utcnow,
)
from newsflow.intelligence.credentials import AIKeyStore, CredentialError
from newsflow.publishing.auth import TokenBundle

from .activation import youtube_operation
from .callback import CALLBACK_REJECTION_MESSAGES, CallbackError, LoopbackCallbackListener
from .identity import (
    IDENTITY_LINK_SCOPES,
    YouTubeHTTPSIdentityTransport,
    _channel_response,
    grant_fingerprint,
)
from .production import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    BrowserLaunchError,
    DesktopClientConfig,
    GoogleHTTPSOAuthTransport,
    GoogleOAuthProtocol,
    GoogleSystemBrowser,
    ProtocolError,
    _json_object,
    _safe_string,
)
from .production_dpapi import ProductionWindowsCredentialVault

MODE = "youtube_live"
_PENDING = ("authorizing", "exchanging", "refreshing")
_MESSAGES = {
    "consent_required": "Google 계정 연결 또는 게시 실행에 동의해 주세요.",
    "client_missing": "Google Desktop OAuth 클라이언트 파일을 먼저 등록해 주세요.",
    "client_changed": "Google 앱 설정이 변경되었습니다. 계정을 다시 연결해 주세요.",
    "pending": "이미 계정 연결 또는 인증 갱신이 진행 중입니다.",
    "not_connected": "YouTube 계정을 연결해 주세요.",
    "cancelled": "YouTube 연결을 취소했습니다.",
    "expired": "Google 인증이 만료되었습니다. 계정을 다시 연결해 주세요.",
    "permission_denied": "채널 조회와 업로드 권한을 모두 승인해 주세요.",
    "identity_mismatch": "연결한 YouTube 채널이 변경되었습니다. 새 계정으로 연결해 주세요.",
    "ambiguous_identity": "게시할 YouTube 채널 한 개를 확인하지 못했습니다.",
    "outcome_unknown": "인증 처리 결과를 확인하지 못했습니다. 자동으로 다시 요청하지 않습니다.",
    "connection_failed": "YouTube 연결에 실패했습니다. 계정과 Google 앱 설정을 확인해 주세요.",
    "callback_invalid": "Google 인증 응답을 안전하게 검증하지 못했습니다.",
    "callback_timeout": "Google 인증 응답 대기 시간이 만료되었습니다.",
    "port_conflict": "로컬 인증 응답 포트를 사용할 수 없습니다.",
    **{f"callback_{reason}": message for reason, message in CALLBACK_REJECTION_MESSAGES.items()},
}


class YouTubeConnectionError(Exception):
    def __init__(self, code: str = "connection_failed") -> None:
        self.code = code if code in _MESSAGES else "connection_failed"
        super().__init__(_MESSAGES[self.code])


class YouTubeClientStore(AIKeyStore):
    """Separate DPAPI file; never accept a client configuration from environment."""

    FILE = "youtube-desktop-client.dpapi"
    ENV = "NEWSFLOW_UNUSED_YOUTUBE_CLIENT"
    ENTROPY = b"NewsFlowAI:YouTube:desktop-client"

    @classmethod
    def validate(cls, value: str) -> str:
        if not isinstance(value, str) or not 0 < len(value.encode("utf-8")) <= 7000:
            raise CredentialError("Google Desktop OAuth 클라이언트 JSON 파일을 확인해 주세요.")
        DesktopClientConfig.from_json(value)
        return value

    def key(self) -> str:
        if not self.path.is_file() or self.path.is_symlink() or self.path.is_junction():
            raise YouTubeConnectionError("client_missing")
        return super().key()

    def status(self) -> dict:
        state = super().status()
        stored = self.path.is_file() and not self.path.is_symlink() and not self.path.is_junction()
        return {**state, "configured": stored, "stored": stored, "environment": False,
                "source": "stored" if stored else None}


def _setting(session: Any, key: str, value: str | None = None) -> str | None:
    row = session.get(AppSetting, key)
    if value is None:
        return row.value if row else None
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))
    return value


def _digest(*values: object) -> str:
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def _tokens(response: Any, previous: TokenBundle | None = None) -> tuple[TokenBundle, str | None]:
    """Apply the existing strict parser to the explicit two-scope desktop grant."""
    if response.status in {400, 401}:
        raise YouTubeConnectionError("expired")
    if response.status == 403:
        raise YouTubeConnectionError("permission_denied")
    GoogleOAuthProtocol._response_status(response)
    data = _json_object(response.body)
    if set(data) - {"access_token", "refresh_token", "expires_in", "scope", "token_type",
                    "refresh_token_expires_in"}:
        raise ProtocolError("response_invalid", outcome_unknown=True)
    lifetime = data.get("expires_in")
    if (data.get("token_type") != "Bearer" or not _safe_string(data.get("access_token"), maximum=4096)
            or type(lifetime) is not int or not 1 <= lifetime <= 86400):
        raise ProtocolError("response_invalid", outcome_unknown=True)
    scopes = data.get("scope")
    if scopes is None and previous is not None:
        scopes = " ".join(previous.scopes)
    if (not isinstance(scopes, str) or len(scopes.split()) != 2
            or set(scopes.split()) != set(IDENTITY_LINK_SCOPES)):
        raise YouTubeConnectionError("permission_denied")
    refresh = data.get("refresh_token")
    if refresh is None and previous is not None and previous.refresh_token:
        refresh = previous.refresh_token.get_secret_value()
    if not _safe_string(refresh, maximum=4096):
        raise ProtocolError("response_invalid", outcome_unknown=True)
    refresh_lifetime = data.get("refresh_token_expires_in")
    if refresh_lifetime is not None and (type(refresh_lifetime) is not int or not 1 <= refresh_lifetime <= 31536000):
        raise ProtocolError("response_invalid", outcome_unknown=True)
    return TokenBundle(
        access_token=SecretStr(data["access_token"]), refresh_token=SecretStr(refresh),
        expires_at=utcnow() + timedelta(seconds=lifetime), scopes=IDENTITY_LINK_SCOPES,
    ), (utcnow() + timedelta(seconds=refresh_lifetime)).isoformat() if refresh_lifetime else None


class YouTubeConnectionService:
    def __init__(
        self, sessions: Any, data_dir: Path, *, client_store: Any = None, vault: Any = None,
        token_transport: Any = None, identity_transport: Any = None, browser: Any = None,
        listener_factory: Any = None,
    ) -> None:
        self.sessions, self.data_dir = sessions, Path(data_dir)
        self.client_store = client_store if client_store is not None else YouTubeClientStore(self.data_dir)
        self.vault = vault if vault is not None else ProductionWindowsCredentialVault(self.data_dir / "youtube-oauth")
        self.tokens = token_transport if token_transport is not None else GoogleHTTPSOAuthTransport()
        self.identity = identity_transport if identity_transport is not None else YouTubeHTTPSIdentityTransport()
        self.browser = browser if browser is not None else GoogleSystemBrowser()
        self.listener_factory = listener_factory or LoopbackCallbackListener
        self._listeners: dict[int, Any] = {}
        self._workers: dict[int, threading.Thread] = {}
        # Authorization URLs contain state. Keep them only in memory, never in status/DB/logs.
        self._authorization_links: dict[int, tuple[int, SecretStr, float]] = {}
        self._lock = threading.RLock()

    def save_client(self, raw_json: str) -> None:
        config = DesktopClientConfig.from_json(raw_json)
        with self._lock:
            if any(worker.is_alive() for worker in self._workers.values()) or self.status()["pending"]:
                raise YouTubeConnectionError("pending")
            self.client_store.save(raw_json)
            with self.sessions.begin() as session:
                for connection in session.scalars(select(OAuthConnection).where(OAuthConnection.mode == MODE)):
                    prior = _setting(session, f"youtube.client.{connection.account_id}")
                    if prior and prior != config.client_id:
                        connection.status, connection.error_code = "error", "client_changed"
                        connection.updated_at = utcnow()
                        account = session.get(PlatformAccount, connection.account_id)
                        account.api_ready = False

    def _client(self) -> DesktopClientConfig:
        try:
            return DesktopClientConfig.from_json(self.client_store.key())
        except YouTubeConnectionError:
            raise
        except Exception:  # noqa: BLE001 - configuration and DPAPI errors must not expose secrets
            raise YouTubeConnectionError("client_missing") from None

    def accounts(self) -> list[dict]:
        with self.sessions() as session:
            rows = session.execute(select(PlatformAccount, OAuthConnection).join(
                OAuthConnection, PlatformAccount.id == OAuthConnection.account_id,
            ).where(PlatformAccount.platform == "youtube", OAuthConnection.mode == MODE)).all()
            return [{
                "id": account.id, "label": account.label,
                "channel_id": _setting(session, f"youtube.channel.{account.id}"),
                "status": connection.status, "ready": account.api_ready and connection.status == "connected",
                "error_code": connection.error_code,
                "message": _MESSAGES.get(connection.error_code, "Google 인증이 연결되었습니다."
                                        if connection.status == "connected" else "계정 연결을 확인해 주세요."),
                "expires_at": connection.expires_at,
                "refresh_needed": bool(connection.expires_at and connection.expires_at <= utcnow()),
            } for account, connection in rows]

    def status(self) -> dict:
        client = self.client_store.status()
        accounts = self.accounts()
        return {"client_configured": bool(client["configured"]),
                "storage_supported": bool(client["storage_supported"]),
                "pending": any(row["status"] in _PENDING for row in accounts), "accounts": accounts}

    def _start_record(self, account_id: int | None, client: DesktopClientConfig) -> tuple[int, str, int]:
        with self.sessions() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            if session.scalar(select(OAuthConnection.account_id).where(
                OAuthConnection.mode == MODE, OAuthConnection.status.in_(_PENDING),
            ).limit(1)) is not None:
                raise YouTubeConnectionError("pending")
            if account_id is None:
                account = PlatformAccount(platform="youtube", label="YouTube 연결 중", account_type="youtube_channel")
                session.add(account)
                session.flush()
                account_id = account.id
                connection = OAuthConnection(account_id=account_id, mode=MODE, revision=1)
                session.add(connection)
            else:
                account = session.get(PlatformAccount, account_id)
                connection = session.get(OAuthConnection, account_id)
                if not account or account.platform != "youtube" or not connection or connection.mode != MODE:
                    raise YouTubeConnectionError("not_connected")
                connection.revision += 1
            account.status, account.api_ready = "connecting", False
            connection.status, connection.error_code = "authorizing", None
            connection.updated_at = utcnow()
            revision = connection.revision
            operation_id = uuid4().hex
            session.add(OAuthLifecycleOperation(
                id=operation_id, account_id=account_id, account_key=f"youtube:{account_id}",
                identity_digest=_digest("pending", client.client_id, account_id), operation="youtube_connect",
                expected_revision=revision, old_reference=account.credential_ref, status="youtube_pending",
            ))
            session.commit()
            return account_id, operation_id, revision

    def begin(self, *, consent: bool = False, account_id: int | None = None) -> int:
        if consent is not True:
            raise YouTubeConnectionError("consent_required")
        client = self._client()
        with self._lock:
            account_id, operation_id, revision = self._start_record(account_id, client)
            listener = self.listener_factory()
            self._listeners[account_id] = listener
            try:
                with youtube_operation(consent=True):
                    deadline = monotonic() + 300
                    launch = listener.start(f"youtube:{account_id}", scopes=IDENTITY_LINK_SCOPES)
                    url = GOOGLE_AUTHORIZATION_ENDPOINT + "?" + urlencode({
                        "client_id": client.client_id, "redirect_uri": launch.redirect_uri,
                        "response_type": "code", "scope": " ".join(IDENTITY_LINK_SCOPES),
                        "state": launch.request.state.get_secret_value(),
                        "code_challenge": launch.request.code_challenge, "code_challenge_method": "S256",
                        "access_type": "offline", "prompt": "consent",
                    })
                    self._authorization_links[account_id] = (revision, SecretStr(url), deadline)
                    try:
                        self.browser.open(SecretStr(url))
                    except BrowserLaunchError:
                        # A validated URL remains usable manually on this PC until callback expiry.
                        pass
                worker = threading.Thread(target=self._complete, args=(account_id, operation_id, revision, client, listener),
                                          name="newsflow-youtube-connect", daemon=True)
                self._workers[account_id] = worker
                worker.start()
                return account_id
            except Exception as error:  # noqa: BLE001 - sanitize browser and callback failures
                self._authorization_links.pop(account_id, None)
                listener.close()
                self._fail(account_id, operation_id, revision, error)
                raise YouTubeConnectionError("connection_failed") from None

    def authorization_link(self, account_id: int) -> tuple[SecretStr, int]:
        """Explicit local POST only; never create, extend or replay an OAuth operation."""
        with self._lock:
            saved = self._authorization_links.get(account_id)
            if saved is None:
                raise YouTubeConnectionError("expired")
            revision, url, deadline = saved
            with self.sessions() as session:
                connection = session.get(OAuthConnection, account_id)
                if (deadline <= monotonic() or account_id not in self._listeners
                        or connection is None or connection.mode != MODE
                        or connection.revision != revision or connection.status != "authorizing"):
                    self._authorization_links.pop(account_id, None)
                    raise YouTubeConnectionError("expired")
            return url, max(0, int(deadline - monotonic()))

    def reopen_authorization(self, account_id: int) -> None:
        with self._lock:
            url, _ = self.authorization_link(account_id)
            with youtube_operation(consent=True):
                self.browser.open(url)

    def _complete(self, account_id: int, operation_id: str, revision: int, client: DesktopClientConfig,
                  listener: Any) -> None:
        try:
            callback = listener.wait()
            with self._lock:
                if self._listeners.get(account_id) is listener:
                    self._authorization_links.pop(account_id, None)
            with youtube_operation(consent=True):
                callback.assert_valid(f"youtube:{account_id}", production=True)
                if tuple(callback.scopes) != IDENTITY_LINK_SCOPES:
                    raise YouTubeConnectionError("permission_denied")
                with self.sessions.begin() as session:
                    changed = session.execute(update(OAuthConnection).where(
                        OAuthConnection.account_id == account_id, OAuthConnection.mode == MODE,
                        OAuthConnection.revision == revision, OAuthConnection.status == "authorizing",
                    ).values(status="exchanging", updated_at=utcnow()))
                    if changed.rowcount != 1:
                        raise YouTubeConnectionError("cancelled")
                response = self.tokens.post("token", {
                    "client_id": client.client_id, "client_secret": client.client_secret.get_secret_value(),
                    "code": callback.code.get_secret_value(), "code_verifier": callback.verifier.get_secret_value(),
                    "redirect_uri": callback.redirect_uri, "grant_type": "authorization_code",
                })
                bundle, refresh_deadline = _tokens(response)
                channel = _channel_response(self.identity.get_channels(bundle.access_token))
                self._commit(account_id, operation_id, revision, client, bundle, channel, refresh_deadline)
        except Exception as error:  # noqa: BLE001 - never print token transport errors from a worker
            self._fail(account_id, operation_id, revision, error)
        finally:
            listener.close()
            with self._lock:
                if self._listeners.get(account_id) is listener:
                    self._authorization_links.pop(account_id, None)
                    self._listeners.pop(account_id, None)

    def _commit(self, account_id: int, operation_id: str, revision: int, client: DesktopClientConfig,
                bundle: TokenBundle, channel: str, refresh_deadline: str | None) -> None:
        account_key = f"youtube:{account_id}"
        identity = _digest("youtube", account_key, client.client_id, channel, IDENTITY_LINK_SCOPES)
        channel_digest = _digest("youtube", client.client_id, channel)
        reference = uuid4().hex
        with self.sessions.begin() as session:
            connection = session.get(OAuthConnection, account_id)
            operation = session.get(OAuthLifecycleOperation, operation_id)
            binding = session.get(OAuthIdentityBinding, account_id)
            if (not connection or connection.mode != MODE or connection.revision != revision
                    or connection.status not in {"exchanging", "refreshing"}
                    or not operation or operation.status != "youtube_pending"):
                raise YouTubeConnectionError("outcome_unknown")
            if binding and _setting(session, f"youtube.channel.{account_id}") != channel:
                raise YouTubeConnectionError("identity_mismatch")
            other = session.scalar(select(OAuthIdentityBinding.account_id).where(
                OAuthIdentityBinding.channel_binding_digest == channel_digest,
                OAuthIdentityBinding.account_id != account_id,
            ))
            if other is not None:
                raise YouTubeConnectionError("identity_mismatch")
            operation.new_reference, operation.identity_digest = reference, identity
            operation.status, operation.updated_at = "youtube_writing", utcnow()
        self.vault.write_reserved(account_key, identity, reference, bundle, operation_id=operation_id)
        with self.sessions.begin() as session:
            connection = session.get(OAuthConnection, account_id)
            operation = session.get(OAuthLifecycleOperation, operation_id)
            account = session.get(PlatformAccount, account_id)
            if (connection.revision != revision or connection.status not in {"exchanging", "refreshing"}
                    or operation.status != "youtube_writing"):
                raise YouTubeConnectionError("outcome_unknown")
            binding = session.get(OAuthIdentityBinding, account_id)
            if binding is None:
                binding = OAuthIdentityBinding(account_id=account_id, account_key=account_key,
                                               identity_digest=identity, channel_binding_digest=channel_digest, mode=MODE)
                session.add(binding)
            binding.identity_digest, binding.grant_fingerprint = identity, grant_fingerprint(bundle)
            binding.channel_binding_digest = channel_digest
            account.credential_ref, account.api_ready, account.status = reference, True, "connected"
            account.label, account.scopes, account.connected_at = f"YouTube · {channel}", list(bundle.scopes), utcnow()
            connection.status, connection.error_code = "connected", None
            connection.expires_at, connection.updated_at = bundle.expires_at, utcnow()
            operation.status, operation.updated_at = "youtube_completed", utcnow()
            _setting(session, f"youtube.channel.{account_id}", channel)
            _setting(session, f"youtube.client.{account_id}", client.client_id)
            if refresh_deadline:
                _setting(session, f"youtube.refresh_end.{account_id}", refresh_deadline)

    def _fail(self, account_id: int, operation_id: str, revision: int, error: Exception) -> None:
        code = getattr(error, "code", "connection_failed")
        callback_reason = None
        observed_rejection = None
        if isinstance(error, CallbackError):
            # Only allowlisted classifications reach storage/UI; never the exception text.
            if code == "expired":
                # A local callback deadline is not evidence that Google rejected a token.
                code = "callback_expired"
            if isinstance(error.reason, str) and error.reason in CALLBACK_REJECTION_MESSAGES:
                callback_reason = error.reason
                if code in {"callback_invalid", "state_mismatch", "provider_error"}:
                    code = f"callback_{callback_reason}"
            if (isinstance(error.last_rejection, str)
                    and error.last_rejection in CALLBACK_REJECTION_MESSAGES):
                observed_rejection = error.last_rejection
        if getattr(error, "outcome_unknown", False) or isinstance(error, (TimeoutError, OSError)):
            code = "outcome_unknown"
        if code not in _MESSAGES:
            code = "connection_failed"
        with self.sessions.begin() as session:
            connection = session.get(OAuthConnection, account_id)
            operation = session.get(OAuthLifecycleOperation, operation_id)
            account = session.get(PlatformAccount, account_id)
            if not connection or connection.mode != MODE or connection.revision != revision:
                return
            if operation and operation.status == "youtube_writing":
                code = "outcome_unknown"
            if connection.status in {"cancelled", "unknown"}:
                return
            if isinstance(error, CallbackError):
                session.add(AuditLog(level="warning", event="youtube_callback_rejected", message=json.dumps({
                    "account_id": account_id, "stage": "callback", "outcome": code,
                    "operation_id": operation_id, "revision": revision,
                    "reason": callback_reason,
                    # A pre-state rejection is an observation, not proof of why login expired.
                    "last_rejected_request": observed_rejection if callback_reason is None else None,
                    "observation": error.safe_observation(),
                }, separators=(",", ":"))))
            status = "unknown" if code == "outcome_unknown" else "cancelled" if code == "cancelled" else "error"
            connection.status, connection.error_code, connection.updated_at = status, code, utcnow()
            account.api_ready, account.status = False, "not_connected"
            if operation:
                operation.status, operation.updated_at = f"youtube_{status}", utcnow()

    def cancel(self, account_id: int) -> None:
        with self._lock:
            self._authorization_links.pop(account_id, None)
            listener = self._listeners.get(account_id)
            if listener:
                listener.cancel()
            with self.sessions.begin() as session:
                connection = session.get(OAuthConnection, account_id)
                if not connection or connection.mode != MODE or connection.status not in _PENDING:
                    return
                status = "cancelled" if connection.status == "authorizing" else "unknown"
                connection.status, connection.error_code, connection.updated_at = (
                    status, "cancelled" if status == "cancelled" else "outcome_unknown", utcnow(),
                )
                account = session.get(PlatformAccount, account_id)
                account.api_ready, account.status = False, "not_connected"
                for operation in session.scalars(select(OAuthLifecycleOperation).where(
                    OAuthLifecycleOperation.account_id == account_id,
                    OAuthLifecycleOperation.status.in_(("youtube_pending", "youtube_writing")),
                )):
                    operation.status, operation.updated_at = f"youtube_{status}", utcnow()

    def access_for_upload(self, account_id: int, *, consent: bool = False) -> tuple[TokenBundle, str]:
        if consent is not True:
            raise YouTubeConnectionError("consent_required")
        with self._lock:
            return self._access_for_upload(account_id)

    def _access_for_upload(self, account_id: int) -> tuple[TokenBundle, str]:
        client = self._client()
        with youtube_operation(consent=True):
            with self.sessions() as session:
                account, connection = session.get(PlatformAccount, account_id), session.get(OAuthConnection, account_id)
                binding = session.get(OAuthIdentityBinding, account_id)
                channel = _setting(session, f"youtube.channel.{account_id}")
                if (not account or account.platform != "youtube" or not connection or connection.mode != MODE
                        or connection.status != "connected" or not account.api_ready or not binding or binding.mode != MODE
                        or not channel or not account.credential_ref):
                    raise YouTubeConnectionError("not_connected")
                if _setting(session, f"youtube.client.{account_id}") != client.client_id:
                    raise YouTubeConnectionError("client_changed")
                reference, identity, fingerprint, revision = (
                    account.credential_ref, binding.identity_digest, binding.grant_fingerprint, connection.revision,
                )
                deadline = _setting(session, f"youtube.refresh_end.{account_id}")
            bundle = self.vault.load(f"youtube:{account_id}", identity, reference, allow_expired=True)
            if grant_fingerprint(bundle) != fingerprint or tuple(bundle.scopes) != IDENTITY_LINK_SCOPES:
                raise YouTubeConnectionError("not_connected")
            if bundle.expires_at > utcnow() + timedelta(seconds=30):
                return bundle, channel
            if deadline and deadline <= utcnow().isoformat():
                raise YouTubeConnectionError("expired")
            if bundle.refresh_token is None:
                raise YouTubeConnectionError("expired")
            operation_id = uuid4().hex
            with self.sessions.begin() as session:
                changed = session.execute(update(OAuthConnection).where(
                    OAuthConnection.account_id == account_id, OAuthConnection.mode == MODE,
                    OAuthConnection.revision == revision, OAuthConnection.status == "connected",
                ).values(status="refreshing", revision=revision + 1, updated_at=utcnow()))
                if changed.rowcount != 1:
                    raise YouTubeConnectionError("pending")
                revision += 1
                session.add(OAuthLifecycleOperation(
                    id=operation_id, account_id=account_id, account_key=f"youtube:{account_id}",
                    identity_digest=identity, operation="youtube_refresh", expected_revision=revision,
                    old_reference=reference, status="youtube_pending",
                ))
            try:
                response = self.tokens.post("token", {
                    "client_id": client.client_id, "client_secret": client.client_secret.get_secret_value(),
                    "refresh_token": bundle.refresh_token.get_secret_value(), "grant_type": "refresh_token",
                })
                replacement, refresh_deadline = _tokens(response, previous=bundle)
                confirmed = _channel_response(self.identity.get_channels(replacement.access_token))
                if confirmed != channel:
                    raise YouTubeConnectionError("identity_mismatch")
                self._commit(account_id, operation_id, revision, client, replacement, channel, refresh_deadline)
                return replacement, channel
            except Exception as error:  # noqa: BLE001 - retain an uncertain refresh without retry
                self._fail(account_id, operation_id, revision, error)
                raise YouTubeConnectionError(getattr(error, "code", "outcome_unknown")) from None

    def recover(self) -> int:
        """Startup metadata recovery only; preserve all ciphertext and never retry."""
        count = 0
        with self.sessions.begin() as session:
            for connection in session.scalars(select(OAuthConnection).where(
                OAuthConnection.mode == MODE, OAuthConnection.status.in_(_PENDING),
            )):
                connection.status, connection.error_code, connection.updated_at = "unknown", "outcome_unknown", utcnow()
                account = session.get(PlatformAccount, connection.account_id)
                account.api_ready, account.status = False, "not_connected"
                count += 1
            session.execute(update(OAuthLifecycleOperation).where(
                OAuthLifecycleOperation.status.in_(("youtube_pending", "youtube_writing")),
            ).values(status="youtube_unknown", updated_at=utcnow()))
        return count

    def close(self) -> None:
        with self._lock:
            identifiers = list(self._listeners)
        for identifier in identifiers:
            self.cancel(identifier)
        for listener in list(self._listeners.values()):
            listener.close()
