"""Vendor-neutral contract for optional AI video providers (Phase 5D).

A provider turns one storyboard scene prompt into one short clip. NewsFlow never shows a
clip as news footage: FFmpeg composes it under the burned-in AI label, the narration WAV and
the same subtitles as the local card path. Any other video API can implement this Protocol.

Error messages are fixed Korean sentences chosen by code; provider response text, prompts,
URLs and credentials never reach a message, the database or a log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Protocol

# Provider job states as NewsFlow stores them. Higgsfield's official SDK (higgsfield-client 0.2.0,
# types_.StatusEnum) uses queued / in_progress / completed / failed / nsfw / canceled.
QUEUED, IN_PROGRESS, COMPLETED, FAILED, NSFW, CANCELED = (
    "queued", "in_progress", "completed", "failed", "nsfw", "canceled",
)
PROVIDER_STATES = frozenset({QUEUED, IN_PROGRESS, COMPLETED, FAILED, NSFW, CANCELED})
TERMINAL_STATES = frozenset({COMPLETED, FAILED, NSFW, CANCELED})

ASPECT_RATIO = "9:16"  # NewsFlow renders 1080x1920 vertical videos only.


@dataclass(frozen=True)
class ClipRequest:
    """One text-to-video request. ``prompt`` already carries the mandatory style guard."""

    model_path: str
    prompt: str
    seconds: int
    resolution: str
    aspect_ratio: str = ASPECT_RATIO
    # Sent as Idempotency-Key; whether Higgsfield honours it is NOT VERIFIED, so nothing relies on it.
    idempotency_key: str | None = None


@dataclass(frozen=True)
class Submission:
    request_id: str
    state: str = QUEUED


@dataclass(frozen=True)
class ClipStatus:
    state: str
    video_url: str | None = None
    # Only short machine-readable facts (never provider prose) for the evidence record.
    facts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FetchResult:
    path: Path
    bytes: int
    sha256: str
    host: str


class VideoProviderError(Exception):
    """Classified provider failure. ``code`` selects a fixed message; ``sent`` tells accounting
    whether the request may have reached the provider (a billable submission is never retried)."""

    code = "video_ai_failed"
    message = "AI 영상 생성에 실패했습니다. 해당 장면을 카드나 로컬 이미지로 바꾸거나 나중에 다시 시도하세요."
    retryable = False

    def __init__(self, message: str | None = None, *, sent: bool = True, status_code: int | None = None) -> None:
        super().__init__(message or self.message)
        self.sent = sent
        self.status_code = status_code


class ProviderNotConfigured(VideoProviderError):
    code = "video_ai_key_missing"
    message = "AI 영상 API 키가 설정되지 않았습니다. AI 영상 설정에서 키를 저장하세요."


class ProviderAuthError(VideoProviderError):
    code = "video_ai_auth_failed"
    message = "AI 영상 공급사 인증에 실패했습니다. AI 영상 설정에서 API 키를 다시 확인하세요."


class ProviderCreditError(VideoProviderError):
    code = "video_ai_credits"
    message = "AI 영상 공급사 잔액·권한이 부족하다는 응답을 받았습니다. 공급사 대시보드에서 잔액과 권한을 확인하세요."


class ProviderInputError(VideoProviderError):
    code = "video_ai_bad_input"
    message = (
        "AI 영상 공급사가 요청을 거부했습니다. 모델 경로·길이·해상도를 공식 문서와 비교하고, "
        "다른 곳에서 동시에 생성 중인 요청이 많지 않은지 확인하세요."
    )


class ProviderModelError(VideoProviderError):
    code = "video_ai_bad_model"
    message = "AI 영상 모델 경로를 찾지 못했습니다. AI 영상 설정의 모델 경로를 공식 문서에서 다시 확인하세요."


class ProviderRateLimited(VideoProviderError):
    code = "video_ai_rate_limited"
    message = "AI 영상 공급사의 동시 요청·요청 빈도 제한에 걸렸습니다. 잠시 후 다시 시도하세요."
    retryable = True


class ProviderUnavailable(VideoProviderError):
    code = "video_ai_unavailable"
    message = "AI 영상 공급사에 연결하지 못했거나 서버 오류가 발생했습니다. 잠시 후 다시 시도하세요."
    retryable = True


class ProviderResponseError(VideoProviderError):
    code = "video_ai_bad_response"
    message = "AI 영상 공급사 응답 형식을 확인하지 못했습니다. 해당 장면을 카드로 바꾸거나 다시 시도하세요."


class ProviderRequestMissing(VideoProviderError):
    """Status or cancel answered 404: the provider no longer knows this request (or its result expired)."""

    code = "video_ai_request_missing"
    message = "공급사가 이 생성 요청을 찾지 못했습니다. 공급사 대시보드를 확인한 뒤 다시 생성하거나 카드로 바꾸세요."


class ProviderAmbiguousSubmit(VideoProviderError):
    """The submit request was sent but its outcome is unknown (timeout, dropped connection)."""

    code = "video_ai_unknown_submit"
    message = (
        "생성 요청을 보냈지만 결과를 확인하지 못했습니다. 중복 과금을 막기 위해 자동으로 다시 보내지 않습니다. "
        "공급사 대시보드에서 확인한 뒤 '결과 불명을 실패로 확정'을 누르면 장면을 다시 생성하거나 카드로 바꿀 수 있습니다."
    )


class ClipDownloadError(VideoProviderError):
    code = "video_ai_download_failed"
    message = "생성된 영상을 안전하게 내려받지 못했습니다. 주소·크기·형식 검사를 통과하지 못했습니다."


class ClipInvalidError(VideoProviderError):
    code = "video_ai_clip_invalid"
    message = "생성된 영상 파일의 형식·길이·해상도 검증에 실패했습니다."


ERROR_MESSAGES: dict[str, str] = {
    cls.code: cls.message
    for cls in (
        VideoProviderError, ProviderNotConfigured, ProviderAuthError, ProviderCreditError, ProviderInputError,
        ProviderModelError, ProviderRateLimited, ProviderUnavailable, ProviderResponseError,
        ProviderRequestMissing, ProviderAmbiguousSubmit, ClipDownloadError, ClipInvalidError,
    )
}
ERROR_MESSAGES.update({
    "video_ai_nsfw": "공급사가 콘텐츠 정책 위반(NSFW)으로 생성을 거부했습니다. 프롬프트를 바꾸거나 카드로 바꾸세요.",
    "video_ai_provider_failed": "공급사에서 생성이 실패했습니다. 프롬프트를 바꿔 다시 생성하거나 카드로 바꾸세요.",
    "video_ai_canceled": "생성 요청이 취소되었습니다.",
    "video_ai_timeout": "생성이 제한시간 안에 끝나지 않았습니다. 다시 생성하거나 카드로 바꾸세요.",
    "video_ai_interrupted": "프로그램 종료로 다운로드가 중단되었습니다. 다시 시작하면 이어서 확인합니다.",
    "video_ai_disk_full": "디스크 여유 공간이 부족해 생성된 영상을 내려받지 않았습니다. 공간을 확보한 뒤 '결과 다시 받기'를 누르세요.",
})


class VideoProvider(Protocol):
    """Implementations must not retry ``submit``: a resent submission can be billed twice."""

    name: str
    label: str

    def submit(self, request: ClipRequest) -> Submission: ...

    def status(self, request_id: str) -> ClipStatus: ...

    def cancel(self, request_id: str) -> bool: ...

    def fetch(self, status: ClipStatus, target: Path, cancel: Event) -> FetchResult: ...
