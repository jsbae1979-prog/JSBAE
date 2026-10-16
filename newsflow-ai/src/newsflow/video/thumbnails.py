"""Small, bounded first-frame previews of already validated local MP4 files."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore

from .engine import FFmpegAdapter, RenderError
from .tts import local_process_env

_workers = BoundedSemaphore(2)


@lru_cache(maxsize=32)
def _frame(executable: str, source: str, size: int, modified: int) -> bytes:
    # Size/mtime invalidate a cache entry without modifying the video or user data.
    if not _workers.acquire(timeout=2):
        raise RenderError("미리보기 준비 중입니다. 잠시 후 다시 확인하세요.")
    try:
        result = subprocess.run(
            [executable, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
             "-f", "mov", "-i", source, "-frames:v", "1", "-an", "-sn", "-dn",
             "-vf", "scale=240:426:force_original_aspect_ratio=decrease",
             "-threads", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
            shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=local_process_env(), timeout=10, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode or not result.stdout.startswith(b"\x89PNG\r\n\x1a\n") or len(result.stdout) > 512_000:
            raise RenderError("영상 미리보기를 준비하지 못했습니다.")
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        raise RenderError("영상 미리보기를 준비하지 못했습니다.") from None
    finally:
        _workers.release()


def thumbnail(source: Path, ffmpeg: Path | None = None) -> bytes:
    """Caller must validate the render's state and local output path on EVERY call."""
    info = source.stat()
    executable = FFmpegAdapter.executable("ffmpeg", ffmpeg)
    return _frame(str(executable), str(source), info.st_size, info.st_mtime_ns)
