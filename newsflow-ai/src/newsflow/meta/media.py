"""Local finished-content resolution and explicit, owner-scoped HTTPS delivery."""

import json
import re
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr

from newsflow.db.models import AppSetting, RenderJob, utcnow
from newsflow.news.rss_adapter import PinnedConnection, public_addresses
from newsflow.publishing.auth import TokenBundle
from newsflow.publishing.image_delivery import delivery_origin

from .contracts import MetaError, fingerprint

LIMIT = 100 * 1024 * 1024


def validate_media(raw, kind):
    if not raw or len(raw) > LIMIT:
        raise MetaError("media")
    if kind == "image":
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(raw)) as im:
            if (
                im.format != "JPEG"
                or im.width > 8192
                or im.height > 8192
                or not 0.8 <= im.width / im.height <= 1.91
            ):
                raise MetaError("media")
            im.verify()
    elif kind != "video" or len(raw) < 16 or raw[4:8] != b"ftyp":
        raise MetaError("media")


def resolve_content(state, identifier):
    from newsflow.publishing.posting_copy import source_for

    try:
        source = source_for(state, identifier)  # Finished, visible content only.
        kind, key = identifier.split(":", 1)
        if kind == "feed":
            from newsflow.creation.feed_designs import FeedDesigns
            from newsflow.studio.feed_library import images

            batch, rank = map(int, key.split(":"))
            feeds = state.top_three_feeds
            item = next(p for p in images(feeds, publishable_only=True) if p["id"] == identifier)
            if item["designVersion"]:
                designs = FeedDesigns(feeds)
                version = designs.version(batch, rank, item["designVersion"])
                path = designs.path(version["filename"], version["sha256"])
            else:
                path = feeds.path(batch, rank)
        elif kind == "character":
            path = state.character.folder(key) / "final.mp4"
        elif kind == "news":
            with state.sessions() as db:
                path = state.video.output_path(db.get(RenderJob, int(key)).output_name)
        elif kind == "image":
            path = state.image_studio.generation.path(state.image_studio.output(int(key)).id)
        else:
            path = state.image_posts.path(int(key))
        root = Path(state.config.data_dir).resolve()
        path = Path(path)
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise MetaError("media")
        for part in (path, *path.parents):
            if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
                raise MetaError("media")
            if part == root:
                break
        if path.stat().st_size > LIMIT:
            raise MetaError("media")
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()
        expected = source["content"].get("output_sha256")
        if expected and expected != digest:
            raise MetaError("media")
        media_kind = "image" if source["kind"] == "image" else "video"
        if media_kind == "image" and raw.startswith(b"\x89PNG\r\n\x1a\n"):
            path, raw = jpeg_derivative(root, raw)
            digest = sha256(raw).hexdigest()
        validate_media(raw, media_kind)
        return {"path": path, "sha256": digest, "kind": media_kind}
    except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
        raise MetaError("media") from None


class MetaDelivery:
    def __init__(self, connections, *, transport=None):
        self.accounts = connections
        self.transport = transport or self._upload
        self.key = "meta.media." + connections.owner
        self.identifier = fingerprint(["media", connections.owner])[:32]

    def config(self):
        with self.accounts.sessions() as db:
            row = db.get(AppSetting, self.key)
            return json.loads(row.value) if row else {}

    def configure(self, origin, credential):
        origin = delivery_origin(origin)
        if not isinstance(credential, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", credential):
            raise MetaError("invalid")
        identity = fingerprint([self.accounts.owner, origin])
        old = self.config()
        ref = self.accounts.vault.put(
            self.identifier,
            identity,
            TokenBundle(
                access_token=SecretStr(credential),
                expires_at=utcnow() + timedelta(days=365),
                scopes=("media_upload",),
            ),
        )
        try:
            with self.accounts.sessions.begin() as db:
                value = json.dumps({"origin": origin, "reference": ref, "identity": identity})
                row = db.get(AppSetting, self.key)
                if row:
                    row.value = value
                else:
                    db.add(AppSetting(key=self.key, value=value))
        except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
            self.accounts.vault.delete(self.identifier, identity, ref)
            raise MetaError("configuration") from None
        if old:
            self.accounts.vault.delete(self.identifier, old["identity"], old["reference"])

    def ready(self):
        # No decryption or remote request during a screen read.
        cfg = self.config()
        return bool(cfg.get("origin") and cfg.get("reference"))

    @staticmethod
    def _upload(origin, raw, kind, secret):
        host = urlsplit(origin).hostname
        addresses = public_addresses(host, 443, 30)
        conn = PinnedConnection(host, addresses[0], 443, 60, True)
        try:
            conn.request(
                "POST",
                "/v1/media",
                body=raw,
                headers={
                    "Content-Type": "image/jpeg" if kind == "image" else "video/mp4",
                    "Authorization": "Bearer " + secret,
                },
            )
            response = conn.getresponse()
            if response.status != 200 or response.getheader("Content-Encoding"):
                raise MetaError("unknown")
            payload = response.read(8193)
            if len(payload) > 8192:
                raise MetaError("unknown")
            return json.loads(payload)
        finally:
            conn.close()

    def upload(self, path, expected_sha, kind):
        cfg = self.config()
        if not self.ready():
            raise MetaError("configuration")
        if path.stat().st_size > LIMIT:
            raise MetaError("media")
        raw = path.read_bytes()
        validate_media(raw, kind)
        if sha256(raw).hexdigest() != expected_sha:
            raise MetaError("media")
        try:
            secret = self.accounts.vault.get(self.identifier, cfg["identity"], cfg["reference"]).access_token
            result = self.transport(cfg["origin"], raw, kind, secret.get_secret_value())
            suffix = "jpg" if kind == "image" else "mp4"
            if (
                not re.fullmatch(
                    re.escape(cfg["origin"]) + r"/media/[a-f0-9]{64}\." + suffix, result.get("url", "")
                )
                or result.get("sha256") != expected_sha
            ):
                raise MetaError("unknown")
            return result["url"]
        except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
            raise MetaError("unknown") from None


def jpeg_derivative(root, raw):
    """Create a deterministic posting copy; never rewrite the user's PNG."""
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(raw)) as image:
        if image.format != "PNG" or image.width > 8192 or image.height > 8192:
            raise MetaError("media")
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", image.size, "white")
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        output = BytesIO()
        canvas.save(output, format="JPEG", quality=95, subsampling=0)
    result = output.getvalue()
    validate_media(result, "image")
    folder = Path(root) / "meta-publish-media"
    if folder.is_symlink() or (hasattr(folder, "is_junction") and folder.is_junction()):
        raise MetaError("media")
    folder.mkdir(exist_ok=True)
    path = folder / (sha256(result).hexdigest() + ".jpg")
    if path.is_symlink() or (path.exists() and path.read_bytes() != result):
        raise MetaError("media")
    try:
        with path.open("xb") as stream:
            stream.write(result)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != result:
            raise MetaError("media") from None
    return path, result
