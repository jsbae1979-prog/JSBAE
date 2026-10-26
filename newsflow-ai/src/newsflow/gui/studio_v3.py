"""Read-only Studio v3 projection. No provider sync, credential decode or state mutation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from hashlib import sha256
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from newsflow.db.models import (
    RenderJob,
    VideoProject,
    ContentDraft,
    IntelligenceRun,
    PublishDraft,
    ProductionSchedule,
    PublishSchedule,
    WorkspaceRemoval,
)
from newsflow.publishing.service import PublishingError, PublishingService

router = APIRouter()
ACTIVE = {"running", "queued", "submitting", "waiting", "in_progress", "downloading", "composing"}
COMPLETE = {"success", "completed", "ready"}


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def _project(identifier, title, kind, status, at, href, *, thumb=None, media=None, review="review_required"):
    return dict(
        id=identifier,
        title=str(title)[:150],
        kind=kind,
        technicalStatus=status,
        contentReviewStatus=review,
        publishApprovalStatus="separate_approval_required",
        updatedAt=_iso(at),
        href=href,
        thumbnailUrl=thumb,
        mediaUrl=media,
        sourceLabel="저장된 로컬 제작 자료",
    )


@router.get("/api/studio/workspace")
def workspace(request: Request):
    import os

    state = request.app.state
    projects = []
    now = datetime.now(UTC)
    with state.sessions() as session:
        removed = {x.key for x in session.scalars(select(WorkspaceRemoval))}
        renders = list(
            session.execute(
                select(RenderJob, VideoProject, ContentDraft)
                .join(VideoProject, RenderJob.project_id == VideoProject.id)
                .join(ContentDraft, VideoProject.draft_id == ContentDraft.id)
                .order_by(RenderJob.id.desc())
            )
        )
        images = list(
            session.scalars(
                select(IntelligenceRun)
                .where(IntelligenceRun.kind == "image_draft")
                .order_by(IntelligenceRun.id.desc())
            )
        )
        for job, project, draft in renders:
            if f"video:{job.id}" in removed:
                continue
            status = job.status
            media = thumb = None
            if status == "success":
                try:
                    path = PublishingService(state.sessions, state.video.outputs).media_path(job)
                except (PublishingError, OSError, ValueError):
                    path = None
                if path is not None:
                    media = f"/video/jobs/{job.id}/file"
                    thumb = f"/video/jobs/{job.id}/thumbnail"
                else:
                    status = "missing"
            projects.append(
                _project(
                    f"news:{job.id}",
                    project.title,
                    "news",
                    status,
                    job.finished_at or job.created_at,
                    f"/video?job_id={job.id}",
                    media=media,
                    thumb=thumb,
                    review=draft.review_status,
                )
            )
        for image in images:
            status = image.status
            url = None
            if status == "success":
                try:
                    state.image_generation.path(image.id)
                    url = f"/image-studio/{image.id}/file"
                except (PublishingError, ValueError, OSError):
                    status = "missing"
            projects.append(
                _project(
                    f"image:{image.id}",
                    image.options.get("prompt", "이미지 초안"),
                    "image",
                    status,
                    image.finished_at or image.created_at,
                    f"/image-studio?draft_id={image.id}",
                    thumb=url,
                    media=url,
                )
            )
        schedules = [
            dict(title=x.name, at=_iso(x.next_run_at), href="/schedule")
            for x in session.scalars(
                select(ProductionSchedule)
                .where(ProductionSchedule.status == "active", ProductionSchedule.next_run_at >= now)
                .order_by(ProductionSchedule.next_run_at)
                .limit(5)
            )
        ]
        schedules += [
            dict(title="게시 예약 #" + str(x.id), at=_iso(x.due_at), href="/publishing/calendar")
            for x in session.scalars(
                select(PublishSchedule)
                .where(PublishSchedule.status == "active", PublishSchedule.due_at >= now)
                .order_by(PublishSchedule.due_at)
                .limit(5)
            )
        ]
        publish_count = session.scalar(select(func.count(PublishDraft.id))) or 0
    for job in state.character.listing():
        status = job["state"]
        url = None
        if status == "completed":
            try:
                path = state.character.folder(job["id"]) / "final.mp4"
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or sha256(path.read_bytes()).hexdigest() != job["output"]["sha256"]
                ):
                    status = "missing"
                else:
                    url = f"/character/{job['id']}/file"
            except (OSError, KeyError, ValueError):
                status = "missing"
        projects.append(
            _project(
                "character:" + job["id"],
                job.get("topic", "캐릭터 쇼츠"),
                "character",
                status,
                job.get("created_at"),
                "/character?job_id=" + job["id"],
                media=url,
            )
        )
    projects.sort(key=lambda x: x["updatedAt"], reverse=True)
    synthetic = getattr(state, "studio_synthetic", False)
    if synthetic:
        # Design illustration only; never used as a real production media fallback.
        for i, item in enumerate(projects):
            item["thumbnailUrl"] = "/studio/assets/design-art-" + str([2, 0, 3, 10][i % 4]) + ".webp"
            item["sourceLabel"] = "개발용 합성 프로젝트의 설계 일러스트"
    completed = sum(p["technicalStatus"] in COMPLETE for p in projects)
    running = sum(p["technicalStatus"] in ACTIVE for p in projects)
    kst = now + timedelta(hours=9)
    today = []
    for p in projects:
        try:
            at = datetime.fromisoformat(p["updatedAt"])
            at = at.replace(tzinfo=UTC) if at.tzinfo is None else at
            if (at.astimezone(UTC) + timedelta(hours=9)).date() == kst.date():
                today.append(p)
        except (ValueError, TypeError):
            pass
    daily = {k: 0 for k in ["done", "running", "waiting", "failed", "unknown"]}
    for p in today:
        status = p["technicalStatus"]
        key = (
            "done"
            if status in COMPLETE
            else "running"
            if status in ACTIVE
            else "failed"
            if status == "failed"
            else "unknown"
            if status == "unknown"
            else "waiting"
        )
        daily[key] += 1
    daily["total"] = len(today)
    providers = [
        ("openai", "OpenAI", getattr(state, "ai_keys", None)),
        ("claude", "Claude", getattr(state, "api_keys", {}).get("claude_api")),
        ("elevenlabs", "ElevenLabs", None),
        ("higgsfield", "Higgsfield", getattr(getattr(state, "video_ai", None), "keys", None)),
    ]
    services = []
    for identifier, label, store in providers:
        configured = False
        if store is not None:
            configured = bool(store.status().get("configured"))  # metadata only; never key()
        if identifier == "elevenlabs":
            p = state.config.data_dir / "tts-elevenlabs-key.dpapi"
            configured = (p.is_file() and not p.is_symlink()) or bool(
                os.environ.get("NEWSFLOW_ELEVENLABS_KEY", "")
            )
        services.append(
            dict(id=identifier, label=label, configured=configured, verified=False, href="/settings")
        )
    return dict(
        schemaVersion=1,
        capabilities=dict(legacyAvailable=True, workspaceReadOnly=True),
        dataOrigin="development-fixtures" if synthetic else "local-workspace",
        projects=projects[:100],
        stats=dict(running=running, ready=completed, publishDrafts=publish_count, total=len(projects)),
        today=daily,
        services=services,
        upcoming=sorted(schedules, key=lambda x: x["at"])[:5],
        upcomingStatus="connected",
        activity=[
            dict(
                title=p["title"]
                + " · "
                + ("결과 불명" if p["technicalStatus"] == "unknown" else "작업 기록"),
                at=p["updatedAt"],
                href=p["href"],
            )
            for p in projects[:5]
        ],
    )


def mount_studio(app):
    """Optional static build in source development. Existing routes stay available."""
    app.include_router(router)
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        return
    app.mount(
        "/studio/assets", StaticFiles(directory=dist / "assets", follow_symlink=False), name="studio-assets"
    )

    @app.get("/studio/", include_in_schema=False)
    @app.get("/studio/dashboard", include_in_schema=False)
    @app.get("/studio/create", include_in_schema=False)
    def studio_shell():
        return FileResponse(dist / "index.html", media_type="text/html")
