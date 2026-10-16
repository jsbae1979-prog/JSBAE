"""Small, explicit boundary between durable orchestration and existing studios."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Any, Protocol

STAGES = ("collect", "select", "script", "render", "validate", "queue")
STAGE_LABELS = {
    "collect": "뉴스 모으기", "select": "뉴스 고르기", "script": "대본 만들기",
    "render": "영상 만들기", "validate": "영상 확인하기", "queue": "게시 대기함에 보관",
}
CONTENT_MODES = ("trial", "real")
AI_MODES = ("offline", "openai", "claude_code", "codex", "claude_api")
ARTIFACT_KEYS = frozenset({
    "collection_run_id", "search_run_id", "intelligence_run_id", "analysis_run_id", "script_run_id", "article_id", "content_draft_id",
    "video_project_id", "render_job_id", "publish_draft_id",
})


class AutopilotError(Exception):
    """Public safe error, with no provider response or credential contents."""


class AutopilotBusy(AutopilotError):
    pass


class AutopilotConflict(AutopilotError):
    pass


class AutopilotNotFound(AutopilotError):
    pass


class BackendError(AutopilotError):
    def __init__(
        self, message: str = "이 단계를 마치지 못했습니다.", *, retryable: bool = True,
        outcome_unknown: bool = False, code: str = "stage_failed",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown
        self.code = code


class AutopilotBackend(Protocol):
    def execute(
        self, stage: str, context: dict[str, Any], cancel: Event,
        progress: Callable[[int, str], None], save_artifact: Callable[[str, int | str], None],
    ) -> dict[str, Any]: ...

    def can_retry(self, stage: str, context: dict[str, Any]) -> bool: ...
