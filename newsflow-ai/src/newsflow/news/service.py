"""Transaction boundaries, provenance, scoring and persistent collection history."""

from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from filelock import FileLock, Timeout
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import (
    AppSetting,
    ArticleMention,
    ArticleScore,
    ArticleThumbnail,
    AuditLog,
    CollectionRun,
    NewsArticle,
    NewsSource,
    utcnow,
)

from .collector import CollectedArticle, Collector
from .dedup import canonical_url, similar_title
from .ranking import classify, rank
from .rss_adapter import FeedError


class CollectionBusy(Exception):
    pass


# Every fixed message the adapter and parser can raise. A FeedError carrying any other text
# (for example a transport wrapper echoing response data) is logged generically, so raw
# URLs, tokens or server text never reach the audit log; the kind is always safe to show.
KNOWN_FEED_MESSAGES = frozenset({
    "RSS URL 형식이 올바르지 않습니다.",
    "공개 HTTP(S) RSS와 기본 포트만 허용합니다. 사설 주소·인증정보는 금지됩니다.",
    "RSS 요청 시간이 초과되었습니다.",
    "RSS 호스트 DNS 조회에 실패했습니다.",
    "사설·예약 IP로 연결되는 RSS 주소는 허용하지 않습니다.",
    "압축 응답은 Phase 1 RSS 정책에서 지원하지 않습니다.",
    "RSS 응답이 최대 2 MiB를 초과했습니다.",
    "RSS TLS 인증서 또는 HTTPS 연결 검증에 실패했습니다.",
    "RSS 연결 또는 TLS 검증에 실패했습니다.",
    "RSS 리디렉션 주소가 없습니다.",
    "RSS 리디렉션 횟수가 제한을 초과했습니다.",
    "robots.txt 확인 실패로 수집을 중단했습니다.",
    "robots.txt 정책에서 이 RSS 경로를 허용하지 않습니다.",
    "robots.txt 요청 간격 정책을 지원하지 않아 수집을 중단했습니다.",
    "crawl-delay가 지정된 출처는 Phase 1에서 수집하지 않습니다.",
    "RSS XML 형식이 잘못되었거나 안전하지 않습니다.",
    "RSS 또는 Atom 문서가 아닙니다.",
    "RSS 문서를 정상적으로 파싱하지 못했습니다.",
    "RSS 항목이 최대 1000개를 초과했습니다.",
    "RSS 항목에 제목 또는 원문 링크가 없습니다.",
})
_HTTP_STATUS_MESSAGE = re.compile(r"RSS 서버가 HTTP [1-5]\d{2}을 반환했습니다\.")
GENERIC_FEED_MESSAGE = "RSS 수집 또는 저장에 실패했습니다."


def safe_feed_message(exc: Exception) -> str:
    """Audit-log text for a collection failure: '[kind] fixed message' or the generic text."""
    if not isinstance(exc, FeedError):
        return GENERIC_FEED_MESSAGE
    text = str(exc)
    if text in KNOWN_FEED_MESSAGES or _HTTP_STATUS_MESSAGE.fullmatch(text):
        return f"[{exc.kind}] {text}"
    return f"[{exc.kind}] {GENERIC_FEED_MESSAGE}"


