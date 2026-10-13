"""Bounded public RSS transport; DNS is checked and pinned for every hop."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from queue import Empty, Queue
from threading import Thread
from typing import Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

MAX_BYTES = 2 * 1024 * 1024
USER_AGENT = "NewsFlowAI/0.1 (+RSS-only local reader)"


class ErrorKind(StrEnum):
    DNS = "dns"
    PROXY = "proxy"
    HTTPS = "https"
    TIMEOUT = "timeout"
    HTTP = "http"
    ROBOTS = "robots"
    PARSE = "parse"
    POLICY = "policy"
    NETWORK = "network"


class FeedError(Exception):
    """Classified external failure, without raw URL/credential diagnostics."""

    def __init__(self, message: str, kind: ErrorKind = ErrorKind.NETWORK):
        super().__init__(message)
        self.kind = kind


class URLPolicyError(FeedError):
    def __init__(self, message: str):
        super().__init__(message, ErrorKind.POLICY)


def validate_url(url: str) -> str:
    if len(url) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise URLPolicyError("RSS URL 형식이 올바르지 않습니다.")
    try:
        parts = urlsplit(url)
        port = parts.port
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError
        if parts.username or parts.password or parts.fragment:
            raise ValueError
        if port not in {None, 80 if parts.scheme == "http" else 443}:
            raise ValueError
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if host == "localhost" or host.endswith((".", ".local", ".localhost", ".internal")):
            raise ValueError
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise ValueError
        else:
            if not ip.is_global or ip.is_multicast or ip.is_reserved:
                raise ValueError
        # Credentials in query strings are not supported in public feeds.
        from urllib.parse import parse_qsl

        forbidden = {"token", "key", "api_key", "access_token", "password", "secret", "authorization"}
        if any(k.lower() in forbidden for k, _ in parse_qsl(parts.query)):
            raise ValueError
        authority = f"[{host}]" if ":" in host else host
        return urlunsplit((parts.scheme, authority, parts.path or "/", parts.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise URLPolicyError(
            "공개 HTTP(S) RSS와 기본 포트만 허용합니다. 사설 주소·인증정보는 금지됩니다."
        ) from exc


def public_addresses(host: str, port: int, timeout: float = 10) -> list[str]:
    answers: Queue[list[str] | OSError] = Queue(maxsize=1)

    def resolve() -> None:
        try:
            addresses = list(
                dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            )
            answers.put(addresses)
        except OSError as exc:
            answers.put(exc)

    # getaddrinfo has no timeout API; a daemon resolver lets the request deadline win.
    Thread(target=resolve, daemon=True, name="rss-dns").start()
    try:
        result = answers.get(timeout=timeout)
    except Empty as exc:
        raise FeedError("RSS 요청 시간이 초과되었습니다.", ErrorKind.TIMEOUT) from exc
    if isinstance(result, OSError):
        raise FeedError("RSS 호스트 DNS 조회에 실패했습니다.", ErrorKind.DNS) from result
    if not result or any(
        not ipaddress.ip_address(ip).is_global
        or ipaddress.ip_address(ip).is_multicast
        or ipaddress.ip_address(ip).is_reserved
        for ip in result
    ):
        raise URLPolicyError("사설·예약 IP로 연결되는 RSS 주소는 허용하지 않습니다.")
    return result


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float, tls: bool):
        super().__init__(host, port, timeout=timeout)
        self.ip = ip
        self.tls = tls

    def connect(self) -> None:
        self.sock = socket.create_connection((self.ip, self.port), self.timeout)
        if self.tls:
            self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    location: str | None = None


class Transport(Protocol):
    def get(self, url: str, timeout: float) -> Response: ...


class PublicTransport:
    def get(self, url: str, timeout: float) -> Response:
        url = validate_url(url)
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = 443 if parts.scheme == "https" else 80
        # DNS answers are validated before opening a socket; that exact IP is used.
        addresses = public_addresses(host, port, timeout)
        connection = PinnedConnection(host, addresses[0], port, timeout, parts.scheme == "https")
        try:
            path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.getheader("Content-Encoding", "identity") not in {"identity", ""}:
                raise FeedError("압축 응답은 Phase 1 RSS 정책에서 지원하지 않습니다.")
            # Bound total read time, not only individual socket operations.
            deadline = time.monotonic() + timeout
            chunks: list[bytes] = []
            size = 0
            while size <= MAX_BYTES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                chunks.append(chunk)
            if size > MAX_BYTES:
                raise FeedError("RSS 응답이 최대 2 MiB를 초과했습니다.")
            return Response(response.status, b"".join(chunks), response.getheader("Location"))
        except TimeoutError as exc:
            raise FeedError("RSS 요청 시간이 초과되었습니다.", ErrorKind.TIMEOUT) from exc
        except ssl.SSLError as exc:
            raise FeedError("RSS TLS 인증서 또는 HTTPS 연결 검증에 실패했습니다.", ErrorKind.HTTPS) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise FeedError("RSS 연결 또는 TLS 검증에 실패했습니다.") from exc
        finally:
            connection.close()


class RSSAdapter(Protocol):
    def fetch(self, url: str, timeout: int) -> bytes: ...


class PublicRSSAdapter:
    def __init__(self, transport: Transport | None = None):
        self.transport = transport or PublicTransport()

    def _get(self, url: str, timeout: int, approve: Callable[[str], None] | None = None) -> Response:
        for _ in range(4):
            url = validate_url(url)
            if approve:
                approve(url)
            response = self.transport.get(url, timeout)
            if response.status in {301, 302, 303, 307, 308}:
                if not response.location:
                    raise FeedError("RSS 리디렉션 주소가 없습니다.")
                url = urljoin(url, response.location)
                continue
            return response
        raise FeedError("RSS 리디렉션 횟수가 제한을 초과했습니다.")

    def fetch(self, url: str, timeout: int) -> bytes:
        checked: dict[str, RobotFileParser] = {}

        def approve(target: str) -> None:
            parts = urlsplit(validate_url(target))
            origin = f"{parts.scheme}://{parts.netloc}"
            if origin not in checked:
                response = self._get(origin + "/robots.txt", timeout)
                if response.status == 404:
                    rules = ["User-agent: *", "Allow: /"]
                elif response.status == 200:
                    rules = response.body.decode("utf-8", errors="replace").splitlines()
                else:
                    raise FeedError("robots.txt 확인 실패로 수집을 중단했습니다.", ErrorKind.ROBOTS)
                robot = RobotFileParser()
                robot.parse(rules)
                checked[origin] = robot
            if not checked[origin].can_fetch(USER_AGENT, target):
                raise FeedError("robots.txt 정책에서 이 RSS 경로를 허용하지 않습니다.", ErrorKind.ROBOTS)
            # Local manual collector makes one feed request per source. For crawl-delay,
            # conservatively reject unsupported timing rather than ignoring it.
            delay = checked[origin].crawl_delay(USER_AGENT)
            if checked[origin].request_rate(USER_AGENT):
                raise FeedError(
                    "robots.txt 요청 간격 정책을 지원하지 않아 수집을 중단했습니다.", ErrorKind.ROBOTS
                )
            if delay:
                raise FeedError(
                    "crawl-delay가 지정된 출처는 Phase 1에서 수집하지 않습니다.", ErrorKind.ROBOTS
                )

        response = self._get(url, timeout, approve)
        if response.status != 200:
            raise FeedError(f"RSS 서버가 HTTP {response.status}을 반환했습니다.", ErrorKind.HTTP)
        return response.body


class FakeRSSAdapter:
    """Offline deterministic adapter, usable by tests and demo tools."""

    def __init__(self, feeds: dict[str, bytes | Exception]):
        self.feeds = feeds
        self.calls: list[str] = []

    def fetch(self, url: str, timeout: int) -> bytes:
        self.calls.append(url)
        value = self.feeds.get(url, FeedError("Fake RSS fixture가 없습니다."))
        if isinstance(value, Exception):
            raise value
        return value
