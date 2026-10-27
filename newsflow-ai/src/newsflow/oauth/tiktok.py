"""Desktop TikTok account lifecycle; default closed, explicit synthetic dependency tests."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, update

from newsflow.db.models import (
    AppSetting,
    OAuthConnection,
    OAuthIdentityBinding,
    OAuthLifecycleOperation,
    PlatformAccount,
    utcnow,
)

from .tiktok_callback import TikTokCallback
from .tiktok_credentials import TikTokClientStore, TikTokVault
from .tiktok_protocol import (
    MESSAGES,
    SCOPES,
    TikTokBrowser,
    TikTokError,
    TikTokHTTP,
    identity_result,
    production_enabled,
    token_result,
)

MODES = ("tiktok_desktop", "tiktok_fake")
PENDING = ("authorizing", "exchanging", "refreshing", "revoking")


def digest(*values):
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def setting(session, key, value=None):
    row = session.get(AppSetting, key)
    if value is None:
        return row.value if row else None
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))


class TikTokConnectionService:
    def __init__(self, sessions, data_dir: Path, *, client_store=None, http=None, browser=None, vault=None):
        self.sessions = sessions
        self.http = http if http is not None else TikTokHTTP()
        self.synthetic = self.http.synthetic
        if self.synthetic and (client_store is None or browser is None or vault is None or not vault.synthetic):
            raise TikTokError("config")
        self.mode = "tiktok_fake" if self.synthetic else "tiktok_desktop"
        self.client = client_store if client_store is not None else TikTokClientStore(data_dir)
        self.browser = browser if browser is not None else TikTokBrowser()
        self.vault = vault if vault is not None else TikTokVault(data_dir / "tiktok-oauth")
        self._lock = threading.RLock()
        self._listeners, self._workers = {}, {}

    def _permit(self, consent):
        if consent is not True:
            raise TikTokError("consent")
        if not self.synthetic and not production_enabled():
            raise TikTokError("blocked")

    def status(self):
        with self.sessions() as session:
            records = session.execute(select(PlatformAccount, OAuthConnection).join(
                OAuthConnection, PlatformAccount.id == OAuthConnection.account_id).where(
                    PlatformAccount.platform == "tiktok", OAuthConnection.mode == self.mode)).all()
            accounts = [{"id": a.id, "label": a.label, "status": "expired" if c.status == "connected" and (not c.expires_at or c.expires_at <= utcnow()) else c.status,
                         "ready": bool(a.api_ready and c.status == "connected" and c.expires_at and c.expires_at > utcnow()),
                         "synthetic": self.synthetic, "message": MESSAGES.get(c.error_code,
                             MESSAGES["expired"] if c.status == "connected" and (not c.expires_at or c.expires_at <= utcnow())
                             else "계정 상태를 확인하세요."),
                         "expires_at": c.expires_at} for a, c in records]
            port = setting(session, "tiktok.port") or "0"
        return {"accounts": accounts, "client": self.client.status(), "port": port,
                "pending": any(a["status"] in PENDING for a in accounts),
                "enabled": self.synthetic or production_enabled(), "synthetic": self.synthetic,
                "redirect": f"http://127.0.0.1:{port if port != '0' else '*'}/oauth/tiktok/callback/"}

    def save_client(self, raw):
        self.client.validate(raw)
        with self._lock, self.sessions() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            if session.scalar(select(OAuthConnection.account_id).where(
                    OAuthConnection.mode.in_(MODES), OAuthConnection.status.in_(PENDING))):
                raise TikTokError("pending")
            self.client.save(raw)
            setting(session, "tiktok.port", str(json.loads(raw)["port"]))
            for connection in session.scalars(select(OAuthConnection).where(OAuthConnection.mode.in_(MODES))):
                connection.status, connection.error_code = "reconnect", "config"
                connection.revision += 1
                session.get(PlatformAccount, connection.account_id).api_ready = False
            session.commit()

    def _claim(self, account_id, operation, *, config, snapshot=None):
        with self.sessions() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            if session.scalar(select(OAuthConnection.account_id).where(
                    OAuthConnection.mode.in_(MODES), OAuthConnection.status.in_(PENDING))):
                raise TikTokError("pending")
            if self.client.config() != config:
                raise TikTokError("config")
            if account_id is None:
                if operation != "connect":
                    raise TikTokError("identity")
                account = PlatformAccount(platform="tiktok", account_type="tiktok_creator", label="TikTok 연결 중")
                session.add(account)
                session.flush()
                connection = OAuthConnection(account_id=account.id, mode=self.mode)
                session.add(connection)
                session.flush()
            else:
                account = session.get(PlatformAccount, account_id)
                connection = session.get(OAuthConnection, account_id)
                if not account or account.platform != "tiktok" or not connection or connection.mode != self.mode:
                    raise TikTokError("identity")
                if snapshot is not None and snapshot != (connection.revision, account.credential_ref):
                    raise TikTokError("identity")
                if operation != "connect" and connection.status != "connected":
                    raise TikTokError("expired")
            connection.revision += 1
            connection.status = {"connect": "authorizing", "refresh": "refreshing", "revoke": "revoking"}[operation]
            connection.error_code = None
            account.api_ready = False
            identifier = uuid4().hex
            session.add(OAuthLifecycleOperation(
                id=identifier, account_id=account.id, account_key=f"tiktok:{account.id}", identity_digest="0" * 64,
                operation="tiktok_" + operation, expected_revision=connection.revision,
                old_reference=account.credential_ref, status="tt_pending"))
            session.commit()
            return account.id, identifier, connection.revision

    def begin(self, *, consent=False, account_id=None):
        self._permit(consent)
        with self._lock:
            config = self.client.config()
            account_id, op, revision = self._claim(account_id, "connect", config=config)
            listener = TikTokCallback(synthetic=self.synthetic)
            self._listeners[account_id] = listener
            try:
                url = listener.start(config)
                self.browser.open(url)
                worker = threading.Thread(target=self._complete, args=(account_id, op, revision, config, listener), daemon=True)
                self._workers[account_id] = worker
                worker.start()
                return account_id
            except Exception as error:  # noqa: BLE001 - persist fixed error codes only
                listener.close()
                self._listeners.pop(account_id, None)
                self._fail(account_id, op, revision, error)
                raise TikTokError(getattr(error, "code", "unknown")) from None

    def _complete(self, account_id, op, revision, config, listener):
        try:
            code = listener.wait()
            with self.sessions.begin() as session:
                changed = session.execute(update(OAuthConnection).where(
                    OAuthConnection.account_id == account_id, OAuthConnection.mode == self.mode,
                    OAuthConnection.revision == revision, OAuthConnection.status == "authorizing",
                ).values(status="exchanging"))
                if changed.rowcount != 1:
                    raise TikTokError("cancelled")
            response = self.http.request("token", {"client_key": config.client_key,
                "client_secret": config.client_secret.get_secret_value(), "code": code.get_secret_value(),
                "grant_type": "authorization_code", "redirect_uri": listener.redirect_uri,
                "code_verifier": listener.verifier.get_secret_value()})
            self._accept(account_id, op, revision, config, response)
        except Exception as error:  # noqa: BLE001 - persist fixed error codes only
            self._fail(account_id, op, revision, error)
        finally:
            listener.close()
            with self._lock:
                if self._listeners.get(account_id) is listener:
                    self._listeners.pop(account_id, None)

    def _accept(self, account_id, op, revision, config, response, expected=None):
        bundle, open_id, refresh_end = token_result(response, expected)
        identity = digest("tiktok", config.client_key, open_id)
        label = identity_result(self.http.request("identity", {"access_token": bundle.access_token.get_secret_value()}), open_id)
        reference = uuid4().hex
        with self.sessions.begin() as session:
            connection = session.get(OAuthConnection, account_id)
            operation = session.get(OAuthLifecycleOperation, op)
            previous = session.get(OAuthIdentityBinding, account_id)
            if (connection.revision != revision or connection.status not in ("exchanging", "refreshing")
                    or operation.status != "tt_pending"):
                raise TikTokError("cancelled")
            if previous and previous.identity_digest != identity:
                raise TikTokError("identity")
            if session.scalar(select(OAuthIdentityBinding.account_id).where(
                    OAuthIdentityBinding.channel_binding_digest == identity,
                    OAuthIdentityBinding.account_id != account_id)):
                raise TikTokError("identity")
            operation.status, operation.new_reference, operation.identity_digest = "tt_writing", reference, identity
        self.vault.write_reserved(f"tiktok:{account_id}", identity, reference, bundle, operation_id=op)
        with self.sessions.begin() as session:
            connection = session.get(OAuthConnection, account_id)
            operation = session.get(OAuthLifecycleOperation, op)
            if (connection.revision != revision or connection.status not in ("exchanging", "refreshing")
                    or operation.status != "tt_writing"):
                raise TikTokError()
            binding = session.get(OAuthIdentityBinding, account_id)
            if not binding:
                session.add(OAuthIdentityBinding(account_id=account_id, account_key=f"tiktok:{account_id}",
                                                identity_digest=identity, channel_binding_digest=identity, mode=self.mode))
            account = session.get(PlatformAccount, account_id)
            account.credential_ref, account.api_ready, account.status = reference, True, "connected"
            account.label = ("합성 · " if self.synthetic else "") + label
            account.scopes, account.connected_at = list(SCOPES), utcnow()
            connection.status, connection.expires_at, connection.error_code = "connected", bundle.expires_at, None
            operation.status, operation.updated_at = "tt_completed", utcnow()
            setting(session, f"tiktok.client.{account_id}", config.client_key)
            setting(session, f"tiktok.open.{account_id}", open_id)
            setting(session, f"tiktok.refresh.{account_id}", refresh_end.isoformat())

    def _fail(self, account_id, op, revision, error):
        code = getattr(error, "code", "unknown")
        if code not in MESSAGES:
            code = "unknown"
        with self.sessions.begin() as session:
            c, operation = session.get(OAuthConnection, account_id), session.get(OAuthLifecycleOperation, op)
            if not c or c.revision != revision:
                return
            c.status = "cancelled" if code == "cancelled" else "unknown" if code == "unknown" else "error"
            c.error_code, c.updated_at = code, utcnow()
            session.get(PlatformAccount, account_id).api_ready = False
            if operation:
                operation.status = "tt_" + c.status

    def cancel(self, account_id):
        with self._lock, self.sessions.begin() as session:
            c = session.get(OAuthConnection, account_id)
            if not c or c.mode != self.mode or c.status not in PENDING:
                raise TikTokError("identity")
            c.status = "cancelled" if c.status == "authorizing" else "unknown"
            c.error_code = "cancelled" if c.status == "cancelled" else "unknown"
            c.revision += 1
            session.get(PlatformAccount, account_id).api_ready = False
            for op in session.scalars(select(OAuthLifecycleOperation).where(
                    OAuthLifecycleOperation.account_id == account_id,
                    OAuthLifecycleOperation.status.in_(("tt_pending", "tt_writing")))):
                op.status = "tt_" + c.status
            listener = self._listeners.get(account_id)
            if listener:
                listener.cancel()

    def _stored(self, account_id):
        config = self.client.config()
        with self.sessions() as session:
            c, a = session.get(OAuthConnection, account_id), session.get(PlatformAccount, account_id)
            binding = session.get(OAuthIdentityBinding, account_id)
            open_id = setting(session, f"tiktok.open.{account_id}")
            if (not c or c.mode != self.mode or c.status != "connected" or not a or not a.api_ready or not binding
                    or not a.credential_ref or setting(session, f"tiktok.client.{account_id}") != config.client_key
                    or binding.identity_digest != digest("tiktok", config.client_key, open_id)):
                raise TikTokError("identity")
            reference, identity = a.credential_ref, binding.identity_digest
            snapshot = (c.revision, reference)
            refresh_end = setting(session, f"tiktok.refresh.{account_id}")
        bundle = self.vault.load(f"tiktok:{account_id}", identity, reference, allow_expired=True)
        if tuple(bundle.scopes) != SCOPES:
            raise TikTokError("permission")
        return config, bundle, open_id, refresh_end, snapshot

    def refresh(self, account_id, *, consent=False):
        self._permit(consent)
        with self._lock:
            config, old, open_id, refresh_end, snapshot = self._stored(account_id)
            if not refresh_end or refresh_end <= utcnow().isoformat():
                raise TikTokError("expired")
            account_id, op, revision = self._claim(account_id, "refresh", config=config, snapshot=snapshot)
            try:
                response = self.http.request("token", {"client_key": config.client_key,
                    "client_secret": config.client_secret.get_secret_value(), "grant_type": "refresh_token",
                    "refresh_token": old.refresh_token.get_secret_value()})
                self._accept(account_id, op, revision, config, response, expected=open_id)
            except Exception as error:  # noqa: BLE001 - persist fixed error codes only
                self._fail(account_id, op, revision, error)
                raise TikTokError(getattr(error, "code", "unknown")) from None

    def revoke(self, account_id, *, consent=False):
        self._permit(consent)
        with self._lock:
            config, old, _, _, snapshot = self._stored(account_id)
            account_id, op, revision = self._claim(account_id, "revoke", config=config, snapshot=snapshot)
            try:
                result = self.http.request("revoke", {"client_key": config.client_key,
                    "client_secret": config.client_secret.get_secret_value(), "token": old.access_token.get_secret_value()})
                if result != {}:
                    raise TikTokError()
                with self.sessions.begin() as session:
                    c = session.get(OAuthConnection, account_id)
                    if c.revision != revision or c.status != "revoking":
                        raise TikTokError()
                    c.status, c.error_code = "revoked", None
                    a = session.get(PlatformAccount, account_id)
                    a.status, a.credential_ref, a.api_ready = "not_connected", None, False
                    session.get(OAuthLifecycleOperation, op).status = "tt_revoked"
            except Exception as error:  # noqa: BLE001 - persist fixed error codes only
                self._fail(account_id, op, revision, error)
                raise TikTokError(getattr(error, "code", "unknown")) from None

    def synthetic_binding(self, account_id):
        """Existing Fake publisher bridge; never convert a real credential to synthetic."""
        if not self.synthetic:
            raise TikTokError("blocked")
        with self._lock:
            _, bundle, open_id, _, _ = self._stored(account_id)
            if bundle.expires_at <= utcnow() + timedelta(seconds=30):
                raise TikTokError("expired")
            return {"account_id": account_id, "platform": "tiktok", "identity": open_id,
                    "scopes": list(bundle.scopes), "synthetic": True}

    def recover(self):
        with self.sessions.begin() as session:
            for c in session.scalars(select(OAuthConnection).where(OAuthConnection.mode.in_(MODES), OAuthConnection.status.in_(PENDING))):
                c.status, c.error_code = "unknown", "unknown"
                c.revision += 1
                session.get(PlatformAccount, c.account_id).api_ready = False
            session.execute(update(OAuthLifecycleOperation).where(
                OAuthLifecycleOperation.operation.in_(("tiktok_connect", "tiktok_refresh", "tiktok_revoke")),
                OAuthLifecycleOperation.status.in_(("tt_pending", "tt_writing"))).values(status="tt_unknown"))

    def close(self):
        for account_id, listener in list(self._listeners.items()):
            try:
                self.cancel(account_id)
            except TikTokError:
                pass
            listener.close()
        for worker in list(self._workers.values()):
            worker.join(3)
