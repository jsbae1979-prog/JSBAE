"""Read-only local ffprobe inspection; physical file/hash checks live in the service."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Protocol

from newsflow.video.engine import FFmpegAdapter
from newsflow.video.tts import local_process_env


class MediaInspector(Protocol):
    def inspect(self, path: Path) -> dict: ...


class MediaInspectionError(Exception):
    pass


class FFprobeMediaInspector:
    def inspect(self, path: Path) -> dict:
        try:
            probe = FFmpegAdapter.executable("ffprobe", None)
            result = subprocess.run(
                [
                    str(probe),
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-f",
                    "mov",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(path),
                ],
                shell=False,
                capture_output=True,
                env=local_process_env(),
                timeout=20,
                check=False,
            )
            if result.returncode or len(result.stdout) > 1_000_000:
                raise ValueError
            value = json.loads(result.stdout)
            video = next(s for s in value["streams"] if s["codec_type"] == "video")
            audio = next(s for s in value["streams"] if s["codec_type"] == "audio")
            num, den = video.get("avg_frame_rate", "0/1").split("/")
            duration = float(value["format"]["duration"])
            fps = float(num) / float(den)
            if not math.isfinite(duration) or not math.isfinite(fps):
                raise ValueError
            return {
                "format": value["format"]["format_name"],
                "video_codec": video["codec_name"],
                "audio_codec": audio["codec_name"],
                "width": video["width"],
                "height": video["height"],
                "duration": duration,
                "fps": fps,
                "audio_channels": audio.get("channels"),
                "playable": True,
            }
        except Exception:  # noqa: BLE001 - never reflect raw probe stderr/exception
            raise MediaInspectionError("로컬 MP4 무결성·스트림 검증에 실패했습니다.") from None


class FakeMediaInspector:
    def __init__(self, metadata: dict | None = None) -> None:
        self.metadata = {
            "format": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": 1080,
            "height": 1920,
            "duration": 30,
            "fps": 30,
            "audio_channels": 2,
            "playable": True,
            **(metadata or {}),
        }
        self.calls: list[Path] = []

    def inspect(self, path: Path) -> dict:
        self.calls.append(path)
        return dict(self.metadata)
