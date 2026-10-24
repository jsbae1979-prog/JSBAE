"""Official YouTube resumable upload, with no automatic request replay."""

from __future__ import annotations

import ctypes
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from newsflow.oauth.contracts import YOUTUBE_UPLOAD_SCOPE

from .adapters import YouTubeAdapter
from .auth import TokenBundle
from .categories import valid_category

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
MAX_BYTES = 2 * 1024**3
CHUNK_BYTES = 8 * 1024**2
_MAX_RESPONSE = 256 * 1024
_CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
_VIDEO = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_MESSAGES = {
    "approval_required": "영상 업로드 승인이 필요합니다.",
    "invalid_input": "영상·게시 설정을 다시 확인하세요.",
    "media_changed": "검토한 영상 파일이 변경되었거나 접근할 수 없습니다.",
    "authentication": "YouTube 인증이 만료되었거나 유효하지 않습니다. 다시 연결해 주세요.",
    "permission": "YouTube 업로드 권한 또는 프로젝트 할당량을 확인하세요.",
    "rejected": "YouTube가 업로드 요청을 거부했습니다. 자동 재시도하지 않습니다.",
    "unknown": "업로드 결과를 확인할 수 없습니다. YouTube Studio에서 확인하기 전 재전송하지 마세요.",
}


class YouTubeUploadError(Exception):
    def __init__(self, code: str, *, unknown: bool = False) -> None:
        self.code = code if code in _MESSAGES else "unknown"
        self.unknown = unknown or self.code == "unknown"
        super().__init__(_MESSAGES[self.code])


@dataclass(frozen=True)
class UploadHTTPResponse:
    status: int
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(repr=False)


class UploadTransport(Protocol):
    def request(self, method: str, url: str, headers: dict[str, str], body: bytes) -> UploadHTTPResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def _session_url(value: str) -> str:
    """Upload-session URLs are bearer-like capabilities: never persist or reflect them."""
    try:
        parsed = urlsplit(value)
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        if (
            not isinstance(value, str) or len(value) > 8192
            or parsed.scheme != "https" or parsed.netloc != "www.googleapis.com"
            or parsed.path != "/upload/youtube/v3/videos" or parsed.fragment
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
            or sum(key == "upload_id" and bool(item) for key, item in query) != 1
        ):
            raise ValueError
    except Exception:  # noqa: BLE001 - never reflect an upload capability URL
        raise YouTubeUploadError("unknown") from None
    return value


class GoogleUploadTransport:
    """System TLS/proxy trust, bounded responses, redirects disabled, no retries."""

    def __init__(self, *, timeout: float = 60) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 120:
            raise ValueError("Invalid upload timeout")
        self.timeout = timeout

    def request(self, method: str, url: str, headers: dict[str, str], body: bytes) -> UploadHTTPResponse:
        if not ((method == "POST" and url == UPLOAD_URL) or (method == "PUT" and _session_url(url))):
            raise YouTubeUploadError("invalid_input")
        request = Request(url, data=body, headers=headers, method=method)
        opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
        try:
            try:
                response = opener.open(request, timeout=self.timeout)
            except HTTPError as error:
                response = error
            with response:
                data = response.read(_MAX_RESPONSE + 1)
                if len(data) > _MAX_RESPONSE:
                    raise YouTubeUploadError("unknown")
                # Restrict headers to protocol fields; never retain cookies or authentication headers.
                fields = {key.lower(): response.headers[key] for key in ("Location", "Range")
                          if key in response.headers}
                return UploadHTTPResponse(response.code, fields, data)
        except YouTubeUploadError:
            raise
        except (OSError, URLError, TimeoutError, http.client.HTTPException):
            raise YouTubeUploadError("unknown") from None


