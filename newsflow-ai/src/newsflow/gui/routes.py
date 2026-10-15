"""Korean UI routes; no external service calls from templates."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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
    AuditLog,
    CollectionRun,
    NewsArticle,
    NewsSource,
)
from newsflow.news.ranking import CATEGORY_WORDS
from newsflow.news.rss_adapter import URLPolicyError, validate_url
from newsflow.news.service import CollectionBusy

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def page(request: Request, name: str, **context: object) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name=name, context={"csrf": request.state.csrf, **context}
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
) -> HTMLResponse:
    try:
        source = int(source) if source else None
        if source is not None and source < 1:
            raise ValueError
        start = date.fromisoformat(start) if start else None
        end = date.fromisoformat(end) if end else None
        if end == date.max:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(422, "출처 번호 또는 날짜 형식이 잘못되었습니다.") from exc
    if start and end and start > end:
        raise HTTPException(422, "시작 날짜는 종료 날짜보다 늦을 수 없습니다.")
    if category and category not in {*CATEGORY_WORDS, "미분류"}:
        raise HTTPException(422, "알 수 없는 카테고리입니다.")
    statement = select(NewsArticle, ArticleScore).outerjoin(ArticleScore)
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
            NewsArticle.published_at >= datetime.combine(start, datetime.min.time(), UTC)
        )
    if end:
        statement = statement.where(
            NewsArticle.published_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC)
        )
    with request.app.state.sessions() as session:
        count = session.scalar(select(func.count()).select_from(statement.subquery()))
        order = (
            (ArticleScore.total.desc().nullslast(), NewsArticle.id.desc())
            if sort == "score"
            else (NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc())
        )
        articles = session.execute(statement.order_by(*order).offset((page_number - 1) * 20).limit(20)).all()
        return page(
            request,
            "news.html",
            active="news",
            articles=articles,
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
    return go("/")


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
