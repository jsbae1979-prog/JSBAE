"""Ephemeral JPEG capabilities. The operating application is never the public origin."""

import re
import secrets
import threading
import time
from hashlib import sha256
from http.server import BaseHTTPRequestHandler

from .contracts import MetaError
from .media import validate_media
from .storage import transfer

MAX_IMAGE = 8 * 1024 * 1024


class LocalImageSession:
    def __init__(self, bridge_factory, port, *, verify=transfer, clock=time.monotonic, ttl=3600):
        if type(port) is not int or not 1024 <= port <= 65535 or port in {8765, 18768}:
            raise MetaError("invalid")
        if not 900 <= ttl <= 3600:
            raise MetaError("invalid")
        self.factory, self.port, self.verify = bridge_factory, port, verify
        self.clock, self.ttl = clock, ttl
        self.lock = threading.RLock()
        self.bridge = self.timer = None
        self.origin = ""
        self.expires = 0
        self.images = {}

    def handler(self):
        session = self

        class ImagesOnly(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *args):
                pass  # Capability URLs must not enter access/error logs.

            def send_error(self, code, message=None, explain=None):
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

            def do_GET(self):
                self._image(False)

            def do_HEAD(self):
                self._image(True)

            def _image(self, head):
                raw = session.read(self.path)
                if raw is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if not head:
                    self.wfile.write(raw)

        return ImagesOnly

    def read(self, path):
        with self.lock:
            if self.clock() >= self.expires or not re.fullmatch(r"/image/[a-f0-9]{64}\.jpg", path):
                return None
            return self.images.get(path)

    def offer(self, raw, expected_sha):
        if len(raw) > MAX_IMAGE or sha256(raw).hexdigest() != expected_sha:
            raise MetaError("media")
        validate_media(raw, "image")
        try:
            # Caller holds its per-owner publication lock. GET uses only the small snapshot lock.
            if self.bridge is None:
                self.bridge = self.factory()
                origin = self.bridge.start(self.handler(), self.port)
                if not re.fullmatch(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com", origin):
                    raise MetaError("media")
                self.origin = origin
                self.expires = self.clock() + self.ttl
                self.timer = threading.Timer(self.ttl, self.close)
                self.timer.daemon = True
                self.timer.start()
            if not self.bridge.alive() or self.expires - self.clock() < 900:
                raise MetaError("media")
            with self.lock:
                if len(self.images) >= 8:
                    raise MetaError("media")
                path = "/image/" + secrets.token_hex(32) + ".jpg"
                self.images[path] = bytes(raw)  # Immutable snapshot; no public filesystem access.
            url = self.origin + path
            received = self.verify("GET", url)
            if sha256(received).hexdigest() != expected_sha:
                raise MetaError("media")
            return url
        except Exception:  # noqa: BLE001 - redact transport diagnostics and capability URLs
            self.close()
            raise MetaError("media") from None

    def close(self):
        with self.lock:
            bridge, timer = self.bridge, self.timer
            self.bridge = self.timer = None
            self.images.clear()
            self.origin = ""
            self.expires = 0
        if timer:
            timer.cancel()
        if bridge:
            bridge.close()
