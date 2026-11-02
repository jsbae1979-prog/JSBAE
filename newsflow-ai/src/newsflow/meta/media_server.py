"""Separately deployed TLS media service. Credentials are individually revocable.

The operator injects a credential SHA-256 -> tenant ID mapping; never ship its
values or the operator's secrets in a desktop package. URLs expire after TTL.
"""

import json
import re
import secrets
import time
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from newsflow.publishing.image_delivery import delivery_origin

from .media import LIMIT, validate_media


def create_media_app(root, origin, credential_owners, *, ttl=3600, clock=time.time):
    root = Path(root)
    origin = delivery_origin(origin)
    if not 900 <= ttl <= 86400 or not credential_owners:
        raise ValueError("media configuration")
    if any(
        not re.fullmatch(r"[a-f0-9]{64}", key) or not re.fullmatch(r"[a-f0-9]{32}", owner)
        for key, owner in credential_owners.items()
    ):
        raise ValueError("credential configuration")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        raise ValueError("media root")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/v1/media")
    async def upload(request: Request):
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(403, "credential required")
        owner = credential_owners.get(sha256(auth[7:].encode()).hexdigest())
        if not owner:
            raise HTTPException(403, "credential invalid")
        content_type = request.headers.get("content-type", "")
        kind = {"image/jpeg": "image", "video/mp4": "video"}.get(content_type)
        if not kind:
            raise HTTPException(415, "JPEG or MP4 required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > LIMIT:
                raise HTTPException(413, "media too large")
        try:
            validate_media(raw, kind)
        except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
            raise HTTPException(422, "invalid media") from None
        filename = secrets.token_hex(32) + (".jpg" if kind == "image" else ".mp4")
        digest = sha256(raw).hexdigest()
        with (root / filename).open("xb") as file:
            file.write(raw)
        with (root / (filename + ".json")).open("x", encoding="utf8") as file:
            json.dump({"owner": owner, "expires": clock() + ttl, "sha256": digest}, file)
        return {"url": origin + "/media/" + filename, "sha256": digest, "expiresIn": ttl}

    @app.api_route("/media/{filename}", methods=["GET", "HEAD"])
    def download(filename: str):
        if not re.fullmatch(r"[a-f0-9]{64}\.(jpg|mp4)", filename):
            raise HTTPException(404)
        path = root / filename
        receipt = root / (filename + ".json")
        try:
            if path.is_symlink() or receipt.is_symlink():
                raise ValueError()
            data = json.loads(receipt.read_text(encoding="utf8"))
            if data["expires"] <= clock() or data["owner"] not in credential_owners.values():
                raise ValueError()
            if path.stat().st_size > LIMIT or sha256(path.read_bytes()).hexdigest() != data["sha256"]:
                raise ValueError()
        except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
            raise HTTPException(404) from None
        return FileResponse(
            path,
            media_type="image/jpeg" if filename.endswith(".jpg") else "video/mp4",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    return app


def from_environment():
    """Server-only factory; private credential-map file contains hashes, not tokens."""
    import os

    source = Path(os.environ["NEWSFLOW_META_MEDIA_CREDENTIALS_FILE"])
    if not source.is_absolute() or source.is_symlink() or source.stat().st_size > 65536:
        raise ValueError("credential configuration")
    owners = json.loads(source.read_text(encoding="utf8"))
    if not isinstance(owners, dict):
        raise TypeError("credential configuration")
    root = Path(os.environ["NEWSFLOW_META_MEDIA_ROOT"])
    if not root.is_absolute():
        raise ValueError("media root")
    return create_media_app(
        root,
        os.environ["NEWSFLOW_META_MEDIA_ORIGIN"],
        owners,
        ttl=int(os.environ.get("NEWSFLOW_META_MEDIA_TTL", "3600")),
    )
