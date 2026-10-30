"""Explicit, reversible local removal. Never erase provider/audit/approval history."""
import hashlib
import re

from fastapi import APIRouter, Form, HTTPException, Request
from filelock import FileLock, Timeout
from sqlalchemy import select

from newsflow.db.models import (
    AutopilotArtifact,
    AutopilotJob,
    IntelligenceRun,
    PublishDraft,
    RenderJob,
    VideoProject,
    WorkspaceRemoval,
)
from newsflow.news.lifecycle import remember_video_sources
from newsflow.publishing.service import PublishingError, PublishingService

from .routes import go, page
from .task_views import task_rows

router = APIRouter()


def _library_visibility(request, items, confirm, *, hidden):
    from newsflow.studio.library_visibility import LibraryVisibility, LibraryVisibilityError
    if not confirm:
        raise HTTPException(422, "선택한 콘텐츠를 확인해 주세요.")
    try:
        return LibraryVisibility(request.app.state.sessions, request.app.state.character).change(items, hidden=hidden)
    except LibraryVisibilityError as error:
        status, message = {
            'invalid': (422, '선택한 콘텐츠를 확인해 주세요.'),
            'missing': (404, '콘텐츠를 찾지 못했습니다.'),
            'busy': (409, '진행 중인 콘텐츠는 완료 후 삭제해 주세요.'),
        }[str(error)]
        raise HTTPException(status, message) from None


@router.post('/api/studio/library/remove')
def library_remove(request: Request, items: str = Form(max_length=10000), confirm: bool = Form(False)):
    return _library_visibility(request, items, confirm, hidden=True)


@router.post('/api/studio/library/restore')
def library_restore(request: Request, items: str = Form(max_length=10000), confirm: bool = Form(False)):
    return _library_visibility(request, items, confirm, hidden=False)


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@router.get("/workspace/trash")
def trash(request: Request):
    with request.app.state.sessions() as session:
        rows = list(session.scalars(select(WorkspaceRemoval).where(
            ~WorkspaceRemoval.key.startswith('library:')).order_by(WorkspaceRemoval.created_at.desc())))
        return page(request, "workspace_trash.html", active="videos", removed=rows)


@router.post("/workspace/activity/remove")
def remove_activity(request: Request, item: str = Form(max_length=70), confirm: bool = Form(False)):
    if not confirm:
        raise HTTPException(422, "삭제할 활동을 확인해 주세요.")
    key = "activity:" + item
    with request.app.state.sessions() as session:
        if session.get(WorkspaceRemoval, key):
            return go("/#workspace-tasks")
    row = next((row for row in task_rows(request) if row["id"] == item), None)
    if row is None:
        raise HTTPException(404, "활동을 찾지 못했습니다.")
    if not row["can_remove"]:
        raise HTTPException(409, "진행·검토 중인 자동 작업은 먼저 기존 화면에서 정상 취소해 주세요.")
    with request.app.state.sessions.begin() as session:
        # Recheck actual work, not just a stale card.
        auto = session.get(AutopilotJob, row["task_id"]) if row.get("task_id") else None
        render = session.get(RenderJob, row["render_job_id"]) if row.get("render_job_id") else None
        runs = list(session.scalars(select(IntelligenceRun).where(IntelligenceRun.id.in_(
            [value for value in (row.get("analysis_run_id"), row.get("script_run_id")) if value]))))
        if (auto and auto.status in {"queued", "running", "waiting_review"} or render and render.status == "running"
                or any(run.status == "running" for run in runs)):
            raise HTTPException(409, "진행 중인 작업은 삭제할 수 없습니다.")
        if not session.get(WorkspaceRemoval, key):
            session.add(WorkspaceRemoval(key=key, detail={"title": row["title"], "state": "hidden"}))
    return go("/#workspace-tasks")


