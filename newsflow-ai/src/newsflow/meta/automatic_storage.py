"""Owner-owned S3-compatible storage. Sign locally; upload only after publication consent."""

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit
from uuid import uuid4

from pydantic import SecretStr

from newsflow.db.models import AppSetting, utcnow
from newsflow.publishing.auth import TokenBundle

from .contracts import MetaError, fingerprint
from .storage import storage_url


def presign(method, endpoint, region, bucket, key, access, secret, now, seconds=86400):
    """AWS SigV4 query signing, path style; only caller-owned object keys."""
    if method not in {"GET", "PUT"} or not 900 <= seconds <= 604800:
        raise MetaError("invalid")
    host = urlsplit(endpoint).netloc
    path = "/" + quote(bucket, safe="") + "/" + quote(key, safe="/")
    date = now.strftime("%Y%m%d")
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    scope = f"{date}/{region}/s3/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": access + "/" + scope,
        "X-Amz-Date": stamp,
        "X-Amz-Expires": str(seconds),
        "X-Amz-SignedHeaders": "host",
    }
    query = "&".join(quote(k, safe="") + "=" + quote(v, safe="") for k, v in sorted(params.items()))
    canonical = f"{method}\n{path}\n{query}\nhost:{host}\n\nhost\nUNSIGNED-PAYLOAD"
    to_sign = (
        "AWS4-HMAC-SHA256\n" + stamp + "\n" + scope + "\n" + hashlib.sha256(canonical.encode()).hexdigest()
    )
    signature = sign_string(to_sign, date, region, secret)
    return endpoint + path + "?" + query + "&X-Amz-Signature=" + signature


def sign_string(to_sign, date, region, secret):
    signing = ("AWS4" + secret).encode()
    for part in (date, region, "s3", "aws4_request"):
        signing = hmac.new(signing, part.encode(), hashlib.sha256).digest()
    return hmac.new(signing, to_sign.encode(), hashlib.sha256).hexdigest()


class AutomaticStorage:
    def __init__(self, accounts, links):
        self.accounts, self.links = accounts, links
        self.key = "meta.auto-storage." + accounts.owner
        self.identifier = fingerprint([accounts.owner, "auto-storage"])[:32]

    def config(self):
        with self.accounts.sessions() as db:
            row = db.get(AppSetting, self.key)
            return json.loads(row.value) if row else None

    def ready(self):
        return bool(self.config())  # No vault access or network on page load.

    def configure(self, endpoint, region, bucket, access_key, secret_key):
        try:
            endpoint = endpoint.rstrip("/")
            u = urlsplit(storage_url(endpoint + "/"))
            if u.path != "/" or u.query or u.netloc != u.hostname:
                raise ValueError
            if not re.fullmatch(r"[a-z0-9-]{1,40}", region):
                raise ValueError
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
                raise ValueError
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", access_key):
                raise ValueError
            if not re.fullmatch(r"[A-Za-z0-9/+=_-]{16,256}", secret_key):
                raise ValueError
        except (ValueError, TypeError):
            raise MetaError("invalid") from None
        with self.accounts.lock:
            old = self.config()
            identity = fingerprint([self.accounts.owner, endpoint, region, bucket])
            ref = self.accounts.vault.put(
                self.identifier,
                identity,
                TokenBundle(
                    access_token=SecretStr(access_key),
                    refresh_token=SecretStr(secret_key),
                    expires_at=utcnow() + timedelta(days=365),
                    scopes=("media_upload",),
                ),
            )
            try:
                with self.accounts.sessions.begin() as db:
                    value = json.dumps(
                        {
                            "endpoint": endpoint,
                            "region": region,
                            "bucket": bucket,
                            "identity": identity,
                            "reference": ref,
                        }
                    )
                    row = db.get(AppSetting, self.key)
                    if row:
                        row.value = value
                    else:
                        db.add(AppSetting(key=self.key, value=value))
            except Exception:  # noqa: BLE001 - redact vault and database failures
                self.accounts.vault.delete(self.identifier, identity, ref)
                raise MetaError("configuration") from None
            if old:
                self.accounts.vault.delete(self.identifier, old["identity"], old["reference"])

    def renewable(self, link):
        cfg = self.config()
        return bool(
            cfg
            and link["state"] in {"prepared", "uploaded"}
            and link.get("automaticIdentity") == cfg["identity"]
            and re.fullmatch(
                r"newsflow/" + re.escape(self.accounts.owner) + r"/[a-f0-9]{32}\.(?:jpg|mp4)",
                link.get("objectKey", ""),
            )
        )

    def provision(self, digest, kind):
        # Called inside the owner's publication lock, after explicit send consent.
        # Existing unknown/in-flight upload records are never reset or replaced.
        old = self.links.config(digest)
        if old and (
            not self.renewable(old) or datetime.fromisoformat(old["expires"]) > utcnow() + timedelta(hours=1)
        ):
            return
        cfg = self.config()
        if not cfg:
            raise MetaError("configuration")
        bundle = self.accounts.vault.get(self.identifier, cfg["identity"], cfg["reference"])
        now = utcnow()
        key = (
            old["objectKey"]
            if old
            else "newsflow/"
            + self.accounts.owner
            + "/"
            + uuid4().hex
            + (".jpg" if kind == "image" else ".mp4")
        )
        urls = [
            presign(
                method,
                cfg["endpoint"],
                cfg["region"],
                cfg["bucket"],
                key,
                bundle.access_token.get_secret_value(),
                bundle.refresh_token.get_secret_value(),
                now,
            )
            for method in ("PUT", "GET")
        ]
        self.links.configure(
            digest,
            *urls,
            (now + timedelta(days=1)).isoformat(),
            automatic_identity=cfg["identity"],
            object_key=key,
            reuse_uploaded=bool(old and old["state"] == "uploaded"),
        )
