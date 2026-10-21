"""Private HTTP rejection detail; never put supplier prose in SQLite or ordinary logs."""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from .credentials import Cipher, _entropy, _native_cipher

_ENTROPY = b"NewsFlowAI:Claude:http-error-diagnostic:v1"
_REFERENCE = re.compile(r"[a-f0-9]{32}\Z")


class ErrorDiagnosticStore:
    """Current-user DPAPI only; Fake cipher injection is restricted to tests."""

    def __init__(self, data_dir: Path, cipher: Cipher | None = None):
        self.root = data_dir / "diagnostics" / "claude-http"
        self.cipher = cipher

    def _directory(self) -> None:
        for path in (self.root, *self.root.parents):
            if path.is_symlink() or path.is_junction():
                raise ValueError("진단 경로를 안전하게 확인하지 못했습니다.")
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, *, status: int, error_type: str, message: str, secret: str) -> str:
        if type(status) is not int or not 400 <= status <= 599:
            raise ValueError("진단 상태가 잘못되었습니다.")
        if not isinstance(message, str) or len(message.encode("utf-8")) > 8192:
            raise ValueError("진단 메시지 크기가 잘못되었습니다.")
        # Never save the request, response envelope, headers, or authentication value.
        text = message.replace(secret, "[REDACTED]") if secret else message
        text = re.sub(r"(?i)\b(?:sk-ant-|sk-)[A-Za-z0-9_-]+", "[REDACTED]", text)
        kind = error_type if isinstance(error_type, str) and error_type in {
            "invalid_request_error", "not_found_error", "request_too_large", "api_error",
        } else "other"
        plain = bytearray(json.dumps({
            "version": 1, "http_status": status, "error_type": kind, "message": text,
        }, ensure_ascii=False).encode("utf-8"))
        try:
            cipher = self.cipher or _native_cipher()
            protected = cipher.protect(plain, _entropy(_ENTROPY))
        finally:
            for index in range(len(plain)):
                plain[index] = 0
        self._directory()
        reference = uuid.uuid4().hex
        # Unique, exclusive files preserve every failed attempt; never replace another.
        with (self.root / (reference + ".dpapi")).open("xb") as stream:
            stream.write(protected)
            stream.flush()
            os.fsync(stream.fileno())
        return reference

    def read(self, reference: str) -> dict:
        """Explicit local diagnostic review only; callers must not log the returned prose."""
        if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
            raise ValueError("진단 식별자가 잘못되었습니다.")
        for path in (self.root, *self.root.parents):
            if path.is_symlink() or path.is_junction():
                raise ValueError("진단 경로를 안전하게 확인하지 못했습니다.")
        path = self.root / (reference + ".dpapi")
        if path.is_symlink() or not 0 < path.stat().st_size <= 65536:
            raise ValueError("보호된 진단 파일을 확인하지 못했습니다.")
        cipher = self.cipher or _native_cipher()
        plain = cipher.unprotect(bytearray(path.read_bytes()), _entropy(_ENTROPY))
        try:
            return json.loads(plain)
        finally:
            for index in range(len(plain)):
                plain[index] = 0
