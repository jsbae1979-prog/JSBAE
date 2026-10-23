"""Easy news page: public RSS registration, explicit connection tests and manual collection.

A connection test fetches and parses one feed through the application's registered
adapter and policy (public DNS, pinned TLS, robots, size limits) without storing any
article. Results keep only counts and a classified message; raw feed text is never kept.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from newsflow.autopilot.samples import SAMPLE_URL
from newsflow.db.models import (
    AppSetting,
    ArticleMention,
    AuditLog,
    CollectionRun,
    NewsArticle,
    NewsSource,
    NewsSourceCheck,
    utcnow,
)
from newsflow.intelligence.korean import MIN_SUMMARY_CHARS
from newsflow.news.catalog import FEED_PRESETS
from newsflow.news.rss_adapter import FeedError, URLPolicyError, validate_url
from newsflow.news.service import CollectionBusy

from .routes import go, page

router = APIRouter()
MAX_SOURCES = 100


def _source(session, source_id: int) -> NewsSource:
    source = session.get(NewsSource, source_id)
    if not source or source.url == SAMPLE_URL:
        raise HTTPException(404, "RSS 출처가 없습니다.")
    return source


def _valid_name(name: str) -> str:
    name = name.strip()
    if not name or any(ord(c) < 32 for c in name):
        raise HTTPException(422, "출처 이름을 입력하세요.")
    return name


def _valid_url(url: str) -> str:
    try:
        normalized = validate_url(url.strip())
    except URLPolicyError as exc:
        raise HTTPException(422, str(exc)) from exc
    if normalized == SAMPLE_URL:
        raise HTTPException(422, "체험 뉴스 주소는 등록할 수 없습니다.")
    return normalized


def article_view(article: NewsArticle, sample_source_id: int | None) -> dict:
    summary = (article.summary or "").strip()
    return {
        "article": article,
        "synthetic": article.source_id == sample_source_id,
        "sufficient": len(summary) >= MIN_SUMMARY_CHARS,
        "dated": article.published_at is not None,
    }


@router.get("/sources", response_class=HTMLResponse)
def sources(request: Request, tested: int | None = None) -> HTMLResponse:
    with request.app.state.sessions() as session:
        sample = session.scalar(select(NewsSource.id).where(NewsSource.url == SAMPLE_URL))
        rows = []
        for source in session.scalars(select(NewsSource).where(NewsSource.url != SAMPLE_URL).order_by(NewsSource.id)):
            check = session.get(NewsSourceCheck, source.id)
            count = session.scalar(
                select(func.count(func.distinct(ArticleMention.article_id))).where(ArticleMention.source_id == source.id)
            )
            last_error = session.scalar(
                select(AuditLog).where(AuditLog.source_id == source.id, AuditLog.level == "error")
                .order_by(AuditLog.id.desc()).limit(1)
            )
            rows.append({"source": source, "check": check, "article_count": count, "last_error": last_error})
        recent = [
            article_view(article, sample)
            for article in session.scalars(select(NewsArticle).order_by(NewsArticle.id.desc()).limit(12))
        ]
        run = session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
        timeout = session.get(AppSetting, "request_timeout")
        return page(
            request, "sources.html", active="sources", sources=rows, recent=recent, run=run,
            enabled_count=sum(1 for row in rows if row["source"].enabled), tested=tested,
            timeout=int(timeout.value) if timeout else request.app.state.config.request_timeout,
            max_sources=MAX_SOURCES, min_summary=MIN_SUMMARY_CHARS,
            feed_presets=FEED_PRESETS, registered_urls={row["source"].url for row in rows},
        )


@router.post("/sources/preset")
def add_preset(
    request: Request, preset: str = Form(max_length=40), permission: bool = Form(False),
) -> RedirectResponse:
    selected = next((item for item in FEED_PRESETS if item.id == preset), None)
    if selected is None:
        raise HTTPException(422, "목록에서 RSS 출처를 선택하세요.")
    # Reuse URL, permission, duplicate and limit checks; registration never fetches.
    return add_source(request, name=selected.name, url=selected.url, permission=permission)


@router.post("/sources")
def add_source(
    request: Request, name: str = Form(min_length=1, max_length=100), url: str = Form(max_length=2048),
    permission: bool = Form(False),
) -> RedirectResponse:
    if not permission:
        raise HTTPException(422, "공개 RSS 이용 약관·저작권 확인이 필요합니다.")
    name, normalized = _valid_name(name), _valid_url(url)
    try:
        with request.app.state.sessions.begin() as session:
            if session.scalar(select(func.count()).select_from(NewsSource)) >= MAX_SOURCES:
                raise HTTPException(422, f"최대 {MAX_SOURCES}개 출처를 등록할 수 있습니다.")
            source = NewsSource(name=name, url=normalized, enabled=False)
            session.add(source)
            session.add(AuditLog(level="info", event="source_added", message="RSS 출처 등록 및 이용 권한 확인"))
            session.flush()
            identifier = source.id
    except IntegrityError as exc:
        raise HTTPException(409, "이미 등록된 RSS URL입니다.") from exc
    return go(f"/sources#source-{identifier}")


@router.post("/sources/{source_id}/edit")
def edit_source(
    request: Request, source_id: int, name: str = Form(min_length=1, max_length=100),
    url: str = Form(max_length=2048), permission: bool = Form(False),
) -> RedirectResponse:
    name, normalized = _valid_name(name), _valid_url(url)
    try:
        with request.app.state.sessions.begin() as session:
            source = _source(session, source_id)
            if normalized != source.url:
                if not permission:
                    raise HTTPException(422, "주소를 바꾸면 새 RSS의 이용 권한 확인이 다시 필요합니다.")
                source.url, source.enabled = normalized, False
                check = session.get(NewsSourceCheck, source.id)
                if check:
                    session.delete(check)
            source.name = name
            session.add(AuditLog(source_id=source.id, level="info", event="source_edited", message="RSS 출처 수정"))
    except IntegrityError as exc:
        raise HTTPException(409, "이미 등록된 RSS URL입니다.") from exc
    return go(f"/sources#source-{source_id}")


@router.post("/sources/{source_id}/toggle")
def toggle_source(request: Request, source_id: int, permission: bool = Form(False)) -> RedirectResponse:
    with request.app.state.sessions.begin() as session:
        source = _source(session, source_id)
        if not source.enabled and not permission:
            raise HTTPException(422, "활성화 전 RSS 이용 권한을 확인해 주세요.")
        source.enabled = not source.enabled
        session.add(AuditLog(
            source_id=source.id, level="info", event="source_toggled",
            message="출처 활성화" if source.enabled else "출처 비활성화",
        ))
    return go(f"/sources#source-{source_id}")


@router.post("/sources/{source_id}/test")
def test_source(request: Request, source_id: int) -> RedirectResponse:
    """One bounded feed request; nothing is stored except counts and a safe classification."""
    with request.app.state.sessions() as session:
        source = _source(session, source_id)
        name, url = source.name, source.url
        timeout = session.get(AppSetting, "request_timeout")
        timeout_value = int(timeout.value) if timeout else 10
    collector = request.app.state.coordinator.service.collector
    status, kind, message, counts = "pass", None, "", (0, 0, 0)
    try:
        articles = collector.collect(url, name, timeout_value)
        counts = (
            len(articles), sum(1 for a in articles if a.published_at is not None),
            sum(1 for a in articles if len(a.summary.strip()) >= MIN_SUMMARY_CHARS),
        )
        if not articles:
            status, kind, message = "fail", "empty", "피드에 기사 항목이 없습니다."
        else:
            message = f"기사 {counts[0]}개 · 발행시각 있음 {counts[1]}개 · 요약 충분 {counts[2]}개"
    except FeedError as exc:
        status, kind, message = "fail", str(exc.kind), str(exc)[:300]
    except Exception:  # noqa: BLE001 - never surface raw adapter or network details
        status, kind, message = "fail", "network", "RSS 수집 또는 파싱에 실패했습니다."
    with request.app.state.sessions.begin() as session:
        check = session.get(NewsSourceCheck, source_id)
        if check is None:
            check = NewsSourceCheck(source_id=source_id, status=status, message=message)
            session.add(check)
        check.status, check.kind, check.message = status, kind, message
        check.article_count, check.dated_count, check.summarized_count = counts
        check.checked_at = utcnow()
        session.add(AuditLog(
            source_id=source_id, level="info" if status == "pass" else "warning", event="source_tested",
            message=("연결 테스트 성공: " if status == "pass" else "연결 테스트 실패: ") + message[:450],
        ))
    return go(f"/sources?tested={source_id}#source-{source_id}")


@router.post("/sources/collect")
def collect(request: Request) -> RedirectResponse:
    with request.app.state.sessions() as session:
        enabled = list(session.scalars(select(NewsSource.id).where(NewsSource.enabled, NewsSource.url != SAMPLE_URL)))
    if not enabled:
        raise HTTPException(422, "활성화된 뉴스 출처가 없습니다. 출처를 등록하고 활성화하세요.")
    try:
        request.app.state.coordinator.start(enabled)
    except CollectionBusy as exc:
        raise HTTPException(409, "이미 뉴스 수집이 실행 중입니다.") from exc
    return go("/sources")
