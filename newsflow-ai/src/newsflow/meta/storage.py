"""Bring-your-own temporary storage URLs. No hosting account or real upload on configuration."""

import json
from datetime import datetime, timedelta
from hashlib import sha256
from urllib.parse import urlsplit

from pydantic import SecretStr

from newsflow.db.models import AppSetting, utcnow
from newsflow.news.rss_adapter import PinnedConnection, public_addresses
from newsflow.publishing.auth import TokenBundle

from .contracts import MetaError, fingerprint
from .media import LIMIT, validate_media


def storage_url(value):
    try:
        u = urlsplit(value)
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 4096
            or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
            or u.scheme != "https"
            or not u.hostname
            or u.username
            or u.password
            or u.fragment
            or u.port not in (None, 443)
            or not u.path
            or "\\" in value
        ):
            raise ValueError
        return value
    except Exception:  # noqa: BLE001 - redact signed URLs and storage/native errors
        raise MetaError("media") from None


def transfer(method, url, raw=None, kind=None):
    u = urlsplit(storage_url(url))
    # Re-resolve and pin each independent request; no redirects, cookies, or credentials to other hosts.
    addresses = public_addresses(u.hostname, 443, 30)
    conn = PinnedConnection(u.hostname, addresses[0], 443, 60, True)
    try:
        target = u.path + ("?" + u.query if u.query else "")
        headers = {"Content-Type": "image/jpeg" if kind == "image" else "video/mp4"} if raw else {}
        conn.request(method, target, body=raw, headers=headers)
        response = conn.getresponse()
        if not 200 <= response.status < 300 or response.getheader("Content-Encoding"):
            raise MetaError("unknown")
        body = response.read(LIMIT + 1 if method == "GET" else 8193)
        if len(body) > (LIMIT if method == "GET" else 8192):
            raise MetaError("media")
        return body
    finally:
        conn.close()


class StorageLinks:
    def __init__(self, accounts, transport=None):
        self.accounts = accounts
        self.transport = transport or transfer

    def keys(self, digest):
        identifier = fingerprint([self.accounts.owner, "storage", digest])[:32]
        return "meta.storage." + self.accounts.owner + "." + digest, identifier

    def config(self, digest):
        key, _ = self.keys(digest)
        with self.accounts.sessions() as db:
            row = db.get(AppSetting, key)
            return json.loads(row.value) if row else None

    def ready(self, digest):
        cfg = self.config(digest)
        return bool(
            cfg
            and cfg["state"] == "prepared"
            and datetime.fromisoformat(cfg["expires"]) > utcnow() + timedelta(minutes=15)
        )

    def configure(
        self,
        digest,
        put_url,
        get_url,
        expires,
        *,
        automatic_identity=None,
        object_key=None,
        reuse_uploaded=False,
    ):
        storage_url(put_url)
        storage_url(get_url)
        try:
            expiry = datetime.fromisoformat(expires)
            if expiry.tzinfo is None or not utcnow() + timedelta(minutes=15) < expiry <= utcnow() + timedelta(
                days=7
            ):
                raise ValueError
        except (TypeError, ValueError):
            raise MetaError("invalid") from None
        key, identifier = self.keys(digest)
        identity = fingerprint([self.accounts.owner, digest])
        old = self.config(digest)
        # A failed/unknown upload is never reset by entering the same or another URL.
        if old and old["state"] not in {"prepared", "uploaded"}:
            raise MetaError("unknown")
        if reuse_uploaded and (
            not old
            or old["state"] != "uploaded"
            or old.get("automaticIdentity") != automatic_identity
            or old.get("objectKey") != object_key
        ):
            raise MetaError("invalid")
        ref = self.accounts.vault.put(
            identifier,
            identity,
            TokenBundle(
                access_token=SecretStr(put_url),
                refresh_token=SecretStr(get_url),
                expires_at=expiry,
                scopes=("media_upload",),
            ),
        )
        try:
            with self.accounts.sessions() as db:
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                existing = db.get(AppSetting, key)
                if (json.loads(existing.value) if existing else None) != old:
                    raise MetaError("pending")
                value = json.dumps(
                    {
                        "reference": ref,
                        "identity": identity,
                        "expires": expiry.isoformat(),
                        "state": "uploaded" if reuse_uploaded else "prepared",
                        **(
                            {"automaticIdentity": automatic_identity, "objectKey": object_key}
                            if automatic_identity
                            else {}
                        ),
                    }
                )
                row = db.get(AppSetting, key)
                if row:
                    row.value = value
                else:
                    db.add(AppSetting(key=key, value=value))
                db.commit()
        except Exception:  # noqa: BLE001 - redact signed URLs and storage/native errors
            self.accounts.vault.delete(identifier, identity, ref)
            raise MetaError("configuration") from None
        if old:
            self.accounts.vault.delete(identifier, old["identity"], old["reference"])

    def upload(self, path, digest, kind):
        if path.stat().st_size > LIMIT:
            raise MetaError("media")
        raw = path.read_bytes()
        validate_media(raw, kind)
        if sha256(raw).hexdigest() != digest:
            raise MetaError("media")
        key, identifier = self.keys(digest)
        with self.accounts.sessions() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            row = db.get(AppSetting, key)
            cfg = json.loads(row.value) if row else None
            if not cfg or cfg["state"] not in {"prepared", "uploaded"}:
                raise MetaError("unknown")
            if datetime.fromisoformat(cfg["expires"]) <= utcnow() + timedelta(minutes=15):
                raise MetaError("expired")
            reuse = cfg["state"] == "uploaded"
            cfg["state"] = "verifying" if reuse else "sending"
            row.value = json.dumps(cfg)
            db.commit()
        try:
            bundle = self.accounts.vault.get(identifier, cfg["identity"], cfg["reference"])
            urls = {
                "put": bundle.access_token.get_secret_value(),
                "get": bundle.refresh_token.get_secret_value(),
            }
            if not reuse:
                self.transport("PUT", urls["put"], raw, kind)
            received = self.transport("GET", urls["get"])
            if sha256(received).hexdigest() != digest:
                raise MetaError("media")
            with self.accounts.sessions.begin() as db:
                cfg["state"] = "uploaded"
                db.get(AppSetting, key).value = json.dumps(cfg)
            return urls["get"]
        except Exception:  # noqa: BLE001 - redact signed URLs and storage/native errors
            with self.accounts.sessions.begin() as db:
                cfg["state"] = "unknown"
                db.get(AppSetting, key).value = json.dumps(cfg)
            raise MetaError("unknown") from None
