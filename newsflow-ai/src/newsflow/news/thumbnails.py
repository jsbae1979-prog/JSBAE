"""Supplied preview URLs and bounded safe raster previews, never article scraping."""
from __future__ import annotations

import time
import warnings
from collections import OrderedDict
from html.parser import HTMLParser
from io import BytesIO
from threading import Lock
from urllib.parse import urljoin, urlsplit

from PIL import Image, ImageOps

from .rss_adapter import MAX_BYTES, FeedError, PublicRSSAdapter, validate_url


def thumbnail_url(value, base: str = "") -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        url = validate_url(urljoin(base, value.strip()))
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname in {"serpapi.com", "api.openai.com", "api.anthropic.com"}:
            return None
        return url
    except (FeedError, ValueError):
        return None


class _FeedImage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.src = None

    def handle_starttag(self, tag, attrs):
        if tag == "img" and self.src is None:
            self.src = dict(attrs).get("src")


def rss_thumbnail(entry: dict, article_url: str) -> str | None:
    candidates = [r.get("url") for r in entry.get("media_thumbnail", []) if isinstance(r, dict)]
    for row in [*entry.get("media_content", []), *entry.get("enclosures", [])]:
        if isinstance(row, dict) and (row.get("medium") == "image" or str(row.get("type", "")).startswith("image/")):
            candidates.append(row.get("url") or row.get("href"))
    html = _FeedImage()
    html.feed(entry.get("summary", ""))
    candidates.append(html.src)
    return next((url for value in candidates if (url := thumbnail_url(value, article_url))), None)


def raster_preview(raw: bytes) -> bytes:
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("preview_size")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(raw)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP", "GIF"} or image.width * image.height > 16_000_000:
                raise ValueError("preview_format_or_dimensions")
            image.seek(0)
            # Fresh image strips EXIF/comments, animation, scripts and external references.
            frame = ImageOps.exif_transpose(image).convert("RGB")
            frame.thumbnail((320, 180))
            clean = Image.new("RGB", frame.size)
            clean.paste(frame)
            output = BytesIO()
            clean.save(output, format="JPEG", quality=82)
            return output.getvalue()


class _HTTPSOnlyTransport:
    def __init__(self, transport):
        self.transport = transport

    def get(self, url, timeout):
        if urlsplit(url).scheme != "https":
            raise FeedError("이미지 HTTPS 연결을 확인해 주세요.")
        return self.transport.get(url, timeout)


class ThumbnailService:
    """Same RSS TLS/robots/DNS pinning policy; bounded cache also remembers failures."""

    def __init__(self, adapter):
        self.adapter = PublicRSSAdapter(_HTTPSOnlyTransport(adapter.transport)) if isinstance(adapter, PublicRSSAdapter) else adapter
        self.cache = OrderedDict()
        self.lock = Lock()

    def get(self, url: str) -> bytes | None:
        safe = thumbnail_url(url)
        if safe is None:
            return None
        # Serialize misses to prevent duplicate downloads for the same image.
        with self.lock:
            cached = self.cache.get(safe)
            if cached and time.monotonic() - cached[0] < 600:
                self.cache.move_to_end(safe)
                return cached[1]
            try:
                result = raster_preview(self.adapter.fetch(safe, 6))
            except Exception:  # noqa: BLE001 - never expose transport URLs, supplier text or credentials
                result = None
            self.cache[safe] = (time.monotonic(), result)
            self.cache.move_to_end(safe)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return result
