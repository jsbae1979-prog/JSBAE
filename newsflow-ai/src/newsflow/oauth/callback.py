"""Dedicated, ephemeral IPv4-loopback callbacks with scoped production access.

The GUI remains on port 8765. The separate synthetic validation listener handles
only recognizable fixture codes. The explicit YouTube service separately consumes
sealed production results; the listener never exchanges tokens or launches browsers.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import secrets
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from time import monotonic
from typing import BinaryIO, Self
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from pydantic import SecretStr

from .activation import require_production_activation
from .contracts import YOUTUBE_UPLOAD_SCOPE, OAuthError, account_key_valid
from .session import checked_time, pkce_s256

_CALLBACK_PATH = "/oauth/callback"
_MAX_REQUEST_LINE = 4096
_MAX_HEADERS = 8192
_MAX_QUERY = 4096
_MAX_FIELDS = 8
_PROOF_KEY = secrets.token_bytes(32)
_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
_OBSERVATION_COUNTS = (
    "tcp_connections", "http_requests", "read_failures", "accepted_callbacks", "rejected_requests",
)
_MAX_OBSERVATION_COUNT = 1_000_000
_MESSAGES = {
    "callback_timeout": "인증 응답 대기 시간이 만료되었습니다. 연결되지 않았습니다.",
    "port_conflict": "로컬 인증 응답 포트를 사용할 수 없습니다. 연결되지 않았습니다.",
}
_ACCEPTED = b"Local callback received. No service connection has been activated."
_REJECTED = b"Local callback rejected. No service connection has been activated."
CALLBACK_REJECTION_MESSAGES = {
    "request_size": "로컬 인증 응답의 크기가 허용 범위를 초과했습니다.",
    "headers": "로컬 인증 응답의 HTTP 헤더를 확인하지 못했습니다.",
    "method": "로컬 인증 응답의 요청 방식이 올바르지 않습니다.",
    "host": "로컬 인증 응답의 수신 주소가 일치하지 않습니다.",
    "origin": "허용되지 않은 출처의 로컬 인증 응답을 거절했습니다.",
    "body": "로컬 인증 응답에 허용되지 않는 요청 본문이 있습니다.",
    "query": "로컬 인증 응답의 주소 또는 매개변수 형식이 올바르지 않습니다.",
    "state": "로컬 인증 응답이 현재 로그인 요청과 일치하지 않습니다.",
    "reused": "이미 처리했거나 종료된 로컬 인증 응답입니다.",
    "expired": "로컬 인증 응답의 대기 시간이 만료되었습니다.",
    "unknown_field": "Google 인증 응답에 지원되지 않는 항목이 있습니다.",
    "duplicate_field": "Google 인증 응답에 중복된 항목이 있습니다.",
    "empty_field": "Google 인증 응답에 빈 항목이 있습니다.",
    "field_format": "Google 인증 응답 항목의 길이 또는 문자 형식이 올바르지 않습니다.",
    "result_fields": "Google 인증 응답의 성공·오류 항목 구성이 올바르지 않습니다.",
    "provider_denied": "Google 권한 승인이 취소되었습니다.",
    "provider_error": "Google이 인증 오류를 반환했습니다.",
    "code_format": "인증 코드 형식이 현재 연결 방식과 일치하지 않습니다.",
    "pkce": "로컬 인증 요청의 보안 검증에 실패했습니다.",
    "internal": "로컬 인증 응답 처리 중 내부 오류가 발생했습니다.",
}


class CallbackError(OAuthError):
    """Fixed local error messages that never include callbacks or credentials."""

    def __init__(self, code: str, *, reason: str | None = None) -> None:
        super().__init__(code)
        # Never retain arbitrary request fields or exception text in diagnostics.
        self.reason = reason if reason in CALLBACK_REJECTION_MESSAGES else None
        self.last_rejection: str | None = None
        self.observation: dict[str, object] = {}
        if code in _MESSAGES:
            self.code = code
            self.args = (_MESSAGES[code],)

    def safe_observation(self) -> dict[str, object]:
        """Recheck the fixed diagnostic contract at the persistence boundary."""
        if type(self.observation) is not dict:
            return {}
        safe: dict[str, object] = {}
        for key in (*_OBSERVATION_COUNTS, "elapsed_ms"):
            value = self.observation.get(key)
            maximum = 86_400_000 if key == "elapsed_ms" else _MAX_OBSERVATION_COUNT
            if type(value) is int and 0 <= value <= maximum:
                safe[key] = value
        for key in ("deadline_reached", "listener_running"):
            value = self.observation.get(key)
            if type(value) is bool:
                safe[key] = value
        return safe


def _seconds(value: float, *, maximum: float = 300) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.01 <= value <= maximum:
        raise CallbackError("invalid_input")
    return float(value)


def _origin(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.port is None or not 1024 <= parsed.port <= 65535
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment
            or value != f"http://127.0.0.1:{parsed.port}"
        ):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise CallbackError("invalid_input") from None


@dataclass(frozen=True)
class DynamicOAuthRequest:
    """Per-listener binding; it does not alter the legacy fixed-URI contract."""

    session_id: str
    account_key: str
    scopes: tuple[str, ...]
    redirect_uri: str
    state: SecretStr = field(repr=False)
    code_challenge: str
    expires_at: datetime
    code_challenge_method: str = "S256"
    mode: str = "SYNTHETIC_CALLBACK"


@dataclass(frozen=True)
class CallbackLaunch:
    request: DynamicOAuthRequest
    redirect_uri: str


@dataclass(frozen=True)
class CallbackResult:
    session_id: str
    account_key: str
    scopes: tuple[str, ...]
    redirect_uri: str
    verifier: SecretStr = field(repr=False)
    code: SecretStr = field(repr=False)
    code_challenge: str
    expires_at: datetime
    mode: str = "SYNTHETIC_CALLBACK"
    _seal: bytes = field(default=b"", repr=False)

    def assert_valid(self, account_key: str, *, production: bool = False) -> None:
        """Authenticate a consumed callback binding for its specific execution mode.

        Dataclass immutability alone would not stop a forged/modified result. This
        process-local seal covers every input to the later token POST. It cannot
        protect against code injection or inspection of this process's memory.
        """
        try:
            if production:
                require_production_activation()
            expected_mode = "YOUTUBE_CALLBACK" if production else "SYNTHETIC_CALLBACK"
            if (
                type(self) is not CallbackResult or self.mode != expected_mode
                or not isinstance(self._seal, bytes) or len(self._seal) != 32
                or not hmac.compare_digest(self._seal, _result_seal(self))
                or pkce_s256(self.verifier.get_secret_value()) != self.code_challenge
                or (not production and not re.fullmatch(
                    r"nf-synthetic-code-[A-Za-z0-9_-]{1,200}", self.code.get_secret_value()))
                or (production and (not 1 <= len(self.code.get_secret_value()) <= 2048
                                    or any(ord(char) < 33 or ord(char) == 127
                                           for char in self.code.get_secret_value())))
            ):
                raise CallbackError("callback_invalid")
            if self.account_key != account_key:
                raise CallbackError("account_mismatch")
            if checked_time(self.expires_at) <= checked_time():
                raise CallbackError("expired")
        except CallbackError:
            raise
        except Exception:  # noqa: BLE001 - malformed result objects must not reflect credential values
            raise CallbackError("callback_invalid") from None


def _result_seal(result: CallbackResult) -> bytes:
    values = [result.session_id, result.account_key, list(result.scopes), result.redirect_uri,
              result.verifier.get_secret_value(), result.code.get_secret_value(),
              result.code_challenge, result.expires_at.isoformat(), result.mode]
    return hmac.digest(_PROOF_KEY, json.dumps(values, separators=(",", ":")).encode(), "sha256")


class _BoundedHeaders:
    def __init__(self, reader: BinaryIO) -> None:
        self.reader = reader
        self.total = 0
        self.count = 0

    def readline(self, limit: int = -1) -> bytes:
        remaining = _MAX_HEADERS - self.total
        line = self.reader.readline(min(limit if limit >= 0 else remaining + 1, remaining + 1))
        self.total += len(line)
        self.count += 1
        if self.total > _MAX_HEADERS or self.count > 33:
            raise http.client.LineTooLong("header")
        return line


class _CallbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # Avoid HTTPServer.server_bind's getfqdn: numeric loopback needs no DNS.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address

    def handle_error(self, request: object, client_address: object) -> None:
        # The standard implementation prints tracebacks, which may contain input.
        return None


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self) -> None:
        self.request.settimeout(1)
        super().setup()
        self.server.owner._observe("tcp_connections")

    def log_message(self, format: str, *args: object) -> None:
        return None

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._reject(code, "headers" if code == 431 else "query")

    def _reject(self, status: int, reason: str) -> None:
        self.server.owner._reject(self, status, reason)

    def _reply(self, status: int, body: bytes) -> None:
        self.close_connection = True
        try:
            self.send_response_only(status)
            for key, value in (
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                ("Pragma", "no-cache"), ("Referrer-Policy", "no-referrer"),
                ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
                ("X-Content-Type-Options", "nosniff"), ("Connection", "close"),
            ):
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            # The browser may close a rejected response; no exception text leaves.
            pass

    def handle_one_request(self) -> None:
        try:
            self.raw_requestline = self.rfile.readline(_MAX_REQUEST_LINE + 1)
            if self.raw_requestline:
                self.server.owner._observe("http_requests")
            if len(self.raw_requestline) > _MAX_REQUEST_LINE:
                self.requestline, self.request_version, self.command = "", "HTTP/1.0", ""
                self._reject(414, "request_size")
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            reader = self.rfile
            self.rfile = _BoundedHeaders(reader)
            try:
                parsed = self.parse_request()
            finally:
                self.rfile = reader
            if not parsed:
                return
            if self.command != "GET":
                self._reject(405, "method")
                return
            owner: LoopbackCallbackListener = self.server.owner
            owner._handle(self)
            self.wfile.flush()
        except (TimeoutError, OSError, http.client.HTTPException):
            self.server.owner._observe("read_failures")
            self.close_connection = True
        except Exception:  # noqa: BLE001 - malformed local input must never print raw request/traceback
            self.close_connection = True
            self._reject(400, "internal")


class LoopbackCallbackListener:
    """The explicit YouTube activation context is required before any production bind."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._event = threading.Event()
        self._server: _CallbackHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._launch: CallbackLaunch | None = None
        self._verifier: SecretStr | None = None
        self._state_digest: bytes | None = None
        self._deadline = 0.0
        self._allowed_origin: str | None = None
        self._synthetic = False
        self._consumed = False
        self._closed = False
        self._result: CallbackResult | None = None
        self._error: CallbackError | None = None
        self._delivered = False
        self._accepted = 0
        self._rejected = 0
        self._last_rejection: str | None = None
        self._observations = dict.fromkeys(_OBSERVATION_COUNTS, 0)
        self._started_at = 0.0

    def start(
        self, account_key: str, *, scopes: tuple[str, ...] = (YOUTUBE_UPLOAD_SCOPE,),
        port: int = 0, allowed_origin: str | None = None, ttl_seconds: float = 300,
    ) -> CallbackLaunch:
        require_production_activation()
        return self._start(account_key, scopes, port, allowed_origin, ttl_seconds, synthetic=False)

    def _start(
        self, account_key: str, scopes: tuple[str, ...], port: int,
        allowed_origin: str | None, ttl_seconds: float, *, synthetic: bool,
    ) -> CallbackLaunch:
        if not synthetic:
            require_production_activation()
        if (
            not account_key_valid(account_key) or not account_key.startswith("youtube:")
            or not isinstance(scopes, tuple) or not 1 <= len(scopes) <= 2
            or any(not isinstance(scope, str) for scope in scopes)
            or len(set(scopes)) != len(scopes)
            or any(scope not in {YOUTUBE_UPLOAD_SCOPE, _READ_SCOPE} for scope in scopes)
            or isinstance(port, bool) or not isinstance(port, int)
            or (port != 0 and (not 1024 <= port <= 65535 or port == 8765))
        ):
            raise CallbackError("invalid_input")
        lifetime, origin = _seconds(ttl_seconds), _origin(allowed_origin)
        with self._lock:
            if self._server is not None or self._closed or self._consumed:
                raise CallbackError("reused")
            try:
                server = _CallbackHTTPServer(("127.0.0.1", port), _Handler, bind_and_activate=False)
                # The exact numeric host is bound before any authorization URL exists.
                server.server_bind()
                server.server_activate()
                bound_port = server.server_address[1]
                if bound_port == 8765:
                    server.server_close()
                    raise CallbackError("port_conflict")
            except OSError:
                if "server" in locals():
                    server.server_close()
                raise CallbackError("port_conflict") from None
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
            uri = f"http://127.0.0.1:{bound_port}{_CALLBACK_PATH}"
            request = DynamicOAuthRequest(
                uuid4().hex, account_key, scopes, uri, SecretStr(state), pkce_s256(verifier),
                checked_time() + timedelta(seconds=lifetime),
                mode="SYNTHETIC_CALLBACK" if synthetic else "YOUTUBE_CALLBACK",
            )
            self._server, self._launch = server, CallbackLaunch(request, uri)
            self._verifier, self._state_digest = SecretStr(verifier), hashlib.sha256(state.encode()).digest()
            self._started_at = monotonic()
            self._deadline, self._allowed_origin, self._synthetic = self._started_at + lifetime, origin, synthetic
            server.owner = self
            self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                                            name="newsflow-synthetic-callback", daemon=True)
            self._thread.start()
            return self._launch

    def _observe(self, name: str) -> None:
        with self._lock:
            self._observations[name] = min(self._observations[name] + 1, _MAX_OBSERVATION_COUNT)

    def _failure_observation(self) -> dict[str, object]:
        # No address, port, query, field name/value, header or exception text.
        with self._lock:
            now = monotonic()
            return {
                **self._observations,
                "elapsed_ms": min(86_400_000, max(0, int((now - self._started_at) * 1000))),
                "deadline_reached": now >= self._deadline,
                "listener_running": bool(self._thread and self._thread.is_alive() and not self._closed),
            }

    def _finish_locked(
        self, *, error: str | None = None, result: CallbackResult | None = None, reason: str | None = None,
    ) -> None:
        self._consumed = True
        self._error = CallbackError(error, reason=reason) if error is not None else None
        self._result = result
        self._event.set()

    def _reject(self, handler: _Handler, status: int, reason: str) -> None:
        reason = reason if reason in CALLBACK_REJECTION_MESSAGES else "internal"
        with self._lock:
            self._rejected += 1
            self._last_rejection = reason
            self._observe("rejected_requests")
        # Fixed reason only: never reflect a URL, state, code, header or field name.
        handler._reply(status, _REJECTED + b"\nReason: callback_" + reason.encode("ascii") + b"\n")

    def _handle(self, handler: _Handler) -> None:
        assert self._launch is not None
        uri = urlsplit(self._launch.redirect_uri)
        host = f"127.0.0.1:{uri.port}"
        origins = handler.headers.get_all("Origin", [])
        hosts = handler.headers.get_all("Host", [])
        if handler.client_address[0] != "127.0.0.1" or hosts != [host]:
            self._reject(handler, 400, "host")
            return
        if len(origins) > 1 or (origins and origins[0] != self._allowed_origin):
            self._reject(handler, 400, "origin")
            return
        if (handler.headers.get_all("Transfer-Encoding", [])
                or handler.headers.get_all("Content-Length", []) not in ([], ["0"])):
            self._reject(handler, 400, "body")
            return
        raw_path = handler.path
        try:
            path = urlsplit(raw_path)
            if (
                not raw_path.startswith("/") or raw_path.startswith("//")
                or path.scheme or path.netloc or path.fragment or path.path != _CALLBACK_PATH
                or len(path.query) > _MAX_QUERY or re.search(r"%(?![a-fA-F0-9]{2})", path.query)
            ):
                raise ValueError
            pairs = parse_qsl(path.query, keep_blank_values=True, strict_parsing=True,
                              max_num_fields=_MAX_FIELDS, encoding="utf-8", errors="strict")
        except (ValueError, UnicodeError):
            self._reject(handler, 400, "query")
            return
        with self._lock:
            if self._closed or self._consumed:
                self._reject(handler, 409, "reused")
                return
            if monotonic() >= self._deadline:
                self._finish_locked(error="expired")
                self._reject(handler, 410, "expired")
                return
            # Unauthenticated requests must not burn a legitimate pending login.
            # GET image/navigation requests may omit Origin, so Host checks alone
            # cannot protect availability against a process that knows this port.
            supplied_states = [value for key, value in pairs if key == "state"]
            if (
                len(supplied_states) != 1
                or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", supplied_states[0])
                or not hmac.compare_digest(hashlib.sha256(supplied_states[0].encode("ascii")).digest(),
                                           self._state_digest)
            ):
                self._reject(handler, 400, "state")
                return
            try:
                values: dict[str, str] = {}
                allowed = {"state", "code", "error", "error_description", "scope", "authuser", "prompt"}
                if not 1 <= len(pairs) <= _MAX_FIELDS:
                    raise CallbackError("callback_invalid")
                for key, value in pairs:
                    if key not in allowed:
                        raise CallbackError("callback_invalid", reason="unknown_field")
                    if key in values:
                        raise CallbackError("callback_invalid", reason="duplicate_field")
                    if not value:
                        raise CallbackError("callback_invalid", reason="empty_field")
                    if (len(value) > 2048
                            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
                        raise CallbackError("callback_invalid", reason="field_format")
                    values[key] = value
                state = values.get("state", "")
                if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", state) or not hmac.compare_digest(
                    hashlib.sha256(state.encode("ascii")).digest(), self._state_digest,
                ):
                    raise CallbackError("state_mismatch", reason="state")
                if ("code" in values) == ("error" in values):
                    raise CallbackError("callback_invalid", reason="result_fields")
                if "error" in values:
                    denied = values["error"] == "access_denied"
                    raise CallbackError("cancelled" if denied else "provider_error",
                                        reason="provider_denied" if denied else "provider_error")
                if "error_description" in values:
                    raise CallbackError("callback_invalid", reason="result_fields")
                if self._synthetic and not re.fullmatch(r"nf-synthetic-code-[A-Za-z0-9_-]{1,200}", values["code"]):
                    raise CallbackError("callback_invalid", reason="code_format")
                verifier = self._verifier
                if verifier is None or pkce_s256(verifier.get_secret_value()) != self._launch.request.code_challenge:
                    raise CallbackError("callback_invalid", reason="pkce")
                # Optional scope/authuser/prompt are not identity or grant evidence.
                result = CallbackResult(
                    self._launch.request.session_id, self._launch.request.account_key,
                    self._launch.request.scopes, self._launch.redirect_uri, verifier,
                    SecretStr(values["code"]), self._launch.request.code_challenge,
                    self._launch.request.expires_at, mode=self._launch.request.mode,
                )
                object.__setattr__(result, "_seal", _result_seal(result))
                self._finish_locked(result=result)
                self._accepted += 1
                self._observe("accepted_callbacks")
                handler._reply(200, _ACCEPTED if self._synthetic else
                               b"Authorization received. Close this tab and return to NewsFlow AI.")
            except CallbackError as error:
                self._finish_locked(error=error.code, reason=error.reason)
                self._reject(handler, 400, error.reason or "internal")

    def wait(self, timeout_seconds: float = 300) -> CallbackResult:
        timeout = _seconds(timeout_seconds)
        with self._lock:
            if self._launch is None:
                raise CallbackError("invalid_input")
        remaining = max(0.0, self._deadline - monotonic())
        # A wait bounded by the launch deadline is an expiry even when the OS timer wakes a
        # few milliseconds early (Windows timer resolution); only a shorter caller timeout is
        # reported as callback_timeout.
        bounded_by_deadline = remaining <= timeout
        if not self._event.wait(min(timeout, remaining)):
            with self._lock:
                if not self._consumed:
                    expired = bounded_by_deadline or monotonic() >= self._deadline
                    self._finish_locked(error="expired" if expired else "callback_timeout")
        with self._lock:
            if self._error is not None:
                self._error.last_rejection = self._last_rejection
                self._error.observation = self._failure_observation()
                raise self._error
            if self._result is None:
                raise CallbackError("callback_invalid")
            if self._delivered:
                raise CallbackError("reused")
            self._delivered = True
            return self._result

    def cancel(self) -> None:
        with self._lock:
            if not self._consumed:
                self._finish_locked(error="cancelled")

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if not self._consumed:
                self._finish_locked(error="cancelled")
            server, thread = self._server, self._thread
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)

    def evidence(self) -> dict[str, object]:
        with self._lock:
            return {
                "mode": "SYNTHETIC_CALLBACK" if self._synthetic else "OFFLINE/BLOCKED",
                "synthetic_callbacks_accepted": self._accepted if self._synthetic else 0,
                "synthetic_callbacks_rejected": self._rejected if self._synthetic else 0,
                "real_oauth_requests": 0, "real_sns_upload_requests": 0,
                "loopback_host": "127.0.0.1", "gui_port_unchanged": 8765,
                "registered_uri_verified": False,
            }

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class SyntheticLoopbackCallback(LoopbackCallbackListener):
    """Explicit fixture listener; real-format codes can never enter its result."""

    def start(
        self, account_key: str, *, scopes: tuple[str, ...] = (YOUTUBE_UPLOAD_SCOPE,),
        port: int = 0, allowed_origin: str | None = None, ttl_seconds: float = 300,
    ) -> CallbackLaunch:
        return self._start(account_key, scopes, port, allowed_origin, ttl_seconds, synthetic=True)
