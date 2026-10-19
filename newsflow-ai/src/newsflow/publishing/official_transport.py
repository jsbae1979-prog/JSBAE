"""One-attempt HTTPS transport for the documented platform contracts.

Production activation is deliberately a code boundary, never an environment or
GUI flag. No app route constructs this transport with real credentials. Tests use
synthetic bearer strings and in-memory HTTP connections; no external network.
"""

from __future__ import annotations

import http.client
import json
import re
import ssl
from collections.abc import Callable
from typing import BinaryIO
from urllib.parse import parse_qs, urlsplit

from pydantic import SecretStr

from .platforms import PlatformBlocked
from .service import PublishingError


class TransportOutcomeUnknown(PublishingError):
    pass


def production_activation() -> bool:
    # Requires a separately reviewed production activation; config cannot change it.
    return False


def allowed_request(platform: str, method: str, url: str) -> tuple[str, str]:
    try:
        value = urlsplit(url)
        if (
            value.scheme != "https"
            or value.username
            or value.password
            or value.port not in (None, 443)
            or value.fragment
            or len(url) > 4096
            or any(ord(c) < 32 for c in url)
        ):
            raise ValueError
        host, path = value.hostname, value.path
        allowed = False
        if platform == "tiktok":
            allowed = (
                host == "open.tiktokapis.com"
                and method == "POST"
                and path
                in {
                    "/v2/post/publish/creator_info/query/",
                    "/v2/post/publish/video/init/",
                    "/v2/post/publish/status/fetch/",
                    "/v2/video/query/",
                }
            ) or (host == "open-upload.tiktokapis.com" and method == "PUT" and path == "/video/")
        elif platform in {"facebook", "instagram"}:
            allowed = (
                host == "graph.facebook.com"
                and bool(
                    re.fullmatch(r"/v26\.0/[0-9]{1,40}(?:/(?:video_reels|video_insights|insights))?", path)
                )
                and (
                    method == "GET"
                    or platform == "facebook"
                    and method == "POST"
                    and path.endswith("/video_reels")
                )
            )
            if platform == "facebook" and host == "rupload.facebook.com":
                allowed = method == "POST" and bool(
                    re.fullmatch(r"/video-upload/(?:v26\.0/)?[0-9]{1,40}", path)
                )
        elif platform == "youtube":
            allowed = method == "GET" and (
                (host == "www.googleapis.com" and path == "/youtube/v3/videos")
                or (host == "youtubeanalytics.googleapis.com" and path == "/v2/reports")
            )
        if not allowed or any(
            k.lower() in {"access_token", "client_secret", "redirect_uri"} for k in parse_qs(value.query)
        ):
            raise ValueError
        return host, path + ("?" + value.query if value.query else "")
    except (ValueError, TypeError):
        raise PublishingError("공식 API의 허용된 주소·요청 방식이 아닙니다.") from None


class OfficialHTTPS:
    def __init__(self, platform: str, token: SecretStr, *, synthetic_connection: Callable | None = None):
        if platform not in {"youtube", "instagram", "facebook", "tiktok"}:
            raise ValueError("Unsupported platform")
        if synthetic_connection is not None:
            if not token.get_secret_value().startswith("nf-synthetic-"):
                raise PlatformBlocked("합성 HTTP 검증에는 합성 자격 증명만 사용할 수 있습니다.")
            self.factory = synthetic_connection
        elif not production_activation():
            raise PlatformBlocked("공식 HTTPS 전송의 운영 활성화는 별도 코드 검토 전까지 차단됩니다.")
        else:
            self.factory = http.client.HTTPSConnection
        self.platform, self._token = platform, token

    def request(
        self,
        method: str,
        url: str,
        *,
        payload: dict | None = None,
        stream: BinaryIO | None = None,
        headers: dict | None = None,
    ) -> dict:
        host, target = allowed_request(self.platform, method, url)
        supplied = headers or {}
        if set(supplied) - {"Content-Type", "Content-Length", "Content-Range", "offset", "file_size"}:
            raise PublishingError("지원하지 않는 HTTP 헤더입니다.")
        if any(not isinstance(v, str) or "\r" in v or "\n" in v for v in supplied.values()):
            raise PublishingError("HTTP 헤더 형식을 확인하세요.")
        metadata = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b""
        if len(metadata) > 1024 * 1024 or stream is not None and payload is not None:
            raise PublishingError("요청 크기·형식을 확인하세요.")
        authorization = "OAuth " if host == "rupload.facebook.com" else "Bearer "
        outgoing = {"Content-Type": "application/json", **supplied}
        if host != "open-upload.tiktokapis.com":
            outgoing["Authorization"] = authorization + self._token.get_secret_value()
        outgoing["Content-Length"] = (
            str(len(metadata))
            if stream is None
            else supplied.get("Content-Length", supplied.get("file_size", ""))
        )
        try:
            size = int(outgoing["Content-Length"])
            if size < 0 or size > 2 * 1024**3:
                raise ValueError
        except (ValueError, TypeError):
            raise PublishingError("전송 파일 크기를 확인하세요.") from None
        connection = None
        try:
            connection = self.factory(host, timeout=30, context=ssl.create_default_context())
            connection.putrequest(method, target, skip_accept_encoding=True)
            for key, value in outgoing.items():
                connection.putheader(key, value)
            connection.endheaders()
            if stream is not None:
                remaining = size
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError
                    connection.send(chunk)
                    remaining -= len(chunk)
            elif metadata:
                connection.send(metadata)
            response = connection.getresponse()
            # Never follow redirects; never retry 408, 429, 5xx or ambiguous submits.
            if not 200 <= response.status < 300:
                raise ValueError
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise ValueError
            if not body and stream is not None:
                return {"success": True}  # Upload transfer only, never publication success.
            value = json.loads(body)
            if not isinstance(value, dict):
                raise TypeError
            return value
        except Exception:  # noqa: BLE001 - no target URL, header, body or raw provider exception
            raise TransportOutcomeUnknown(
                "공식 API 응답을 확인하지 못했습니다. 자동 재전송하지 않습니다."
            ) from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:  # noqa: BLE001, S110 - cleanup must not expose a transport exception
                    pass
