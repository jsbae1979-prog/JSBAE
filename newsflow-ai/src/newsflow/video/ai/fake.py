"""Fake AI video provider for tests and CI: no network, deterministic, real playable clips.

It is never selectable in the GUI settings. It exists only when injected into ``create_app``
(tests, ``tools/ci_fixture_server.py``) and is labelled as a test provider on every page.
Behaviour can be steered per scene by markers in the prompt, e.g. ``[fake:nsfw]``.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock

from newsflow.video.engine import FFmpegAdapter, RenderError
from newsflow.video.tts import local_process_env

from .contracts import (
    CANCELED,
    COMPLETED,
    FAILED,
    IN_PROGRESS,
    NSFW,
    QUEUED,
    ClipDownloadError,
    ClipRequest,
    ClipStatus,
    FetchResult,
    ProviderAmbiguousSubmit,
    ProviderAuthError,
    ProviderCreditError,
    ProviderInputError,
    ProviderRateLimited,
    ProviderUnavailable,
    Submission,
)

SUBMIT_ERRORS = {
    "[fake:auth]": ProviderAuthError, "[fake:credits]": ProviderCreditError, "[fake:input]": ProviderInputError,
    "[fake:rate]": ProviderRateLimited, "[fake:ambiguous]": ProviderAmbiguousSubmit,
}


@dataclass
class _Job:
    request: ClipRequest
    polls: int = 0
    state: str = QUEUED
    outcome: str = COMPLETED
    slow: bool = False
    bad_clip: bool = False
    canceled: bool = False


@dataclass
class FakeVideoProvider:
    name: str = "fake"
    label: str = "Fake 공급자 (테스트 전용 · 외부 호출 없음)"
    steps: int = 2
    ffmpeg: Path | None = None
    jobs: dict[str, _Job] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def submit(self, request: ClipRequest) -> Submission:
        with self._lock:
            self.calls.append(("submit", request.model_path, request.idempotency_key))
            if "[fake:unavailable]" in request.prompt:
                raise ProviderUnavailable(sent=False)
            for marker, error in SUBMIT_ERRORS.items():
                if marker in request.prompt:
                    raise error()
            request_id = "fake-" + hashlib.sha256(f"{len(self.jobs)}:{request.prompt}".encode()).hexdigest()[:24]
            outcome = NSFW if "[fake:nsfw]" in request.prompt else FAILED if "[fake:fail]" in request.prompt else COMPLETED
            self.jobs[request_id] = _Job(
                request, outcome=outcome, slow="[fake:slow]" in request.prompt, bad_clip="[fake:bad-clip]" in request.prompt,
            )
            return Submission(request_id, QUEUED)

    def status(self, request_id: str) -> ClipStatus:
        with self._lock:
            self.calls.append(("status", request_id))
            job = self.jobs.get(request_id)
            if job is None:
                raise ProviderUnavailable()
            if job.canceled:
                return ClipStatus(CANCELED)
            job.polls += 1
            if job.slow or job.polls < self.steps:
                job.state = QUEUED if job.polls <= 1 else IN_PROGRESS
                return ClipStatus(job.state)
            job.state = job.outcome
            if job.outcome != COMPLETED:
                return ClipStatus(job.outcome)
            return ClipStatus(COMPLETED, f"https://fake.invalid/clips/{request_id}.mp4", {"result_shape": "fake"})

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            self.calls.append(("cancel", request_id))
            job = self.jobs.get(request_id)
            if job is None or job.state not in (QUEUED,):
                return False
            job.canceled = True
            return True

    def fetch(self, status: ClipStatus, target: Path, cancel: Event) -> FetchResult:
        request_id = (status.video_url or "").rsplit("/", 1)[-1].removesuffix(".mp4")
        with self._lock:
            self.calls.append(("fetch", request_id))
            job = self.jobs.get(request_id)
        if job is None or cancel.is_set():
            raise ClipDownloadError()
        if job.bad_clip:
            target.write_bytes(b"NOT A VIDEO")
        else:
            try:
                binary = FFmpegAdapter.executable("ffmpeg", self.ffmpeg)
            except RenderError:
                raise ClipDownloadError() from None
            hue = int(hashlib.sha256(request_id.encode()).hexdigest()[:2], 16) * 360 // 256
            result = subprocess.run(
                [str(binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                 f"testsrc2=size=540x960:rate=30:duration={int(job.request.seconds)}",
                 "-vf", f"hue=h={hue}", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                 "-an", "-f", "mp4", str(target)],
                shell=False, env=local_process_env(), capture_output=True, timeout=120, check=False,
            )
            if result.returncode != 0:
                target.unlink(missing_ok=True)
                raise ClipDownloadError()
        data = target.read_bytes()
        return FetchResult(target, len(data), hashlib.sha256(data).hexdigest(), "fake.invalid")
