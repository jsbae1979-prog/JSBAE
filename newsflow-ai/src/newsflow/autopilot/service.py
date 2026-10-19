"""Durable, explicitly requested local automation. Never publishes or grants approval."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock
from typing import Any
from uuid import uuid4

from filelock import FileLock, Timeout
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import (
    AIVideoPlan,
    AutopilotArticleClaim,
    AutopilotArtifact,
    AutopilotAttempt,
    AutopilotEvent,
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    RenderJob,
    ScheduledRun,
    utcnow,
)
from newsflow.intelligence.capabilities import NEWS_CATEGORIES, NEWS_PERIODS, require_acquisition
from newsflow.intelligence.news_usage import validate_news_usage

from .contracts import (
    AI_MODES,
    ARTIFACT_KEYS,
    CONTENT_MODES,
    STAGE_LABELS,
    STAGES,
    AutopilotBackend,
    AutopilotBusy,
    AutopilotConflict,
    AutopilotError,
    AutopilotNotFound,
    BackendError,
    BackendWaiting,
)

_ERROR_MESSAGES = {
    "stage_failed": "이 단계를 마치지 못했습니다. 설정과 이전 결과를 확인하세요.",
    "collect_failed": "뉴스를 가져오지 못했습니다. 뉴스 출처와 연결 상태를 확인하세요.",
    "no_sources": "사용 중인 뉴스 출처가 없어 제작을 시작하지 못했습니다.",
    "select_failed": "뉴스를 고르지 못했습니다. 다른 뉴스를 모으거나 기존 작업을 확인하세요.",
    "script_failed": "대본을 만들지 못했습니다. 이전 대본 결과를 확인하고 다시 시도하세요.",
    "render_failed": "영상을 만들지 못했습니다. 고급 설정에서 제작 도구와 저장 공간을 확인하세요.",
    "validate_failed": "영상 규격이나 파일을 확인하지 못했습니다. 결과 영상을 확인하세요.",
    "queue_failed": "게시 대기함에 보관하지 못했습니다. 영상과 기존 초안을 확인하세요.",
    "outcome_unknown": "작업 결과를 확인할 수 없어 중단했습니다. 이전 결과를 먼저 확인하세요.",
    "interrupted": "프로그램이 종료되어 작업이 중단되었습니다. 이전 결과를 확인한 뒤 다시 시도하세요.",
    "duplicate_article": "이 뉴스로 이미 제작한 작업이 있습니다. 기존 작업에서 영상을 확인하세요.",
    "no_articles": "제작할 뉴스가 없습니다. 다른 뉴스를 모으거나 예제 뉴스를 선택하세요.",
    "cancelled": "요청에 따라 중단했습니다. 이미 만든 결과는 보관합니다.",
    # Phase 5C real-content stages
    "ai_not_ready": "외부 AI를 사용할 준비가 되지 않아 대본을 만들지 않았습니다. AI 설정을 확인하세요.",
    "ai_key_missing": "AI API 키가 없어 대본을 만들지 않았습니다. AI 설정에서 키를 저장하세요.",
    "ai_auth_failed": "AI 인증에 실패했습니다. API 키와 권한을 확인한 뒤 다시 시도하세요.",
    "ai_rate_limited": "AI 요청 한도(Rate Limit)에 걸렸습니다. 잠시 후 다시 시도하세요.",
    "ai_timeout": "AI 응답을 제한시간 안에 받지 못했습니다. 네트워크를 확인하고 다시 시도하세요.",
    "ai_unavailable": "AI 서비스에 연결하지 못했습니다. 네트워크를 확인하고 다시 시도하세요.",
    "ai_bad_response": "AI 응답 형식이 올바르지 않아 대본을 저장하지 않았습니다. 다시 시도하거나 기본 대본을 사용하세요.",
    "ai_budget": "이번 달 AI 토큰 한도에 도달해 외부 AI를 호출하지 않았습니다. AI 설정에서 한도를 확인하세요.",
    "ai_consent": "외부 AI 사용 승인이 없어 호출하지 않았습니다. AI 설정에서 승인하세요.",
    "ai_request_stopped": "이전 AI 요청이 실패했거나 결과가 불명확합니다. 자동 재전송하지 않습니다. 작업 이력을 확인하세요.",
    "news_search_blocked": "웹 뉴스 검색의 사용 승인·계정·비용 조건이 확인되지 않았습니다. 다른 방식으로 자동 전환하지 않습니다.",
    "no_eligible_articles": "선택한 분야·기간에 발행일과 출처가 확인되는 기사가 없습니다. 검색 요약의 날짜를 사실로 확정하지 않습니다.",
    "news_evidence_required": "개별 기사·발행일·핵심 사실의 확인 근거가 부족하여 사실 중심 제작을 중단했습니다.",
    "news_usage_script": "미검증 자료의 대본에 확인되지 않은 사실이 포함될 수 있어 제작을 중단했습니다.",
    "voice_unavailable": "선택한 한국어 음성을 이 PC에서 찾지 못했습니다. 음성 설정을 확인하거나 무음으로 제작하세요.",
    "speech_too_long": "음성이 영상 길이보다 깁니다. 대본을 줄이거나 영상 길이를 늘리세요.",
    "audio_review": "실제 음성 분량과 목표 길이가 맞지 않아 제작을 멈췄습니다. 추가 API 요청은 하지 않았습니다.",
    "voice_failed": "음성을 만들지 못했습니다. 선택한 한국어 음성과 PowerShell 실행 상태를 확인하세요.",
    "voice_api_failed": "ElevenLabs 음성 제작을 완료하지 못했습니다. 다른 음성으로 전환하거나 자동 재요청하지 않습니다.",
    "script_auto_review": "자동 대본 점검에서 확인이 필요한 내용이 발견되어 멈췄습니다. 대본과 출처를 직접 검토·수정하세요.",
    "ai_video_review": "Higgsfield 장면별 생성·내용 검토·최종 합성 승인이 필요합니다. 기본 영상으로 대체하지 않았습니다.",
    "voice_consent_required": "수정한 대본에 대한 ElevenLabs 전송·음성 사용 동의를 다시 확인하세요. 새 요청은 보내지 않았습니다.",
    "ai_scene_approval": "모든 장면의 AI 영상 계획에서 유료 생성·장면 검토·최종 합성 승인을 진행하세요.",
}
_SOLUTIONS = {
    "no_sources": "뉴스 출처 설정에서 출처를 등록하고 활성화한 뒤 다시 시도하세요. 체험 뉴스로 새 작업을 시작할 수도 있습니다.",
    "ai_not_ready": "설정 → AI 연결에서 제공자·승인·월 한도·API 키를 확인하거나, AI 없이 기본 대본으로 다시 시작하세요.",
    "ai_key_missing": "설정 → AI 연결에서 API 키를 저장한 뒤 다시 시도하세요.",
    "ai_auth_failed": "설정 → AI 연결에서 연결 상태 확인을 실행해 키가 유효한지 확인하세요.",
    "ai_rate_limited": "몇 분 뒤 다시 시도하거나 기본 대본으로 제작하세요.",
    "ai_timeout": "네트워크 상태를 확인하고 AI 설정의 제한시간을 늘린 뒤 다시 시도하세요.",
    "ai_unavailable": "인터넷 연결을 확인한 뒤 다시 시도하세요. 기본 대본으로도 제작할 수 있습니다.",
    "ai_bad_response": "AI 설정에서 모델 이름을 확인하거나 기본 대본으로 다시 시도하세요.",
    "ai_budget": "설정 → AI 연결에서 월 토큰 한도를 조정하거나 다음 달까지 기본 대본을 사용하세요.",
    "ai_consent": "설정 → AI 연결에서 유료 호출 승인을 저장하세요.",
    "news_evidence_required": "원문과 발행일을 확인해 주세요. 주제 참고용 제작은 작업실에서 빠른 제작 또는 균형 제작을 직접 선택하세요. 자동 재검색하지 않습니다.",
    "news_usage_script": "주제 설명형 대본과 참고 출처를 확인해 주세요. 개별 사건·수치·발언을 임의로 추가할 수 없습니다.",
    "voice_unavailable": "설정 → 음성과 자막에서 설치된 한국어 음성을 다시 선택하거나 무음 검토영상으로 제작하세요.",
    "speech_too_long": "대본 수정에서 문장을 줄이거나, 더 긴 영상 길이로 새 작업을 시작하세요.",
    "audio_review": "대본 수정에서 장면별 분량과 시간을 검토한 뒤 영상 제작 화면에서 다시 제작하세요. API 재생성은 별도 승인 없이는 실행하지 않습니다.",
    "voice_failed": "설정 → 음성과 자막에서 미리 듣기로 음성이 소리를 내는지 확인하고, 안 되면 무음 검토영상으로 제작하세요. 안내서의 실행 정책 항목도 확인하세요.",
}


class _Cancellation(Event):
    """A different local process can persist cancellation without owning the worker lock."""

    def __init__(self, sessions: sessionmaker[Session], job_id: str, stop: Event) -> None:
        super().__init__()
        self.sessions, self.job_id, self.stop = sessions, job_id, stop

    def is_set(self) -> bool:
        if super().is_set() or self.stop.is_set():
            return True
        with self.sessions() as session:
            value = session.scalar(select(AutopilotJob.cancel_requested).where(AutopilotJob.id == self.job_id))
        return value is not False

    def wait(self, timeout: float | None = None) -> bool:
        from time import monotonic

        deadline = monotonic() + timeout if timeout is not None else None
        while not self.is_set():
            if deadline is not None and monotonic() >= deadline:
                return False
            self.stop.wait(0.05 if deadline is None else min(0.05, max(0, deadline - monotonic())))
        return True


class AutopilotCoordinator:
    def __init__(
        self, sessions: sessionmaker[Session], data_dir: Path, backend: AutopilotBackend,
    ) -> None:
        self.sessions, self.backend = sessions, backend
        self.root = data_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.root / "autopilot.lock"), thread_local=False)
        self.guard = Lock()
        self.stop = Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="newsflow-autopilot")
        self.future: Future[None] | None = None

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        """Serialize read-modify-write transitions with cancellation from other processes.

        SQLite is the application database. Acquiring its writer reservation before
        reading prevents a worker from overwriting a concurrent cancel/CAS revision.
        No external work occurs while this short transaction is held.
        """
        with self.sessions.begin() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield session

    @staticmethod
    def _id(job_id: str) -> str:
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise AutopilotNotFound("작업을 찾을 수 없습니다.")
        return job_id

    @staticmethod
    def _revision(revision: int) -> int:
        if type(revision) is not int or revision < 1:
            raise AutopilotConflict("작업 상태가 바뀌었습니다. 화면을 새로 고침하세요.")
        return revision

    @staticmethod
    def _event(session: Session, job: AutopilotJob, status: str, message: str) -> None:
        session.add(AutopilotEvent(job_id=job.id, stage=job.current_stage, status=status, message=message))

    def _acquire(self) -> None:
        if self.stop.is_set():
            raise AutopilotBusy("프로그램 종료 중에는 시작할 수 없습니다.")
        if self.future is not None and not self.future.done():
            raise AutopilotBusy("진행 중인 작업을 먼저 확인하세요.")
        try:
            self.lock.acquire(timeout=0)
        except Timeout:
            raise AutopilotBusy("다른 창에서 제작 중입니다. 진행 중인 작업을 확인하세요.") from None

    @staticmethod
    def _pauses(job: AutopilotJob) -> set[str]:
        """Legacy review gates plus an explicit new-job script choice; final review stays mandatory."""
        pauses = {"select", "script", "validate"} if job.mode == "guided" else set()
        if job.content_mode == "real":
            pauses |= {"script", "validate"}
        if job.stage_results.get("request", {}).get("unified"):
            pauses.discard("select")
        choices = job.stage_results.get("request", {}).get("production_options", {})
        if choices.get("version") in {1, 2}:
            if choices.get("video_provider") == "higgsfield" and choices["version"] == 1:
                pauses.add("script")  # Existing per-scene approvals remain mandatory.
            elif choices.get("script_review") is False:
                pauses.discard("script")
            pauses.add("validate")  # Skipping script review never approves the finished video.
        return pauses

    def start(
        self, mode: str = "easy", source: str = "sample", duration: int = 30, platform: str = "youtube",
        content_mode: str | None = None, ai_mode: str = "offline", voice: str | None = None,
        *, request_id: str | None = None, ai_model: str | None = None,
        acquisition_policy: str | None = None, category: str = "all", period: str | None = None,
        external_consent: bool = False, news_usage: str = "STANDARD",
        production_options: dict | None = None,
    ) -> str:
        if mode not in {"easy", "guided"} or source not in {"sample", "feeds"}:
            raise AutopilotError("제작 방식과 뉴스 종류를 다시 선택하세요.")
        if type(duration) is not int or duration not in {30, 45, 60} or platform not in {"youtube", "instagram"}:
            raise AutopilotError("영상 길이와 게시 대상을 다시 선택하세요.")
        content_mode = content_mode or ("real" if source == "feeds" else "trial")
        if content_mode not in CONTENT_MODES or (content_mode == "real") != (source == "feeds"):
            raise AutopilotError("체험 제작은 체험 뉴스, 실제 콘텐츠 제작은 등록한 뉴스 출처를 사용합니다.")
        if ai_mode not in AI_MODES or (content_mode == "trial" and ai_mode != "offline"):
            raise AutopilotError("체험 제작에서는 외부 AI를 사용하지 않습니다. AI 방식을 다시 선택하세요.")
        if voice is not None and (not isinstance(voice, str) or not 0 < len(voice) <= 200 or "\x00" in voice):
            raise AutopilotError("음성을 다시 선택하세요.")
        try:
            news_usage = validate_news_usage(news_usage)
        except ValueError:
            raise AutopilotError("뉴스 활용 수준을 다시 선택하세요.") from None
        request = {}
        if acquisition_policy is not None or ai_mode in {"claude_code", "codex", "claude_api"}:
            from newsflow.intelligence.settings import SettingsError, studio_model

            try:
                ready = getattr(self.backend, "acquisition_ready", lambda _: False)
                require_acquisition(ai_mode, acquisition_policy,
                                    api_ready=ready(ai_mode) if acquisition_policy != "rss" else False)
            except ValueError:
                raise AutopilotError(_ERROR_MESSAGES["news_search_blocked"]) from None
            if category not in NEWS_CATEGORIES or period not in NEWS_PERIODS:
                raise AutopilotError("뉴스 분야와 조사 기간을 다시 선택하세요.")
            if ai_mode != "offline" and external_consent is not True:
                raise AutopilotError("이 작업의 검색·분석·대본 생성에 필요한 자료 전송과 사용량·비용 동의가 필요합니다.")
            try:
                model = studio_model(ai_mode, ai_model)
            except (SettingsError, TypeError):
                raise AutopilotError("제작할 AI와 모델 설정을 확인하세요.") from None
            request = {
                "unified": True, "ai_model": model, "acquisition_policy": acquisition_policy,
                "category": category, "period": period, "external_consent": external_consent is True,
                "consented_at": utcnow().isoformat() if external_consent is True else None,
                "requested_at": utcnow().isoformat(),
                "analysis_provider": ai_mode, "script_provider": ai_mode,
                "news_method": ("synthetic_rss" if source == "sample" else "ai_web+rss" if acquisition_policy == "hybrid"
                                else "ai_web" if acquisition_policy == "ai_web" else "rss"),
                **({"search_provider": ai_mode} if acquisition_policy != "rss" else {}),
            }
        # A per-job policy does not opt legacy/sample paths into the unified AI pipeline.
        request["news_usage"] = news_usage
        if production_options is not None:
            from .production_options import freeze_options

            if voice == "elevenlabs" and content_mode != "real":
                raise AutopilotError("체험 뉴스는 ElevenLabs로 보내지 않습니다. 실제 뉴스와 별도 음성 동의를 확인하세요.")
            request["production_options"] = freeze_options(production_options, voice)
        if content_mode == "real" and ai_mode in {"openai", "claude_api"}:
            # Server-owned creation marker: old local jobs must never gain paid analysis
            # or script requests merely because an app version changed after restart.
            if external_consent is not True:
                raise AutopilotError("선택한 API의 검색·분석·대본 생성에 대한 자료 전송과 비용 동의가 필요합니다.")
            from newsflow.intelligence.settings import SettingsError, studio_model

            try:
                model = studio_model(ai_mode, ai_model)
            except (SettingsError, TypeError):
                raise AutopilotError("제작할 AI와 모델 설정을 확인하세요.") from None
            request.update(script_method="api_grounded_v1", ai_model=model,
                           external_consent=True, consented_at=request.get("consented_at") or utcnow().isoformat())
        if request_id is not None:
            self._id(request_id)
        with self.guard:
            # Durable caller identity closes the scheduler/start crash gap. Existing jobs are
            # returned without starting or retrying them; parameters must describe the same work.
            if request_id:
                with self.sessions() as session:
                    existing = session.get(AutopilotJob, request_id)
                    if existing:
                        if (existing.mode, existing.source, existing.duration, existing.platform,
                            existing.content_mode, existing.ai_mode, existing.voice) != (
                            mode, source, duration, platform, content_mode, ai_mode, voice):
                            raise AutopilotConflict("같은 작업 번호로 다른 제작을 시작할 수 없습니다.")
                        old = existing.stage_results.get("request", {})
                        comparable = {"news_usage": "STANDARD", **old}
                        if (any(comparable.get(key) != value for key, value in request.items()
                                if key not in {"consented_at", "requested_at"})
                                or bool(set(old) - {"news_usage"}) != bool(set(request) - {"news_usage"})):
                            raise AutopilotConflict("같은 작업 번호의 AI와 뉴스 수집 정책을 변경할 수 없습니다.")
                        return existing.id
            self._acquire()
            job_id = request_id or uuid4().hex
            try:
                with self._transaction() as session:
                    job = AutopilotJob(
                        id=job_id, active_slot=1, mode=mode, source=source, duration=duration,
                        platform=platform, status="queued", current_stage="collect",
                        stage_results={"request": request} if request else {},
                        content_mode=content_mode, ai_mode=ai_mode, voice=voice,
                    )
                    session.add(job)
                    session.flush()
                    self._event(session, job, "queued", "자동 제작을 준비합니다.")
                self.future = self.executor.submit(self._run, job_id)
            except IntegrityError:
                self.lock.release()
                raise AutopilotBusy("진행 중이거나 확인을 기다리는 작업이 있습니다.") from None
            except BaseException:
                self.lock.release()
                raise
        return job_id

    def _context(self, session: Session, job: AutopilotJob) -> dict[str, Any]:
        scheduled = session.scalar(select(ScheduledRun.id).where(ScheduledRun.job_id == job.id)) is not None
        if scheduled and job.ai_mode != "offline":
            raise BackendError(code="ai_consent", retryable=False, outcome_unknown=True)
        context: dict[str, Any] = dict(job.stage_results.get("request", {}))
        for stage in STAGES:
            context.update(job.stage_results.get(stage, {}))
        # Keep the initial user choice authoritative. Do not opt old jobs into a
        # new execution policy merely by reading/resuming their saved state.
        if "news_usage" in job.stage_results.get("request", {}):
            context["news_usage"] = job.stage_results["request"]["news_usage"]
        if "production_options" in job.stage_results.get("request", {}):
            context["production_options"] = job.stage_results["request"]["production_options"]
        context.update({
            "job_id": job.id, "mode": job.mode, "source": job.source, "duration": job.duration, "scheduled": scheduled,
            "platform": job.platform, "stage_results": dict(job.stage_results), "article_id": job.article_id,
            "content_mode": job.content_mode, "ai_mode": job.ai_mode, "voice": job.voice,
        })
        for item in session.scalars(
            select(AutopilotArtifact).where(AutopilotArtifact.job_id == job.id).order_by(AutopilotArtifact.id)
        ):
            if item.kind != "article_id":
                context[item.kind] = int(item.reference)
        return context

    def snapshot(self, job_id: str) -> dict[str, Any]:
        sync = getattr(self.backend, "sync_video", None)
        if sync:
            sync()  # Only adopts an already approved, completed local result; never generates.
        with self.sessions() as session:
            job = session.get(AutopilotJob, self._id(job_id))
            if job is None:
                raise AutopilotNotFound("작업을 찾을 수 없습니다.")
            context = self._context(session, job)
            artifacts = {key: context[key] for key in ARTIFACT_KEYS if context.get(key) is not None}
            candidates = job.stage_results.get("select", {}).get("candidate_article_ids", [])
            articles = session.scalars(select(NewsArticle).where(NewsArticle.id.in_(candidates))).all()
            attempts = session.scalars(
                select(AutopilotAttempt).where(AutopilotAttempt.job_id == job.id).order_by(AutopilotAttempt.id)
            ).all()
            events = session.scalars(
                select(AutopilotEvent).where(AutopilotEvent.job_id == job.id).order_by(AutopilotEvent.id.desc()).limit(50)
            ).all()
            render = session.get(RenderJob, artifacts["render_job_id"]) if artifacts.get("render_job_id") else None
            ai_plan = session.get(AIVideoPlan, artifacts["ai_plan_id"]) if artifacts.get("ai_plan_id") else None
            ai_phase = None
            if ai_plan and job.current_stage == "render" and job.status == "waiting_review":
                ai_phase = {"draft": "AI 장면 모델·유료 생성 승인 대기", "generating": "승인한 AI 장면 생성·수신 중",
                            "review": "최종 합성 승인 대기" if ai_plan.reviewed_at else "생성 장면의 뉴스 관련성 검토 대기",
                            "composing": "선택한 음성과 AI 장면 합성 중", "compose_failed": "AI 영상 합성 실패 · 결과 보존 · 계획에서 원인 확인",
                            "composed": "완성 영상 검사·연결 중"}.get(ai_plan.status, "AI 장면 상태·실패 원인 확인")
            usage_result = context.get("news_usage_result")
            if job.error_code == "news_evidence_required":
                usage_result = {
                    "mode": context.get("news_usage", "STANDARD"), "approach": "blocked",
                    "source_kind": usage_result.get("source_kind", "unknown") if isinstance(usage_result, dict) else "unknown",
                    "verification_status": "NOT VERIFIED", "message": _ERROR_MESSAGES["news_evidence_required"],
                }
            return {
                "id": job.id, "revision": job.revision, "mode": job.mode, "source": job.source,
                "duration": job.duration, "platform": job.platform, "status": job.status,
                "content_mode": job.content_mode, "ai_mode": job.ai_mode, "voice": job.voice,
                **job.stage_results.get("request", {}),
                "news_usage": context.get("news_usage", "STANDARD"),
                "news_usage_result": usage_result if isinstance(usage_result, dict) else None,
                **{key: context[key] for key in ("analysis_provider", "script_provider", "script_method", "actual_method")
                   if key in context},
                "review_pauses": sorted(self._pauses(job), key=STAGES.index),
                "current_stage": job.current_stage,
                "stage_label": "기사 분석·뉴스 선정" if job.current_stage == "select" and context.get("unified")
                else STAGE_LABELS[job.current_stage],
                "progress": job.progress, "message": ai_phase or job.message, "error_code": job.error_code,
                "ai_phase": ai_phase, "ai_plan_status": ai_plan.status if ai_plan else None,
                "retryable": job.retryable, "cancel_requested": job.cancel_requested,
                "solution": _SOLUTIONS.get(
                    job.error_code or "",
                    _ERROR_MESSAGES.get(job.error_code or "", "결과를 확인한 뒤 다음 단계로 진행하세요."),
                ),
                "article_id": job.article_id, "artifacts": artifacts, **artifacts,
                "stage_results": dict(job.stage_results),
                "candidates": [{"id": a.id, "title": a.title, "publisher": a.publisher, "category": a.category} for a in articles],
                "attempts": [{"stage": a.stage, "number": a.number, "status": a.status, "error_code": a.error_code} for a in attempts],
                "events": [{"stage": e.stage, "status": e.status, "message": e.message, "created_at": e.created_at.isoformat()} for e in reversed(events)],
                "output_name": render.output_name if render else None,
                "preview_playable": bool(render and render.status == "success" and render.metadata_json.get("playable") is True),
                "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            }

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AutopilotError("목록 크기를 확인하세요.")
        with self.sessions() as session:
            ids = session.scalars(select(AutopilotJob.id).order_by(AutopilotJob.created_at.desc()).limit(limit)).all()
        return [self.snapshot(job_id) for job_id in ids]

    def _save_artifact(self, job_id: str, kind: str, reference: int | str) -> None:
        if kind not in ARTIFACT_KEYS or isinstance(reference, bool) or not re.fullmatch(r"[1-9][0-9]{0,17}", str(reference)):
            raise BackendError(code="stage_failed", retryable=False, outcome_unknown=True)
        with self._transaction() as session:
            existing = session.scalar(select(AutopilotArtifact.id).where(
                AutopilotArtifact.job_id == job_id, AutopilotArtifact.kind == kind,
                AutopilotArtifact.reference == str(reference),
            ))
            if existing is None:
                session.add(AutopilotArtifact(job_id=job_id, kind=kind, reference=str(reference)))

    def _progress(self, job_id: str, stage: str, value: int, _message: str) -> None:
        if type(value) is not int or not 0 <= value <= 100:
            return
        overall = min(99, round((STAGES.index(stage) * 100 + value) / len(STAGES)))
        with self._transaction() as session:
            session.execute(update(AutopilotJob).where(
                AutopilotJob.id == job_id, AutopilotJob.status == "running", AutopilotJob.current_stage == stage,
            ).values(progress=overall, message=STAGE_LABELS[stage] + " 진행 중", updated_at=utcnow()))

    @staticmethod
    def _validated_result(value: dict[str, Any], stage: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise BackendError(retryable=False, outcome_unknown=True)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 32768:
            raise BackendError(retryable=False, outcome_unknown=True)
        def inspect(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str) or re.search(r"token|secret|password|authorization|api_key|verifier", key, re.IGNORECASE):
                        raise BackendError(retryable=False, outcome_unknown=True)
                    inspect(child)
            elif isinstance(item, list):
                for child in item:
                    inspect(child)
        inspect(value)
        required_ids = {
            "collect": (("search_run_id",) if value.get("news_method") == "ai_web" else
                        ("collection_run_id", "search_run_id") if value.get("news_method") == "ai_web+rss" else
                        ("collection_run_id",)), "select": ("article_id",),
            "script": ("content_draft_id",), "render": ("render_job_id", "video_project_id"),
            "validate": (), "queue": ("publish_draft_id",),
        }
        if any(type(value.get(key)) is not int or value[key] < 1 for key in required_ids[stage]):
            raise BackendError(retryable=False, outcome_unknown=True)
        if stage == "collect" and value.get("collection_status") != "success":
            raise BackendError(retryable=False, outcome_unknown=True)
        if stage == "script" and value.get("ai_mode", "offline") not in AI_MODES:
            raise BackendError(retryable=False, outcome_unknown=True)
        if stage == "render" and value.get("preview_only") is not True:
            raise BackendError(retryable=False, outcome_unknown=True)
        if stage == "validate" and not (
            re.fullmatch(r"[a-f0-9]{64}", str(value.get("media_sha256", "")))
            and value.get("preview_only") is True and value.get("human_review_required") is True
        ):
            raise BackendError(retryable=False, outcome_unknown=True)
        if stage == "queue" and not (
            value.get("queue_state") == "review_required" and value.get("external_publishing_enabled") is False
        ):
            raise BackendError(retryable=False, outcome_unknown=True)
        return json.loads(encoded)

    @staticmethod
    def _claim(session: Session, job: AutopilotJob, article_id: int) -> None:
        if type(article_id) is not int or session.get(NewsArticle, article_id) is None:
            raise BackendError(code="no_articles", retryable=True)
        claim = session.get(AutopilotArticleClaim, article_id)
        if claim is not None and claim.job_id != job.id:
            raise BackendError(code="duplicate_article", retryable=False)
        old = session.scalar(select(AutopilotArticleClaim).where(AutopilotArticleClaim.job_id == job.id))
        if old and old.article_id != article_id:
            session.delete(old)
            session.flush()
        if claim is None:
            session.add(AutopilotArticleClaim(article_id=article_id, job_id=job.id))
        job.article_id = article_id

    def _run(self, job_id: str) -> None:
        cancellation = _Cancellation(self.sessions, job_id, self.stop)
        attempt_id: int | None = None
        try:
            while True:
                if cancellation.is_set():
                    self._finish_failure(job_id, attempt_id, "interrupted" if self.stop.is_set() else "cancelled", True)
                    return
                with self._transaction() as session:
                    job = session.get(AutopilotJob, job_id)
                    if job is None or job.status not in {"queued", "running"}:
                        return
                    stage = job.current_stage
                    context = self._context(session, job)
                    if stage == "script":
                        self._claim(session, job, job.article_id)
                    number = (session.scalar(select(func.max(AutopilotAttempt.number)).where(
                        AutopilotAttempt.job_id == job_id, AutopilotAttempt.stage == stage,
                    )) or 0) + 1
                    attempt = AutopilotAttempt(job_id=job_id, stage=stage, number=number, status="running")
                    session.add(attempt)
                    job.status, job.message, job.updated_at = "running", STAGE_LABELS[stage] + " 진행 중", utcnow()
                    job.revision += 1
                    self._event(session, job, "running", job.message)
                    session.flush()
                    attempt_id = attempt.id
                result = self._validated_result(self.backend.execute(
                    stage, context, cancellation,
                    lambda value, message, stage=stage: self._progress(job_id, stage, value, message),
                    lambda kind, reference: self._save_artifact(job_id, kind, reference),
                ), stage)
                # Persist useful results even when cancellation arrived after the side effect.
                with self._transaction() as session:
                    job = session.get(AutopilotJob, job_id)
                    attempt = session.get(AutopilotAttempt, attempt_id)
                    if stage == "select":
                        candidates = result.get("candidate_article_ids", [])
                        chosen = result.get("article_id")
                        if not isinstance(candidates, list) or not candidates or len(candidates) > 100 or any(type(item) is not int or item < 1 for item in candidates) or len(candidates) != len(set(candidates)) or chosen not in candidates:
                            raise BackendError(code="no_articles", retryable=False)
                        self._claim(session, job, chosen)
                    job.stage_results = {**job.stage_results, stage: result}
                    attempt.status, attempt.finished_at = "completed", utcnow()
                    job.progress = round((STAGES.index(stage) + 1) * 100 / len(STAGES))
                    job.updated_at, job.revision = utcnow(), job.revision + 1
                    self._event(session, job, "stage_completed", STAGE_LABELS[stage] + " 완료")
                    if cancellation.is_set():
                        # No further stage starts; artifacts and successful attempt remain visible.
                        job.status = "interrupted" if self.stop.is_set() else "cancelled"
                        job.active_slot, job.finished_at = None, utcnow()
                        job.error_code, job.retryable = job.status, True
                        job.message = _ERROR_MESSAGES[job.status]
                        if stage != "queue" and stage not in self._pauses(job):
                            job.current_stage = STAGES[STAGES.index(stage) + 1]
                        self._event(session, job, job.status, job.message)
                        return
                    if stage == "queue":
                        job.status, job.active_slot, job.finished_at = "completed", None, utcnow()
                        job.message, job.error_code, job.retryable = "영상과 게시 초안을 보관했습니다. 게시 전 직접 검토하세요.", None, False
                        self._event(session, job, "completed", job.message)
                        return
                    if stage in self._pauses(job):
                        job.status, job.message = "waiting_review", "결과를 확인하고 다음 단계로 진행하세요."
                        self._event(session, job, "waiting_review", job.message)
                        return
                    job.current_stage = STAGES[STAGES.index(stage) + 1]
                    attempt_id = None
        except BackendWaiting:
            with self._transaction() as session:
                job = session.get(AutopilotJob, job_id)
                if job and job.status == "running":
                    stopped = job.cancel_requested or self.stop.is_set()
                    job.status = ("interrupted" if self.stop.is_set() else "cancelled") if stopped else "waiting_review"
                    job.error_code = job.status if stopped else "ai_scene_approval"
                    job.message, job.retryable = _ERROR_MESSAGES[job.error_code], bool(stopped)
                    if stopped:
                        job.active_slot, job.finished_at = None, utcnow()
                    job.revision, job.updated_at = job.revision + 1, utcnow()
                    if attempt_id:
                        attempt = session.get(AutopilotAttempt, attempt_id)
                        attempt.status, attempt.finished_at = "waiting_review", utcnow()
                    self._event(session, job, job.status, job.message)
        except BackendError as error:
            code = error.code if error.code in _ERROR_MESSAGES else "stage_failed"
            if code == "cancelled" and self.stop.is_set():
                code = "interrupted"
            if code == "stage_failed" and "stage" in locals():
                code = f"{stage}_failed"
            self._finish_failure(job_id, attempt_id, "outcome_unknown" if error.outcome_unknown else code, error.retryable)
        except Exception:  # noqa: BLE001 - never expose provider errors; quarantine unknown effects
            # Provider tracebacks/raw errors may contain secrets; only an internal stable category is persisted.
            self._finish_failure(job_id, attempt_id, "outcome_unknown", False)
        finally:
            self.lock.release()

    def _finish_failure(self, job_id: str, attempt_id: int | None, code: str, retryable: bool) -> None:
        with self._transaction() as session:
            job = session.get(AutopilotJob, job_id)
            if job is None:
                return
            attempt = session.get(AutopilotAttempt, attempt_id) if attempt_id else None
            if attempt and attempt.status == "running":
                attempt.status = "unknown" if code in {"outcome_unknown", "interrupted"} else "cancelled" if code == "cancelled" else "failed"
                attempt.error_code, attempt.finished_at = code, utcnow()
            job.status = code if code in {"cancelled", "interrupted"} else "failed"
            job.active_slot, job.error_code, job.retryable = None, code, retryable
            job.message, job.updated_at, job.finished_at = _ERROR_MESSAGES[code], utcnow(), utcnow()
            job.revision += 1
            self._event(session, job, job.status, job.message)

    def cancel(self, job_id: str, revision: int) -> dict[str, Any]:
        self._id(job_id)
        self._revision(revision)
        with self._transaction() as session:
            job = session.get(AutopilotJob, job_id)
            if job is None:
                raise AutopilotNotFound("작업을 찾을 수 없습니다.")
            if job.revision != revision or job.status not in {"queued", "running", "waiting_review"}:
                raise AutopilotConflict("작업 상태가 바뀌었습니다. 화면을 새로 고침하세요.")
            changed = session.execute(update(AutopilotJob).where(
                AutopilotJob.id == job_id, AutopilotJob.revision == revision,
            ).values(cancel_requested=True, revision=revision + 1, updated_at=utcnow()))
            if changed.rowcount != 1:
                raise AutopilotConflict("작업 상태가 바뀌었습니다.")
            session.refresh(job)
            if job.status == "waiting_review":
                job.status, job.active_slot, job.error_code = "cancelled", None, "cancelled"
                job.message, job.retryable, job.finished_at = _ERROR_MESSAGES["cancelled"], True, utcnow()
            self._event(session, job, "cancel_requested", "중단 요청을 받았습니다.")
        cancel_ai = getattr(self.backend, "cancel_ai", None)
        if cancel_ai:
            cancel_ai(job_id)
        return self.snapshot(job_id)

    def resume(self, job_id: str, revision: int, article_id: int | None = None) -> dict[str, Any]:
        return self._continue(job_id, revision, retry=False, article_id=article_id)

    def attach_completed_ai(self, plan_id: int) -> None:
        """Resume only the local adoption of an existing completed AI render."""
        with self.sessions() as session:
            job = session.scalar(select(AutopilotJob).join(AutopilotArtifact, AutopilotArtifact.job_id == AutopilotJob.id).where(
                AutopilotArtifact.kind == "ai_plan_id", AutopilotArtifact.reference == str(plan_id),
                AutopilotJob.status == "waiting_review", AutopilotJob.current_stage == "render"))
            identity = (job.id, job.revision) if job and not job.cancel_requested else None
        if identity:
            try:
                self.resume(*identity)
            except AutopilotError:
                pass  # Another poll/process owns the command; a later local sync rechecks it.

    def approve_voice(self, job_id: str, revision: int, consent: bool) -> dict[str, Any]:
        from newsflow.video.production_policy import approve_voice

        if consent is not True:
            raise AutopilotError("수정한 대본의 ElevenLabs 전송·음성 생성에 별도로 동의하세요.")
        with self._transaction() as session:
            job = session.get(AutopilotJob, self._id(job_id))
            if not job or job.revision != revision or job.cancel_requested:
                raise AutopilotConflict("작업 상태를 다시 확인하세요.")
            if job.status != "waiting_review" and not (job.status == "failed" and job.error_code == "voice_consent_required"):
                raise AutopilotConflict("실패·결과 불명 요청을 새 동의만으로 재실행할 수 없습니다.")
            context = self._context(session, job)
            choices = context.get("production_options", {})
            draft = session.get(ContentDraft, context.get("content_draft_id"))
            if choices.get("version") != 2 or choices.get("voice") != "elevenlabs" or not draft:
                raise AutopilotError("이 작업의 저장된 음성·대본을 확인하세요.")
            approve_voice(session, job, draft, choices)
            job.revision += 1
            if job.status == "failed":
                job.status, job.error_code, job.active_slot = "waiting_review", None, 1
            self._event(session, job, "voice_consent", "수정한 대본의 음성 사용 동의를 보존했습니다. 자동 요청하지 않습니다.")
        return self.snapshot(job_id)

    def retry(self, job_id: str, revision: int) -> dict[str, Any]:
        return self._continue(job_id, revision, retry=True)

    def _continue(self, job_id: str, revision: int, *, retry: bool, article_id: int | None = None) -> dict[str, Any]:
        self._id(job_id)
        self._revision(revision)
        with self.guard:
            self._acquire()
            try:
                with self._transaction() as session:
                    job = session.get(AutopilotJob, job_id)
                    if job is None:
                        raise AutopilotNotFound("작업을 찾을 수 없습니다.")
                    allowed = {"failed", "cancelled", "interrupted"} if retry else {"waiting_review"}
                    if job.revision != revision or job.status not in allowed:
                        raise AutopilotConflict("작업 상태가 바뀌었습니다. 화면을 새로 고침하세요.")
                    context = self._context(session, job)
                    restore_review = retry and job.current_stage in self._pauses(job) and job.current_stage in job.stage_results
                    if retry:
                        if not job.retryable or (not restore_review and not self.backend.can_retry(job.current_stage, context)):
                            raise AutopilotConflict("이 작업은 안전하게 다시 시작할 수 없습니다. 이전 결과를 확인하세요.")
                    elif article_id is not None:
                        if job.current_stage != "select" or type(article_id) is not int or article_id not in job.stage_results.get("select", {}).get("candidate_article_ids", []):
                            raise AutopilotError("이 작업에서 모은 뉴스 중 하나를 선택하세요.")
                        self._claim(session, job, article_id)
                        job.stage_results = {**job.stage_results, "select": {**job.stage_results["select"], "article_id": article_id}}
                    changed = session.execute(update(AutopilotJob).where(
                        AutopilotJob.id == job_id, AutopilotJob.revision == revision,
                    ).values(
                        status="waiting_review" if restore_review else "queued", active_slot=1, revision=revision + 1, cancel_requested=False,
                        retryable=False, error_code=None, finished_at=None, updated_at=utcnow(),
                        current_stage=job.current_stage if retry or job.current_stage == "render" else STAGES[STAGES.index(job.current_stage) + 1],
                        message="결과를 확인하고 다음 단계로 진행하세요." if restore_review else "작업을 이어서 진행합니다.",
                    ))
                    if changed.rowcount != 1:
                        raise AutopilotConflict("작업 상태가 바뀌었습니다.")
                    session.refresh(job)
                    self._event(session, job, job.status, job.message)
                if restore_review:
                    self.lock.release()
                else:
                    self.future = self.executor.submit(self._run, job_id)
            except IntegrityError:
                self.lock.release()
                raise AutopilotBusy("다른 작업이 진행 중입니다.") from None
            except BaseException:
                self.lock.release()
                raise
        return self.snapshot(job_id)

    def recover(self) -> int:
        """Never overwrite another process's active work; never turn uncertainty into success."""
        with self.guard:
            if self.future is not None and not self.future.done():
                return 0
            try:
                self.lock.acquire(timeout=0)
            except Timeout:
                return 0
            try:
                with self._transaction() as session:
                    jobs = session.scalars(select(AutopilotJob).where(AutopilotJob.status.in_(["queued", "running"]))).all()
                    for job in jobs:
                        job.status, job.active_slot, job.error_code = "interrupted", None, "interrupted"
                        job.message, job.retryable = _ERROR_MESSAGES["interrupted"], True
                        if job.ai_mode != "offline" and job.current_stage in {"collect", "select", "script"}:
                            context = self._context(session, job)
                            for key in ("search_run_id", "analysis_run_id", "script_run_id"):
                                identifier = context.get(key)
                                run = session.get(IntelligenceRun, identifier) if identifier else None
                                if identifier and (run is None or run.status != "success"):
                                    job.error_code = ("ai_request_stopped" if run and run.status == "failed"
                                                      else "outcome_unknown")
                                    job.status, job.retryable = "failed", False
                                    job.message = _ERROR_MESSAGES[job.error_code]
                                    break
                        job.updated_at, job.finished_at, job.revision = utcnow(), utcnow(), job.revision + 1
                        self._event(session, job, "interrupted", job.message)
                        session.execute(update(AutopilotAttempt).where(
                            AutopilotAttempt.job_id == job.id, AutopilotAttempt.status == "running",
                        ).values(status="unknown", error_code="interrupted", finished_at=utcnow()))
                    return len(jobs)
            finally:
                self.lock.release()

    def close(self) -> None:
        self.stop.set()
        self.executor.shutdown(wait=True, cancel_futures=False)
