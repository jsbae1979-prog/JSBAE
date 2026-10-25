"""Desktop-only loopback callback, reusing the existing bounded HTTP server/handler."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import SecretStr

from .callback import _CallbackHTTPServer, _Handler, _seconds
from .tiktok_protocol import AUTHORIZE, SCOPES, DesktopConfig, TikTokError, challenge, production_enabled

PATH = "/oauth/tiktok/callback/"


class TikTokCallback:
    def __init__(self, *, synthetic=False):
        self.synthetic = synthetic
        self._lock, self._event = threading.Lock(), threading.Event()
        self._server = self._thread = None
        self._used = self._delivered = False
        self._code = self._error = None
        self.verifier = SecretStr(secrets.token_urlsafe(64))
        self.state = SecretStr(secrets.token_urlsafe(32))
        self.redirect_uri = ""
        self.deadline = 0.0
        self._observations = dict.fromkeys(
            ("tcp_connections", "http_requests", "read_failures", "rejected_requests"), 0)

    def start(self, config: DesktopConfig, *, ttl=300) -> SecretStr:
        if not self.synthetic and not production_enabled():
            raise TikTokError("blocked")
        with self._lock:
            if self._server or self._used:
                raise TikTokError("callback")
            lifetime = _seconds(ttl)
            server = _CallbackHTTPServer(("127.0.0.1", config.port), _Handler, bind_and_activate=False)
            try:
                server.server_bind()
                server.server_activate()
                port = server.server_address[1]
                if port == 8765:
                    raise OSError
            except OSError:
                server.server_close()
                raise TikTokError("port") from None
            self._server = server
            self.redirect_uri = f"http://127.0.0.1:{port}{PATH}"
            self.deadline = monotonic() + lifetime
            server.owner = self
            self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
            self._thread.start()
            return SecretStr(AUTHORIZE + "?" + urlencode({
                "client_key": config.client_key, "response_type": "code", "scope": ",".join(SCOPES),
                "redirect_uri": self.redirect_uri, "state": self.state.get_secret_value(),
                "code_challenge": challenge(self.verifier.get_secret_value()), "code_challenge_method": "S256",
            }))

    def _observe(self, name: str) -> None:
        # Shared HTTP handler diagnostics contain bounded counts, never callback data.
        if name in self._observations:
            with self._lock:
                self._observations[name] = min(self._observations[name] + 1, 1_000_000)

    def _reject(self, handler: _Handler, status: int, reason: str) -> None:
        # Malformed/unauthenticated input must not consume the pending login or echo secrets.
        self._observe("rejected_requests")
        status = status if type(status) is int and 400 <= status <= 599 else 400
        handler._reply(status, b"Local callback rejected. Return to NewsFlow AI.")

    def _finish(self, error=None, code=None):
        self._used, self._error, self._code = True, error, code
        self._event.set()

    def _handle(self, handler):
        def reply(status):
            handler._reply(status, b"Return to NewsFlow AI to check the connection.")
        if (handler.client_address[0] != "127.0.0.1"
                or handler.headers.get_all("Host", []) != [urlsplit(self.redirect_uri).netloc]
                or handler.headers.get_all("Origin", [])
                or handler.headers.get_all("Transfer-Encoding", [])
                or handler.headers.get_all("Content-Length", []) not in ([], ["0"])):
            reply(400)
            return
        try:
            path = urlsplit(handler.path)
            if (not handler.path.startswith("/") or handler.path.startswith("//") or path.scheme or path.netloc
                    or path.fragment or path.path != PATH or len(path.query) > 4096
                    or re.search(r"%(?![a-fA-F0-9]{2})", path.query)):
                raise ValueError
            pairs = parse_qsl(path.query, keep_blank_values=True, strict_parsing=True, max_num_fields=5,
                              encoding="utf-8", errors="strict")
        except (ValueError, UnicodeError):
            reply(400)
            return
        with self._lock:
            if self._used:
                reply(409)
                return
            if monotonic() >= self.deadline:
                self._finish("expired")
                reply(410)
                return
            supplied = [v for k, v in pairs if k == "state"]
            if (len(supplied) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", supplied[0])
                    or not hmac.compare_digest(hashlib.sha256(supplied[0].encode()).digest(),
                                               hashlib.sha256(self.state.get_secret_value().encode()).digest())):
                reply(400)  # Unauthenticated input must not consume the pending login.
                return
            values = dict(pairs)
            if (len(values) != len(pairs) or set(values) - {"code", "state", "scopes", "error", "error_description"}
                    or any(not v or len(v) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in v) for v in values.values())
                    or ("code" in values) == ("error" in values)):
                self._finish("callback")
                reply(400)
                return
            if "error" in values:
                self._finish("cancelled" if values["error"] == "access_denied" else "permission")
            elif ("error_description" in values or self.synthetic and not values["code"].startswith("nf-synthetic-")
                  or "scopes" in values and (set(values["scopes"].split(",")) != set(SCOPES)
                      or len(values["scopes"].split(",")) != len(SCOPES))):
                self._finish("permission")
            else:
                self._finish(code=SecretStr(values["code"]))
            reply(400 if self._error else 200)

    def wait(self) -> SecretStr:
        self._event.wait(max(0, self.deadline - monotonic()))
        with self._lock:
            if not self._used:
                self._finish("expired")
            if self._error:
                raise TikTokError(self._error)
            if self._delivered or not self._code:
                raise TikTokError("callback")
            self._delivered = True
            return self._code

    def cancel(self):
        with self._lock:
            if not self._used:
                self._finish("cancelled")

    def close(self):
        self.cancel()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(2)
