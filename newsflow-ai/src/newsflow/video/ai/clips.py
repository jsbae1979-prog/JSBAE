"""Local store and ffprobe validation for generated clips before FFmpeg composition."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from uuid import uuid4

from newsflow.video.engine import FFmpegAdapter, RenderError
from newsflow.video.tts import local_process_env

from .contracts import ClipInvalidError

NAME = re.compile(r"clip-[0-9a-f]{32}\.(mp4|mov|webm)")
FORMATS = {"mov,mp4,m4a,3gp,3g2,mj2": "mov", "matroska,webm": "matroska"}
VIDEO_CODECS = frozenset({"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"})


class ClipStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = (data_dir / "ai-clips").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def new_path(self) -> Path:
        return self.root / f"clip-{uuid4().hex}.mp4"

    def path(self, name: str) -> Path:
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ClipInvalidError(sent=False)
        path = self.root / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ClipInvalidError(sent=False)
        return path


def probe_clip(path: Path, ffprobe: Path | None = None, *, min_seconds: float = 0.5) -> dict:
    """Validate container, codec, size and duration; returns safe metadata for the evidence."""
    try:
        binary = FFmpegAdapter.executable("ffprobe", ffprobe)
    except RenderError:
        raise ClipInvalidError(sent=False) from None
    try:
        size = path.stat().st_size
        if path.is_symlink() or size <= 0:
            raise ValueError
        result = subprocess.run(
            [str(binary), "-v", "error", "-protocol_whitelist", "file", "-show_streams", "-show_format",
             "-of", "json", str(path)],
            shell=False, env=local_process_env(), capture_output=True, timeout=30, check=False,
        )
        if result.returncode != 0 or len(result.stdout) > 1_000_000:
            raise ValueError
        payload = json.loads(result.stdout)
        format_name = payload["format"].get("format_name", "")
        video = next(s for s in payload["streams"] if s.get("codec_type") == "video")
        duration = float(payload["format"]["duration"])
        width, height = int(video["width"]), int(video["height"])
        if (
            format_name not in FORMATS or video.get("codec_name") not in VIDEO_CODECS
            or not math.isfinite(duration) or not min_seconds <= duration <= 120
            or not (128 <= width <= 4096 and 128 <= height <= 4096)
        ):
            raise ValueError
    except (OSError, ValueError, KeyError, StopIteration, TypeError, subprocess.TimeoutExpired):
        raise ClipInvalidError(sent=False) from None
    return {
        "format": FORMATS[format_name], "video_codec": video["codec_name"], "width": width, "height": height,
        "duration": round(duration, 3), "bytes": size,
        "has_audio": any(s.get("codec_type") == "audio" for s in payload["streams"]),
    }
