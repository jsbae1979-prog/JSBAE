"""Shared interpreter policy; no dependencies or installation side effects."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SUPPORTED_PYTHON = ((3, 12), (3, 14))
PYTHON_GUIDANCE = "Python 3.12 또는 3.14가 필요합니다. Python 3.13은 지원하지 않습니다."


def supported(version: tuple[int, ...] | None = None) -> bool:
    return tuple((sys.version_info if version is None else version)[:2]) in SUPPORTED_PYTHON


def installation_fingerprint(root: Path, version: tuple[int, ...] | None = None) -> str:
    current = tuple((sys.version_info if version is None else version)[:2])
    if not supported(current):
        raise ValueError("unsupported Python")
    digest = hashlib.sha256(str(current).encode())
    for name in ("pyproject.toml", "requirements-dev.lock"):
        digest.update((root / name).read_bytes())
    return digest.hexdigest()
