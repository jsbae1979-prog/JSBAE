"""Optional, explicitly provisioned cloudflared bridge; never downloads or installs tools."""

import os
import queue
import re
import socket
import subprocess
import tempfile
import threading
import time
from hashlib import sha256
from http.server import HTTPServer
from pathlib import Path

from .contracts import MetaError


class ImageHTTPServer(HTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        pass  # Do not include a request URL in an exception/access log.


class QuickTunnel:
    def __init__(self, executable, expected_sha, *, popen=subprocess.Popen):
        self.executable, self.expected_sha = Path(executable), expected_sha
        self.popen = popen
        self.process = self.server = self.thread = self.temp = self.reader = None

    def available(self):
        path = self.executable
        if not isinstance(self.expected_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", self.expected_sha):
            return False
        try:
            if not path.is_absolute() or path.name.lower() != "cloudflared.exe" or not path.is_file():
                return False
            if any(
                p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                for p in (path, *path.parents)
            ):
                return False
            with path.open("rb") as file:
                digest = sha256()
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest() == self.expected_sha
        except OSError:
            return False

    def start(self, handler, port):
        if self.process is not None or not self.available():
            raise MetaError("configuration")
        try:
            # Explicit fixed loopback port; collision is an error, never an automatic fallback.
            self.server = ImageHTTPServer(("127.0.0.1", port), handler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.temp = tempfile.TemporaryDirectory(prefix="newsflow-image-bridge-")
            config = Path(self.temp.name) / "config.yml"
            config.write_text("{}\n", encoding="utf-8")
            # Exclude user/API secrets from the child environment.
            env = {
                k: v
                for k, v in os.environ.items()
                if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "SYSTEMDRIVE"}
            }
            self.process = self.popen(
                [
                    str(self.executable),
                    "--no-autoupdate",
                    "--config",
                    str(config),
                    "tunnel",
                    "--url",
                    f"http://127.0.0.1:{port}",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=self.temp.name,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                shell=False,
            )
            found = queue.Queue(maxsize=1)
            process = self.process

            def read_origin():
                # Drain privately; neither provider diagnostics nor URLs are logged.
                while True:
                    line = process.stdout.readline(4096)
                    if not line:
                        return
                    match = re.search(
                        r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com(?=[\s|]|$)", line
                    )
                    if match:
                        try:
                            found.put_nowait(match.group())
                        except queue.Full:
                            pass

            self.reader = threading.Thread(target=read_origin, daemon=True)
            self.reader.start()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and self.process.poll() is None:
                try:
                    return found.get(timeout=0.1)
                except queue.Empty:
                    pass
            raise MetaError("media")
        except Exception:  # noqa: BLE001 - redact transport diagnostics and capability URLs
            self.close()
            raise MetaError("media") from None

    def alive(self):
        return bool(self.process and self.process.poll() is None and self.thread and self.thread.is_alive())

    def close(self):
        process, self.process = self.process, None
        stopped = True
        if process and process.poll() is None:
            process.terminate()  # Only this owned transport helper; never the operating application.
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                stopped = False  # No force-kill or process-name matching.
        if self.server:
            if self.thread and self.thread.is_alive():
                self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread:
            self.thread.join(timeout=2)
        if self.reader:
            self.reader.join(timeout=2)
        if stopped and process and process.stdout:
            process.stdout.close()
        if stopped and self.temp:
            self.temp.cleanup()
            self.temp = None
        if not stopped:
            self.process = process
            raise MetaError("unknown")
