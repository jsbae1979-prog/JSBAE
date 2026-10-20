"""Publishing descriptors and fail-closed adapters: NO HTTP/OAuth transport in Phase 4A."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ExternalPublishingDisabled(Exception):
    def __init__(self) -> None:
        super().__init__("Phase 4A에서는 실제 SNS 연결·게시가 차단됩니다.")


@dataclass(frozen=True)
class PublishResult:
    status: str
    message: str = ""
    reference: str | None = None


class Publisher(Protocol):
    def publish(self, payload: dict, idempotency_key: str, approved: bool = False) -> PublishResult: ...


class InstagramAdapter:
    platform = "instagram"
    real_publish_calls = 0
    real_oauth_calls = 0

    def prepare(self, payload: dict) -> dict:
        return {
            "operation": "/media then /media_publish",
            "media_type": "REELS",
            "caption": "\n".join(
                part
                for part in (
                    payload.get("title", ""),
                    payload.get("description", ""),
                    " ".join("#" + tag for tag in payload.get("hashtags", [])),
                )
                if part
            ),
            "is_ai_generated": payload.get("ai_disclosure") == "disclose",
            "delivery": "unconfigured; official login/upload route must be reviewed",
        }

    def publish(self, payload: dict, idempotency_key: str, approved: bool = False) -> PublishResult:
        raise ExternalPublishingDisabled()

    def connect(self, *args: object, **kwargs: object) -> None:
        raise ExternalPublishingDisabled()


class YouTubeAdapter:
    platform = "youtube"
    real_publish_calls = 0
    real_oauth_calls = 0

    def prepare(self, payload: dict) -> dict:
        return {
            "operation": "videos.insert",
            "upload": "resumable",
            "endpoint": "https://www.googleapis.com/upload/youtube/v3/videos",
            "snippet": {
                "categoryId": payload.get("youtube_category_id", "25"),
                "title": payload.get("title", ""),
                "description": "\n".join(
                    part
                    for part in (
                        payload.get("description", ""),
                        " ".join("#" + tag for tag in payload.get("hashtags", [])),
                    )
                    if part
                ),
                "tags": payload.get("hashtags", []),
            },
            "status": {
                "privacyStatus": "private",
                "containsSyntheticMedia": payload.get("ai_disclosure") == "disclose",
            },
            "shorts_classification": "platform decision; never guaranteed by videos.insert",
        }

    def publish(self, payload: dict, idempotency_key: str, approved: bool = False) -> PublishResult:
        raise ExternalPublishingDisabled()

    def connect(self, *args: object, **kwargs: object) -> None:
        raise ExternalPublishingDisabled()


class FakePublisher:
    def __init__(self, outcome: str = "simulated") -> None:
        if outcome not in {"simulated", "unknown", "failed", "expired"}:
            raise ValueError("Fake outcome is unsupported")
        self.outcome, self.calls = outcome, []

    def publish(self, payload: dict, idempotency_key: str, approved: bool = False) -> PublishResult:
        if not approved:
            raise ExternalPublishingDisabled()
        self.calls.append(idempotency_key)
        messages = {
            "simulated": "Fake 게시 시뮬레이션; 실제 SNS 게시 아님",
            "unknown": "결과 불명; 재시도 금지",
            "failed": "Fake 게시 실패",
            "expired": "Fake 인증 만료",
        }
        return PublishResult(
            self.outcome,
            messages[self.outcome],
            "fake:" + idempotency_key[:16] if self.outcome == "simulated" else None,
        )


def safety_status() -> dict:
    # No outbound transport, OAuth callback, or execution route exists. Real adapter methods always raise.
    return {
        "real_publish_calls": 0,
        "real_oauth_calls": 0,
        "mode": "foundation",
        "external_execution_enabled": False,
    }
