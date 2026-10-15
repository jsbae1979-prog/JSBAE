"""Dedicated, ephemeral IPv4-loopback callbacks with a blocked production entry.

The GUI remains on port 8765. The separate synthetic validation listener handles
only recognizable fixture codes. It does not launch browsers, exchange codes, or
assert a live Google grant. A future activation review must connect those steps.
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
_MESSAGES = {
    "callback_timeout": "인증 응답 대기 시간이 만료되었습니다. 연결되지 않았습니다.",
    "port_conflict": "로컬 인증 응답 포트를 사용할 수 없습니다. 연결되지 않았습니다.",
}
_ACCEPTED = b"Local callback received. No service connection has been activated."
_REJECTED = b"Local callback rejected. No service connection has been activated."


class CallbackError(OAuthError):
    """Fixed local error messages that never include callbacks or credentials."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        if code in _MESSAGES:
            self.code = code
            self.args = (_MESSAGES[code],)


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

    def assert_valid(self, account_key: str) -> None:
        """Authenticate the consumed callback binding before synthetic exchange.

        Dataclass immutability alone would not stop a forged/modified result. This
        process-local seal covers every input to the later token POST. It cannot
        protect against code injection or inspection of this process's memory.
        """
        try:
            if (
                type(self) is not CallbackResult or self.mode != "SYNTHETIC_CALLBACK"
                or not isinstance(self._seal, bytes) or len(self._seal) != 32
                or not hmac.compare_digest(self._seal, _result_seal(self))
                or pkce_s256(self.verifier.get_secret_value()) != self.code_challenge
                or not re.fullmatch(r"nf-synthetic-code-[A-Za-z0-9_-]{1,200}", self.code.get_secret_value())
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

    def log_message(self, format: str, *args: object) -> None:
        return None

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._reply(code, _REJECTED)

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
            if len(self.raw_requestline) > _MAX_REQUEST_LINE:
                self.requestline, self.request_version, self.command = "", "HTTP/1.0", ""
                self._reply(414, _REJECTED)
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
                self._reply(405, _REJECTED)
                return
            owner: LoopbackCallbackListener = self.server.owner
            owner._handle(self)
            self.wfile.flush()
        except (TimeoutError, OSError, http.client.HTTPException):
            self.close_connection = True
        except Exception:  # noqa: BLE001 - malformed local input must never print raw request/traceback
            self.close_connection = True
            self._reply(400, _REJECTED)


class LoopbackCallbackListener:
    """Dormant production listener. The activation gate executes before any bind."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
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
                mode="SYNTHETIC_CALLBACK" if synthetic else "PRODUCTION_BLOCKED",
            )
            self._server, self._launch = server, CallbackLaunch(request, uri)
            self._verifier, self._state_digest = SecretStr(verifier), hashlib.sha256(state.encode()).digest()
            self._deadline, self._allowed_origin, self._synthetic = monotonic() + lifetime, origin, synthetic
            server.owner = self
            self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                                            name="newsflow-synthetic-callback", daemon=True)
            self._thread.start()
            return self._launch

    def _finish_locked(self, *, error: str | None = None, result: CallbackResult | None = None) -> None:
        self._consumed = True
        self._error = CallbackError(error) if error is not None else None
        self._result = result
        self._event.set()

    def _handle(self, handler: _Handler) -> None:
        assert self._launch is not None
        uri = urlsplit(self._launch.redirect_uri)
        host = f"127.0.0.1:{uri.port}"
        origins = handler.headers.get_all("Origin", [])
        hosts = handler.headers.get_all("Host", [])
        if (
            handler.client_address[0] != "127.0.0.1" or hosts != [host]
            or len(origins) > 1 or (origins and origins[0] != self._allowed_origin)
            or handler.headers.get_all("Transfer-Encoding", [])
            or handler.headers.get_all("Content-Length", []) not in ([], ["0"])
        ):
            with self._lock:
                self._rejected += 1
            handler._reply(400, _REJECTED)
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
            with self._lock:
                self._rejected += 1
            handler._reply(400, _REJECTED)
            return
        with self._lock:
            if self._closed or self._consumed:
                self._rejected += 1
                handler._reply(409, _REJECTED)
                return
            if monotonic() >= self._deadline:
                self._finish_locked(error="expired")
                self._rejected += 1
                handler._reply(410, _REJECTED)
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
                self._rejected += 1
                handler._reply(400, _REJECTED)
                return
            try:
                values: dict[str, str] = {}
                allowed = {"state", "code", "error", "error_description", "scope", "authuser", "prompt"}
                if not 1 <= len(pairs) <= _MAX_FIELDS:
                    raise CallbackError("callback_invalid")
                for key, value in pairs:
                    if (
                        key not in allowed or key in values or not value or len(value) > 2048
                        or any(ord(character) < 32 or ord(character) == 127 for character in value)
                    ):
                        raise CallbackError("callback_invalid")
                    values[key] = value
                state = values.get("state", "")
                if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", state) or not hmac.compare_digest(
                    hashlib.sha256(state.encode("ascii")).digest(), self._state_digest,
                ):
                    raise CallbackError("state_mismatch")
                if ("code" in values) == ("error" in values):
                    raise CallbackError("callback_invalid")
                if "error" in values:
                    raise CallbackError("cancelled" if values["error"] == "access_denied" else "provider_error")
                if "error_description" in values:
                    raise CallbackError("callback_invalid")
                if self._synthetic and not re.fullmatch(r"nf-synthetic-code-[A-Za-z0-9_-]{1,200}", values["code"]):
                    raise CallbackError("callback_invalid")
                verifier = self._verifier
                if verifier is None or pkce_s256(verifier.get_secret_value()) != self._launch.request.code_challenge:
                    raise CallbackError("callback_invalid")
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
                handler._reply(200, _ACCEPTED)
            except CallbackError as error:
                self._finish_locked(error=error.code)
                self._rejected += 1
                handler._reply(400, _REJECTED)

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
