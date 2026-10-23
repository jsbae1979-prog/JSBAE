"""Deploy separately behind HTTPS. Stores only one validated JPG per request, never OAuth/MP4/DB.

No default app, deployment, bucket creation or background cleanup. A server operator supplies
an isolated storage directory, HTTPS origin and server-side upload secret. Expired images are
inaccessible immediately; cleanup_expired explicitly removes their JPG/receipt pair.
"""
import hashlib
import hmac
import json
import re
import time
import warnings
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from PIL import Image

from .service import PublishingError

MAX_BYTES = 2 * 1024 * 1024


def validate_jpeg(raw):
    try:
        if not 0 < len(raw) <= MAX_BYTES:
            raise ValueError
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if image.format != "JPEG" or image.size != (1080, 1350) or image.getexif():
                    raise ValueError
                image.verify()
    except Exception:  # noqa: BLE001 - never return decoder/file metadata
        raise PublishingError("1080×1350 JPEG 1장, 2MiB 이하만 전송할 수 있습니다.") from None


def cleanup_expired(root: Path, now=None):
    now = time.time() if now is None else now
    for receipt in root.glob("*.json"):
        if not re.fullmatch(r"[a-f0-9]{32}\.json", receipt.name) or receipt.is_symlink():
            continue
        meta = json.loads(receipt.read_text("utf-8"))
        if meta["expires_at"] <= now:
            image = receipt.with_suffix(".jpg")
            if image.is_symlink():
                continue
            image.unlink(missing_ok=True)
            receipt.unlink()


def create_delivery_app(root: Path, public_origin: str, upload_secret: str, *, ttl_seconds=3600, clock=time.time):
    from .image_delivery import delivery_origin
    origin = delivery_origin(public_origin)
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", upload_secret) or not 900 <= ttl_seconds <= 86400:
        raise ValueError("Dedicated secret and bounded retention required")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/v1/images")
    async def put(request: Request):
        if request.url.scheme != "https":
            raise HTTPException(400, "HTTPS required")
        authorization = request.headers.get("authorization", "")
        if not hmac.compare_digest(authorization.encode("utf-8"), ("Bearer " + upload_secret).encode("ascii")):
            raise HTTPException(401, "Unauthorized")
        if request.headers.get("content-type") != "image/jpeg":
            raise HTTPException(415, "JPEG only")
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > MAX_BYTES:
                raise HTTPException(413, "Image too large")
        try:
            validate_jpeg(raw)
        except PublishingError:
            raise HTTPException(422, "Invalid feed JPEG") from None
        identifier, digest = uuid4().hex, hashlib.sha256(raw).hexdigest()
        target = root / (identifier + ".jpg")
        expires_at = clock() + ttl_seconds
        with target.open("xb") as output:
            output.write(raw)
        (root / (identifier + ".json")).write_text(json.dumps({
            "sha256": digest, "expires_at": expires_at}), encoding="utf-8")
        return {"url": origin + "/images/" + target.name, "sha256": digest, "expires_at": expires_at}

    @app.get("/images/{name}")
    def image(name: str, request: Request):
        if request.url.scheme != "https" or not re.fullmatch(r"[a-f0-9]{32}\.jpg", name):
            raise HTTPException(404)
        target, receipt = root / name, root / (name[:-4] + ".json")
        if target.is_symlink() or receipt.is_symlink() or not receipt.is_file() or not target.is_file():
            raise HTTPException(404)
        meta = json.loads(receipt.read_text("utf-8"))
        if meta["expires_at"] <= clock():
            raise HTTPException(410)
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
            raise HTTPException(409)
        return Response(raw, media_type="image/jpeg", headers={"Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff"})

    @app.get("/robots.txt")
    def robots():
        return Response("User-agent: *\nAllow: /images/\nDisallow: /v1/\n", media_type="text/plain")
    return app


def from_env():
    """Explicit deployment factory; Windows app startup never calls or hosts this service."""
    import os
    return create_delivery_app(Path(os.environ["NEWSFLOW_FEED_STORAGE"]),
                               os.environ["NEWSFLOW_FEED_PUBLIC_ORIGIN"],
                               os.environ["NEWSFLOW_FEED_UPLOAD_SECRET"])