@router.post("/workspace/videos/{identifier}/remove")
def remove_video(request: Request, identifier: int, confirm: bool = Form(False)):
    if not confirm:
        raise HTTPException(422, "삭제할 영상을 확인해 주세요.")
    sessions, video = request.app.state.sessions, request.app.state.video
    key = f"video:{identifier}"
    try:
        with FileLock(str(video.root / "workspace-cleanup.lock")).acquire(timeout=0):
            with sessions.begin() as session:
                if session.get(WorkspaceRemoval, key):
                    return go("/workspace/trash")
                job = session.get(RenderJob, identifier)
                if job is None:
                    raise HTTPException(404, "영상을 찾지 못했습니다.")
                # A prepared/past publication keeps its media and independent history intact.
                linked = session.scalar(select(PublishDraft.id).where(PublishDraft.render_job_id == identifier))
                active = session.scalar(select(AutopilotJob.id).join(
                    AutopilotArtifact, AutopilotArtifact.job_id == AutopilotJob.id).where(
                    AutopilotArtifact.kind == "render_job_id", AutopilotArtifact.reference == str(identifier),
                    AutopilotJob.status.in_(["queued", "running", "waiting_review"])))
                if linked or active or job.status == "running":
                    raise HTTPException(409, "진행·검토 중이거나 게시 기록에 연결된 영상은 삭제할 수 없습니다.")
                try:
                    source = PublishingService(sessions, video.outputs).media_path(job)
                except PublishingError:
                    raise HTTPException(409, "영상 파일 상태를 확인해 주세요. 파일을 임의로 삭제하지 않았습니다.") from None
                remember_video_sources(session)
                title = session.get(VideoProject, job.project_id).title
                digest = file_digest(source)
                # Durable tombstone precedes move: crash/unknown never makes this publishable again.
                session.add(WorkspaceRemoval(key=key, detail={"title": title, "state": "pending",
                            "output_name": source.name, "sha256": digest}))
            destination = video.root / "trash/videos" / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.parent.is_symlink() or destination.exists() or not destination.resolve().is_relative_to(video.root.resolve()):
                raise HTTPException(409, "휴지 보관 경로를 확인해 주세요. 자동 재시도하지 않습니다.")
            try:
                source.rename(destination)
            except OSError:
                raise HTTPException(409, "영상이 사용 중이거나 이동에 실패했습니다. 기록을 보존했으며 자동 재시도하지 않습니다.") from None
            with sessions.begin() as session:
                row = session.get(WorkspaceRemoval, key)
                row.detail = {**row.detail, "state": "trashed"}
    except Timeout:
        raise HTTPException(409, "다른 정리 작업이 진행 중입니다.") from None
    return go("/videos")


@router.post("/workspace/trash/restore")
def restore(request: Request, item: str = Form(max_length=80), confirm: bool = Form(False)):
    if not confirm:
        raise HTTPException(422, "복원할 항목을 확인해 주세요.")
    video, sessions = request.app.state.video, request.app.state.sessions
    try:
        with FileLock(str(video.root / "workspace-cleanup.lock")).acquire(timeout=0), sessions.begin() as session:
            row = session.get(WorkspaceRemoval, item)
            if row is None:
                raise HTTPException(404, "보관된 항목이 없습니다.")
            if item.startswith("video:"):
                detail = row.detail
                name = detail.get("output_name", "")
                if detail.get("state") != "trashed" or not re.fullmatch(r"video-[a-f0-9]{32}\.mp4", name):
                    raise HTTPException(409, "이동 결과 확인이 필요한 항목입니다. 자동 복원하지 않습니다.")
                source, target = video.root / "trash/videos" / name, video.outputs / name
                if (source.is_symlink() or not source.resolve().is_relative_to(video.root.resolve())
                        or not source.is_file() or target.exists()
                        or file_digest(source) != detail["sha256"]):
                    raise HTTPException(409, "영상 파일의 무결성·경로를 확인하지 못했습니다.")
                try:
                    source.rename(target)
                except OSError:
                    raise HTTPException(409, "파일 복원에 실패했습니다. 휴지 보관 기록과 파일을 유지합니다.") from None
            elif not item.startswith("activity:"):
                raise HTTPException(422, "복원 항목을 확인해 주세요.")
            session.delete(row)
    except Timeout:
        raise HTTPException(409, "다른 정리 작업이 진행 중입니다.") from None
    return go("/workspace/trash")
