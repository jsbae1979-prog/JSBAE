"""Owner-scoped connection service; login is explicit and credentials stay outside SQLite."""

import json
import re
from datetime import timedelta
from pathlib import Path
from threading import RLock, Thread
from uuid import uuid4

from sqlalchemy import select

from newsflow.db.models import AppSetting, utcnow
from newsflow.oauth.instagram_relay import RelayConfig
from newsflow.publishing.auth import TokenBundle

from .contracts import SCOPES, Grant, MetaError, fingerprint, object_id
from .models import MetaAccount
from .relay import MetaDesktopAuthorization
from .vault import MetaVault, local_owner

DEFAULTS = {
    "appId": "1390637697472218",
    "configId": "1370882678260953",
    "graphVersion": "v26.0",
    "relayOrigin": "",
}


class MetaConnections:
    def __init__(self, sessions, root, *, owner=None, vault=None, authorization_factory=None):
        self.sessions, self.root = sessions, Path(root)
        self.owner = owner or local_owner()
        if not re.fullmatch("[a-f0-9]{64}", self.owner):
            raise MetaError("invalid")
        self.vault = vault or MetaVault(self.root / "meta-oauth", self.owner)
        self.factory = authorization_factory or MetaDesktopAuthorization
        self.lock = RLock()
        self.authorization = None
        self.pending = None
        self.error = None
        self.cleanup_pending = False

    def config(self):
        with self.sessions() as db:
            row = db.get(AppSetting, "meta.service." + self.owner)
            return {**DEFAULTS, **(json.loads(row.value) if row else {})}

    def configure(self, value):
        if set(value) != set(DEFAULTS):
            raise MetaError("invalid")
        object_id(value["appId"])
        object_id(value["configId"])
        if not re.fullmatch("v[1-9][0-9]\\.0", value["graphVersion"]):
            raise MetaError("invalid")
        if value["relayOrigin"]:
            RelayConfig.parse(value["relayOrigin"], value["appId"])
        with self.lock:
            if self.pending:
                raise MetaError("pending")
            with self.sessions.begin() as db:
                row = db.get(AppSetting, "meta.service." + self.owner)
                if row:
                    row.value = json.dumps(value)
                else:
                    db.add(AppSetting(key="meta.service." + self.owner, value=json.dumps(value)))

    def owned(self, db, identifier):
        row = db.scalar(
            select(MetaAccount).where(MetaAccount.id == identifier, MetaAccount.owner == self.owner)
        )
        if row is None:
            raise MetaError("not_found")
        return row

    def readiness(self, row, platform=None):
        if row.state != "connected":
            return row.state
        if row.app_id != self.config()["appId"]:
            return "identity"
        now = utcnow() + timedelta(seconds=30)
        if row.data_expires_at <= now or row.page_expires_at and row.page_expires_at <= now:
            return "expired"
        required = set(SCOPES[:3]) if platform == "facebook" else set(SCOPES)
        if platform == "instagram" and not row.instagram_id:
            return "permission"
        if platform and not required <= set(row.scopes):
            return "permission"
        return "connected"

    def accounts(self):
        with self.sessions() as db:
            rows = db.scalars(
                select(MetaAccount)
                .where(MetaAccount.owner == self.owner)
                .order_by(MetaAccount.updated_at.desc())
            ).all()
            return [
                {
                    "id": r.id,
                    "label": r.label,
                    "pageId": r.page_id,
                    "instagramId": r.instagram_id,
                    "instagramName": r.instagram_name,
                    "state": self.readiness(r),
                    "scopes": r.scopes,
                    "tasks": r.tasks,
                    "userExpiresAt": r.user_expires_at.isoformat(),
                    "pageExpiresAt": r.page_expires_at.isoformat() if r.page_expires_at else None,
                    "dataExpiresAt": r.data_expires_at.isoformat(),
                    "facebookReady": self.readiness(r, "facebook") == "connected",
                    "instagramReady": self.readiness(r, "instagram") == "connected",
                    "revision": r.revision,
                    "cleanupRequired": r.state == "disconnected" and bool(r.user_ref or r.page_ref),
                }
                for r in rows
            ]

    def status(self):
        with self.lock:
            state = self.authorization.snapshot() if self.pending and self.authorization else {}
            return {
                "config": self.config(),
                "accounts": self.accounts(),
                "pending": bool(self.pending),
                "error": self.error,
                "cleanupPending": self.cleanup_pending,
                "pages": state.get("pages", []),
                "loginState": state.get("relay_state", "idle"),
                "configured": bool(self.config()["relayOrigin"]),
                "requirement": "Facebook 페이지에 연결된 Instagram 비즈니스·크리에이터 계정이 필요합니다. 개인 계정은 지원하지 않습니다.",
            }

    def begin(self, *, consent=False, reconnect=None):
        if consent is not True:
            raise MetaError("consent")
        cfg = self.config()
        if not cfg["relayOrigin"]:
            raise MetaError("configuration")
        with self.lock:
            if self.pending:
                raise MetaError("pending")
            if reconnect:
                with self.sessions() as db:
                    self.owned(db, reconnect)
            backend = self.factory(
                RelayConfig.parse(cfg["relayOrigin"], cfg["appId"]),
                config_id=cfg["configId"],
                graph_version=cfg["graphVersion"],
            )
            backend.prepare()
            op = uuid4().hex
            self.pending = op
            self.authorization = backend
            self.error = None
            thread = Thread(target=self._worker, args=(op, backend, cfg, reconnect), daemon=True)
            thread.start()

    def _worker(self, op, backend, cfg, reconnect):
        try:
            grant = backend.authorize(scopes=SCOPES)
            with self.lock:
                if self.pending != op:
                    raise MetaError("disconnected")
                self.accept(grant, app_id=cfg["appId"], reconnect=reconnect)
        except Exception as e:  # noqa: BLE001 - never expose provider, credential or native exception details
            with self.lock:
                if self.pending == op:
                    self.error = (
                        e.code
                        if isinstance(e, MetaError)
                        else {
                            "expired": "expired",
                            "permission_denied": "permission",
                            "professional_required": "permission",
                            "identity_mismatch": "identity",
                            "cancelled": "disconnected",
                            "authentication_failed": "expired",
                        }.get(getattr(e, "code", ""), "unknown")
                    )
        finally:
            with self.lock:
                if self.pending == op:
                    self.pending = None

    def select_page(self, page):
        with self.lock:
            if not self.pending or not self.authorization:
                raise MetaError("pending")
            self.authorization.select_page(object_id(page))

    def cancel(self):
        with self.lock:
            if self.authorization:
                self.authorization.cancel()
            self.pending = None

    def accept(self, grant, *, app_id, reconnect=None):
        # Only called with a verified relay result, never from a route/request token body.
        if not isinstance(grant, Grant) or grant.app_id != app_id or app_id != self.config()["appId"]:
            raise MetaError("identity")
        if min(grant.user_expires_at, grant.data_expires_at) <= utcnow() + timedelta(seconds=30):
            raise MetaError("expired")
        with self.sessions() as db:
            prior = (
                self.owned(db, reconnect)
                if reconnect
                else db.scalar(
                    select(MetaAccount).where(
                        MetaAccount.owner == self.owner,
                        MetaAccount.app_id == app_id,
                        MetaAccount.page_id == grant.page_id,
                    )
                )
            )
            if prior and (
                prior.page_id != grant.page_id
                or prior.app_id != app_id
                or (prior.instagram_id != grant.instagram_id and not reconnect)
            ):
                raise MetaError("identity")
            identifier = prior.id if prior else uuid4().hex
            revision = prior.revision if prior else 0
        identity = fingerprint([self.owner, app_id, grant.page_id, grant.instagram_id])
        created = []
        try:
            user_ref = self.vault.put(
                identifier,
                identity,
                TokenBundle(
                    access_token=grant.user_token, expires_at=grant.user_expires_at, scopes=grant.scopes
                ),
            )
            created.append(user_ref)
            expiry = (
                min(grant.data_expires_at, grant.page_expires_at)
                if grant.page_expires_at
                else grant.data_expires_at
            )
            page_ref = self.vault.put(
                identifier,
                identity,
                TokenBundle(access_token=grant.page_token, expires_at=expiry, scopes=grant.scopes),
            )
            created.append(page_ref)
            old = []
            old_identity = identity
            with self.sessions() as db:
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                row = db.get(MetaAccount, identifier)
                if row and (row.owner != self.owner or row.revision != revision):
                    raise MetaError("pending")
                if row:
                    old = [r for r in (row.user_ref, row.page_ref) if r]
                    old_identity = row.identity
                else:
                    row = MetaAccount(id=identifier, owner=self.owner, app_id=app_id, page_id=grant.page_id)
                    db.add(row)
                row.label = grant.page_name
                row.instagram_id = grant.instagram_id
                row.instagram_name = grant.instagram_name
                row.scopes = list(grant.scopes)
                row.tasks = list(grant.tasks)
                row.state = "connected"
                row.revision = revision + 1
                row.user_expires_at = grant.user_expires_at
                row.page_expires_at = grant.page_expires_at
                row.data_expires_at = grant.data_expires_at
                row.identity = identity
                row.user_ref = user_ref
                row.page_ref = page_ref
                row.updated_at = utcnow()
                db.commit()
            created = []
            for ref in old:
                try:
                    self.vault.delete(identifier, old_identity, ref)
                except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
                    self.cleanup_pending = True  # Keep unreferenced ciphertext inaccessible; report cleanup.
            return identifier
        finally:
            for ref in created:
                try:
                    self.vault.delete(identifier, identity, ref)
                except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
                    self.cleanup_pending = True

    def disconnect(self, identifier):
        with self.lock:
            if self.pending:
                raise MetaError("pending")
            with self.sessions.begin() as db:
                row = self.owned(db, identifier)
                row.state = "disconnected"
                row.revision += 1
                row.updated_at = utcnow()
                refs = [r for r in (row.user_ref, row.page_ref) if r]
                identity = row.identity
            for ref in refs:
                self.vault.delete(identifier, identity, ref)
            with self.sessions.begin() as db:
                row = self.owned(db, identifier)
                row.user_ref = None
                row.page_ref = None

    def rename(self, identifier, label):
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 200:
            raise MetaError("invalid")
        with self.sessions.begin() as db:
            self.owned(db, identifier).label = label.strip()

    def credential(self, identifier, platform, revision=None):
        if platform not in {"facebook", "instagram"}:
            raise MetaError("invalid")
        with self.sessions() as db:
            row = self.owned(db, identifier)
            status = self.readiness(row, platform)
            if status != "connected":
                raise MetaError(status)
            if revision is not None and row.revision != revision:
                raise MetaError("identity")
            token = self.vault.get(row.id, row.identity, row.page_ref).access_token
            return token, row.page_id if platform == "facebook" else row.instagram_id, row.revision

    def invalidate(self, identifier, code):
        if code not in {"expired", "permission"}:
            return
        with self.sessions.begin() as db:
            self.owned(db, identifier).state = code
