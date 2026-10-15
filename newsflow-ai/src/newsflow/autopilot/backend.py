"""Offline-first integration of existing services; no OAuth or publisher execution."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

from sqlalchemy import select
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
from newsflow.intelligence.provider import OfflineProvider
from newsflow.intelligence.service import IntelligenceService
from newsflow.news.collector import Collector
from newsflow.news.rss_adapter import FakeRSSAdapter
from newsflow.news.service import CollectionCoordinator, NewsService
from newsflow.publishing.media import FFprobeMediaInspector
from newsflow.publishing.service import PublishingService, hash_file
from newsflow.video.service import VideoCoordinator

from .contracts import BackendError
from .samples import SAMPLE_NAME, SAMPLE_URL, sample_feed

Progress = Callable[[int, str], None]
SaveArtifact = Callable[[str, int | str], None]


class PipelineBackend:
    """One explicit local workflow, with synthetic RSS and offline AI as defaults.

    Injected services are for deterministic tests. Runtime never discovers an AI
    provider, account, credential or publisher from environment settings.
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
    ) -> None:
        self.sessions, self.collection, self.video = sessions, collection, video
        self.sample_collection = CollectionCoordinator(
            NewsService(sessions, Collector(FakeRSSAdapter({SAMPLE_URL: sample_feed()}))), data_dir
        )
        self.intelligence = intelligence or IntelligenceService(sessions, OfflineProvider())
        self.publishing = publishing or PublishingService(sessions, video.outputs)
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
        with self.sessions() as session:
            candidates = list(
                session.scalars(
                    select(NewsArticle.id)
                    .outerjoin(ArticleScore, ArticleScore.article_id == NewsArticle.id)
                    .where(
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
                    .limit(100)
                )
            )
        self._cancel(cancel)
        if not candidates:
            raise BackendError("제작할 뉴스가 없습니다. 다른 출처로 다시 시도하세요.")
        chosen = ctx.get("article_id") or candidates[0]
        if chosen not in candidates:
            raise BackendError("선택한 뉴스가 이번 수집 결과와 다릅니다.", retryable=False)
        progress(100, "제작할 뉴스 후보를 골랐어요.")
        return {"article_id": chosen, "candidate_article_ids": candidates}

    def _script(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
        if ctx.get("content_draft_id"):
            with self.sessions() as session:
                draft = session.get(ContentDraft, ctx["content_draft_id"])
                if (
                    draft
                    and draft.duration == ctx["duration"]
                    and {article["id"] for article in draft.sources["articles"]} == {ctx["article_id"]}
                ):
                    return {"content_draft_id": draft.id, "script_revision": draft.revision}
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
                    return {"content_draft_id": completed.id, "script_revision": completed.revision}
                run = session.get(IntelligenceRun, script_id)
                if run is None:
                    raise BackendError("저장된 대본 작업 이력을 찾지 못했습니다.", retryable=False)
                if run.status == "running":
                    raise BackendError("이전 대본 작업의 완료를 확인하지 못했습니다.", outcome_unknown=True)
            if analysis_id:
                run = session.get(IntelligenceRun, analysis_id)
                if run is None:
                    raise BackendError("저장된 분석 이력을 찾지 못했습니다.", retryable=False)
                if run.status in {"failed", "interrupted"}:
                    analysis_id = None
                elif (
                    run.kind != "analysis"
                    or run.provider != "offline"
                    or {a["id"] for a in run.evidence["articles"]} != {ctx["article_id"]}
                ):
                    raise BackendError("분석 이력과 선택 뉴스가 일치하지 않습니다.", retryable=False)
                elif run.status != "success":
                    raise BackendError("이전 분석 작업의 완료를 확인하지 못했습니다.", outcome_unknown=True)
        if analysis_id is None:
            analysis_id = self.intelligence.analyze(
                [ctx["article_id"]],
                mode="offline",
                consent=False,
                on_run=lambda value: save("analysis_run_id", value),
            )
        self._cancel(cancel)
        progress(50, "선택한 뉴스로 검토용 대본을 만들고 있어요.")
        draft_id = self.intelligence.generate(
            analysis_id,
            ctx["duration"],
            mode="offline",
            consent=False,
            on_run=lambda value: save("script_run_id", value),
        )
        save("content_draft_id", draft_id)
        self._cancel(cancel)
        return {"content_draft_id": draft_id, "script_revision": 1, "ai_mode": "offline"}

    def _render(self, ctx: dict, cancel: Event, progress: Progress, save: SaveArtifact) -> dict:
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
            identifier = self.video.start_preview(
                ctx["content_draft_id"], ctx["duration"], lambda value: save("render_job_id", value)
            )
        deadline = time.monotonic() + 1200
        while True:
            if cancel.is_set():
                self.video.request_cancel(identifier)
                self._cancel(cancel)
            with self.sessions() as session:
                job = session.get(RenderJob, identifier)
                if job.status == "success":
                    save("video_project_id", job.project_id)
                    return {
                        "render_job_id": identifier,
                        "video_project_id": job.project_id,
                        "output_name": job.output_name,
                        "preview_only": True,
                    }
                if job.status == "simulated":
                    raise BackendError(
                        "모의 영상은 재생할 수 없어 게시 대기함에 넣지 않습니다.", retryable=False
                    )
                if job.status != "running":
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
        progress(100, "영상 파일 확인을 마쳤어요. 내용 검토가 필요해요.")
        return {
            "media_sha256": before,
            "media_metadata": metadata,
            "output_name": path.name,
            "preview_only": True,
            "human_review_required": True,
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