class NewsService:
    def __init__(self, sessions: sessionmaker[Session], collector: Collector):
        self.sessions = sessions
        self.collector = collector

    @staticmethod
    def store_articles(session: Session, source_id: int, articles: list[CollectedArticle],
                       *, rss_metadata: bool = False) -> dict:
        """Shared RSS/search dedup boundary. Inputs must already pass their source policy.

        Search imports and their durable request result use one transaction. Existing
        articles, dates and summaries are never overwritten by an AI response.
        """
        existing = list(session.scalars(select(NewsArticle)))
        identifiers, added, duplicates = [], 0, 0
        for item in articles:
            canonical = canonical_url(item.url)
            article = next((a for a in existing if a.canonical_url == canonical), None)
            if article is None:
                article = next((a for a in existing if similar_title(
                    a.title, item.title, a.published_at, item.published_at,
                )), None)
            if article is None:
                article = NewsArticle(
                    title=item.title, url=item.url, canonical_url=canonical, source_id=source_id,
                    publisher=item.publisher, summary=item.summary, published_at=item.published_at,
                    category=classify(item.title + " " + item.summary),
                )
                session.add(article)
                session.flush()
                existing.append(article)
                added += 1
            else:
                duplicates += 1
                # An explicitly collected RSS item may complete unknown metadata on a
                # new API-search row. Existing RSS records and known dates are untouched.
                origin = session.get(NewsSource, article.source_id)
                if (rss_metadata and article.published_at is None and item.published_at is not None
                        and origin and origin.url in {
                            "https://api.openai.com/v1/responses", "https://api.anthropic.com/v1/messages",
                        } and article.canonical_url == canonical):
                    article.published_at, article.publisher = item.published_at, item.publisher
            if not session.scalar(select(ArticleMention).where(
                ArticleMention.article_id == article.id, ArticleMention.url == item.url,
            )):
                session.add(ArticleMention(
                    article_id=article.id, source_id=source_id, publisher=item.publisher, url=item.url,
                ))
            from .thumbnails import thumbnail_url

            image = thumbnail_url(getattr(item, "thumbnail_url", None))
            if image and article.canonical_url == canonical and session.get(ArticleThumbnail, article.id) is None:
                session.add(ArticleThumbnail(article_id=article.id, url=image, source_article_url=item.url,
                                             publisher=item.publisher))
            identifiers.append(article.id)
        return {"article_ids": list(dict.fromkeys(identifiers)), "added": added, "duplicates": duplicates}

    def collect(self, run_id: int, source_ids: list[int] | None = None) -> dict:
        with self.sessions() as session:
            query = select(NewsSource).order_by(NewsSource.id)
            query = query.where(NewsSource.enabled if source_ids is None else NewsSource.id.in_(source_ids))
            sources = [(s.id, s.name, s.url) for s in session.scalars(query)]
            timeout = session.get(AppSetting, "request_timeout")
            timeout_value = int(timeout.value) if timeout else 10
        added = duplicates = succeeded = failed = 0
        article_ids = []
        for source_id, name, url in sources:
            try:
                articles = self.collector.collect(url, name, timeout_value)
                source_added = source_duplicates = 0
                with self.sessions.begin() as session:
                    stored = self.store_articles(session, source_id, articles, rss_metadata=True)
                    source_added, source_duplicates = stored["added"], stored["duplicates"]
                    article_ids.extend(stored["article_ids"])
                    session.add(
                        AuditLog(
                            run_id=run_id,
                            source_id=source_id,
                            level="info",
                            event="source_success",
                            message=f"신규 {source_added}, 중복 {source_duplicates}",
                        )
                    )
                added += source_added
                duplicates += source_duplicates
                succeeded += 1
            except Exception as exc:  # noqa: BLE001 -- isolate one source, redact and record failure
                failed += 1
                # Raw adapter exceptions/URLs must never enter logs (see safe_feed_message).
                message = safe_feed_message(exc)
                with self.sessions.begin() as session:
                    session.add(
                        AuditLog(
                            run_id=run_id,
                            source_id=source_id,
                            level="error",
                            event="source_error",
                            message=message,
                        )
                    )
        with self.sessions.begin() as session:
            self.rescore(session)
            if succeeded and not failed:
                from .lifecycle import replace_collection

                replace_collection(session, article_ids)
            run = session.get(CollectionRun, run_id)
            assert run is not None
            run.added, run.duplicates = added, duplicates
            run.succeeded, run.failed = succeeded, failed
            run.status = (
                "partial"
                if failed and succeeded
                else "failed"
                if failed
                else "success"
                if sources
                else "empty"
            )
            run.finished_at = utcnow()
            session.add(
                AuditLog(
                    run_id=run_id,
                    level="info" if not failed else "warning",
                    event="collection_finished",
                    message=f"성공 {succeeded}, 실패 {failed}, 신규 {added}",
                )
            )

        return {"article_ids": list(dict.fromkeys(article_ids)), "added": added, "duplicates": duplicates,
                "succeeded": succeeded, "failed": failed}

    def rescore(self, session: Session) -> None:
        now = utcnow()
        for article in session.scalars(select(NewsArticle)):
            publishers = set(
                session.scalars(
                    select(ArticleMention.publisher).where(ArticleMention.article_id == article.id)
                )
            )
            result = rank(article.title, article.summary, article.published_at, publishers, now)
            score = session.get(ArticleScore, article.id)
            if score is None:
                score = ArticleScore(article_id=article.id)
                session.add(score)
            score.total, score.assessed_max = result.total, result.assessed_max
            score.components, score.scored_at = result.components, now


