"""Facebook Login for Business connection contract for Instagram publishing.

The Windows app stores only the configured HTTPS relay origin and Meta App ID.
The relay owns its App Secret and exchanges authorization codes server-side.
Without that deployment the connection remains blocked. Graph account checks
and the existing Windows DPAPI kernel are reused below.
"""

from __future__ import annotations

import hashlib
import json
import re
import ssl
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import select

from newsflow.db.models import (
    AppSetting,
    OAuthConnection,
    OAuthIdentityBinding,
    OAuthLifecycleOperation,
    PlatformAccount,
    utcnow,
)
from newsflow.publishing.auth import TokenBundle

from .identity import grant_fingerprint
from .production_dpapi import _owner_sid, _ProductionDPAPIFileKernel
from .vault import _DPAPI

GRAPH_VERSION = "v25.0"
FACEBOOK_SCOPES = (
    "instagram_basic", "instagram_content_publish", "pages_show_list", "pages_read_engagement",
)
MODE = "instagram_fb"
_ID = re.compile(r"[1-9][0-9]{0,29}\Z")
_CONTENT_TASKS = {"CREATE_CONTENT", "MANAGE", "PROFILE_PLUS_CREATE_CONTENT", "PROFILE_PLUS_FULL_CONTROL"}
_OPERATION: ContextVar[bool] = ContextVar("newsflow_instagram_connection_operation", default=False)
_MESSAGES = {
    "auth_relay_required": "Meta 연결은 BLOCKED입니다. 등록된 HTTPS 인증 중계와 서버 측 App Secret 관리가 필요합니다.",
    "consent_required": "Instagram 계정 연결 또는 영상 전송에 동의해 주세요.",
    "not_connected": "게시할 Instagram 프로페셔널 계정을 연결해 주세요.",
    "permission_denied": "Instagram 게시 및 Facebook 페이지 조회 권한이 필요합니다.",
    "professional_required": "게시 권한이 있는 Facebook 페이지에 연결된 Instagram 프로페셔널 계정이 필요합니다.",
    "identity_mismatch": "승인한 Facebook 페이지와 Instagram 계정이 일치하지 않습니다.",
    "expired": "Meta 인증이 만료되었거나 취소되었습니다. 계정을 다시 연결해 주세요.",
    "pending": "이미 Instagram 계정 연결을 처리하고 있습니다.",
    "outcome_unknown": "계정 연결 결과를 확인하지 못했습니다. 자동 재시도하지 않습니다.",
    "response_invalid": "Meta 계정 확인 응답을 안전하게 검증하지 못했습니다.",
    "connection_failed": "Instagram 계정 연결에 실패했습니다. 앱과 계정 권한을 확인해 주세요.",
    "relay_config_invalid": "인증 중계의 공개 HTTPS 주소와 Meta App ID를 확인해 주세요.",
    "cancelled": "Instagram 계정 연결을 취소했습니다.",
    "rate_limited": "로그인 연결 요청 한도에 도달했습니다. 자동으로 다시 요청하지 않습니다.",
}


class InstagramConnectionError(Exception):
    def __init__(self, code: str = "connection_failed") -> None:
        self.code = code if code in _MESSAGES else "connection_failed"
        super().__init__(_MESSAGES[self.code])


@dataclass(frozen=True)
class MetaAuthorization:
    """Trusted backend result, never constructed from a GUI token or callback form.

    The backend must verify state, exact registered HTTPS redirect, one-use code,
    app identity and data-access expiry on its secret-holding server. It must let
    the user select the Page. The desktop receives no shared App Secret.
    """

    app_id: str
    page_id: str
    user_bundle: TokenBundle = field(repr=False)
    data_access_expires_at: datetime


@dataclass(frozen=True)
class InstagramCredential:
    bundle: TokenBundle = field(repr=False)
    page_id: str
    instagram_id: str
    app_id: str


class TrustedFacebookAuthorization(Protocol):
    def authorize(self, *, scopes: tuple[str, ...]) -> MetaAuthorization: ...


@contextmanager
def _approved_operation():
    token = _OPERATION.set(True)
    try:
        yield
    finally:
        _OPERATION.reset(token)


