"""Offline-first integration of existing services; no OAuth or publisher execution."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import (
    ArticleMention,
    ArticleScore,
    AuditLog,
    AutopilotArticleClaim,
    CollectionRun,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    PublishDraft,
    PublishValidation,
    RenderJob,
    VideoProject,
)
from newsflow.intelligence.capabilities import NEWS_CATEGORIES, require_acquisition
from newsflow.intelligence.korean import MIN_SUMMARY_CHARS, speech_plan
from newsflow.intelligence.news_usage import assess_news_usage
from newsflow.intelligence.provider import Options
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import ANALYSIS_MAX_TOKENS, max_tokens_for, read_settings
from newsflow.news.collector import Collector
from newsflow.news.rss_adapter import FakeRSSAdapter
from newsflow.news.service import CollectionCoordinator, NewsService
from newsflow.publishing.media import FFprobeMediaInspector
from newsflow.publishing.service import PublishingService, hash_file
from newsflow.video.service import VideoCoordinator, VideoError
from newsflow.video.tts import SpeechSettings, TTSError

from .contracts import BackendError
from .samples import SAMPLE_NAME, SAMPLE_URL, sample_feed

Progress = Callable[[int, str], None]
SaveArtifact = Callable[[str, int | str], None]
_AI_CODES = {
    "ai_not_ready", "ai_key_missing", "ai_auth_failed", "ai_rate_limited", "ai_timeout", "ai_unavailable",
    "ai_bad_response", "ai_budget", "ai_consent",
}


class PipelineBackend:
    """One explicit local workflow, with synthetic RSS and offline AI as defaults.

    Injected services are for deterministic tests. External AI runs only for a real-content
    job whose stored settings (provider, dated approval, monthly limit, key) pass the gate
    at execution time; trial jobs never leave the machine.
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        data_dir: Path,
        collection: CollectionCoordinator,
        video: VideoCoordinator,
        *,
        intelligence: IntelligenceService | None = None,
        publishing: PublishingService | None = None,
        ai_gate: Callable[[], dict] | None = None,
    ) -> None:
        self.sessions, self.collection, self.video = sessions, collection, video
        self.sample_collection = CollectionCoordinator(
            NewsService(sessions, Collector(FakeRSSAdapter({SAMPLE_URL: sample_feed()}))), data_dir
        )
        self.intelligence = intelligence or IntelligenceService(sessions)
        self.publishing = publishing or PublishingService(sessions, video.outputs)
        # Without a gate, external AI is never ready: the safe default for tests and tools.
        self.ai_gate = ai_gate or (lambda: {"ready": False, "reasons": ["AI 설정이 연결되지 않았습니다."]})
        # Always independently inspect the physical MP4. FakeRenderAdapter cannot
        # promote its nonplayable marker merely through injected publish metadata.
        self.inspector = FFprobeMediaInspector()

    def close(self) -> None:
        self.sample_collection.close()

    @staticmethod
    def _cancel(cancel: Event) -> None:
        if cancel.is_set():
            raise BackendError("요청에 따라 제작을 중단했습니다.", code="cancelled")

    def execute(
        self,
        stage: str,
        context: dict[str, Any],
        cancel: Event,
        progress: Progress,
        save_artifact: SaveArtifact,
    ) -> dict[str, Any]:
        self._cancel(cancel)
        handlers = {
            "collect": self._collect,
            "select": self._select,
            "script": self._script,
            "render": self._render,
            "validate": self._validate,
            "queue": self._queue,
        }
        if stage not in handlers:
            raise BackendError("지원하지 않는 제작 단계입니다.", retryable=False)
        try:
            return handlers[stage](context, cancel, progress, save_artifact)
        except BackendError:
            raise
        except Exception:  # noqa: BLE001 - do not persist raw adapter or filesystem errors
            messages = {
                "collect": "뉴스를 가져오지 못했습니다. 출처 설정과 연결 상태를 확인하세요.",
                "select": "제작할 뉴스를 찾지 못했습니다. 다른 뉴스를 선택하세요.",
                "script": "대본을 만들지 못했습니다. 대본 단계에서 다시 시도하세요.",
                "render": "영상을 만들지 못했습니다. 고급 설정에서 제작 도구와 저장 공간을 확인하세요.",
                "validate": "영상 파일을 확인하지 못했습니다. 결과 영상을 다시 제작하세요.",
                "queue": "게시 대기함에 보관하지 못했습니다. 영상을 확인한 뒤 다시 시도하세요.",
            }
            raise BackendError(messages[stage]) from None

    def can_retry(self, stage: str, context: dict[str, Any]) -> bool:
        if stage in {"collect", "select", "script"} and context.get("ai_mode", "offline") != "offline":
            with self.sessions() as session:
                for key in ("search_run_id", "analysis_run_id", "script_run_id"):
                    identifier = context.get(key)
                    if identifier:
                        run = session.get(IntelligenceRun, identifier)
                        if run is None or run.status != "success":
                            return False  # Failed/unknown external requests are never replayed.
        if stage in {"collect", "select", "validate", "queue"}:
            if stage == "collect" and context.get("collection_run_id"):
                with self.sessions() as session:
                    run = session.get(CollectionRun, context["collection_run_id"])
                    return bool(run and run.status != "running")
            return True
        with self.sessions() as session:
            if stage == "render":
                job = (
                    session.get(RenderJob, context.get("render_job_id"))
                    if context.get("render_job_id")
                    else None
                )
                return not context.get("render_job_id") or bool(
                    job and job.status in {"success", "failed", "interrupted"}
                )
            if stage == "script":
                if context.get("content_draft_id"):
                    return session.get(ContentDraft, context["content_draft_id"]) is not None
                identifier = context.get("script_run_id") or context.get("analysis_run_id")
                run = session.get(IntelligenceRun, identifier) if identifier else None
                return not identifier or bool(run and run.status in {"success", "failed", "interrupted"})
        return False

    def _sources(self, source: str) -> list[int]:
        if source == "sample":
            with self.sessions.begin() as session:
                row = session.scalar(select(NewsSource).where(NewsSource.url == SAMPLE_URL))
                if row is None:
                    row = NewsSource(name=SAMPLE_NAME, url=SAMPLE_URL, enabled=False)
                    session.add(row)
                    session.flush()
                return [row.id]
        if source != "feeds":
            raise BackendError("뉴스 종류를 다시 선택하세요.", retryable=False)
        with self.sessions() as session:
            identifiers = list(
                session.scalars(select(NewsSource.id).where(NewsSource.enabled, NewsSource.url != SAMPLE_URL))
            )
        if not identifiers:
            raise BackendError("사용 중인 뉴스 출처가 없습니다.", code="no_sources")
        if len(identifiers) > 20:
            raise BackendError("한 번에 가져올 뉴스 출처를 20개 이하로 선택하세요.")
        return identifiers

    def _collect(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
        if ctx.get("acquisition_policy") is not None:
            try:
                require_acquisition(ctx.get("ai_mode", "offline"), ctx["acquisition_policy"],
                                    api_ready=(self.acquisition_ready(ctx.get("ai_mode", "offline"))
                                               if ctx["acquisition_policy"] != "rss" else False))
            except ValueError:
                raise BackendError(code="news_search_blocked", retryable=False) from None
        if ctx.get("acquisition_policy") in {"ai_web", "hybrid"}:
            search = self._search_collect(ctx, cancel, progress, save)
            if ctx["acquisition_policy"] == "ai_web":
                return search
            # Explicit hybrid policy only. Search failures never fall through to RSS.
            rss = self._rss_collect(ctx, cancel, progress, save)
            return {**rss, **search, "news_method": "ai_web+rss", "rss_collection_run_id": rss["collection_run_id"],
                    "collection_run_id": rss["collection_run_id"],
                    "source_ids": list(dict.fromkeys([*search["source_ids"], *rss["source_ids"]])),
                    "rss_source_ids": rss["source_ids"],
                    "added": rss["added"] + search["added"], "duplicates": rss["duplicates"] + search["duplicates"]}
        return self._rss_collect(ctx, cancel, progress, save)

    def acquisition_ready(self, mode: str) -> bool:
        if mode not in {"openai", "claude_api"}:
            return False
        return self.intelligence.api_readiness(mode, "search").get("ready") is True

    def _search_collect(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
        from newsflow.intelligence.api_search import SearchRequest

        mode = self._ai_mode(ctx)
        identifier = ctx.get("search_run_id")
        if identifier is None:
            try:
                identifier = self.intelligence.search_news(
                    mode, SearchRequest(category=ctx["category"], period=ctx["period"], count=5),
                    consent=ctx.get("external_consent") is True, options=self._options(ctx, 3000),
                    on_run=self._remember(ctx, "search_run_id", save), cancel=cancel,
                )
            except IntelligenceError as exc:
                raise self._ai_failure(exc, external=True) from None
        self._cancel(cancel)
        with self.sessions() as session:
            run = session.get(IntelligenceRun, identifier)
            if run is None or run.kind != "search" or run.provider != mode or run.status != "success":
                raise BackendError(code="ai_request_stopped", retryable=False,
                                   outcome_unknown=bool(run and run.status in {"running", "interrupted"}))
            result = run.result
            progress(100, "검색 도구 출처를 확보했어요. 발행일·원문 사실은 별도 확인이 필요해요.")
            return {"search_run_id": identifier, "source_ids": result["source_ids"],
                    "collection_status": "success",
                    "search_article_ids": result["article_ids"], "search_provider": mode,
                    "added": result["added"], "duplicates": result["duplicates"], "synthetic_news": False,
                    "news_method": "ai_web", "researched_at": result["searched_at"],
                    "web_search_performed": result["web_search_performed"],
                    "simulated_search": result["simulated"], "facts_verified": False}

    def _rss_collect(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
        source_ids = list(ctx.get("source_ids") or [])
        coordinator = self.sample_collection if ctx["source"] == "sample" else self.collection
        identifier = ctx.get("collection_run_id")
        if identifier:
            with self.sessions() as session:
                previous = session.get(CollectionRun, identifier)
                if previous is None:
                    raise BackendError("수집 이력을 찾지 못했습니다.", retryable=False)
                if previous.status in {"failed", "partial", "empty", "interrupted"}:
                    identifier = None
        if identifier is None:
            source_ids = source_ids or self._sources(ctx["source"])
            identifier = coordinator.start(source_ids, lambda value: save("collection_run_id", value))
        deadline = time.monotonic() + 1200
        while True:
            self._cancel(cancel)
            with self.sessions() as session:
                run = session.get(CollectionRun, identifier)
                if run.status != "running":
                    if run.status != "success":
                        raise BackendError(
                            "일부 뉴스 출처를 가져오지 못했습니다. 오류 출처를 확인하고 다시 시도하세요."
                            if run.status == "partial"
                            else "뉴스를 가져오지 못했습니다. 출처와 연결 상태를 확인하세요."
                        )
                    # Use the completed run's own source journal after a restart,
                    # not a potentially edited current source configuration.
                    collected_sources = list(
                        session.scalars(
                            select(AuditLog.source_id)
                            .where(
                                AuditLog.run_id == identifier,
                                AuditLog.event == "source_success",
                                AuditLog.source_id.is_not(None),
                            )
                            .distinct()
                        )
                    )
                    urls = list(
                        session.scalars(select(NewsSource.url).where(NewsSource.id.in_(collected_sources)))
                    )
                    if (
                        not urls
                        or (ctx["source"] == "sample" and urls != [SAMPLE_URL])
                        or (ctx["source"] == "feeds" and SAMPLE_URL in urls)
                    ):
                        raise BackendError("수집 이력과 뉴스 출처가 일치하지 않습니다.", retryable=False)
                    return {
                        "collection_run_id": identifier,
                        "source_ids": collected_sources,
                        "collection_status": run.status,
                        "added": run.added,
                        "duplicates": run.duplicates,
                        "synthetic_news": ctx["source"] == "sample",
                        "news_method": "synthetic_rss" if ctx["source"] == "sample" else "rss",
                        "researched_at": run.finished_at.isoformat() if run.finished_at else None,
                        "web_search_performed": False,
                    }
            if time.monotonic() >= deadline:
                raise BackendError(
                    "수집 완료를 확인하지 못했습니다. 작업 이력을 확인하세요.", outcome_unknown=True
                )
            progress(
                30,
                "체험용 뉴스를 준비하고 있어요."
                if ctx["source"] == "sample"
                else "등록한 출처에서 뉴스를 가져오고 있어요.",
            )
            cancel.wait(0.1)

    def _select(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
        source_ids = ctx.get("source_ids", [])
        conditions = []
        if ctx.get("search_run_id"):
            scope = NewsArticle.id.in_(ctx.get("search_article_ids", []))
            if ctx.get("acquisition_policy") == "hybrid":
                scope = or_(scope, NewsArticle.id.in_(select(ArticleMention.article_id).where(
                    ArticleMention.source_id.in_(ctx.get("rss_source_ids", [])),
                )))
            conditions.append(scope)
        if ctx.get("unified") and ctx["source"] != "sample":
            requested = datetime.fromisoformat(ctx["requested_at"])
            if requested.tzinfo is None:
                raise BackendError(code="select_failed", retryable=False)
            since = (requested.astimezone(timezone(timedelta(hours=9))).replace(hour=0, minute=0, second=0, microsecond=0)
                     if ctx["period"] == "today" else requested - timedelta(days=7 if ctx["period"] == "7d" else 1))
            since = since.astimezone(UTC)
            # Unknown/future dates remain in the DB, but never become confirmed current news.
            dated = and_(NewsArticle.published_at >= since, NewsArticle.published_at <= requested)
            if ctx.get("news_usage") and ctx.get("search_run_id"):
                # Unknown search dates may supply topics, never confirmed current events.
                dated = or_(dated, and_(NewsArticle.id.in_(ctx.get("search_article_ids", [])),
                                       NewsArticle.published_at.is_(None)))
            conditions.append(dated)
            category = NEWS_CATEGORIES[ctx["category"]]
            if ctx["category"] != "all":
                conditions.append(NewsArticle.category == category)
        with self.sessions() as session:
            candidates = list(
                session.scalars(
                    select(NewsArticle.id)
                    .outerjoin(ArticleScore, ArticleScore.article_id == NewsArticle.id)
                    .where(
                        *conditions,
                        ~NewsArticle.id.in_(
                            select(AutopilotArticleClaim.article_id).where(
                                AutopilotArticleClaim.job_id != ctx["job_id"]
                            )
                        ),
                        NewsArticle.id.in_(
                            select(ArticleMention.article_id).where(ArticleMention.source_id.in_(source_ids))
                        ),
                    )
                    .order_by(ArticleScore.total.desc(), NewsArticle.collected_at.desc(), NewsArticle.id)
                    .limit(10 if ctx.get("unified") or ctx.get("news_usage") else 100)
                )
            )
        self._cancel(cancel)
        if not candidates:
            raise BackendError("제작할 뉴스가 없습니다. 다른 출처로 다시 시도하세요.",
                               code="no_eligible_articles" if ctx.get("unified") else "no_articles")
        if ctx.get("news_usage") and (ctx["source"] != "sample" or ctx["news_usage"] == "VERIFIED"):
            return self._select_topic(ctx, candidates, cancel, progress, save)
        analysis_id = ctx.get("analysis_run_id")
        selection_method = "rss_heuristic"
        selection_reason = "RSS 내부 추천 후보 순서 · 실제 조회수·화제성 측정 아님"
        if ctx.get("unified"):
            ai_mode = self._ai_mode(ctx)
            if analysis_id:
                with self.sessions() as session:
                    previous = session.get(IntelligenceRun, analysis_id)
                    if previous is None or previous.status != "success":
                        raise BackendError(code="ai_request_stopped", retryable=False,
                                           outcome_unknown=bool(previous and previous.status in {"running", "interrupted"}))
                    # Resume uses the original evidence set; RSS can change after an interrupted worker.
                    candidates = [a["id"] for a in previous.evidence["articles"]]
                    if previous.kind != "analysis" or previous.provider != ai_mode:
                        raise BackendError(code="select_failed", retryable=False)
            else:
                try:
                    with self._ai_service(ai_mode, cancel) as service:
                        analysis_id = service.analyze(
                            candidates, mode=ai_mode, consent=ai_mode != "offline",
                            options=self._options(ctx, ANALYSIS_MAX_TOKENS),
                            on_run=self._remember(ctx, "analysis_run_id", save),
                        )
                except IntelligenceError as exc:
                    raise self._ai_failure(exc, external=ai_mode != "offline") from None
                self._cancel(cancel)
            with self.sessions() as session:
                analysis = session.get(IntelligenceRun, analysis_id)
                recommended = analysis.result.get("recommended_article_id")
                if type(recommended) is int and recommended in candidates:
                    candidates = [recommended, *(item for item in candidates if item != recommended)]
                    selection_method = "ai_recommendation"
                    selection_reason = analysis.result.get("selection_reason") or "AI 제안 · 사실 확인 및 원문 검토 필요"
        chosen = ctx.get("article_id") or candidates[0]
        if chosen not in candidates:
            raise BackendError("선택한 뉴스가 이번 수집 결과와 다릅니다.", retryable=False)
        with self.sessions() as session:
            article = session.get(NewsArticle, chosen)
            sufficient = bool(article and len(article.summary.strip()) >= MIN_SUMMARY_CHARS)
            dated = bool(article and article.published_at is not None)
        progress(100, "제작할 뉴스 후보를 골랐어요.")
        return {
            "article_id": chosen, "candidate_article_ids": candidates,
            "content_sufficient": sufficient, "publication_dated": dated,
            "synthetic_news": ctx.get("source") == "sample",
            "selection_method": selection_method, "selection_reason": selection_reason,
            **({"analysis_run_id": analysis_id, "analysis_provider": ctx.get("ai_mode", "offline"),
                "ai_model": ctx.get("ai_model"), "analyzed_article_ids": candidates} if analysis_id else {}),
        }

    def _select_topic(self, ctx: dict, candidates: list[int], cancel: Event,
                      progress: Progress, save: SaveArtifact) -> dict:
        """Unverified sources select a topic; no second inference or factual promotion."""
        analysis_id = ctx.get("analysis_run_id")
        if analysis_id:
            with self.sessions() as session:
                run = session.get(IntelligenceRun, analysis_id)
                if (not run or run.status != "success" or run.kind != "analysis"
                        or run.provider != "local_topic_template"
                        or run.evidence.get("news_usage") != ctx["news_usage"]):
                    raise BackendError(code="ai_request_stopped", retryable=False)
                evidence = run.evidence
                candidates = [a["id"] for a in evidence["articles"]]
        else:
            evidence = self.intelligence.evidence_for(candidates)
        assessment = assess_news_usage(evidence, ctx["news_usage"])
        if assessment["approach"] == "blocked":
            raise BackendError(assessment["message"], code="news_evidence_required", retryable=False)
        candidates = assessment["preferred_article_ids"]
        chosen = ctx.get("article_id") or candidates[0]
        if chosen not in candidates:
            raise BackendError(code="select_failed", retryable=False)
        self._cancel(cancel)
        if analysis_id is None:
            try:
                analysis_id = self.intelligence.create_topic_analysis(
                    candidates, ctx["news_usage"], category=ctx.get("category"),
                    selected_provider=ctx.get("ai_mode", "offline"),
                    on_run=self._remember(ctx, "analysis_run_id", save),
                )
            except IntelligenceError:
                raise BackendError(code="news_usage_script", retryable=False) from None
        with self.sessions() as session:
            article = session.get(NewsArticle, chosen)
            sufficient = bool(article and len(article.summary.strip()) >= MIN_SUMMARY_CHARS)
            dated = bool(article and article.published_at)
        selected = {**evidence, "articles": [a for a in evidence["articles"] if a["id"] == chosen]}
        assessment = assess_news_usage(selected, ctx["news_usage"])
        progress(100, "주제 참고 자료를 골랐어요. 개별 사건의 원문 사실은 미검증입니다.")
        return {"article_id": chosen, "candidate_article_ids": candidates,
                "content_sufficient": sufficient, "publication_dated": dated,
                "synthetic_news": ctx["source"] == "sample", "selection_method": "topic_reference",
                "selection_reason": assessment["message"], "analysis_run_id": analysis_id,
                "analysis_provider": "local_topic_template", "analyzed_article_ids": candidates,
                "news_usage_result": assessment, "script_method": "local_topic_template"}

    def _speech(self) -> SpeechSettings:
        from newsflow.easy_setup import speech_preferences

        try:
            return speech_preferences(self.sessions)
        except TTSError:
            return SpeechSettings()

    def _ai_mode(self, ctx: dict) -> str:
        mode = ctx.get("ai_mode") or "offline"
        if ctx.get("scheduled") and mode != "offline":
            raise BackendError(code="ai_consent", retryable=False)
        if ctx.get("content_mode", "trial") != "real" and mode != "offline":
            raise BackendError("체험 제작에서는 외부 AI를 사용하지 않습니다.", retryable=False, code="ai_consent")
        if ((mode in {"claude_code", "codex"} or ctx.get("unified") and mode != "offline")
                and not (ctx.get("external_consent") is True and ctx.get("consented_at"))):
            raise BackendError(code="ai_consent", retryable=False)
        if mode == "openai":
            gate = self.ai_gate()
            if not gate.get("ready"):
                raise BackendError("외부 AI 준비 상태를 확인하세요.", code="ai_not_ready")
        if ((mode == "claude_api" or mode == "openai" and self.intelligence.api_managed)
                and not self.intelligence.api_readiness(mode, "analysis").get("ready")):
            raise BackendError("API 사용 승인·계정·비용 한도 확인이 필요합니다.", code="ai_not_ready", retryable=False)
        return mode

    @staticmethod
    def _ai_failure(exc: IntelligenceError, *, external: bool = False) -> BackendError:
        aliases = {"codex_auth": "ai_auth_failed", "codex_billing": "ai_consent",
                   "codex_usage": "ai_budget", "ai_billing_approval": "ai_consent",
                   "codex_cancelled": "cancelled", "ai_cancelled": "cancelled"}
        mapped = aliases.get(exc.code, exc.code)
        code = mapped if mapped in _AI_CODES | {"cancelled"} else "ai_request_stopped" if external else "script_failed"
        return BackendError(str(exc), code=code, retryable=False if external else exc.retryable,
                            outcome_unknown=external and mapped in {"ai_timeout", "ai_unavailable", "codex_rpc"})

    def _options(self, ctx: dict, maximum: int) -> Options | None:
        mode = ctx.get("ai_mode", "offline")
        if mode == "offline":
            return None
        settings = read_settings(self.sessions)
        if mode == "claude_api":
            from newsflow.intelligence.api_settings import read_api_settings

            api = read_api_settings(self.sessions, mode)
            return Options(model=ctx.get("ai_model") or api.model, max_tokens=maximum, timeout=60)
        return Options(model=ctx.get("ai_model") or settings.model, max_tokens=maximum,
                       timeout=60 if mode in {"claude_code", "codex"} else settings.timeout)

    def _remember(self, ctx: dict, kind: str, save: SaveArtifact):
        def remember(identifier: int) -> None:
            # Journal before a possible side effect. A crash after this point blocks replay.
            save(kind, identifier)
            if ctx.get("unified"):
                with self.sessions.begin() as session:
                    run = session.get(IntelligenceRun, identifier)
                    run.options = {**run.options, "autopilot_job_id": ctx["job_id"],
                                   "production_context": {
                                       "source": ctx["source"], "initial_duration": ctx["duration"],
                                       "initial_provider": ctx["ai_mode"], "initial_model": ctx["ai_model"],
                                       "initial_voice": ctx.get("voice") or "silent", "initial_video": "off",
                                       "news_usage": ctx.get("news_usage"),
                                   }, "external_consent": ctx.get("external_consent", False),
                                   "consented_at": ctx.get("consented_at"),
                                   "news_method": ("synthetic_rss" if ctx["source"] == "sample" else
                                                   "ai_web+rss" if ctx.get("acquisition_policy") == "hybrid" else
                                                   "ai_web" if ctx.get("acquisition_policy") == "ai_web" else "rss")}
        return remember

    @contextmanager
    def _ai_service(self, mode: str, cancel: Event):
        """Use operation-owned CLI adapters; cancellation must never stop another Studio job."""
        service = self.intelligence
        provider = service.api_providers.get(mode) or service.provider
        if provider is None and mode != "offline":
            if mode == "claude_code":
                from newsflow.intelligence.claude_code import ClaudeCodeProvider

                provider = ClaudeCodeProvider()
            elif mode == "codex":
                from newsflow.intelligence.codex import CodexProvider

                provider = CodexProvider()
            elif mode == "claude_api":
                provider = service._provider(mode)
            else:
                from newsflow.intelligence.provider import OpenAIProvider

                provider = OpenAIProvider(service._key, allow_retry=False)
            service = IntelligenceService(
                self.sessions, provider, key_store=service.key_store, speech=service.speech,
                api_key_stores=service.api_key_stores if service.api_managed else None,
                api_providers=service.api_providers, api_budget=service.api_budget,
            )
        done = Event()

        def monitor():
            while not done.wait(.05):
                if cancel.is_set() and provider.cancel():
                    return

        worker = Thread(target=monitor, daemon=True) if provider is not None and callable(getattr(provider, "cancel", None)) else None
        if worker:
            worker.start()
        try:
            self._cancel(cancel)
            yield service
        finally:
            done.set()
            if worker:
                worker.join(timeout=1)

    def _draft_summary(self, draft: ContentDraft, ai_mode: str) -> dict:
        speech = self._speech()
        plan = speech_plan(draft.content, draft.duration, speech.rate, speech.pause_ms)
        return {
            "content_draft_id": draft.id, "script_revision": draft.revision, "ai_mode": ai_mode,
            "review_notes": len(draft.review_notes or []),
            "speech_estimate_seconds": plan["estimated_total_seconds"], "speech_fits": plan["fits"],
        }

    def _script(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
        if ctx.get("script_method") == "local_topic_template":
            return self._topic_script(ctx, cancel, progress, save)
        ai_mode = ctx.get("ai_mode", "offline")
        if ctx.get("content_draft_id"):
            with self.sessions() as session:
                draft = session.get(ContentDraft, ctx["content_draft_id"])
                if (
                    draft
                    and draft.duration == ctx["duration"]
                    and {article["id"] for article in draft.sources["articles"]} == {ctx["article_id"]}
                ):
                    return self._draft_summary(draft, ai_mode)
            raise BackendError("저장된 대본과 선택 뉴스가 일치하지 않습니다.", retryable=False)
        analysis_id = ctx.get("analysis_run_id")
        script_id = ctx.get("script_run_id")
        with self.sessions() as session:
            if script_id:
                completed = session.scalar(select(ContentDraft).where(ContentDraft.run_id == script_id))
                if completed:
                    if completed.duration != ctx["duration"] or {
                        a["id"] for a in completed.sources["articles"]
                    } != {ctx["article_id"]}:
                        raise BackendError("대본과 선택 뉴스가 일치하지 않습니다.", retryable=False)
                    save("content_draft_id", completed.id)
                    return self._draft_summary(completed, ai_mode)
                run = session.get(IntelligenceRun, script_id)
                if run is None:
                    raise BackendError("저장된 대본 작업 이력을 찾지 못했습니다.", retryable=False)
                if run.status == "running":
                    raise BackendError("이전 대본 작업의 완료를 확인하지 못했습니다.", retryable=False, outcome_unknown=True)
                if ai_mode != "offline":
                    raise BackendError(code="ai_request_stopped", retryable=False)
            if analysis_id:
                run = session.get(IntelligenceRun, analysis_id)
                if run is None:
                    raise BackendError("저장된 분석 이력을 찾지 못했습니다.", retryable=False)
                if run.status in {"failed", "interrupted"}:
                    if ai_mode != "offline":
                        raise BackendError(code="ai_request_stopped", retryable=False,
                                           outcome_unknown=run.status == "interrupted")
                    analysis_id = None
                elif (
                    run.kind != "analysis"
                    or run.provider != ai_mode
                    or (ctx["article_id"] not in {a["id"] for a in run.evidence["articles"]}
                        if ctx.get("unified") else {a["id"] for a in run.evidence["articles"]} != {ctx["article_id"]})
                ):
                    raise BackendError("분석 이력과 선택 뉴스가 일치하지 않습니다.", retryable=False)
                elif run.status != "success":
                    raise BackendError("이전 분석 작업의 완료를 확인하지 못했습니다.", retryable=False, outcome_unknown=True)
        ai_mode = self._ai_mode(ctx)
        speech = self._speech()
        self.intelligence.speech = {"rate": speech.rate, "pause_ms": speech.pause_ms}
        # External calls honour the saved model/timeout and reserve output tokens per script length;
        # offline keeps the service defaults (no request is made).
        analysis_options = self._options(ctx, ANALYSIS_MAX_TOKENS)
        script_options = self._options(ctx, max_tokens_for(ctx["duration"]))
        # consent=True only ever reaches the service for a gated real-content job (see _ai_mode).
        try:
            with self._ai_service(ai_mode, cancel) as service:
                if analysis_id is None:
                    analysis_id = service.analyze(
                        [ctx["article_id"]],
                        mode=ai_mode,
                        consent=ai_mode != "offline",
                        options=analysis_options,
                        on_run=self._remember(ctx, "analysis_run_id", save),
                    )
                self._cancel(cancel)
                progress(
                    50,
                    "선택한 AI로 뉴스 대본을 만들고 있어요." if ai_mode != "offline" else "선택한 뉴스로 검토용 대본을 만들고 있어요.",
                )
                draft_id = service.generate(
                    analysis_id,
                    ctx["duration"],
                    mode=ai_mode,
                    consent=ai_mode != "offline",
                    options=script_options,
                    on_run=self._remember(ctx, "script_run_id", save),
                    **({"article_ids": [ctx["article_id"]]} if ctx.get("unified") else {}),
                )
        except IntelligenceError as exc:
            raise self._ai_failure(exc, external=ai_mode != "offline") from None
        save("content_draft_id", draft_id)
        self._cancel(cancel)
        with self.sessions() as session:
            draft = session.get(ContentDraft, draft_id)
            return {**self._draft_summary(draft, ai_mode), "analysis_run_id": analysis_id,
                    "script_provider": ai_mode, "ai_model": ctx.get("ai_model")}

    def _topic_script(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
        draft_id = ctx.get("content_draft_id")
        with self.sessions() as session:
            if not draft_id and ctx.get("script_run_id"):
                draft_id = session.scalar(select(ContentDraft.id).where(ContentDraft.run_id == ctx["script_run_id"]))
                if not draft_id:
                    raise BackendError(code="ai_request_stopped", retryable=False)
        self._cancel(cancel)
        if draft_id is None:
            try:
                draft_id = self.intelligence.generate_topic(
                    ctx["analysis_run_id"], ctx["duration"], ctx["news_usage"],
                    article_ids=[ctx["article_id"]], on_run=self._remember(ctx, "script_run_id", save),
                )
            except IntelligenceError:
                raise BackendError(code="news_usage_script", retryable=False) from None
        with self.sessions() as session:
            draft = session.get(ContentDraft, draft_id)
            if (not draft or draft.duration != ctx["duration"]
                    or {a["id"] for a in draft.sources["articles"]} != {ctx["article_id"]}
                    or draft.sources.get("news_usage") != ctx["news_usage"]):
                raise BackendError(code="news_usage_script", retryable=False)
            self._check_topic_draft(draft)
            result = {**self._draft_summary(draft, ctx.get("ai_mode", "offline")),
                      "analysis_run_id": ctx["analysis_run_id"], "script_run_id": draft.run_id,
                      "script_provider": "local_topic_template", "script_method": "local_topic_template",
                      "news_usage_result": draft.sources["news_usage_result"]}
        save("content_draft_id", draft_id)
        progress(100, "주제 설명 대본을 준비했어요. 추가 AI 호출 없이 만들었으며 검토가 필요해요.")
        return result

    @staticmethod
    def _check_topic_draft(draft: ContentDraft) -> None:
        try:
            IntelligenceService.check_news_usage(draft.content, draft.sources)
        except IntelligenceError:
            raise BackendError(code="news_usage_script", retryable=False) from None

    def _render(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
        with self.sessions() as session:
            draft = session.get(ContentDraft, ctx["content_draft_id"])
            if not draft:
                raise BackendError(code="news_usage_script", retryable=False)
            self._check_topic_draft(draft)
        identifier = ctx.get("render_job_id")
        if identifier:
            with self.sessions() as session:
                previous = session.get(RenderJob, identifier)
                project = session.get(VideoProject, previous.project_id) if previous else None
                draft = session.get(ContentDraft, ctx["content_draft_id"])
                if (
                    not project
                    or not draft
                    or project.draft_id != draft.id
                    or not project.preview_only
                    or project.duration != ctx["duration"]
                    or project.snapshot.get("draft_revision") != draft.revision
                ):
                    raise BackendError("영상 작업과 대본이 일치하지 않습니다.", retryable=False)
                if previous.status in {"failed", "interrupted"}:
                    identifier = None
        if identifier is None:
            self._cancel(cancel)
            voice = self._voice(ctx)
            try:
                identifier = self.video.start_preview(
                    ctx["content_draft_id"], ctx["duration"], lambda value: save("render_job_id", value),
                    voice=voice, speech=self._speech(),
                )
            except VideoError as exc:
                if "음성 목록" in str(exc):
                    raise BackendError(str(exc), code="voice_unavailable") from None
                raise
        deadline = time.monotonic() + 1200
        while True:
            if cancel.is_set():
                self.video.request_cancel(identifier)
                self._cancel(cancel)
            with self.sessions() as session:
                job = session.get(RenderJob, identifier)
                if job.status == "success":
                    save("video_project_id", job.project_id)
                    metadata = job.metadata_json or {}
                    return {
                        "render_job_id": identifier,
                        "video_project_id": job.project_id,
                        "output_name": job.output_name,
                        "preview_only": True,
                        "audio": metadata.get("audio", "silent"),
                        "audio_fit": bool(metadata.get("audio_fit")),
                    }
                if job.status == "simulated":
                    raise BackendError(
                        "모의 영상은 재생할 수 없어 게시 대기함에 넣지 않습니다.", retryable=False
                    )
                if job.status != "running":
                    # The video service prefixes its fixed failure text with the failure kind;
                    # the generic suffix mentions several causes, so only the prefix is classified.
                    if (job.message or "").startswith("음성 길이 실패"):
                        raise BackendError("음성이 장면 또는 영상 길이보다 길어 영상을 만들지 못했습니다.", code="speech_too_long")
                    if (job.message or "").startswith("음성 생성 실패"):
                        raise BackendError(
                            "음성을 만들지 못했습니다. 선택한 한국어 음성과 PowerShell 실행 상태를 확인하세요.", code="voice_failed",
                        )
                    raise BackendError(
                        "영상 제작이 중단되었습니다. 제작 도구와 저장 공간을 확인하고 다시 시도하세요."
                    )
                progress(job.progress, "검토용 영상을 만들고 있어요.")
            if time.monotonic() >= deadline:
                self.video.request_cancel(identifier)
                raise BackendError(
                    "영상 제작 완료를 확인하지 못했습니다. 제작 이력을 확인하세요.", outcome_unknown=True
                )
            cancel.wait(0.1)

    def _voice(self, ctx: dict) -> str:
        """Job voice or the saved default; a missing installed voice fails instead of substituting."""
        from newsflow.easy_setup import preview_preferences

        voice = ctx.get("voice") or preview_preferences(self.sessions)[0]
        if not self.video.voice_available(voice):
            raise BackendError("선택한 음성을 찾지 못했습니다.", code="voice_unavailable")
        return voice

    def _validate(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
        with self.sessions() as session:
            job = session.get(RenderJob, ctx["render_job_id"])
            if job is None:
                raise BackendError("영상 결과를 찾지 못했습니다.", retryable=False)
            project = session.get(VideoProject, job.project_id)
            draft = session.get(ContentDraft, ctx["content_draft_id"])
            if (
                not project
                or not draft
                or project.draft_id != draft.id
                or not project.preview_only
                or project.duration != ctx["duration"]
                or project.snapshot.get("draft_revision") != draft.revision
            ):
                raise BackendError("영상과 대본 연결을 확인할 수 없습니다.", retryable=False)
            path = self.publishing.media_path(job)
        before = hash_file(path)
        metadata = self.inspector.inspect(path)
        after = hash_file(path)
        duration = float(metadata.get("duration", 0))
        if not (
            before == after
            and metadata.get("playable") is True
            and "mp4" in metadata.get("format", "")
            and 23 <= float(metadata.get("fps", 0)) <= 60
            and metadata.get("video_codec") == "h264"
            and metadata.get("audio_codec") == "aac"
            and metadata.get("width") == 1080
            and metadata.get("height") == 1920
            and math.isfinite(duration)
            and abs(duration - ctx["duration"]) <= 0.25
        ):
            raise BackendError("영상 규격 또는 파일 무결성을 확인하지 못했습니다.", retryable=False)
        self._cancel(cancel)
        with self.sessions() as session:
            render = session.get(RenderJob, ctx["render_job_id"])
            audio = (render.metadata_json or {}).get("audio", "silent") if render else "silent"
        progress(100, "영상 파일 확인을 마쳤어요. 내용 검토가 필요해요.")
        return {
            "media_sha256": before,
            "media_metadata": metadata,
            "output_name": path.name,
            "preview_only": True,
            "human_review_required": True,
            "audio": audio,
            "watch_quality": "NOT VERIFIED",
        }

    def _queue(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
        self._cancel(cancel)
        # Recheck the actual bytes at the boundary, even when retrying after restart.
        checked = self._validate(ctx, cancel, progress, save)
        if not ctx.get("media_sha256") or checked["media_sha256"] != ctx["media_sha256"]:
            raise BackendError("검사 후 영상 파일이 바뀌었습니다. 다시 확인하세요.", retryable=False)
        with self.sessions() as session:
            draft = session.get(ContentDraft, ctx["content_draft_id"])
            title = draft.content["title"]
            description = (
                "검토용 초안입니다. 출처·내용·저작권을 사람이 확인해야 합니다.\n" + draft.content["summary"]
            )
            if ctx["source"] == "sample":
                description = "체험용 합성 뉴스 · 실제 보도 아님\n" + description
            elif ctx.get("ai_mode", "offline") != "offline":
                description = "외부 AI 초안 · 사실 확인 미완료\n" + description
            if ctx.get("audio") == "silent":
                description += "\n무음 검토영상 · 음성 없음"
        identifier = self.publishing.create(
            ctx["render_job_id"],
            ctx["platform"],
            title,
            description,
            "뉴스 검토용",
            content_reviewed=False,
            copyright_confirmed=False,
            sources_confirmed=False,
            ai_disclosure="unreviewed",
            autopilot_task_id=str(ctx["job_id"]),
        )
        save("publish_draft_id", identifier)
        validation_id = self.publishing.validate(identifier)
        with self.sessions() as session:
            draft = session.get(PublishDraft, identifier)
            validation = session.get(PublishValidation, validation_id)
            checks = {item["key"]: item["status"] for item in validation.results}
            if checks.get("media") != "pass" or checks.get("video_profile") != "pass":
                raise BackendError("대기함 영상 검증을 마치지 못했습니다. 파일을 다시 확인하세요.")
            if (
                draft.state != "blocked"
                or draft.media_sha256 != ctx["media_sha256"]
                or draft.render_job_id != ctx["render_job_id"]
                or draft.autopilot_task_id != ctx["job_id"]
                or draft.account_id is not None
                or any(
                    (
                        draft.content_reviewed,
                        draft.copyright_confirmed,
                        draft.sources_confirmed,
                    )
                )
            ):
                raise BackendError("게시 초안 검토 상태를 확인할 수 없습니다.", retryable=False)
        progress(100, "게시 대기함에 보관했어요. 게시 전 사람의 검토가 필요해요.")
        return {
            "publish_draft_id": identifier,
            "publish_validation_id": validation_id,
            "queue_state": "review_required",
            "external_publishing_enabled": False,
        }
