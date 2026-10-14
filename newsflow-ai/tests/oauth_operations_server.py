"""Full fake Google HTTP fixture: local authorization, code exchange and channel.

Only numeric IPv4 loopback is bound. This server has no HTTP client, external
service adapter or browser. All codes and credentials are recognizable NF values.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from newsflow.oauth.identity import IDENTITY_LINK_SCOPES
from newsflow.oauth.session import pkce_s256

FAKE_CHANNEL = "UC" + "a" * 22


@dataclass(frozen=True)
class FakeGoogleResponse:
    status: int = 200
    changes: dict[str, object] = field(default_factory=dict, repr=False)
    delay: float = 0
    location: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class FakeGoogleRequest:
    method: str
    path: str
    values: dict[str, list[str]] = field(repr=False)
    authorization: str = field(default="", repr=False)


class FakeGoogleOAuthHTTPServer:
    """State/S256/exact URI fixture, with scripted failures and no raw logging."""

    def __init__(self, *, channel: str = FAKE_CHANNEL) -> None:
        self.channel = channel
        self.requests: list[FakeGoogleRequest] = []
        self.authorize_responses: deque[FakeGoogleResponse] = deque()
        self.token_responses: deque[FakeGoogleResponse] = deque()
        self.identity_responses: deque[FakeGoogleResponse] = deque()
        self.revoke_responses: deque[FakeGoogleResponse] = deque()
        self._codes: dict[str, dict[str, object]] = {}
        self._tokens: dict[str, str] = {}
        self._refresh: dict[str, tuple[str, str]] = {}
        self._lock = Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: object) -> None:
                return

            def _send(self, response: FakeGoogleResponse, payload: dict[str, object]) -> None:
                if response.delay:
                    time.sleep(response.delay)
                payload.update(response.changes)
                body = json.dumps(payload).encode()
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if response.location:
                    self.send_header("Location", response.location)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self) -> None:
                try:
                    parsed = urlsplit(self.path)
                    values = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=12)
                except ValueError:
                    self._send(FakeGoogleResponse(status=400), {})
                    return
                auth = self.headers.get("Authorization", "")
                with owner._lock:
                    owner.requests.append(FakeGoogleRequest("GET", parsed.path, values, auth))
                    if parsed.path == "/authorize":
                        result = owner._authorize(values)
                        if result is None:
                            response, payload = FakeGoogleResponse(status=400), {}
                        else:
                            response, payload = result
                    elif parsed.path == "/youtube/v3/channels":
                        response = owner.identity_responses.popleft() if owner.identity_responses else FakeGoogleResponse()
                        access = auth.removeprefix("Bearer ")
                        channel = owner._tokens.get(access)
                        if values != {"part": ["id"], "mine": ["true"]} or channel is None:
                            response, payload = FakeGoogleResponse(status=401), {}
                        else:
                            payload = {
                                "kind": "youtube#channelListResponse", "pageInfo": {"totalResults": 1},
                                "items": [{"kind": "youtube#channel", "id": channel}],
                            }
                    else:
                        response, payload = FakeGoogleResponse(status=404), {}
                self._send(response, payload)

            def do_POST(self) -> None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 8192:
                        raise ValueError
                    values = parse_qs(self.rfile.read(length).decode("ascii"), keep_blank_values=True,
                                      strict_parsing=True, max_num_fields=8)
                except (ValueError, UnicodeError):
                    self._send(FakeGoogleResponse(status=400), {})
                    return
                with owner._lock:
                    owner.requests.append(FakeGoogleRequest("POST", self.path, values))
                    if self.path == "/token":
                        payload = owner._token(values)
                        response = owner.token_responses.popleft() if owner.token_responses else FakeGoogleResponse()
                        if payload is None:
                            response, payload = FakeGoogleResponse(status=400), {}
                    elif self.path == "/revoke":
                        response = owner.revoke_responses.popleft() if owner.revoke_responses else FakeGoogleResponse()
                        token = values.get("token", [])
                        if set(values) != {"token"} or len(token) != 1:
                            response, payload = FakeGoogleResponse(status=400), {}
                        else:
                            grant = owner._refresh.pop(token[0], None)
                            if grant is not None:
                                owner._tokens.pop(grant[0], None)
                            payload = {}
                    else:
                        response, payload = FakeGoogleResponse(status=404), {}
                self._send(response, payload)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.thread = Thread(target=lambda: self.http.serve_forever(poll_interval=0.02), daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.http.server_port}"

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)

    def _authorize(self, values: dict[str, list[str]]) -> tuple[FakeGoogleResponse, dict[str, object]] | None:
        required = {"client_id", "response_type", "redirect_uri", "scope", "state",
                    "code_challenge", "code_challenge_method", "access_type"}
        if set(values) != required or any(len(value) != 1 for value in values.values()):
            return None
        fields = {key: value[0] for key, value in values.items()}
        try:
            redirect = urlsplit(fields["redirect_uri"])
            if (
                not fields["client_id"].startswith("nf-synthetic-")
                or fields["response_type"] != "code" or fields["code_challenge_method"] != "S256"
                or fields["access_type"] != "offline"
                or set(fields["scope"].split()) != set(IDENTITY_LINK_SCOPES)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", fields["state"])
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", fields["code_challenge"])
                or redirect.scheme != "http" or redirect.hostname != "127.0.0.1"
                or redirect.port is None or redirect.port == 8765
                or redirect.path != "/oauth/callback" or redirect.query or redirect.fragment
                or fields["redirect_uri"] != f"http://127.0.0.1:{redirect.port}/oauth/callback"
            ):
                return None
        except ValueError:
            return None
        code = "nf-synthetic-code-" + uuid4().hex
        self._codes[code] = {"client_id": fields["client_id"], "redirect_uri": fields["redirect_uri"],
                             "challenge": fields["code_challenge"], "channel": self.channel}
        redirect_query = {"state": fields["state"], "code": code}
        response = self.authorize_responses.popleft() if self.authorize_responses else FakeGoogleResponse(status=302)
        if response.changes.get("error") == "access_denied":
            redirect_query = {"state": fields["state"], "error": "access_denied"}
        location = response.location or fields["redirect_uri"] + "?" + urlencode(redirect_query)
        return FakeGoogleResponse(status=response.status, delay=response.delay, location=location), {}

    def _token(self, values: dict[str, list[str]]) -> dict[str, object] | None:
        if any(len(value) != 1 for value in values.values()):
            return None
        fields = {key: value[0] for key, value in values.items()}
        if (
            not fields.get("client_id", "").startswith("nf-synthetic-")
            or not fields.get("client_secret", "").startswith("nf-synthetic-client-")
        ):
            return None
        if fields.get("grant_type") == "authorization_code":
            if set(fields) != {"client_id", "client_secret", "grant_type", "code", "code_verifier", "redirect_uri"}:
                return None
            grant = self._codes.pop(fields["code"], None)
            if not grant or grant["client_id"] != fields["client_id"] or grant["redirect_uri"] != fields["redirect_uri"]:
                return None
            try:
                if pkce_s256(fields["code_verifier"]) != grant["challenge"]:
                    return None
            except Exception:  # noqa: BLE001 - test provider reports fixed invalid request only
                return None
            channel = grant["channel"]
        elif fields.get("grant_type") == "refresh_token":
            if set(fields) != {"client_id", "client_secret", "grant_type", "refresh_token"}:
                return None
            grant = self._refresh.pop(fields["refresh_token"], None)
            if grant is None:
                return None
            channel = grant[1]
        else:
            return None
        suffix = uuid4().hex
        access, refresh = "nf-synthetic-access-" + suffix, "nf-synthetic-refresh-" + suffix
        self._tokens[access], self._refresh[refresh] = channel, (access, channel)
        return {"access_token": access, "refresh_token": refresh, "scope": " ".join(IDENTITY_LINK_SCOPES),
                "token_type": "Bearer", "expires_in": 3600}

    def evidence(self) -> dict[str, object]:
        with self._lock:
            return {
                "mode": "SYNTHETIC_FAKE_GOOGLE_SERVER",
                "authorization_requests": sum(request.path == "/authorize" for request in self.requests),
                "token_requests": sum(request.path == "/token" for request in self.requests),
                "identity_requests": sum(request.path == "/youtube/v3/channels" for request in self.requests),
                "revoke_requests": sum(request.path == "/revoke" for request in self.requests),
                "real_oauth_requests": 0, "real_sns_upload_requests": 0,
            }