class CollectionCoordinator:
    """OS file lock protects across threads and local worker processes, including crash recovery."""

    def __init__(self, service: NewsService, data_dir: Path):
        self.service = service
        self.lock_path = data_dir / "collection.lock"
        self.guard = Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rss-collector")
        self.future: Future | None = None

    def recover_interrupted(self) -> None:
        lock = FileLock(str(self.lock_path))
        try:
            with lock.acquire(timeout=0), self.service.sessions.begin() as session:
                for run in session.scalars(select(CollectionRun).where(CollectionRun.status == "running")):
                    run.status = "interrupted"
                    run.finished_at = utcnow()
                    session.add(
                        AuditLog(
                            run_id=run.id,
                            level="error",
                            event="collection_interrupted",
                            message="이전 프로세스 종료로 수집이 중단되었습니다.",
                        )
                    )
        except Timeout:
            pass  # Another process still owns a live collection.

    def start(self, source_ids: list[int] | None = None, on_run: Callable[[int], None] | None = None) -> int:
        with self.guard:
            if self.future and not self.future.done():
                raise CollectionBusy
            # Lock is acquired and released by the worker; reserve synchronously with
            # thread_local=False so an already running process is detected before returning.
            lock = FileLock(str(self.lock_path), thread_local=False)
            try:
                lock.acquire(timeout=0)
            except Timeout as exc:
                raise CollectionBusy from exc
            run_id = None
            try:
                with self.service.sessions.begin() as session:
                    for previous in session.scalars(
                        select(CollectionRun).where(CollectionRun.status == "running")
                    ):
                        previous.status = "interrupted"
                        previous.finished_at = utcnow()
                        session.add(
                            AuditLog(
                                run_id=previous.id,
                                level="error",
                                event="collection_interrupted",
                                message="이전 프로세스 종료로 수집이 중단되었습니다.",
                            )
                        )
                    run = CollectionRun()
                    session.add(run)
                    session.flush()
                    run_id = run.id
                if on_run:
                    on_run(run_id)
                self.future = self.executor.submit(self._execute, run_id, lock, source_ids)
                return run_id
            except Exception:
                try:
                    if run_id is not None:
                        with self.service.sessions.begin() as session:
                            run = session.get(CollectionRun, run_id)
                            run.status, run.finished_at = "failed", utcnow()
                            session.add(
                                AuditLog(
                                    run_id=run_id,
                                    level="error",
                                    event="collection_start_error",
                                    message="수집 준비 기록에 실패했습니다. 외부 요청은 시작하지 않았습니다.",
                                )
                            )
                finally:
                    lock.release()
                raise

    def _execute(self, run_id: int, lock: FileLock, source_ids: list[int] | None = None) -> None:
        try:
            if source_ids is None:
                self.service.collect(run_id)
            else:
                self.service.collect(run_id, source_ids)
        except Exception:  # noqa: BLE001 -- background task must persist failure state
            with self.service.sessions.begin() as session:
                run = session.get(CollectionRun, run_id)
                if run:
                    run.status = "failed"
                    run.finished_at = utcnow()
                session.add(
                    AuditLog(
                        run_id=run_id,
                        level="error",
                        event="collection_error",
                        message="수집 완료 처리에 실패했습니다. 기존 기사는 유지됩니다.",
                    )
                )
        finally:
            lock.release()

    def close(self) -> None:
        self.executor.shutdown(wait=True)
