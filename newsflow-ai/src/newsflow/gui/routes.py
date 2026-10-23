"""Korean UI routes; no external service calls from templates."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from newsflow.db.models import (
    AppSetting,
    ArticleMention,
    ArticleScore,
    ArticleThumbnail,
    AuditLog,
    CollectionRun,
    NewsArticle,
    NewsSource,
)
from newsflow.news.ranking import CATEGORY_WORDS
from newsflow.news.rss_adapter import URLPolicyError, validate_url
from newsflow.news.service import CollectionBusy

from .navigation import navigation_context

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
KST = timezone(timedelta(hours=9), "KST")


def kst(value: datetime | None) -> str:
    """Stored times stay UTC; screens show Korea Standard Time (KST, UTC+9) by default."""
    if value is None:
        return "미확인"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")


def kst_day(value: str | None) -> str:
    """An ISO timestamp stored as text (e.g. a dated approval), shown as its KST calendar day."""
    try:
        parsed = datetime.fromisoformat(value or "")
    except ValueError:
        return ""
    return kst(parsed)[:10]


templates.env.filters["kst"] = kst
templates.env.filters["kst_day"] = kst_day

templates.env.globals["workspace_navigation"] = navigation_context


def page(request: Request, name: str, **context: object) -> HTMLResponse:
    if name in {"simple_settings.html", "ai.html", "video.html", "video_ai.html", "creator_dashboard.html", "easy_home.html", "news.html"}:
        from dataclasses import asdict

        from newsflow.shortform import choices
        from newsflow.shortform import read as shortform_settings

        profile = shortform_settings(request.app.state.sessions)
        context["shortform_settings"] = asdict(profile)
        context["shortform_durations"] = choices(profile.enabled, profile.target_seconds)
        if name == "video.html" and context.get("draft"):
            from newsflow.shortform import frozen

            draft_profile = frozen(context["draft"].sources)
            context["shortform_durations"] = choices(draft_profile.enabled, context["draft"].duration)
        if name == "ai.html" and profile.enabled and not context.get("draft") and not context.get("production_context"):
            context["selected_duration"] = profile.target_seconds
    if name in {"creator_dashboard.html", "easy_home.html", "news.html", "ai.html", "video.html"}:
        from .production_picker import selection_context

        overview = context if "production_config" in context else None
        context["production_picker"] = selection_context(request, overview)
    if name == "ai.html":
        from newsflow.intelligence.review import scene_findings

        draft = context.get("draft")
        context["scene_findings"] = scene_findings(draft.content) if draft else []
    return templates.TemplateResponse(
        request=request, name=name, context={"csrf": request.state.csrf,
        "image_selection_available": hasattr(getattr(request.app.state, "image_posts", None), "selection"),
        "image_posts_available": hasattr(request.app.state, "image_posts"), **context}
    )


def go(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    with request.app.state.sessions() as session:
        total = session.scalar(select(func.count()).select_from(NewsArticle))
        sources = session.scalar(select(func.count()).select_from(NewsSource).where(NewsSource.enabled))
        categories = session.execute(
            select(NewsArticle.category, func.count()).group_by(NewsArticle.category)
        ).all()
        latest = session.execute(
            select(NewsArticle, ArticleScore)
            .outerjoin(ArticleScore)
            .order_by(NewsArticle.collected_at.desc(), NewsArticle.id.desc())
            .limit(8)
        ).all()
        top = session.execute(
            select(NewsArticle, ArticleScore)
            .join(ArticleScore)
            .order_by(ArticleScore.total.desc(), NewsArticle.id.desc())
            .limit(10)
        ).all()
        runs = list(session.scalars(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(8)))
        return page(
            request,
            "dashboard.html",
            active="dashboard",
            total=total,
            sources=sources,
            categories=categories,
            latest=latest,
            top=top,
            runs=runs,
            last=runs[0] if runs else None,
        )


@router.get("/news", response_class=HTMLResponse)
def news(
    request: Request,
    q: str = Query("", max_length=200),
    category: str = Query("", max_length=30),
    source: str = Query("", max_length=10),
    start: str = Query("", max_length=10),
    end: str = Query("", max_length=10),
    sort: Literal["score", "newest"] = "score",
    page_number: int = Query(1, ge=1, le=100000),
    curation_id: int | None = Query(None, ge=1),
    view: Literal["current", "used"] = "current",
) -> HTMLResponse:
    from newsflow.db.models import IntelligenceRun
    from newsflow.intelligence.curation import COMPONENTS, GLOBAL_COMPONENTS, GLOBAL_PROFILE, PROFILE

    from .curation_routes import context as curation_context

    try:
        source = int(source) if source else None
        if source is not None and source < 1:
            raise ValueError
        start = date.fromisoformat(start) if start else None
        end = date.fromisoformat(end) if end else None
        if end == date.max or start == date.min:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(422, "출처 번호 또는 날짜 형식이 잘못되었습니다.") from exc
    if start and end and start > end:
        raise HTTPException(422, "시작 날짜는 종료 날짜보다 늦을 수 없습니다.")
    if category and category not in {*CATEGORY_WORDS, "미분류"}:
        raise HTTPException(422, "알 수 없는 카테고리입니다.")
    statement = select(NewsArticle, ArticleScore).outerjoin(ArticleScore)
    from newsflow.news.lifecycle import used_article_ids, visible_news

    if view == "current":
        statement = statement.where(visible_news())
    if q:
        statement = statement.where(
            or_(
                NewsArticle.title.contains(q, autoescape=True),
                NewsArticle.summary.contains(q, autoescape=True),
            )
        )
    if category:
        statement = statement.where(NewsArticle.category == category)
    if source:
        statement = statement.where(
            NewsArticle.id.in_(select(ArticleMention.article_id).where(ArticleMention.source_id == source))
        )
    if start:
        statement = statement.where(
            NewsArticle.published_at >= datetime.combine(start, datetime.min.time(), KST).astimezone(UTC)
        )
    if end:
        statement = statement.where(
            NewsArticle.published_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), KST).astimezone(UTC)
        )
    with request.app.state.sessions() as session:
        if view == "used":
            statement = statement.where(NewsArticle.id.in_(used_article_ids(session)))
        count = session.scalar(select(func.count()).select_from(statement.subquery()))
        order = (
            (ArticleScore.total.desc().nullslast(), NewsArticle.id.desc())
            if sort == "score"
            else (NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc())
        )
        articles = session.execute(statement.order_by(*order).offset((page_number - 1) * 20).limit(20)).all()
        curation_run = session.get(IntelligenceRun, curation_id) if curation_id else session.scalar(
            select(IntelligenceRun).where(IntelligenceRun.kind == "analysis", IntelligenceRun.status == "success",
                                          IntelligenceRun.evidence["curation_contract"]["profile"].as_string().in_([PROFILE, GLOBAL_PROFILE]))
            .order_by(IntelligenceRun.id.desc()).limit(1))
        if curation_id and (not curation_run or curation_run.kind != "analysis"
                            or not curation_run.evidence.get("curation_contract")):
            raise HTTPException(404, "화제성 평가를 찾지 못했습니다.")
        return page(
            request,
            "news.html",
            curation=curation_context(request), curation_run=curation_run,
            curation_components=GLOBAL_COMPONENTS if curation_run and
            curation_run.evidence.get("curation_contract", {}).get("profile") == GLOBAL_PROFILE else COMPONENTS,
            active="news",
            news_view=view,
            articles=articles,
            news_thumbnails={image.article_id: image for image in session.scalars(
                select(ArticleThumbnail).where(ArticleThumbnail.article_id.in_([a.id for a, _s in articles])))},
            categories=list(CATEGORY_WORDS) + ["미분류"],
            sources=list(session.scalars(select(NewsSource))),
            q=q,
            selected_category=category,
            source=source,
            start=start,
            end=end,
            sort=sort,
            count=count,
            page_number=page_number,
            next_url=str(request.url.include_query_params(page_number=page_number + 1)),
            prev_url=str(request.url.include_query_params(page_number=max(1, page_number - 1))),
        )


@router.get("/news/{article_id}", response_class=HTMLResponse)
def detail(request: Request, article_id: int) -> HTMLResponse:
    with request.app.state.sessions() as session:
        article = session.get(NewsArticle, article_id)
        if not article:
            raise HTTPException(404, "기사를 찾을 수 없습니다.")
        return page(
            request,
            "detail.html",
            active="news",
            article=article,
            score=session.get(ArticleScore, article_id),
            mentions=list(
                session.scalars(select(ArticleMention).where(ArticleMention.article_id == article_id))
            ),
        )


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request) -> HTMLResponse:
    with request.app.state.sessions() as session:
        timeout = session.get(AppSetting, "request_timeout")
        logs = list(
            session.scalars(
                select(AuditLog)
                .where(AuditLog.level.in_(["error", "warning"]))
                .order_by(AuditLog.id.desc())
                .limit(50)
            )
        )
        return page(
            request,
            "settings.html",
            active="settings",
            sources=list(session.scalars(select(NewsSource))),
            logs=logs,
            timeout=int(timeout.value) if timeout else request.app.state.config.request_timeout,
            config=request.app.state.config,
            execution_log=request.app.state.config.data_dir / "logs" / "execution.log",
        )


@router.post("/settings/sources")
def add_source(
    request: Request,
    name: str = Form(min_length=1, max_length=100),
    url: str = Form(max_length=2048),
    permission: bool = Form(False),
) -> RedirectResponse:
    name = name.strip()
    if not name or any(ord(c) < 32 for c in name) or not permission:
        raise HTTPException(422, "출처 이름과 RSS 이용 권한 확인이 필요합니다.")
    try:
        normalized = validate_url(url)
    except URLPolicyError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        with request.app.state.sessions.begin() as session:
            if session.scalar(select(func.count()).select_from(NewsSource)) >= 100:
                raise HTTPException(422, "최대 100개 출처를 등록할 수 있습니다.")
            session.add(NewsSource(name=name, url=normalized))
            session.add(
                AuditLog(level="info", event="source_added", message="RSS 출처 등록 및 이용 권한 확인")
            )
    except IntegrityError as exc:
        raise HTTPException(409, "이미 등록된 RSS URL입니다.") from exc
    return go("/settings")


@router.post("/settings/sources/{source_id}/toggle")
def toggle_source(request: Request, source_id: int, permission: bool = Form(False)) -> RedirectResponse:
    with request.app.state.sessions.begin() as session:
        source = session.get(NewsSource, source_id)
        if not source:
            raise HTTPException(404, "RSS 출처가 없습니다.")
        if not source.enabled and not permission:
            raise HTTPException(422, "활성화 전 RSS 이용 권한을 확인해 주세요.")
        source.enabled = not source.enabled
        session.add(
            AuditLog(
                source_id=source.id,
                level="info",
                event="source_toggled",
                message="출처 활성화" if source.enabled else "출처 비활성화",
            )
        )
    return go("/settings")


@router.post("/settings/collection")
def update_settings(request: Request, timeout: int = Form(ge=1, le=30)) -> RedirectResponse:
    with request.app.state.sessions.begin() as session:
        setting = session.get(AppSetting, "request_timeout")
        if setting:
            setting.value = str(timeout)
        else:
            session.add(AppSetting(key="request_timeout", value=str(timeout)))
        session.add(AuditLog(level="info", event="settings_updated", message="수집 타임아웃 변경"))
    return go("/settings")


@router.post("/collection")
def collect(request: Request) -> RedirectResponse:
    try:
        request.app.state.coordinator.start()
    except CollectionBusy as exc:
        raise HTTPException(409, "이미 뉴스 수집이 실행 중입니다.") from exc
    return go("/dashboard")


@router.get("/api/collection")
def collection_status(request: Request) -> dict:
    with request.app.state.sessions() as session:
        run = session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
        return {
            "status": run.status if run else "idle",
            "run_id": run.id if run else None,
            "added": run.added if run else 0,
            "succeeded": run.succeeded if run else 0,
            "failed": run.failed if run else 0,
        }


@router.get("/health")
def health(request: Request) -> dict:
    with request.app.state.sessions() as session:
        session.execute(select(1))
    return {"status": "ok", "phase": 1}
