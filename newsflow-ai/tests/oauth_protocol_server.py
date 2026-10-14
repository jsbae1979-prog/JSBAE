"""Loopback-only synthetic OAuth server; never contacts external services."""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.parse import parse_qs

from newsflow.oauth.contracts import YOUTUBE_UPLOAD_SCOPE


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path: str
    headers: dict[str, str]
    form: dict[str, list[str]] = field(repr=False)


@dataclass(frozen=True)
class FakeResponse:
    status: int = 200
    payload: dict[str, object] | None = field(default=None, repr=False)
    body: bytes | None = field(default=None, repr=False)
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0


def synthetic_response(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "access_token": "nf-synthetic-access-initial",
        "refresh_token": "nf-synthetic-refresh-initial",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": YOUTUBE_UPLOAD_SCOPE,
    }
    result.update(changes)
    return result


class FakeOAuthHTTPServer:
    """Scripted POST responses and redacted request records for protocol assertions."""

    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []
        self.responses: deque[FakeResponse] = deque()
        self._lock = Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: object) -> None:
                # Never emit callback codes, submitted forms, or synthetic token values.
                return

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 65536:
                    self.send_error(413)
                    return
                form = parse_qs(
                    self.rfile.read(length).decode("ascii"),
                    keep_blank_values=True,
                    strict_parsing=True,
                    max_num_fields=20,
                )
                request = RecordedRequest(
                    "POST", self.path, {k.lower(): v for k, v in self.headers.items()}, form,
                )
                with owner._lock:
                    owner.requests.append(request)
                    response = (
                        owner.responses.popleft() if owner.responses else FakeResponse(
                            payload=synthetic_response() if self.path == "/token" else {},
                        )
                    )
                if response.delay:
                    time.sleep(response.delay)
                body = (
                    response.body if response.body is not None
                    else json.dumps(response.payload or {}).encode("utf-8")
                )
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for key, value in response.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    # Expected after a deliberately timed-out client disconnects.
                    pass

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

    def queue(self, *responses: FakeResponse) -> None:
        with self._lock:
            self.responses.extend(responses)