@contextmanager
def _locked_media(path: Path) -> Iterator[BinaryIO]:
    """Windows production handle denies writes/deletes for the entire upload."""
    if sys.platform != "win32":
        # Portable Fake tests only; the Windows connection service owns real grants.
        with path.open("rb") as stream:
            yield stream
        return
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
    handle = create(str(path), 0x80000000, 0x00000001, None, 3, 0x08000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise YouTubeUploadError("media_changed")
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:  # noqa: BLE001 - release native handle and redact path errors
        close(handle)
        raise YouTubeUploadError("media_changed") from None
    with os.fdopen(descriptor, "rb") as stream:
        yield stream


@dataclass(frozen=True)
class YouTubeUploadResult:
    video_id: str
    url: str
    privacy: str
    processing_status: str = "uploaded"


def _http_success(response: UploadHTTPResponse, expected: set[int]) -> None:
    if response.status in expected:
        return
    if response.status == 401:
        raise YouTubeUploadError("authentication")
    if response.status == 403:
        raise YouTubeUploadError("permission")
    if response.status in {408, 429} or response.status >= 500 or 300 <= response.status < 400:
        raise YouTubeUploadError("unknown")
    raise YouTubeUploadError("rejected")


class YouTubeUploadAdapter:
    def __init__(self, transport: UploadTransport | None = None, *, chunk_bytes: int = CHUNK_BYTES) -> None:
        if type(chunk_bytes) is not int or not 256 * 1024 <= chunk_bytes <= CHUNK_BYTES or chunk_bytes % (256 * 1024):
            raise ValueError("Upload chunks must be 256 KiB multiples")
        self.transport = transport or GoogleUploadTransport()
        self.chunk_bytes = chunk_bytes

    def upload(
        self, path: Path, payload: dict, bundle: TokenBundle, channel_id: str, expected_sha256: str,
    ) -> YouTubeUploadResult:
        privacy = payload.get("privacy", "private")
        if (
            payload.get("upload_approved") is not True
            or privacy not in {"private", "unlisted", "public"}
            or (privacy != "private" and payload.get("public_approved") is not True)
        ):
            raise YouTubeUploadError("approval_required")
        if (
            type(bundle) is not TokenBundle or bundle.expires_at <= datetime.now(UTC)
            or YOUTUBE_UPLOAD_SCOPE not in bundle.scopes or not _CHANNEL.fullmatch(channel_id)
            or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)
            or type(payload.get("made_for_kids")) is not bool
            or not valid_category(payload.get("youtube_category_id", "25"))
        ):
            raise YouTubeUploadError("invalid_input")
        prepared = YouTubeAdapter().prepare(payload)
        status = {**prepared["status"], "privacyStatus": privacy,
                  "selfDeclaredMadeForKids": payload["made_for_kids"]}
        metadata = json.dumps({"snippet": prepared["snippet"], "status": status},
                              ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        authorization = "Bearer " + bundle.access_token.get_secret_value()
        try:
            with _locked_media(path) as stream:
                size = os.fstat(stream.fileno()).st_size
                if not 0 < size <= MAX_BYTES:
                    raise YouTubeUploadError("media_changed")
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                if digest.hexdigest() != expected_sha256:
                    raise YouTubeUploadError("media_changed")
                stream.seek(0)
                response = self.transport.request("POST", UPLOAD_URL, {
                    "Authorization": authorization, "Content-Type": "application/json; charset=UTF-8",
                    "Content-Length": str(len(metadata)), "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(size),
                }, metadata)
                _http_success(response, {200, 201})
                session = _session_url(response.headers.get("location", ""))
                offset = 0
                sent_digest = hashlib.sha256()
                while offset < size:
                    block = stream.read(min(self.chunk_bytes, size - offset))
                    if not block:
                        raise YouTubeUploadError("unknown")
                    end = offset + len(block) - 1
                    response = self.transport.request("PUT", session, {
                        "Authorization": authorization, "Content-Type": "video/mp4",
                        "Content-Length": str(len(block)), "Content-Range": f"bytes {offset}-{end}/{size}",
                    }, block)
                    sent_digest.update(block)
                    offset = end + 1
                    if offset < size:
                        _http_success(response, {308})
                        if response.headers.get("range") != f"bytes=0-{end}":
                            raise YouTubeUploadError("unknown")
                    else:
                        _http_success(response, {200, 201})
                if sent_digest.hexdigest() != expected_sha256:
                    raise YouTubeUploadError("unknown")
                return self._result(response, channel_id, privacy)
        except YouTubeUploadError:
            raise
        except Exception:  # noqa: BLE001 - ambiguous sends must never be retried or expose credentials
            # Transport/IO errors can happen after a request was accepted. Never resend.
            raise YouTubeUploadError("unknown") from None

    @staticmethod
    def _result(response: UploadHTTPResponse, channel_id: str, privacy: str) -> YouTubeUploadResult:
        try:
            data = json.loads(response.body)
            identifier = data["id"]
            if not isinstance(identifier, str) or not _VIDEO.fullmatch(identifier):
                raise ValueError
            snippet, status = data.get("snippet", {}), data.get("status", {})
            if snippet.get("channelId") != channel_id:
                raise ValueError
            actual_privacy = status.get("privacyStatus")
            if actual_privacy not in {"private", "unlisted", "public"}:
                raise ValueError
            # A project's audit policy may enforce private even when another visibility was requested.
            if privacy == "private" and actual_privacy != "private":
                raise ValueError
            processing = status.get("uploadStatus", "uploaded")
            if processing not in {"uploaded", "processed", "failed", "rejected", "deleted"}:
                processing = "uploaded"
            return YouTubeUploadResult(identifier, "https://www.youtube.com/watch?v=" + identifier,
                                       actual_privacy, processing)
        except Exception:  # noqa: BLE001 - untrusted provider response stays private
            raise YouTubeUploadError("unknown") from None
