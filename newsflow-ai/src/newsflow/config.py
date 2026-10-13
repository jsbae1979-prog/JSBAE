"""Validated local runtime configuration. No secret is committed."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from .paths import default_data_dir


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    host: str = "127.0.0.1"
    port: int = 8765
    request_timeout: int = 10
    secret_key: str = ""

    def __post_init__(self) -> None:
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Phase 1 GUI는 루프백 주소에서만 실행할 수 있습니다.")
        if not 1024 <= self.port <= 65535:
            raise ValueError("포트는 1024~65535 범위여야 합니다.")
        if not 1 <= self.request_timeout <= 30:
            raise ValueError("타임아웃은 1~30초 범위여야 합니다.")
        if self.secret_key and len(self.secret_key) < 32:
            raise ValueError("세션 키는 최소 32자여야 합니다.")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=default_data_dir(),
            host=os.getenv("NEWSFLOW_HOST", "127.0.0.1"),
            port=int(os.getenv("NEWSFLOW_PORT", "8765")),
            request_timeout=int(os.getenv("NEWSFLOW_REQUEST_TIMEOUT", "10")),
            secret_key=os.getenv("NEWSFLOW_SECRET_KEY", ""),
        )

    def local_secret(self) -> str:
        if self.secret_key:
            return self.secret_key
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / "session.key"
        try:
            with path.open("x", encoding="ascii") as handle:
                if os.name != "nt":
                    path.chmod(0o600)
                handle.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        value = path.read_text(encoding="ascii").strip()
        if len(value) < 32:
            raise ValueError("로컬 세션 키 파일이 잘못되었습니다.")
        return value