def _require_operation():
    if not _OPERATION.get():
        raise InstagramConnectionError("consent_required")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FacebookGraphIdentity:
    """Fixed-host read-only checks. Tokens use headers and never appear in URLs."""

    def get(self, path: str, token: SecretStr, fields: str = "") -> dict:
        _require_operation()
        if path not in {"me/permissions", "me/accounts"} and not _ID.fullmatch(path):
            raise InstagramConnectionError("response_invalid")
        if not isinstance(token, SecretStr) or not 1 <= len(token.get_secret_value()) <= 4096:
            raise InstagramConnectionError("response_invalid")
        query = "?" + urlencode({"fields": fields}) if fields else ""
        request = Request(f"https://graph.facebook.com/{GRAPH_VERSION}/{path}{query}", headers={
            "Authorization": "Bearer " + token.get_secret_value(), "Accept": "application/json",
        })
        opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        try:
            with opener.open(request, timeout=30) as response:
                raw = response.read(262145)
                if response.status != 200 or len(raw) > 262144:
                    raise InstagramConnectionError("response_invalid")
            result = json.loads(raw)
            if not isinstance(result, dict) or "error" in result:
                raise InstagramConnectionError("response_invalid")
            return result
        except InstagramConnectionError:
            raise
        except HTTPError as error:
            raise InstagramConnectionError("expired" if error.code == 401 else
                                           "permission_denied" if error.code == 403 else
                                           "connection_failed") from None
        except Exception:  # noqa: BLE001 - never expose transport URLs, tokens or response bodies
            raise InstagramConnectionError("outcome_unknown") from None


class _InstagramVault:
    """Existing DPAPI cipher/file kernel, isolated from YouTube activation state."""

    def __init__(self, root: Path) -> None:
        self.root, self.kernel = root, None

    def _backend(self):
        _require_operation()
        if sys.platform != "win32":
            raise InstagramConnectionError("connection_failed")
        if self.kernel is None:
            self.kernel = _ProductionDPAPIFileKernel(
                self.root, _DPAPI(), _owner_sid(), native=True, synthetic_only=False,
            )
        return self.kernel

    def write_reserved(self, key, identity, reference, bundle, *, operation_id):
        self._backend().write_reserved(key, identity, reference, bundle, operation_id=operation_id)

    def load(self, key, identity, reference, *, allow_expired=False):
        return self._backend().read(key, identity, reference, check_expiry=not allow_expired)


def _digest(*values: object) -> str:
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def _setting(session, key: str, value: str | None = None):
    row = session.get(AppSetting, key)
    if value is None:
        return row.value if row else None
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))
    return value


