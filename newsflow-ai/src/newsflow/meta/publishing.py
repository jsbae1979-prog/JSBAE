"""Durable per-account publication state. No background submission or POST retry."""

from uuid import uuid4

from sqlalchemy import select

from newsflow.db.models import utcnow

from .contracts import MetaError, fingerprint
from .models import MetaPublication


class MetaPublishing:
    def __init__(self, connections, graph, resolver, delivery):
        self.accounts, self.graph, self.resolve, self.delivery = connections, graph, resolver, delivery
        self.sessions, self.owner = connections.sessions, connections.owner

    def owned(self, db, identifier):
        row = db.scalar(
            select(MetaPublication).where(
                MetaPublication.id == identifier, MetaPublication.owner == self.owner
            )
        )
        if row is None:
            raise MetaError("not_found")
        return row

    @staticmethod
    def view(r):
        return {
            "id": r.id,
            "connectionId": r.connection_id,
            "platform": r.platform,
            "targetId": r.target_id,
            "contentId": r.content_id,
            "state": r.state,
            "caption": r.caption,
            "remoteId": r.remote_id,
            "errorCode": r.error_code,
            "canCheck": bool(
                r.container_id
                and r.platform == "instagram"
                and r.state in {"upload_unknown", "upload_failed"}
            ),
            "createdAt": r.created_at.isoformat(),
            "publishedAt": r.published_at.isoformat() if r.published_at else None,
        }

    def list(self):
        with self.sessions() as db:
            return [
                self.view(r)
                for r in db.scalars(
                    select(MetaPublication)
                    .where(MetaPublication.owner == self.owner)
                    .order_by(MetaPublication.created_at.desc())
                    .limit(100)
                )
            ]

    def prepare(self, content_id, targets, caption, *, reviewed=False):
        if reviewed is not True:
            raise MetaError("consent")
        if (
            not isinstance(targets, list)
            or not 1 <= len(targets) <= 20
            or not all(isinstance(t, dict) for t in targets)
            or len({(t.get("connectionId"), t.get("platform")) for t in targets}) != len(targets)
        ):
            raise MetaError("invalid")
        if not isinstance(caption, str) or not caption.strip() or len(caption) > 2200:
            raise MetaError("invalid")
        media = self.resolve(content_id)
        prepared = []
        # Preflight every target before saving any; no token read or network.
        with self.sessions() as db:
            for t in targets:
                if set(t) != {"connectionId", "platform"} or t["platform"] not in {"facebook", "instagram"}:
                    raise MetaError("invalid")
                account = self.accounts.owned(db, t["connectionId"])
                ready = self.accounts.readiness(account, t["platform"])
                if ready != "connected":
                    raise MetaError(ready)
                prepared.append(
                    (
                        account.id,
                        account.revision,
                        t["platform"],
                        account.page_id if t["platform"] == "facebook" else account.instagram_id,
                    )
                )
        result = []
        with self.sessions() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            for account, revision, platform, target in prepared:
                digest = fingerprint([content_id, media["sha256"], caption, platform, target])
                row = db.scalar(
                    select(MetaPublication).where(
                        MetaPublication.owner == self.owner,
                        MetaPublication.connection_id == account,
                        MetaPublication.platform == platform,
                        MetaPublication.fingerprint == digest,
                    )
                )
                if row is None:
                    row = MetaPublication(
                        id=uuid4().hex,
                        owner=self.owner,
                        connection_id=account,
                        connection_revision=revision,
                        target_id=target,
                        platform=platform,
                        content_id=content_id,
                        media_sha256=media["sha256"],
                        media_kind=media["kind"],
                        caption=caption,
                        fingerprint=digest,
                        state="draft",
                    )
                    db.add(row)
                    db.flush()
                result.append(self.view(row))
            db.commit()
        return result

    def configure_storage(self, identifier, put_url, get_url, expires):
        with self.accounts.lock, self.sessions() as db:
            row = self.owned(db, identifier)
            if row.state != "draft":
                raise MetaError("pending")
            media = self.resolve(row.content_id)
            if media["sha256"] != row.media_sha256 or media["kind"] != row.media_kind:
                raise MetaError("media")
            self.delivery.links.configure(row.media_sha256, put_url, get_url, expires)

    def direct(self, platform, kind):
        return bool(hasattr(self.graph, "supports_direct") and self.graph.supports_direct(platform, kind))

    def transfer_modes(self):
        with self.sessions() as db:
            return {
                r.id: "direct" if self.direct(r.platform, r.media_kind) else "storage"
                for r in db.scalars(select(MetaPublication).where(MetaPublication.owner == self.owner))
            }

    def storage_states(self):
        if not hasattr(self.delivery, "available"):
            return {r["id"]: self.delivery.ready() for r in self.list()}
        with self.sessions() as db:
            return {
                r.id: self.direct(r.platform, r.media_kind) or self.delivery.available(r.media_sha256)
                for r in db.scalars(select(MetaPublication).where(MetaPublication.owner == self.owner)).all()
            }

    def _claim(self, identifier, allowed, next_state):
        with self.sessions() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            row = self.owned(db, identifier)
            if row.state not in allowed:
                raise MetaError("unknown" if "unknown" in row.state else "pending")
            snapshot = {c.name: getattr(row, c.name) for c in row.__table__.columns}
            row.state = next_state
            row.updated_at = utcnow()
            db.commit()
            return snapshot

    def _set(self, identifier, state, *, expected=None, **changes):
        with self.sessions.begin() as db:
            row = self.owned(db, identifier)
            if expected is not None and row.state != expected:
                return self.view(row)
            row.state = state
            row.updated_at = utcnow()
            for k, v in changes.items():
                setattr(row, k, v)
            return self.view(row)

    def _error(self, identifier, row, error):
        code = error.code if isinstance(error, MetaError) else "unknown"
        self.accounts.invalidate(row["connection_id"], code)
        with self.sessions() as db:
            upload_only = self.owned(db, identifier).state == "uploading"
        state = "unknown" if code == "unknown" else "failed"
        return self._set(identifier, "upload_" + state if upload_only else state, error_code=code)

    def _token(self, row):
        token, target, _revision = self.accounts.credential(
            row["connection_id"], row["platform"], row["connection_revision"]
        )
        if target != row["target_id"]:
            raise MetaError("identity")
        return token

    def send(self, identifier, *, consent=False):
        with self.accounts.lock:
            if consent is not True:
                raise MetaError("consent")
            # Check local availability before claiming an external operation.
            with self.sessions() as db:
                current = self.owned(db, identifier)
                if current.state != "draft":
                    raise MetaError("pending")
                media = self.resolve(current.content_id)
                if media["sha256"] != current.media_sha256 or media["kind"] != current.media_kind:
                    raise MetaError("media")
            direct = self.direct(current.platform, current.media_kind)
            if not direct and not (
                self.delivery.available(media["sha256"])
                if hasattr(self.delivery, "available")
                else self.delivery.ready()
            ):
                raise MetaError("configuration")
            row = self._claim(identifier, {"draft"}, "sending")
            try:
                token = self._token(row)
                if direct:
                    from .direct_upload import read_media

                    raw = read_media(media["path"], row["media_sha256"], row["media_kind"])
                    if row["platform"] == "facebook":
                        data = self.graph.upload_file(
                            row["target_id"], token, raw, row["media_kind"], row["caption"]
                        )
                        return self._set(
                            identifier, "published_unverified", remote_id=self._id(data, prefer="post_id")
                        )
                    data = self.graph.call(
                        "POST",
                        row["target_id"] + "/media",
                        token,
                        {"caption": row["caption"], "media_type": "REELS", "upload_type": "resumable"},
                    )
                    container = self._id(data)
                    self._set(identifier, "uploading", container_id=container)
                    self.graph.upload_reel(container, token, raw)
                    return self._set(identifier, "processing")
                url = self.delivery.upload(media["path"], row["media_sha256"], row["media_kind"])
                if row["platform"] == "instagram":
                    payload = {"caption": row["caption"]}
                    payload.update(
                        {"image_url": url}
                        if row["media_kind"] == "image"
                        else {"video_url": url, "media_type": "REELS"}
                    )
                    data = self.graph.call("POST", row["target_id"] + "/media", token, payload)
                    return self._set(identifier, "processing", container_id=self._id(data))
                suffix = "photos" if row["media_kind"] == "image" else "videos"
                payload = (
                    {"url": url, "message": row["caption"], "published": "true"}
                    if suffix == "photos"
                    else {"file_url": url, "description": row["caption"], "published": "true"}
                )
                data = self.graph.call("POST", row["target_id"] + "/" + suffix, token, payload)
                return self._set(
                    identifier, "published_unverified", remote_id=self._id(data, prefer="post_id")
                )
            except Exception as error:  # noqa: BLE001 - never expose provider, credential or native exception details
                return self._error(identifier, row, error)

    @staticmethod
    def _id(data, prefer="id"):
        import re

        value = data.get(prefer) or data.get("id")
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9_]{0,80}", value):
            raise MetaError("unknown")
        return value

    def check(self, identifier):
        with self.sessions() as db:
            entity = self.owned(db, identifier)
            row = {c.name: getattr(entity, c.name) for c in entity.__table__.columns}
        if row["state"] == "published":
            return self.list_one(identifier)
        if row["state"] not in {"processing", "published_unverified", "ready"} and not (
            row["state"] in {"upload_unknown", "upload_failed"}
            and row["container_id"]
            and row["platform"] == "instagram"
        ):
            raise MetaError("unknown")
        try:
            token = self._token(row)
            if row["platform"] == "instagram" and row["state"] != "published_unverified":
                data = self.graph.call("GET", row["container_id"], token, {"fields": "status_code"})
                state = data.get("status_code")
                if state == "FINISHED":
                    return self._set(identifier, "ready", expected=row["state"], error_code=None)
                if state in {"ERROR", "EXPIRED"}:
                    return self._set(identifier, "failed", expected=row["state"], error_code="rejected")
                if state != "IN_PROGRESS":
                    raise MetaError("unknown")
                return self.list_one(identifier)
            fields = (
                "id"
                if row["platform"] == "instagram"
                else "id,status,published"
                if row["media_kind"] == "video"
                else "id,is_published"
            )
            data = self.graph.call("GET", row["remote_id"], token, {"fields": fields})
            if data.get("id") != row["remote_id"]:
                raise MetaError("identity")
            if row["platform"] == "facebook":
                confirmed = (
                    (data.get("published") is True and data.get("status", {}).get("video_status") == "ready")
                    if row["media_kind"] == "video"
                    else data.get("is_published") is True
                )
                if not confirmed:
                    return self._set(
                        identifier, "published_unverified", expected=row["state"], error_code=None
                    )
            return self._set(
                identifier, "published", error_code=None, published_at=utcnow(), expected=row["state"]
            )
        except MetaError as error:
            # A failed GET never discards IDs or permits another POST.
            self.accounts.invalidate(row["connection_id"], error.code)
            return self._set(identifier, row["state"], error_code=error.code, expected=row["state"])

    def publish(self, identifier, *, consent=False):
        with self.accounts.lock:
            if consent is not True:
                raise MetaError("consent")
            row = self._claim(identifier, {"ready"}, "publishing")
            try:
                if row["platform"] != "instagram":
                    raise MetaError("invalid")
                token = self._token(row)
                data = self.graph.call(
                    "POST", row["target_id"] + "/media_publish", token, {"creation_id": row["container_id"]}
                )
                return self._set(identifier, "published_unverified", remote_id=self._id(data))
            except Exception as error:  # noqa: BLE001 - never expose provider, credential or native exception details
                return self._error(identifier, row, error)

    def list_one(self, identifier):
        with self.sessions() as db:
            return self.view(self.owned(db, identifier))

    def recover(self):
        with self.sessions.begin() as db:
            rows = db.scalars(
                select(MetaPublication).where(
                    MetaPublication.owner == self.owner,
                    MetaPublication.state.in_(("sending", "uploading", "publishing")),
                )
            ).all()
            for r in rows:
                r.state = "upload_unknown" if r.state == "uploading" else "unknown"
                r.error_code = "unknown"
                r.updated_at = utcnow()
            return len(rows)
