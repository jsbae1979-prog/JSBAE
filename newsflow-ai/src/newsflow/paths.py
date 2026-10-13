"""Local user-data layout; stdlib only so the Windows bootstrap can import it."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path


def default_data_dir(platform: str | None = None, environ: Mapping[str, str] | None = None) -> Path:
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    override = environ.get("NEWSFLOW_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if platform == "win32":
        local = environ.get("LOCALAPPDATA", "").strip()
        if not local or not Path(local).is_absolute():
            raise ValueError("LOCALAPPDATA가 없거나 절대 경로가 아닙니다. Windows 사용자 환경을 확인하세요.")
        return Path(local) / "NewsFlowAI"
    # Codex development/test fallback; not a Linux deployment target.
    return Path("data").resolve()


def prepare_data_dir(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in ("logs", "content", "videos"):
        (root / name).mkdir(exist_ok=True)