def _object_id(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise InstagramConnectionError("response_invalid")
    return value


class InstagramConnectionService:
    def __init__(self, sessions, data_dir: Path, *, authorization_backend: TrustedFacebookAuthorization | None = None,
                 identity_transport=None, vault=None, relay_factory=None) -> None:
        self.sessions = sessions
        self.authorization = authorization_backend
        self._relay_factory = relay_factory
        self.identity = identity_transport if identity_transport is not None else FacebookGraphIdentity()
        self.vault = vault if vault is not None else _InstagramVault(Path(data_dir) / "instagram-oauth")
        self._lock = RLock()
        self._active: tuple[int, str] | None = None
        self._worker: Thread | None = None
        if self.authorization is None:
            self._load_relay()

    def _relay_config(self):
        from .instagram_relay import RelayConfig

        with self.sessions() as session:
            origin, app_id = _setting(session, "instagram.relay.url"), _setting(session, "instagram.relay.app_id")
        if not origin or not app_id:
            return None
        try:
            return RelayConfig.parse(origin, app_id)
        except InstagramConnectionError:
            return None

    def _load_relay(self):
        from .instagram_relay import InstagramRelayAuthorization

        config = self._relay_config()
        if config is not None:
            self.authorization = (self._relay_factory or InstagramRelayAuthorization)(config)

    def save_relay(self, url: str, app_id: str) -> None:
        from .instagram_relay import InstagramRelayAuthorization, RelayConfig

        config = RelayConfig.parse(url, app_id)
        with self._lock:
            if self._active is not None:
                raise InstagramConnectionError("pending")
            with self.sessions.begin() as session:
                _setting(session, "instagram.relay.url", config.origin)
                _setting(session, "instagram.relay.app_id", config.app_id)
            self.authorization = (self._relay_factory or InstagramRelayAuthorization)(config)

    def accounts(self) -> list[dict]:
        configured_app = getattr(getattr(self.authorization, "config", None), "app_id", None)
        with self.sessions() as session:
            rows = session.execute(select(PlatformAccount, OAuthConnection).join(
                OAuthConnection, PlatformAccount.id == OAuthConnection.account_id,
            ).where(PlatformAccount.platform == "instagram", OAuthConnection.mode == MODE)).all()
            return [{
                "id": account.id, "label": account.label,
                "instagram_id": _setting(session, f"instagram.id.{account.id}"),
                "page_id": _setting(session, f"instagram.page.{account.id}"),
                "status": connection.status, "error_code": connection.error_code,
                "ready": bool(self.authorization is not None and account.api_ready
                              and connection.status == "connected" and connection.expires_at
                              and connection.expires_at > utcnow() + timedelta(seconds=30)
                              and (not configured_app or configured_app == _setting(session, f"instagram.app.{account.id}"))),
                "expires_at": connection.expires_at,
                "message": ("Meta 앱 설정 변경 · 계정을 다시 연결해 주세요."
                            if configured_app and configured_app != _setting(session, f"instagram.app.{account.id}")
                            and connection.status == "connected" else
                            "연결 유효기간 만료 · 계정을 다시 연결해 주세요."
                            if connection.status == "connected" and connection.expires_at
                            and connection.expires_at <= utcnow() + timedelta(seconds=30) else
                            _MESSAGES.get(connection.error_code, "연결된 프로페셔널 계정"
                                          if connection.status == "connected" else "연결 확인 필요")),
            } for account, connection in rows]

    def status(self) -> dict:
        accounts = self.accounts()
        supported = self.authorization is not None
        config = self._relay_config()
        details = self.authorization.snapshot() if hasattr(self.authorization, "snapshot") else {}
        return {"configured": supported, "connection_supported": supported, "relay_code_available": True,
                "relay_configured": config is not None, "relay_url": config.origin if config else "",
                "relay_app_id": config.app_id if config else "", "pending_account_id": self._active[0] if self._active else None,
                "storage_supported": sys.platform == "win32", "accounts": accounts,
                "pending": any(row["status"] in {"authorizing", "exchanging"} for row in accounts),
                "blocked_reason": None if supported else "auth_relay_required",
                "message": "Facebook Login for Business" if supported else _MESSAGES["auth_relay_required"], **details}

    def _verified(self, grant: MetaAuthorization, *, ensure_active=None) -> tuple[InstagramCredential, str]:
        if not isinstance(grant, MetaAuthorization):
            raise InstagramConnectionError("response_invalid")
        app_id, page_id = _object_id(grant.app_id), _object_id(grant.page_id)
        bundle = grant.user_bundle
        if (not isinstance(bundle, TokenBundle) or not set(FACEBOOK_SCOPES).issubset(bundle.scopes)
                or grant.data_access_expires_at.tzinfo is None):
            raise InstagramConnectionError("permission_denied")
        expires = min(bundle.expires_at, grant.data_access_expires_at)
        if expires <= utcnow() + timedelta(seconds=30):
            raise InstagramConnectionError("expired")
        if ensure_active is not None:
            ensure_active()
        permissions = self.identity.get("me/permissions", bundle.access_token).get("data")
        if not isinstance(permissions, list) or not all(isinstance(row, dict) for row in permissions):
            raise InstagramConnectionError("response_invalid")
        approved = {row.get("permission") for row in permissions if row.get("status") == "granted"}
        if not set(FACEBOOK_SCOPES).issubset(approved):
            raise InstagramConnectionError("permission_denied")
        if ensure_active is not None:
            ensure_active()
        pages = self.identity.get("me/accounts", bundle.access_token,
                                  "id,name,access_token,tasks,instagram_business_account").get("data")
        if not isinstance(pages, list) or not all(isinstance(row, dict) for row in pages):
            raise InstagramConnectionError("response_invalid")
        matches = [page for page in pages if page.get("id") == page_id]
        if len(matches) != 1:
            raise InstagramConnectionError("identity_mismatch")
        page = matches[0]
        tasks, linked = page.get("tasks"), page.get("instagram_business_account")
        if (not isinstance(tasks, list) or not all(isinstance(task, str) for task in tasks)
                or not _CONTENT_TASKS.intersection(tasks) or not isinstance(linked, dict)):
            raise InstagramConnectionError("professional_required")
        instagram_id = _object_id(linked.get("id"))
        raw_token = page.get("access_token")
        if (not isinstance(raw_token, str) or not 1 <= len(raw_token) <= 4096
                or any(ord(char) < 33 or ord(char) == 127 for char in raw_token)):
            raise InstagramConnectionError("response_invalid")
        page_token = SecretStr(raw_token)
        if ensure_active is not None:
            ensure_active()
        profile = self.identity.get(instagram_id, page_token, "id,username")
        if profile.get("id") != instagram_id:
            raise InstagramConnectionError("identity_mismatch")
        username = profile.get("username")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", username):
            raise InstagramConnectionError("response_invalid")
        credential = InstagramCredential(
            TokenBundle(access_token=page_token, expires_at=expires, scopes=FACEBOOK_SCOPES),
            page_id, instagram_id, app_id,
        )
        return credential, username

    def begin(self, *, consent: bool = False, account_id: int | None = None) -> int:
        if consent is not True:
            raise InstagramConnectionError("consent_required")
        if self.authorization is None:
            raise InstagramConnectionError("auth_relay_required")
        with self._lock:
            if self._active is not None:
                raise InstagramConnectionError("pending")
            operation_id = uuid4().hex
            with self.sessions() as session:
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                if session.scalar(select(OAuthConnection.account_id).where(
                    OAuthConnection.mode == MODE, OAuthConnection.status.in_(("authorizing", "exchanging")),
                )):
                    raise InstagramConnectionError("pending")
                if hasattr(self.authorization, "prepare"):
                    self.authorization.prepare()
                if account_id is None:
                    account = PlatformAccount(platform="instagram", label="Instagram 연결 중",
                                              account_type="professional", status="not_connected")
                    session.add(account)
                    session.flush()
                    account_id = account.id
                    connection = OAuthConnection(account_id=account_id, mode=MODE, status="authorizing")
                    session.add(connection)
                    session.flush()
                else:
                    account, connection = session.get(PlatformAccount, account_id), session.get(OAuthConnection, account_id)
                    if not account or account.platform != "instagram" or not connection or connection.mode != MODE:
                        raise InstagramConnectionError("not_connected")
                    connection.status, connection.error_code = "authorizing", None
                    connection.revision += 1
                    account.api_ready = False
                session.add(OAuthLifecycleOperation(
                    id=operation_id, account_id=account_id, account_key=f"instagram:{account_id}",
                    identity_digest="0" * 64, operation="instagram_connect",
                    expected_revision=connection.revision, status="instagram_pending",
                ))
                session.commit()
            self._active = (account_id, operation_id)
            if getattr(self.authorization, "background", False):
                self._worker = Thread(target=self._connect, args=(account_id, operation_id),
                                      kwargs={"raise_errors": False}, daemon=True, name="instagram-authorization")
                self._worker.start()
                return account_id
            self._connect(account_id, operation_id, raise_errors=True)
            return account_id

    def _connect(self, account_id: int, operation_id: str, *, raise_errors: bool) -> None:
        try:
            with _approved_operation():
                self._assert_pending(account_id, operation_id)
                grant = self.authorization.authorize(scopes=FACEBOOK_SCOPES)
                self._assert_pending(account_id, operation_id)
                credential, label = self._verified(grant, ensure_active=lambda: self._assert_pending(account_id, operation_id))
                self._commit(account_id, operation_id, credential, label)
        except Exception as error:  # noqa: BLE001 - record only fixed safe error codes
            code = getattr(error, "code", "outcome_unknown")
            if code not in _MESSAGES:
                code = "outcome_unknown"
            self._fail(account_id, operation_id, code)
            if raise_errors:
                raise InstagramConnectionError(code) from None
        finally:
            with self._lock:
                if self._active == (account_id, operation_id):
                    self._active = None

    def _assert_pending(self, account_id: int, operation_id: str) -> None:
        with self.sessions() as session:
            connection = session.get(OAuthConnection, account_id)
            operation = session.get(OAuthLifecycleOperation, operation_id)
            if (not connection or connection.status != "authorizing" or not operation
                    or operation.status != "instagram_pending"):
                raise InstagramConnectionError("cancelled")

    def select_page(self, account_id: int, page_id: str, *, consent: bool = False) -> None:
        if consent is not True:
            raise InstagramConnectionError("consent_required")
        with self._lock:
            if not self._active or self._active[0] != account_id or not hasattr(self.authorization, "select_page"):
                raise InstagramConnectionError("not_connected")
            self.authorization.select_page(page_id)

    def cancel(self, account_id: int) -> None:
        with self._lock:
            if not self._active or self._active[0] != account_id:
                raise InstagramConnectionError("not_connected")
            with self.sessions.begin() as session:
                connection = session.get(OAuthConnection, account_id)
                operation = session.get(OAuthLifecycleOperation, self._active[1])
                if connection.status != "authorizing":
                    raise InstagramConnectionError("not_connected")
                connection.status, connection.error_code, connection.updated_at = "cancelled", "cancelled", utcnow()
                operation.status, operation.updated_at = "instagram_cancelled", utcnow()
                session.get(PlatformAccount, account_id).api_ready = False
            backend = self.authorization
        if hasattr(backend, "cancel"):
            backend.cancel()

    def _commit(self, account_id, operation_id, credential, label):
        self._assert_pending(account_id, operation_id)
        key, reference = f"instagram:{account_id}", uuid4().hex
        identity = _digest(MODE, key, credential.app_id, credential.page_id, credential.instagram_id, FACEBOOK_SCOPES)
        channel = _digest(MODE, credential.app_id, credential.instagram_id)
        with self.sessions.begin() as session:
            binding = session.get(OAuthIdentityBinding, account_id)
            if binding and binding.identity_digest != identity:
                raise InstagramConnectionError("identity_mismatch")
            other = session.scalar(select(OAuthIdentityBinding.account_id).where(
                OAuthIdentityBinding.channel_binding_digest == channel, OAuthIdentityBinding.account_id != account_id,
            ))
            if other is not None:
                raise InstagramConnectionError("identity_mismatch")
            operation = session.get(OAuthLifecycleOperation, operation_id)
            connection = session.get(OAuthConnection, account_id)
            if connection.status != "authorizing" or operation.status != "instagram_pending":
                raise InstagramConnectionError("cancelled")
            operation.identity_digest, operation.new_reference, operation.status = identity, reference, "instagram_writing"
        self.vault.write_reserved(key, identity, reference, credential.bundle, operation_id=operation_id)
        with self.sessions.begin() as session:
            account, connection = session.get(PlatformAccount, account_id), session.get(OAuthConnection, account_id)
            operation = session.get(OAuthLifecycleOperation, operation_id)
            if connection.status == "cancelled" or operation.status in {"instagram_unknown", "instagram_cancelled"}:
                return
            if connection.status != "authorizing" or operation.status != "instagram_writing":
                raise InstagramConnectionError("outcome_unknown")
            binding = session.get(OAuthIdentityBinding, account_id)
            if binding is None:
                binding = OAuthIdentityBinding(account_id=account_id, account_key=key, identity_digest=identity,
                                               channel_binding_digest=channel, mode=MODE)
                session.add(binding)
            binding.grant_fingerprint = grant_fingerprint(credential.bundle)
            account.credential_ref, account.api_ready, account.status = reference, True, "connected"
            account.label, account.scopes, account.connected_at = "Instagram · @" + label, list(FACEBOOK_SCOPES), utcnow()
            connection.status, connection.error_code, connection.expires_at = "connected", None, credential.bundle.expires_at
            operation.status = "instagram_completed"
            for suffix, value in (("id", credential.instagram_id), ("page", credential.page_id), ("app", credential.app_id)):
                _setting(session, f"instagram.{suffix}.{account_id}", value)

    def _fail(self, account_id, operation_id, code):
        with self.sessions.begin() as session:
            connection, account = session.get(OAuthConnection, account_id), session.get(PlatformAccount, account_id)
            operation = session.get(OAuthLifecycleOperation, operation_id)
            if connection.status == "cancelled" or operation.status in {"instagram_unknown", "instagram_cancelled"}:
                return
            if operation.status == "instagram_writing":
                code = "outcome_unknown"
            connection.status = "unknown" if code == "outcome_unknown" else "cancelled" if code == "cancelled" else "error"
            connection.error_code, connection.updated_at = code, utcnow()
            account.api_ready = False
            operation.status, operation.updated_at = f"instagram_{connection.status}", utcnow()

    def access_for_upload(self, account_id: int, *, consent: bool = False) -> InstagramCredential:
        if consent is not True:
            raise InstagramConnectionError("consent_required")
        if self.authorization is None:
            raise InstagramConnectionError("auth_relay_required")
        with self.sessions() as session:
            account, connection = session.get(PlatformAccount, account_id), session.get(OAuthConnection, account_id)
            binding = session.get(OAuthIdentityBinding, account_id)
            if (not account or account.platform != "instagram" or not connection or connection.mode != MODE
                    or connection.status != "connected" or not account.api_ready or not binding
                    or binding.mode != MODE or not account.credential_ref):
                raise InstagramConnectionError("not_connected")
            values = [_setting(session, f"instagram.{suffix}.{account_id}") for suffix in ("page", "id", "app")]
            page_id, instagram_id, app_id = map(_object_id, values)
            configured_app = getattr(getattr(self.authorization, "config", None), "app_id", None)
            if configured_app and app_id != configured_app:
                raise InstagramConnectionError("identity_mismatch")
            identity = _digest(MODE, f"instagram:{account_id}", app_id, page_id, instagram_id, FACEBOOK_SCOPES)
            if binding.identity_digest != identity:
                raise InstagramConnectionError("identity_mismatch")
            try:
                with _approved_operation():
                    bundle = self.vault.load(binding.account_key, identity, account.credential_ref, allow_expired=True)
                if (grant_fingerprint(bundle) != binding.grant_fingerprint
                        or tuple(bundle.scopes) != FACEBOOK_SCOPES):
                    raise InstagramConnectionError("identity_mismatch")
                if bundle.expires_at <= utcnow() + timedelta(seconds=30):
                    raise InstagramConnectionError("expired")
            except InstagramConnectionError:
                raise
            except Exception:  # noqa: BLE001 - redact DPAPI paths and malformed credential details
                raise InstagramConnectionError("not_connected") from None
            return InstagramCredential(bundle, page_id, instagram_id, app_id)

    def recover(self) -> int:
        count = 0
        with self.sessions.begin() as session:
            for connection in session.scalars(select(OAuthConnection).where(
                OAuthConnection.mode == MODE, OAuthConnection.status.in_(("authorizing", "exchanging")),
            )):
                connection.status, connection.error_code = "unknown", "outcome_unknown"
                session.get(PlatformAccount, connection.account_id).api_ready = False
                count += 1
            for operation in session.scalars(select(OAuthLifecycleOperation).where(
                OAuthLifecycleOperation.status.in_(("instagram_pending", "instagram_writing")),
            )):
                operation.status, operation.updated_at = "instagram_unknown", utcnow()
        return count

    def close(self) -> None:
        """Stop local authorization work without a logout request or automatic replay."""
        if self._active and hasattr(self.authorization, "cancel"):
            self.authorization.cancel(remote=False)
        if self._worker is not None:
            self._worker.join(timeout=1)
