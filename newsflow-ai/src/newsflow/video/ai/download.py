"""Bounded, SSRF-safe HTTPS download of one generated clip (Phase 5D).

Reuses the RSS adapter's URL validation, public-address DNS pinning and verified TLS connection
without changing the RSS policy itself. Rules for every hop: HTTPS only, default port, no
userinfo or fragment, every resolved address public, at most 3 redirects (each re-validated),
identity encoding only, a video or octet-stream content type, a byte limit, a wall-clock limit
and cancellation. The provider credential is never sent to the download host. The file is
written with exclusive creation and removed on any failure.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import ssl
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

from newsflow.news.rss_adapter import (
    FeedError,
    PinnedConnection,
    URLPolicyError,
    public_addresses,
    validate_url,
)

from .contracts import ClipDownloadError, FetchResult

MAX_CLIP_BYTES = 200 * 1024 * 1024
MAX_REDIRECTS = 3
USER_AGENT = "NewsFlowAI/0.6 (+local AI video clip download)"
CONTENT_TYPES = frozenset({
    "video/mp4", "video/quicktime", "video/webm", "application/octet-stream", "binary/octet-stream",
})
REDIRECTS = frozenset({301, 302, 303, 307, 308})
MAX_QUERY = 6000
DIGITS = re.compile(r"[0-9]{1,15}")


class Response(Protocol):
    status: int

    def getheader(self, name: str, default: str | None = None) -> str | None: ...
    def read1(self, amount: int) -> bytes: ...


Opener = Callable[[str, str, float], tuple[Response, Callable[[], None]]]


def safe_url(url: str) -> str:
    """HTTPS-only, default port, no userinfo/fragment, public host; returns the normalised URL.

    The address without its query goes through the RSS ``validate_url`` unchanged. The query is
    kept apart because a result URL may be a signed CDN address whose signature parameters look
    like credentials to the RSS rule; it is checked for length and characters instead. Result URLs
    are never stored or logged, and no provider credential is sent to the download host.
    """
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ClipDownloadError()
    if any(ord(c) <= 32 or ord(c) >= 127 for c in url) or "\\" in url or "#" in url:
        raise ClipDownloadError()
    base, _, query = url.partition("?")
    if len(query) > MAX_QUERY:
        raise ClipDownloadError()
    try:
        normal = validate_url(base)
    except (URLPolicyError, FeedError):
        raise ClipDownloadError() from None
    if urlsplit(normal).scheme != "https":
        raise ClipDownloadError()
    return f"{normal}?{query}" if query else normal


def pinned_opener(url: str, method: str, timeout: float) -> tuple[Response, Callable[[], None]]:
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        addresses = public_addresses(host, 443, timeout)
    except (URLPolicyError, FeedError):
        raise ClipDownloadError() from None
    connection = PinnedConnection(host, addresses[0], 443, timeout, True)
    path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
    try:
        connection.request(method, path, headers={
            # An explicit Host keeps http.client from adding ':443' (signed URLs may sign the Host).
            "Host": host, "User-Agent": USER_AGENT, "Accept": "video/*, application/octet-stream",
            "Accept-Encoding": "identity",
        })
        return connection.getresponse(), connection.close
    except (OSError, ssl.SSLError, http.client.HTTPException):
        connection.close()
        raise ClipDownloadError() from None


class SafeDownloader:
    def __init__(
        self, opener: Opener | None = None, *, max_bytes: int = MAX_CLIP_BYTES, timeout: float = 180,
        connect_timeout: float = 20,
    ) -> None:
        self.opener = opener or pinned_opener
        self.max_bytes, self.timeout, self.connect_timeout = max_bytes, timeout, connect_timeout

    def fetch(self, url: str, target: Path, cancel: Event) -> FetchResult:
        deadline = time.monotonic() + self.timeout
        current = safe_url(url)
        for _ in range(MAX_REDIRECTS + 1):
            if cancel.is_set() or time.monotonic() > deadline:
                raise ClipDownloadError()
            response, close = self.opener(current, "GET", self.connect_timeout)
            try:
                if response.status in REDIRECTS:
                    location = response.getheader("Location")
                    if not location:
                        raise ClipDownloadError()
                    current = safe_url(urljoin(current, location))
                    continue
                if response.status != 200:
                    raise ClipDownloadError()
                return self._stream(response, current, target, cancel, deadline)
            finally:
                close()
        raise ClipDownloadError()

    def _stream(self, response: Response, url: str, target: Path, cancel: Event, deadline: float) -> FetchResult:
        encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
        kind = (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
        if encoding not in {"identity", ""} or kind not in CONTENT_TYPES:
            raise ClipDownloadError()
        declared = response.getheader("Content-Length")
        if declared is not None and (not DIGITS.fullmatch(declared.strip()) or int(declared) > self.max_bytes):
            raise ClipDownloadError()
        digest, size = hashlib.sha256(), 0
        created = False
        try:
            with target.open("xb") as handle:
                created = True
                while True:
                    if cancel.is_set() or time.monotonic() > deadline:
                        raise ClipDownloadError()
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ClipDownloadError()
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if size == 0 or (declared is not None and size != int(declared)):
                raise ClipDownloadError()
        except ClipDownloadError:
            if created:
                target.unlink(missing_ok=True)
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException):
            if created:
                target.unlink(missing_ok=True)
            raise ClipDownloadError() from None
        return FetchResult(target, size, digest.hexdigest(), urlsplit(url).hostname or "")
