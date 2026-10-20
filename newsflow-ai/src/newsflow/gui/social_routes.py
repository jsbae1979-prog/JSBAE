"""Local calendar and read-only analytics pages; GET never contacts a provider."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy import select

from newsflow.db.models import PlatformAccount, PublishJob, SocialMetricRun
from newsflow.publishing.calendar import local_time
from newsflow.publishing.platforms import LABELS, REQUIREMENTS
from newsflow.publishing.service import PublishingError

from .routes import go, page

router = APIRouter()

_GUIDES = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok"}


@router.get("/guides/platforms")
def platform_guide_index(request: Request):
    return page(request, "platform_guide.html", active="simple-settings", guides=_GUIDES, platform=None)


@router.get("/guides/platforms/{platform}")
def platform_guide(request: Request, platform: str):
    if platform not in _GUIDES:
        raise HTTPException(404, "지원하는 플랫폼 가이드를 선택하세요.")
    return page(request, "platform_guide.html", active="simple-settings", guides=_GUIDES, platform=platform)


@router.get("/analytics")
def analytics(request: Request, platform: str = "youtube", account: str = ""):
    if account and (not account.isdigit() or int(account) <= 0):
        raise HTTPException(422, "계정을 선택하세요.")
    account_id = int(account) if account else None
    try:
        data = request.app.state.social_analytics.dashboard(platform=platform, account_id=account_id)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    with request.app.state.sessions() as session:
        accounts = list(session.scalars(select(PlatformAccount).where(PlatformAccount.platform == platform)))
        jobs = list(
            session.scalars(
                select(PublishJob)
                .where(
                    PublishJob.platform == platform,
                    PublishJob.status.in_({"uploaded", "ig_published", "ig_published_no_link"}),
                )
                .order_by(PublishJob.id.desc())
                .limit(100)
            )
        )
        runs = list(session.scalars(select(SocialMetricRun).order_by(SocialMetricRun.id.desc()).limit(10)))
    return page(
        request,
        "analytics.html",
        active="activity",
        data=data,
        labels=LABELS,
        accounts=accounts,
        jobs=jobs,
        runs=runs,
    )


@router.post("/analytics/collect")
def collect(
    request: Request,
    start: Annotated[date, Form()],
    end: Annotated[date, Form()],
    job_id: int = Form(ge=1),
    consent: bool = Form(False),
):
    try:
        request.app.state.social_analytics.collect(job_id, start, end, consent=consent)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    return go("/analytics")


@router.get("/publishing/platforms")
def platforms(request: Request):
    return page(
        request,
        "platform_connections.html",
        active="settings",
        labels=LABELS,
        requirements=REQUIREMENTS,
        tiktok=request.app.state.tiktok.status(),
        states={p: s.status() for p, s in request.app.state.social_extensions.items()},
    )


@router.post("/publishing/calendar")
def schedule(
    request: Request,
    cohort_id: int = Form(ge=1),
    due: str = Form(max_length=30),
    revision: int | None = Form(None, ge=1),
):
    try:
        request.app.state.publishing_calendar.save(cohort_id, local_time(due), revision=revision)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    return go("/queue#publishing-calendar")


@router.post("/publishing/calendar/{identifier}/cancel")
def cancel(request: Request, identifier: int, revision: int = Form(ge=1)):
    try:
        request.app.state.publishing_calendar.cancel(identifier, revision)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    return go("/queue#publishing-calendar")


@router.get("/publishing/calendar/{identifier}")
def schedule_detail(request: Request, identifier: int):
    from newsflow.db.models import PublishSchedule
    from newsflow.publishing.calendar import KST

    with request.app.state.sessions() as session:
        item = session.get(PublishSchedule, identifier)
    if not item:
        raise HTTPException(404, "게시 일정을 찾지 못했습니다.")
    cohort = request.app.state.unified_publishing.get(item.cohort_id)
    return page(
        request,
        "publish_schedule.html",
        active="queue",
        item=item,
        cohort=cohort,
        due=item.due_at.astimezone(KST).strftime("%Y-%m-%dT%H:%M"),
    )
