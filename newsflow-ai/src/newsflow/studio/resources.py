"""Resolve shipped React assets without reading a user profile or starting services."""

import sys
from pathlib import Path


def studio_dist_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent / "_internal"))
        return bundle / "frontend" / "dist"
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"
