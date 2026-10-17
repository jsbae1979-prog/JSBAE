"""Small, separately deployed HTTPS authorization relay; never a media server.

App secrets belong only to this server's environment. This module is not mounted
by the Windows NewsFlow application. Sessions, authorization codes and tokens are
short lived in memory; restart invalidates every pending authorization. No request
is retried. The official debug_token request necessarily sends input_token in its
server-to-Meta HTTPS query; it is never a browser/relay URL and is never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import ssl
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from fastapi import FastAPI
from fastapi.requests import Request as WebRequest
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import SecretStr

from .instagram import FACEBOOK_SCOPES, GRAPH_VERSION

_ID = re.compile(r"[1-9][0-9]{0,29}\Z")
_OPAQUE = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_CHALLENGE = re.compile(r"[a-f0-9]{64}\Z")
_CONTENT_TASKS = {"CREATE_CONTENT", "MANAGE", "PROFILE_PLUS_CREATE_CONTENT", "PROFILE_PLUS_FULL_CONTROL"}
_MAX_BODY = 262144
_ERRORS = {"invalid_request", "invalid_state", "expired", "cancelled", "permission_denied",
           "identity_mismatch", "professional_required", "authentication_failed", "outcome_unknown",
           "not_ready", "consumed", "rate_limited", "configuration_invalid"}


class RelayError(Exception):
    def __init__(self, code: str = "outcome_unknown", status: int = 400) -> None:
        self.code = code if code in _ERRORS else "outcome_unknown"
        self.status = status
        super().__init__(self.code)


@dataclass(frozen=True)
class RelayConfig:
    public_origin: str
    app_id: str
    config_id: str
    app_secret: SecretStr = field(repr=False)
    session_ttl: int = 600
    max_sessions: int = 100

    def __post_init__(self):
        try:
            parsed = urlsplit(self.public_origin)
            if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.path
                    or parsed.query or parsed.fragment or not parsed.hostname or parsed.port not in (None, 443)
                    or parsed.hostname != parsed.hostname.lower()
                    or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", parsed.hostname)
                    or "." not in parsed.hostname or parsed.hostname.endswith((".localhost", ".local"))
                    or all(part.isdigit() for part in parsed.hostname.split("."))
                    or not _ID.fullmatch(self.app_id) or not _ID.fullmatch(self.config_id)
                    or not isinstance(self.app_secret, SecretStr)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", self.app_secret.get_secret_value())
                    or type(self.session_ttl) is not int or not 60 <= self.session_ttl <= 600
                    or type(self.max_sessions) is not int or not 1 <= self.max_sessions <= 1000):
                raise ValueError
        except Exception:  # noqa: BLE001 - configuration errors must never reveal the app secret
            raise RelayError("configuration_invalid") from None

    @property
    def callback_uri(self) -> str:
        return self.public_origin + "/oauth/callback"

    @classmethod
    def from_environment(cls):
        """Read server-only configuration, only when this separate factory is called."""
        return cls(os.environ.get("NEWSFLOW_META_RELAY_ORIGIN", ""), os.environ.get("NEWSFLOW_META_APP_ID", ""),
                   os.environ.get("NEWSFLOW_META_CONFIG_ID", ""),
                   SecretStr(os.environ.get("NEWSFLOW_META_APP_SECRET", "")))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RelayError("outcome_unknown")
        result[key] = value
    return result


class MetaRelayTransport:
    """Fixed Graph endpoints, TLS verification, bounded replies and no retry/logging."""

    def __init__(self, config: RelayConfig):
        self.config = config

    def _request(self, method: str, path: str, *, values: dict | None = None, token: SecretStr | None = None):
        if (method, path) not in {("POST", "oauth/access_token"), ("GET", "debug_token"),
                                  ("GET", "me/permissions"), ("GET", "me/accounts")}:
            raise RelayError("invalid_request")
        values = values or {}
        payload = urlencode(values).encode("ascii")
        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{path}"
        headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token.get_secret_value()
        if method == "GET" and payload:
            url += "?" + payload.decode("ascii")
        request = Request(url, data=payload if method == "POST" else None, headers=headers, method=method)
        opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        try:
            with opener.open(request, timeout=25) as response:
                raw = response.read(_MAX_BODY + 1)
                if response.status != 200 or len(raw) > _MAX_BODY:
                    raise RelayError("outcome_unknown")
            data = json.loads(raw, object_pairs_hook=_unique_object)
            if not isinstance(data, dict) or "error" in data:
                raise RelayError("outcome_unknown")
            return data
        except RelayError:
            raise
        except HTTPError as error:
            # A received 4xx is definitive; raw provider descriptions are never echoed.
            raise RelayError("authentication_failed" if error.code in {400, 401} else
                             "permission_denied" if error.code == 403 else "outcome_unknown") from None
        except Exception:  # noqa: BLE001 - includes token-bearing upstream URL and provider body
            raise RelayError("outcome_unknown") from None

    def exchange(self, code: SecretStr) -> dict:
        return self._request("POST", "oauth/access_token", values={
            "client_id": self.config.app_id, "client_secret": self.config.app_secret.get_secret_value(),
            "redirect_uri": self.config.callback_uri, "code": code.get_secret_value(),
        })

    def inspect(self, token: SecretStr) -> dict:
        # Meta requires input_token as a GET parameter. This request never reaches
        # an app browser or relay access log; exceptions and telemetry redact it.
        app_token = SecretStr(self.config.app_id + "|" + self.config.app_secret.get_secret_value())
        return self._request("GET", "debug_token", values={"input_token": token.get_secret_value()}, token=app_token)

    def permissions(self, token: SecretStr) -> dict:
        return self._request("GET", "me/permissions", token=token)

    def pages(self, token: SecretStr) -> dict:
        # Tokens are deliberately omitted. The desktop obtains the selected Page's
        # token directly after this verified user grant is redeemed.
        return self._request("GET", "me/accounts", token=token,
                             values={"fields": "id,name,tasks,instagram_business_account", "limit": "100"})


@dataclass
class _Session:
    identifier: str = field(repr=False)
    challenge: str = field(repr=False)
    state_digest: str = field(repr=False)
    deadline: float
    status: str = "pending"
    error_code: str | None = None
    grant: dict | None = field(default=None, repr=False)
    pages: list[dict] = field(default_factory=list)


class RelaySessions:
    def __init__(self, config: RelayConfig, transport, clock=None):
        self.config, self.transport = config, transport
        self.clock = clock or time.time
        self.lock = threading.RLock()
        self.sessions: dict[str, _Session] = {}
        self.states: dict[str, str] = {}
        self.used_codes: dict[str, float] = {}
        self.rates: dict[str, list[float]] = {}

    def _cleanup(self):
        instant = self.clock()
        for identifier, session in list(self.sessions.items()):
            if session.deadline <= instant:
                session.grant, session.pages = None, []
                self.states.pop(session.state_digest, None)
                self.sessions.pop(identifier, None)
        self.used_codes = {key: expiry for key, expiry in self.used_codes.items() if expiry > instant}
        self.rates = {key: [stamp for stamp in values if stamp > instant - 60]
                      for key, values in self.rates.items() if values and values[-1] > instant - 60}

    def create(self, challenge: str, client: str) -> dict:
        if not isinstance(challenge, str) or not _CHALLENGE.fullmatch(challenge):
            raise RelayError("invalid_request")
        with self.lock:
            self._cleanup()
            times = self.rates.setdefault(client, [])
            if len(self.sessions) >= self.config.max_sessions or len(times) >= 10:
                raise RelayError("rate_limited", 429)
            if any(hmac.compare_digest(session.challenge, challenge) for session in self.sessions.values()):
                raise RelayError("invalid_request", 409)
            times.append(self.clock())
            identifier, state = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            digest = hashlib.sha256(state.encode()).hexdigest()
            self.sessions[identifier] = _Session(identifier, challenge, digest, self.clock() + self.config.session_ttl)
            self.states[digest] = identifier
        query = urlencode({"client_id": self.config.app_id, "config_id": self.config.config_id,
                           "response_type": "code", "override_default_response_type": "true",
                           "redirect_uri": self.config.callback_uri, "state": state})
        return {"session_id": identifier, "app_id": self.config.app_id, "expires_in": self.config.session_ttl,
                "authorize_url": f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?{query}"}

    def _owned(self, identifier: str, verifier: str) -> _Session:
        self._cleanup()
        if not _OPAQUE.fullmatch(identifier) or not _OPAQUE.fullmatch(verifier):
            raise RelayError("invalid_request", 403)
        session = self.sessions.get(identifier)
        if session is None:
            raise RelayError("expired", 410)
        if not hmac.compare_digest(session.challenge, hashlib.sha256(verifier.encode()).hexdigest()):
            raise RelayError("invalid_request", 403)
        return session

    def poll(self, identifier: str, verifier: str) -> dict:
        with self.lock:
            session = self._owned(identifier, verifier)
            result = {"status": "pending" if session.status == "exchanging" else session.status}
            if session.error_code:
                result["code"] = session.error_code
            if session.status == "ready":
                result["pages"] = [dict(page) for page in session.pages]
            return result

    def cancel(self, identifier: str, verifier: str) -> dict:
        with self.lock:
            session = self._owned(identifier, verifier)
            if session.status == "consumed":
                raise RelayError("consumed", 409)
            session.status, session.error_code, session.grant, session.pages = "cancelled", "cancelled", None, []
            self.states.pop(session.state_digest, None)
            return {"status": "cancelled"}

    def redeem(self, identifier: str, verifier: str, page_id: str) -> dict:
        with self.lock:
            session = self._owned(identifier, verifier)
            if session.status != "ready" or session.grant is None:
                raise RelayError("consumed" if session.status == "consumed" else "not_ready", 409)
            if datetime.fromisoformat(session.grant["expires_at"]).timestamp() <= self.clock() + 30:
                session.status, session.error_code, session.grant, session.pages = "error", "expired", None, []
                raise RelayError("expired", 410)
            if not isinstance(page_id, str) or not any(page["id"] == page_id for page in session.pages):
                raise RelayError("identity_mismatch", 403)
            result = {**session.grant, "page_id": page_id}
            # Atomic one-use delivery: a lost response must not be fetched again.
            session.status, session.grant, session.pages = "consumed", None, []
            return result

    def callback(self, state: str, code: SecretStr | None, denied: bool) -> str:
        if not isinstance(state, str) or not _OPAQUE.fullmatch(state):
            raise RelayError("invalid_state")
        digest = hashlib.sha256(state.encode()).hexdigest()
        with self.lock:
            self._cleanup()
            identifier = self.states.pop(digest, None)
            session = self.sessions.get(identifier) if identifier else None
            if session is None or session.status != "pending":
                raise RelayError("invalid_state")
            if denied:
                session.status, session.error_code = "cancelled", "cancelled"
                return "cancelled"
            if (not isinstance(code, SecretStr) or not 1 <= len(code.get_secret_value()) <= 4096
                    or any(ord(char) < 33 or ord(char) == 127 for char in code.get_secret_value())):
                session.status, session.error_code = "error", "invalid_request"
                raise RelayError("invalid_request")
            code_digest = hashlib.sha256(code.get_secret_value().encode()).hexdigest()
            if code_digest in self.used_codes:
                session.status, session.error_code = "error", "invalid_state"
                raise RelayError("invalid_state")
            self.used_codes[code_digest] = session.deadline
            session.status = "exchanging"
        try:
            grant, pages = self._exchange(code, lambda: self._checkpoint(identifier, session))
            with self.lock:
                # Cancellation, expiry or restart cannot resurrect an authorization.
                if self.sessions.get(identifier) is not session or session.status != "exchanging":
                    return "cancelled"
                if session.deadline <= self.clock():
                    session.status, session.error_code = "error", "expired"
                    return "error"
                session.grant, session.pages, session.status = grant, pages, "ready"
                return "ready"
        except Exception as error:  # noqa: BLE001 - never include Meta bodies, codes or tokens in a response
            failure = error.code if isinstance(error, RelayError) else "outcome_unknown"
            with self.lock:
                if session.status == "exchanging":
                    session.status = "unknown" if failure == "outcome_unknown" else "error"
                    session.error_code, session.grant, session.pages = failure, None, []
                return session.status

    def _checkpoint(self, identifier, session):
        with self.lock:
            if self.sessions.get(identifier) is not session or session.status != "exchanging":
                raise RelayError("cancelled")
            if session.deadline <= self.clock():
                raise RelayError("expired")

    def _exchange(self, code: SecretStr, checkpoint) -> tuple[dict, list[dict]]:
        checkpoint()
        response = self.transport.exchange(code)
        raw_token = response.get("access_token") if isinstance(response, dict) else None
        lifetime = response.get("expires_in") if isinstance(response, dict) else None
        if (not isinstance(raw_token, str) or not 1 <= len(raw_token) <= 4096
                or any(ord(char) < 33 or ord(char) == 127 for char in raw_token)
                or str(response.get("token_type", "")).lower() != "bearer"
                or type(lifetime) is not int or not 30 < lifetime <= 86400 * 60):
            raise RelayError("outcome_unknown")
        token = SecretStr(raw_token)
        checkpoint()
        introspection = self.transport.inspect(token)
        data = introspection.get("data") if isinstance(introspection, dict) else None
        if (not isinstance(data, dict) or data.get("is_valid") is not True or data.get("type") != "USER"
                or str(data.get("app_id")) != self.config.app_id
                or not isinstance(data.get("user_id"), str) or not _ID.fullmatch(data["user_id"])):
            raise RelayError("identity_mismatch")
        scopes, expiry, data_expiry = data.get("scopes"), data.get("expires_at"), data.get("data_access_expires_at")
        if (not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes)
                or not set(FACEBOOK_SCOPES).issubset(scopes)):
            raise RelayError("permission_denied")
        if (type(expiry) is not int or type(data_expiry) is not int
                or min(expiry, data_expiry) <= self.clock() + 30):
            raise RelayError("expired")
        checkpoint()
        permissions = self.transport.permissions(token).get("data")
        if not isinstance(permissions, list) or not all(isinstance(item, dict) for item in permissions):
            raise RelayError("outcome_unknown")
        granted = {item.get("permission") for item in permissions if item.get("status") == "granted"}
        if not set(FACEBOOK_SCOPES).issubset(granted):
            raise RelayError("permission_denied")
        checkpoint()
        response = self.transport.pages(token)
        rows = response.get("data") if isinstance(response, dict) else None
        if not isinstance(rows, list) or not 0 < len(rows) <= 100 or not all(isinstance(row, dict) for row in rows):
            raise RelayError("professional_required")
        pages = []
        for row in rows:
            linked, tasks = row.get("instagram_business_account"), row.get("tasks")
            if (not isinstance(linked, dict) or not isinstance(tasks, list)
                    or not all(isinstance(task, str) for task in tasks) or not _CONTENT_TASKS.intersection(tasks)):
                continue
            page_id, instagram_id, name = row.get("id"), linked.get("id"), row.get("name")
            if (not isinstance(page_id, str) or not _ID.fullmatch(page_id)
                    or not isinstance(instagram_id, str) or not _ID.fullmatch(instagram_id)
                    or not isinstance(name, str) or not 1 <= len(name) <= 200
                    or any(ord(char) < 32 for char in name)):
                raise RelayError("outcome_unknown")
            if any(page["id"] == page_id for page in pages):
                raise RelayError("identity_mismatch")
            pages.append({"id": page_id, "name": name, "instagram_id": instagram_id})
        if not pages:
            raise RelayError("professional_required")
        expiry = min(expiry, data_expiry, int(self.clock()) + lifetime)
        return {"app_id": self.config.app_id, "access_token": raw_token,
                "expires_at": datetime.fromtimestamp(expiry, UTC).isoformat(),
                "data_access_expires_at": datetime.fromtimestamp(data_expiry, UTC).isoformat(),
                "scopes": list(FACEBOOK_SCOPES)}, pages


def _bearer(request: WebRequest) -> str:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or not _OPAQUE.fullmatch(authorization[7:]):
        raise RelayError("invalid_request", 403)
    return authorization[7:]


async def _body(request: WebRequest, expected: str) -> str:
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise RelayError("invalid_request", 415)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 2048:
            raise RelayError("invalid_request", 413)
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != {expected} or not isinstance(data[expected], str):
            raise ValueError
        return data[expected]
    except Exception:  # noqa: BLE001 - never reflect request body or credential input
        raise RelayError("invalid_request") from None


def create_relay_app(config: RelayConfig | None = None, *, transport=None, clock=None) -> FastAPI:
    """Factory for a separate TLS listener. No external call occurs during startup."""
    config = config or RelayConfig.from_environment()
    store = RelaySessions(config, transport if transport is not None else MetaRelayTransport(config), clock)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.relay_sessions = store

    @app.exception_handler(RelayError)
    async def error_handler(request: WebRequest, error: RelayError):
        return JSONResponse({"code": error.code}, status_code=error.status)

    @app.middleware("http")
    async def boundary(request: WebRequest, call_next):
        # No proxy headers are used here; launch with --no-proxy-headers and
        # terminate TLS on this listener or an audited end-to-end TLS deployment.
        callback = request.url.path == "/oauth/callback"
        if callback:
            request.scope["relay_callback_query"] = request.scope.get("query_string", b"")
            request.scope["query_string"] = b""  # prevent default ASGI access logs exposing codes/state
        if (request.scope.get("scheme") != "https"
                or request.headers.get("host", "") != urlsplit(config.public_origin).netloc
                or request.headers.get("origin") is not None):
            response = JSONResponse({"code": "invalid_request"}, status_code=403)
        else:
            response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer",
                                 "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                                 "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
                                 "Strict-Transport-Security": "max-age=31536000"})
        return response

    @app.post("/v1/sessions")
    async def create(request: WebRequest):
        challenge = await _body(request, "challenge")
        client = request.client.host if request.client else "unavailable"
        return store.create(challenge, client)

    @app.get("/v1/sessions/{identifier}")
    def poll(identifier: str, request: WebRequest):
        return store.poll(identifier, _bearer(request))

    @app.delete("/v1/sessions/{identifier}")
    def cancel(identifier: str, request: WebRequest):
        return store.cancel(identifier, _bearer(request))

    @app.post("/v1/sessions/{identifier}/redeem")
    async def redeem(identifier: str, request: WebRequest):
        page_id = await _body(request, "page_id")
        return store.redeem(identifier, _bearer(request), page_id)

    @app.get("/oauth/callback")
    def callback(request: WebRequest):
        from urllib.parse import parse_qs

        raw = request.scope.pop("relay_callback_query", b"")
        try:
            if len(raw) > 8192:
                raise RelayError("invalid_request")
            params = parse_qs(raw.decode("ascii"), keep_blank_values=True, max_num_fields=12)
            if (any(len(values) != 1 for values in params.values())
                    or "state" not in params or ("code" in params and "error" in params)):
                raise RelayError("invalid_request")
            code = SecretStr(params["code"][0]) if "code" in params else None
            status = store.callback(params["state"][0], code, "error" in params)
            message = "연결 응답을 처리했습니다. NewsFlow AI로 돌아가 계정을 확인해 주세요." if status == "ready" else (
                "연결을 완료하지 못했습니다. NewsFlow AI에서 상태를 확인해 주세요."
            )
            return HTMLResponse("<!doctype html><html lang='ko'><meta charset='utf-8'><title>NewsFlow AI</title>"
                                "<p>" + message + "</p></html>")
        except Exception:  # noqa: BLE001 - callback values must never enter HTML, logs or errors
            return HTMLResponse("<!doctype html><html lang='ko'><meta charset='utf-8'><p>"
                                "유효하지 않거나 이미 처리된 연결 응답입니다.</p></html>", status_code=400)

    return app
