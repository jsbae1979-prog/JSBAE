"""Publishing preparation routes; no OAuth or external publishing operation."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from newsflow.db.models import (
    PlatformAccount,
    PublishAttempt,
    PublishDraft,
    PublishJob,
    PublishValidation,
    RenderJob,
    VideoProject,
)
from newsflow.publishing.service import ConflictError, PublishingError, PublishingService

from .routes import go, page

router = APIRouter()


def service(request: Request) -> PublishingService:
    return PublishingService(request.app.state.sessions, request.app.state.video.outputs)


def account_identifier(value: str) -> int | None:
    """Empty selection means no account; identifiers are local metadata references."""
    if not value:
        return None
    try:
        identifier = int(value)
    except ValueError:
        raise HTTPException(422, "대상 계정 선택을 확인하세요.") from None
    if identifier < 1:
        raise HTTPException(422, "대상 계정 선택을 확인하세요.")
    return identifier


@router.get("/publishing", response_class=HTMLResponse)
def studio(
    request: Request,
    draft_id: int | None = Query(None, ge=1),
    render_job_id: int | None = Query(None, ge=1),
) -> HTMLResponse:
    with request.app.state.sessions() as session:
        draft = session.get(PublishDraft, draft_id) if draft_id else None
        if draft_id and not draft:
            raise HTTPException(404, "게시 초안을 찾지 못했습니다.")
        selected_job_id = draft.render_job_id if draft else render_job_id
        job = session.get(RenderJob, selected_job_id) if selected_job_id else None
        if selected_job_id and not job:
            raise HTTPException(404, "영상 작업을 찾지 못했습니다.")
        project = session.get(VideoProject, job.project_id) if job else None
        videos = [
            (video, video_project)
            for video, video_project in session.execute(
                select(RenderJob, VideoProject)
                .join(VideoProject, RenderJob.project_id == VideoProject.id)
                .where(RenderJob.status == "success")
                .order_by(RenderJob.id.desc())
                .limit(100)
            )
            if video.metadata_json.get("playable")
        ]
        validations = (
            list(
                session.scalars(
                    select(PublishValidation)
                    .where(PublishValidation.draft_id == draft.id)
                    .order_by(PublishValidation.id.desc())
                    .limit(10)
                )
            )
            if draft
            else []
        )
        jobs = list(session.scalars(select(PublishJob).order_by(PublishJob.id.desc()).limit(30)))
        attempts = list(session.scalars(select(PublishAttempt).order_by(PublishAttempt.id.desc()).limit(30)))
        return page(
            request,
            "publishing.html",
            active="publishing",
            draft=draft,
            job=job,
            project=project,
            videos=videos,
            accounts=list(session.scalars(select(PlatformAccount).order_by(PlatformAccount.id.desc()))),
            drafts=list(session.scalars(select(PublishDraft).order_by(PublishDraft.id.desc()).limit(30))),
            validations=validations,
            validation=validations[0] if validations else None,
            jobs=jobs,
            attempts=attempts,
        )


@router.post("/publishing/drafts")
def create(
    request: Request,
    render_job_id: int = Form(ge=1),
    platform: str = Form(),
    title: str = Form(),
    description: str = Form(""),
    hashtags: str = Form(""),
    account_id: str = Form(""),
    content_reviewed: bool = Form(False),
    copyright_confirmed: bool = Form(False),
    sources_confirmed: bool = Form(False),
    ai_disclosure: str = Form("unreviewed"),
) -> RedirectResponse:
    try:
        identifier = service(request).create(
            render_job_id=render_job_id,
            platform=platform,
            title=title,
            description=description,
            hashtags=hashtags,
            account_id=account_identifier(account_id),
            content_reviewed=content_reviewed,
            copyright_confirmed=copyright_confirmed,
            sources_confirmed=sources_confirmed,
            ai_disclosure=ai_disclosure,
        )
    except PublishingError as exc:
        raise HTTPException(422, str(exc)) from None
    return go(f"/publishing?draft_id={identifier}")


@router.post("/publishing/drafts/{draft_id}")
def edit(
    request: Request,
    draft_id: int,
    revision: int = Form(ge=1),
    platform: str = Form(),
    title: str = Form(),
    description: str = Form(""),
    hashtags: str = Form(""),
    account_id: str = Form(""),
    content_reviewed: bool = Form(False),
    copyright_confirmed: bool = Form(False),
    sources_confirmed: bool = Form(False),
    ai_disclosure: str = Form("unreviewed"),
) -> RedirectResponse:
    try:
        service(request).edit(
            draft_id=draft_id,
            revision=revision,
            platform=platform,
            title=title,
            description=description,
            hashtags=hashtags,
            account_id=account_identifier(account_id),
            content_reviewed=content_reviewed,
            copyright_confirmed=copyright_confirmed,
            sources_confirmed=sources_confirmed,
            ai_disclosure=ai_disclosure,
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    except PublishingError as exc:
        raise HTTPException(422, str(exc)) from None
    return go(f"/publishing?draft_id={draft_id}")


@router.post("/publishing/drafts/{draft_id}/validate")
def validate(request: Request, draft_id: int) -> RedirectResponse:
    try:
        service(request).validate(draft_id)
    except PublishingError as exc:
        raise HTTPException(422, str(exc)) from None
    return go(f"/publishing?draft_id={draft_id}")


@router.post("/publishing/accounts")
def account(
    request: Request,
    platform: str = Form(),
    label: str = Form(),
    account_type: str = Form(),
) -> RedirectResponse:
    try:
        service(request).add_account(platform=platform, label=label, account_type=account_type)
    except PublishingError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/publishing")


@router.get("/api/publishing/safety")
def publishing_safety() -> dict:
    from newsflow.publishing.adapters import safety_status

    return safety_status()
