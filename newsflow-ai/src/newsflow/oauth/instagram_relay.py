"""Desktop client for an operator-owned HTTPS Facebook Login authorization relay.

Only the relay owns the Meta App Secret. Session redemption uses a one-use
memory-only verifier; the browser never receives an access token. Local status
reads do not poll a provider or the relay.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event, RLock
from urllib.parse import parse_qsl, urlsplit

from pydantic import SecretStr

from newsflow.news.rss_adapter import PinnedConnection, public_addresses, validate_url
from newsflow.publishing.auth import TokenBundle

from .instagram import FACEBOOK_SCOPES, GRAPH_VERSION, InstagramConnectionError, MetaAuthorization

_SESSION = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_ID = re.compile(r"[1-9][0-9]{0,29}\Z")
_SAFE_CODES = {"permission_denied", "professional_required", "identity_mismatch", "expired",
               "response_invalid", "connection_failed", "outcome_unknown", "cancelled", "rate_limited"}
_MAX_RESPONSE = 128 * 1024


def _error_code(value: object, default: str = "outcome_unknown") -> str:
    if value == "authentication_failed":
        return "connection_failed"
    if value == "configuration_invalid":
        return "relay_config_invalid"
    return value if isinstance(value, str) and value in _SAFE_CODES else default


@dataclass(frozen=True)
class RelayConfig:
    origin: str
    app_id: str

    @classmethod
    def parse(cls, origin: str, app_id: str) -> RelayConfig:
        try:
            if not isinstance(origin, str) or not isinstance(app_id, str) or not _ID.fullmatch(app_id):
                raise ValueError
            checked = validate_url(origin)
            parts = urlsplit(checked)
            if parts.scheme != "https" or parts.path != "/" or parts.query:
                raise ValueError
            # A relay origin is public HTTPS on the default TLS port, never a path or redirect target.
            return cls(f"https://{parts.netloc}", app_id)
        except Exception:  # noqa: BLE001 - do not echo configuration URLs or parser details
            raise InstagramConnectionError("relay_config_invalid") from None


@dataclass(frozen=True)
class RelayResponse:
    status: int
    data: dict = field(repr=False)


class PublicRelayTransport:
    """Public-IP-pinned TLS requests to one configured origin, with no retries."""

    def __init__(self, config: RelayConfig, *, timeout: float = 30) -> None:
        self.config, self.timeout = config, timeout

    def request(self, method: str, path: str, body: dict | None = None, verifier: str | None = None) -> RelayResponse:
        allowed = ((method == "POST" and path == "/v1/sessions" and verifier is None)
                   or (method in {"GET", "DELETE"} and re.fullmatch(r"/v1/sessions/[A-Za-z0-9_-]{32,128}", path))
                   or (method == "POST" and re.fullmatch(r"/v1/sessions/[A-Za-z0-9_-]{32,128}/redeem", path)))
        if not allowed or (path != "/v1/sessions" and (not isinstance(verifier, str) or not _SESSION.fullmatch(verifier))):
            raise InstagramConnectionError("response_invalid")
        connection = None
        try:
            host = urlsplit(self.config.origin).hostname
            addresses = public_addresses(host, 443, self.timeout)
            connection = PinnedConnection(host, addresses[0], 443, self.timeout, True)
            encoded = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
            headers = {"Accept": "application/json", "Accept-Encoding": "identity", "Cache-Control": "no-store"}
            if encoded is not None:
                headers["Content-Type"] = "application/json"
            if verifier is not None:
                headers["Authorization"] = "Bearer " + verifier
            connection.request(method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            if 300 <= response.status < 400 or response.getheader("Content-Encoding", "identity") not in {"", "identity"}:
                raise InstagramConnectionError("outcome_unknown")
            deadline = time.monotonic() + self.timeout
            chunks, size = [], 0
            while size <= _MAX_RESPONSE:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(16384, _MAX_RESPONSE + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if size > _MAX_RESPONSE:
                raise ValueError
            data = json.loads(b"".join(chunks))
            if not isinstance(data, dict):
                raise TypeError
            return RelayResponse(response.status, data)
        except InstagramConnectionError:
            raise
        except Exception:  # noqa: BLE001 - response/token/connection details must remain private
            raise InstagramConnectionError("outcome_unknown") from None
        finally:
            if connection is not None:
                connection.close()


class InstagramRelayAuthorization:
    """One explicitly initiated session; polling never repeats OAuth exchanges."""

    background = True

    def __init__(self, config: RelayConfig, *, transport=None, browser_open=None, poll_interval: float = 2,
                 monotonic=None) -> None:
        self.config = config
        self.transport = transport if transport is not None else PublicRelayTransport(config)
        self.browser_open = browser_open if browser_open is not None else webbrowser.open
        self.poll_interval = poll_interval
        self.monotonic = monotonic or time.monotonic
        self._lock, self._cancel, self._selection = RLock(), Event(), Event()
        self._session = self._verifier = self._selected = None
        self._pages: list[dict] = []
        self._state, self._cancel_sent = "idle", False

    def snapshot(self) -> dict:
        with self._lock:
            return {"relay_state": self._state, "pages": [dict(page) for page in self._pages],
                    "awaiting_page": self._state == "select_page"}

    def prepare(self) -> None:
        """Reset only at a new explicit connect action, before its worker starts."""
        with self._lock:
            if self._state not in {"idle", "complete", "cancelled", "error"}:
                raise InstagramConnectionError("pending")
            self._cancel.clear()
            self._selection.clear()
            self._session, self._verifier, self._selected, self._pages = None, None, None, []
            self._state, self._cancel_sent = "idle", False

    def select_page(self, page_id: str) -> None:
        with self._lock:
            if self._state != "select_page" or page_id not in {page["id"] for page in self._pages}:
                raise InstagramConnectionError("identity_mismatch")
            self._selected = page_id
            self._selection.set()

    def cancel(self, *, remote: bool = True) -> None:
        with self._lock:
            self._cancel.set()
            self._selection.set()
            self._state = "cancelled"
            session, verifier = self._session, self._verifier
            should_send = remote and bool(session and verifier) and not self._cancel_sent
            if should_send:
                self._cancel_sent = True
        if should_send:
            try:
                self.transport.request("DELETE", f"/v1/sessions/{session}", verifier=verifier)
            except Exception:  # noqa: BLE001, S110 - cancellation remains final; logging could expose verifier material
                pass

    def _response(self, method: str, path: str, body=None, *, initial=False) -> dict:
        if self._cancel.is_set():
            raise InstagramConnectionError("cancelled")
        try:
            response = self.transport.request(method, path, body, None if initial else self._verifier)
            if response.status not in {200, 201}:
                code = response.data.get("code")
                raise InstagramConnectionError(_error_code(code))
            if not isinstance(response.data, dict):
                raise TypeError
            return response.data
        except InstagramConnectionError:
            raise
        except Exception:  # noqa: BLE001 - no secret-bearing transport exception is propagated
            raise InstagramConnectionError("outcome_unknown") from None

    def _authorization_url(self, value: object) -> str:
        try:
            if not isinstance(value, str) or len(value) > 8192 or any(ord(char) <= 32 for char in value):
                raise ValueError
            parts = urlsplit(value)
            pairs = parse_qsl(parts.query, strict_parsing=True)
            values = dict(pairs)
            required = {"client_id", "config_id", "response_type", "override_default_response_type", "state", "redirect_uri"}
            if (parts.scheme != "https" or parts.netloc != "www.facebook.com" or parts.fragment
                    or parts.path != f"/{GRAPH_VERSION}/dialog/oauth" or set(values) != required
                    or len(pairs) != len(values) or values["client_id"] != self.config.app_id
                    or not _ID.fullmatch(values["config_id"]) or values["response_type"] != "code"
                    or values["override_default_response_type"] != "true" or not _SESSION.fullmatch(values["state"])
                    or values["redirect_uri"] != self.config.origin + "/oauth/callback"):
                raise ValueError
            return value
        except Exception:  # noqa: BLE001 - an untrusted redirect is never opened or reflected
            raise InstagramConnectionError("response_invalid") from None

    @staticmethod
    def _page_choices(value: object) -> list[dict]:
        if not isinstance(value, list) or not 1 <= len(value) <= 100:
            raise InstagramConnectionError("professional_required")
        pages = []
        for row in value:
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not _ID.fullmatch(row["id"])
                    or not isinstance(row.get("instagram_id"), str) or not _ID.fullmatch(row["instagram_id"])
                    or not isinstance(row.get("name"), str) or not 1 <= len(row["name"]) <= 200
                    or any(ord(char) < 32 for char in row["name"])):
                raise InstagramConnectionError("response_invalid")
            pages.append({"id": row["id"], "name": row["name"], "instagram_id": row["instagram_id"]})
        if len({page["id"] for page in pages}) != len(pages):
            raise InstagramConnectionError("response_invalid")
        return pages

    def authorize(self, *, scopes: tuple[str, ...]) -> MetaAuthorization:
        if tuple(scopes) != FACEBOOK_SCOPES:
            raise InstagramConnectionError("permission_denied")
        with self._lock:
            if self._cancel.is_set():
                raise InstagramConnectionError("cancelled")
            if self._state != "idle":
                raise InstagramConnectionError("pending")
            self._verifier = secrets.token_urlsafe(32)
            self._state = "starting"
        try:
            started = self._response("POST", "/v1/sessions", {
                "challenge": hashlib.sha256(self._verifier.encode("ascii")).hexdigest(),
            }, initial=True)
            session, expires = started.get("session_id"), started.get("expires_in")
            if (not isinstance(session, str) or not _SESSION.fullmatch(session) or type(expires) is not int
                    or not 30 <= expires <= 600 or started.get("app_id") != self.config.app_id):
                raise InstagramConnectionError("response_invalid")
            authorization_url = self._authorization_url(started.get("authorize_url"))
            with self._lock:
                self._session, self._state = session, "waiting"
            if self._cancel.is_set():
                raise InstagramConnectionError("cancelled")
            if not self.browser_open(authorization_url):
                raise InstagramConnectionError("connection_failed")
            deadline = self.monotonic() + expires
            path = f"/v1/sessions/{session}"
            while self.monotonic() < deadline:
                polled = self._response("GET", path)
                state = polled.get("status")
                if state == "ready":
                    pages = self._page_choices(polled.get("pages"))
                    with self._lock:
                        self._pages, self._state = pages, "select_page"
                    while not self._selection.wait(min(self.poll_interval, max(0, deadline - self.monotonic()))):
                        if self.monotonic() >= deadline:
                            raise InstagramConnectionError("expired")
                    if self._cancel.is_set():
                        raise InstagramConnectionError("cancelled")
                    if not self._selected:
                        raise InstagramConnectionError("identity_mismatch")
                    with self._lock:
                        self._state = "redeeming"
                    data = self._response("POST", path + "/redeem", {"page_id": self._selected})
                    grant = self._grant(data, self._selected)
                    with self._lock:
                        self._state = "complete"
                    return grant
                if state != "pending":
                    code = polled.get("code")
                    raise InstagramConnectionError(_error_code(code, "cancelled" if state == "cancelled" else "outcome_unknown"))
                if self._cancel.wait(self.poll_interval):
                    raise InstagramConnectionError("cancelled")
            raise InstagramConnectionError("expired")
        except Exception as error:
            with self._lock:
                self._state = "cancelled" if self._cancel.is_set() else "error"
            if isinstance(error, InstagramConnectionError):
                raise
            raise InstagramConnectionError("outcome_unknown") from None
        finally:
            with self._lock:
                self._verifier = None

    def _grant(self, data: dict, page_id: str) -> MetaAuthorization:
        try:
            token, scopes = data["access_token"], data["scopes"]
            if (data.get("app_id") != self.config.app_id or data.get("page_id") != page_id
                    or not isinstance(token, str) or not 1 <= len(token) <= 4096
                    or any(ord(char) < 33 or ord(char) == 127 for char in token)
                    or not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes)
                    or not set(FACEBOOK_SCOPES).issubset(scopes)):
                raise ValueError
            expires = datetime.fromisoformat(data["expires_at"])
            data_expires = datetime.fromisoformat(data["data_access_expires_at"])
            if expires.tzinfo is None or data_expires.tzinfo is None:
                raise ValueError
            return MetaAuthorization(self.config.app_id, page_id,
                                     TokenBundle(access_token=SecretStr(token), expires_at=expires, scopes=tuple(scopes)),
                                     data_expires)
        except Exception:  # noqa: BLE001 - invalid grant material must never be echoed or persisted
            raise InstagramConnectionError("response_invalid") from None
