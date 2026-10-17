"""Facebook Login for Business Reels upload; every mutation is a single request.

The container ID is returned before the file is sent so the calling service can
commit its journal. Uploading never publishes. A separate explicit approval is
required for media_publish, and its result ID precedes the permalink lookup.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import ssl
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .adapters import InstagramAdapter
from .auth import TokenBundle
from .youtube import _locked_media

GRAPH_VERSION = "v25.0"
_VERSION_PATH = re.escape(GRAPH_VERSION)
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}"
MAX_BYTES = 1024**3
_MAX_RESPONSE = 256 * 1024
_ID = re.compile(r"[1-9][0-9]{0,31}\Z")
_SCOPES = {"instagram_basic", "instagram_content_publish", "pages_read_engagement"}
_STATUSES = {"IN_PROGRESS", "FINISHED", "PUBLISHED", "ERROR", "EXPIRED"}
_MESSAGES = {
    "approval_required": "선택한 Instagram 계정과 영상의 전송·공개 게시 승인이 필요합니다.",
    "invalid_input": "Instagram 계정·게시 설정을 다시 확인하세요.",
    "media_changed": "검토한 영상 파일이 변경되었거나 접근할 수 없습니다.",
    "authentication": "Instagram 연결 인증이 만료되었거나 유효하지 않습니다. 다시 연결해 주세요.",
    "permission": "Instagram 프로페셔널 계정과 앱 게시 권한을 확인하세요.",
    "limit": "Instagram 사용 한도에 도달했습니다. 자동 재시도하지 않습니다.",
    "rejected": "Instagram이 요청을 거부했습니다. 자동 재시도하지 않습니다.",
    "not_ready": "Instagram 영상 처리가 완료되지 않았습니다. 상태를 확인해 주세요.",
    "unknown": "Instagram 요청 결과를 확인할 수 없습니다. 계정에서 확인하기 전 다시 전송하지 마세요.",
}


class InstagramUploadError(Exception):
    def __init__(self, code: str, *, unknown: bool = False) -> None:
        self.code = code if code in _MESSAGES else "unknown"
        self.unknown = unknown or self.code == "unknown"
        super().__init__(_MESSAGES[self.code])


@dataclass(frozen=True)
class InstagramHTTPResponse:
    status: int
    body: bytes = field(repr=False)


class InstagramTransport(Protocol):
    def request(
        self, method: str, url: str, headers: dict[str, str], body: bytes | BinaryIO,
    ) -> InstagramHTTPResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise InstagramUploadError("invalid_input")
    return value


def _allowed_url(method: str, url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.fragment
                or any(ord(char) <= 32 or ord(char) == 127 for char in url)):
            return False
        if parsed.netloc == "rupload.facebook.com":
            return (method == "POST" and not parsed.query
                    and bool(re.fullmatch(rf"/ig-api-upload/{_VERSION_PATH}/[1-9][0-9]{{0,31}}", parsed.path)))
        if parsed.netloc != "graph.facebook.com":
            return False
        if method == "POST":
            return (not parsed.query
                    and bool(re.fullmatch(rf"/{_VERSION_PATH}/[1-9][0-9]{{0,31}}/(media|media_publish)", parsed.path)))
        return (method == "GET"
                and bool(re.fullmatch(rf"/{_VERSION_PATH}/[1-9][0-9]{{0,31}}", parsed.path))
                and parse_qsl(parsed.query, strict_parsing=True) in (
                    [("fields", "status_code")], [("fields", "id,permalink,owner")]))
    except (TypeError, ValueError):
        return False


class MetaUploadTransport:
    """Pinned official hosts, system TLS trust, streaming bytes, no redirects/retries."""

    def __init__(self, *, timeout: float = 120) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 300:
            raise ValueError("Invalid upload timeout")
        self.timeout = timeout

    def request(
        self, method: str, url: str, headers: dict[str, str], body: bytes | BinaryIO,
    ) -> InstagramHTTPResponse:
        if not _allowed_url(method, url):
            raise InstagramUploadError("invalid_input")
        request = Request(url, data=None if method == "GET" else body, headers=headers, method=method)
        opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
        try:
            try:
                response = opener.open(request, timeout=self.timeout)
            except HTTPError as error:
                response = error
            with response:
                data = response.read(_MAX_RESPONSE + 1)
                if len(data) > _MAX_RESPONSE:
                    raise InstagramUploadError("unknown")
                return InstagramHTTPResponse(response.code, data)
        except InstagramUploadError:
            raise
        except (OSError, URLError, TimeoutError, http.client.HTTPException):
            raise InstagramUploadError("unknown") from None


@dataclass(frozen=True)
class InstagramContainer:
    container_id: str


@dataclass(frozen=True)
class InstagramPublishResult:
    media_id: str
    url: str
    account_id: str


class _HashingBody:
    """http.client consumes bounded reads, never materializes a whole MP4."""

    def __init__(self, stream: BinaryIO, size: int) -> None:
        self.stream, self.size, self.sent = stream, size, 0
        self.digest = hashlib.sha256()

    def read(self, amount: int = 64 * 1024) -> bytes:
        # Bound even an injected transport's unbounded read request.
        amount = min(amount if amount > 0 else 64 * 1024, 1024 * 1024, self.size - self.sent)
        data = self.stream.read(amount)
        self.sent += len(data)
        self.digest.update(data)
        return data


def _credential(bundle: TokenBundle) -> str:
    if (type(bundle) is not TokenBundle or bundle.expires_at <= datetime.now(UTC)
            or not _SCOPES.issubset(bundle.scopes)):
        raise InstagramUploadError("authentication")
    return bundle.access_token.get_secret_value()


def _data(response: InstagramHTTPResponse) -> dict:
    try:
        data = json.loads(response.body)
        if not isinstance(data, dict):
            raise TypeError
    except (ValueError, TypeError):
        raise InstagramUploadError("unknown") from None
    error = data.get("error")
    if response.status == 200 and error is None:
        return data
    code = error.get("code") if isinstance(error, dict) else None
    if response.status == 401 or code in {102, 190}:
        raise InstagramUploadError("authentication")
    if response.status == 429 or code in {4, 17, 32, 613}:
        raise InstagramUploadError("limit")
    if response.status == 403 or code in {10, 200}:
        raise InstagramUploadError("permission")
    if response.status == 408 or response.status >= 500 or 300 <= response.status < 400:
        raise InstagramUploadError("unknown")
    raise InstagramUploadError("rejected")


class InstagramUploadAdapter:
    def __init__(self, transport: InstagramTransport | None = None) -> None:
        self.transport = transport or MetaUploadTransport()

    def _request(self, method: str, url: str, bundle: TokenBundle, body: bytes = b"") -> dict:
        token = _credential(bundle)
        try:
            return _data(self.transport.request(method, url, {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/x-www-form-urlencoded",
                **({"Content-Length": str(len(body))} if method == "POST" else {}),
            }, body))
        except InstagramUploadError:
            raise
        except Exception:  # noqa: BLE001 - never echo a provider response, token, or URI
            raise InstagramUploadError("unknown") from None

    def create_container(self, payload: dict, bundle: TokenBundle, instagram_account_id: str) -> InstagramContainer:
        account_id = _identifier(instagram_account_id)
        if payload.get("upload_approved") is not True:
            raise InstagramUploadError("approval_required")
        if (not isinstance(payload.get("title"), str) or not payload["title"].strip()
                or not isinstance(payload.get("description", ""), str)
                or not isinstance(payload.get("hashtags", []), list)
                or any(not isinstance(tag, str) for tag in payload.get("hashtags", []))
                or payload.get("ai_disclosure") not in {"disclose", "not_required"}):
            raise InstagramUploadError("invalid_input")
        caption = InstagramAdapter().prepare(payload)["caption"]
        # Keep a visible disclosure as well as Meta's official media AI label.
        if payload["ai_disclosure"] == "disclose":
            caption += "\nAI로 생성한 장면이 포함되어 있습니다."
        if len(caption) > 2200 or len(payload.get("hashtags", [])) > 30:
            raise InstagramUploadError("invalid_input")
        data = self._request("POST", f"{GRAPH}/{account_id}/media", bundle, urlencode({
            "media_type": "REELS", "upload_type": "resumable", "caption": caption,
            "is_ai_generated": "true" if payload["ai_disclosure"] == "disclose" else "false",
        }).encode("ascii"))
        try:
            identifier = _identifier(data.get("id"))
            if data.get("uri") != f"{RUPLOAD}/{identifier}":
                raise ValueError
        except (ValueError, InstagramUploadError):
            raise InstagramUploadError("unknown") from None
        return InstagramContainer(identifier)

    def upload(self, path: Path, bundle: TokenBundle, container_id: str, expected_sha256: str) -> None:
        identifier, token = _identifier(container_id), _credential(bundle)
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
            raise InstagramUploadError("invalid_input")
        sending = False
        try:
            with _locked_media(path) as stream:
                size = os.fstat(stream.fileno()).st_size
                if not 0 < size <= MAX_BYTES:
                    raise InstagramUploadError("media_changed")
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                if digest.hexdigest() != expected_sha256:
                    raise InstagramUploadError("media_changed")
                stream.seek(0)
                body = _HashingBody(stream, size)
                sending = True
                response = self.transport.request("POST", f"{RUPLOAD}/{identifier}", {
                    "Authorization": "OAuth " + token, "offset": "0", "file_size": str(size),
                    "Content-Type": "video/mp4", "Content-Length": str(size),
                }, body)
                data = _data(response)
                if (data.get("success") is not True or body.sent != size
                        or body.digest.hexdigest() != expected_sha256):
                    raise InstagramUploadError("unknown")
        except InstagramUploadError:
            raise
        except Exception:  # noqa: BLE001 - path/credentials must not leak from native handles or transport
            raise InstagramUploadError("unknown" if sending else "media_changed") from None

    def status(self, bundle: TokenBundle, container_id: str) -> str:
        identifier = _identifier(container_id)
        data = self._request("GET", f"{GRAPH}/{identifier}?fields=status_code", bundle)
        value = data.get("status_code")
        if not isinstance(value, str) or value not in _STATUSES or data.get("id") != identifier:
            raise InstagramUploadError("unknown")
        return value

    def publish(
        self, bundle: TokenBundle, instagram_account_id: str, container_id: str, *, public_approved: bool,
    ) -> str:
        if public_approved is not True:
            raise InstagramUploadError("approval_required")
        account_id, identifier = _identifier(instagram_account_id), _identifier(container_id)
        state = self.status(bundle, identifier)
        if state == "PUBLISHED":
            raise InstagramUploadError("unknown")
        if state != "FINISHED":
            raise InstagramUploadError("not_ready" if state == "IN_PROGRESS" else "rejected")
        data = self._request("POST", f"{GRAPH}/{account_id}/media_publish", bundle,
                             urlencode({"creation_id": identifier}).encode("ascii"))
        try:
            return _identifier(data.get("id"))
        except InstagramUploadError:
            raise InstagramUploadError("unknown") from None

    def result(self, bundle: TokenBundle, media_id: str, instagram_account_id: str) -> InstagramPublishResult:
        identifier, account_id = _identifier(media_id), _identifier(instagram_account_id)
        data = self._request("GET", f"{GRAPH}/{identifier}?fields=id,permalink,owner", bundle)
        try:
            url = data["permalink"]
            parsed = urlsplit(url)
            if (data.get("id") != identifier or data.get("owner", {}).get("id") != account_id
                    or parsed.scheme != "https" or parsed.netloc not in {"instagram.com", "www.instagram.com"}
                    or parsed.query or parsed.fragment
                    or not re.fullmatch(r"/(reel|p)/[A-Za-z0-9_-]+/", parsed.path)
                    or any(ord(char) <= 32 or ord(char) == 127 for char in url)):
                raise ValueError
        except (KeyError, ValueError, TypeError, AttributeError):
            raise InstagramUploadError("unknown") from None
        # Store one canonical official host so the service and UI can validate identically.
        return InstagramPublishResult(identifier, "https://www.instagram.com" + parsed.path, account_id)
