"""Explicit, bounded Google RSS preparation. Never invokes an AI or changes active sources."""
from __future__ import annotations

import json
import re
from datetime import datetime

from filelock import FileLock, Timeout
from sqlalchemy import select

from newsflow.db.models import (
    AppSetting,
    AuditLog,
    CollectionRun,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    utcnow,
)

from .collector import parse_feed
from .serpapi import SOURCE_URL, SerpApiAdapter, SerpApiError
from .serpapi_settings import claim
from .serpapi_settings import settings as serpapi_settings
from .service import CollectionBusy, safe_feed_message
from .trends import GOOGLE_NEWS_URL, MAX_AGE, TRENDS_URL, parse_trends


class Curator:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.news = coordinator.service
        self.sessions = self.news.sessions

    def refresh(self, permission: bool = False) -> int:
        if not permission:
            raise ValueError("Google News·Trends의 공개 RSS 이용 조건과 출처 표시에 동의해 주세요.")
        try:
            with FileLock(str(self.coordinator.lock_path)).acquire(timeout=0):
                return self._refresh()
        except Timeout:
            raise CollectionBusy from None

    def _refresh(self) -> int:
        with self.sessions.begin() as session:
            source = session.scalar(select(NewsSource).where(NewsSource.url == GOOGLE_NEWS_URL))
            if source is None:
                source = NewsSource(name="Google News · 한국", url=GOOGLE_NEWS_URL, enabled=False)
                session.add(source)
                session.flush()
            source_id = source.id
            collection = CollectionRun(status="running")
            session.add(collection)
            session.flush()
            trend = IntelligenceRun(kind="trends", provider="google_trends", status="running",
                                    options={"collection_run_id": collection.id},
                                    evidence={"region": "KR", "url": TRENDS_URL}, result={},
                                    message="Google News·Trends RSS 수집 중 · AI 호출 없음")
            session.add(trend)
            session.flush()
            collection_id, trend_id = collection.id, trend.id
        collected = self.news.collect(collection_id, [source_id])
        snapshot, error = None, None
        try:
            payload = self.news.collector.adapter.fetch(TRENDS_URL, 10)
            snapshot = parse_trends(payload, utcnow())
        except Exception as exc:  # noqa: BLE001 - never persist transport text/URLs/credentials
            error = safe_feed_message(exc)
        with self.sessions.begin() as session:
            trend = session.get(IntelligenceRun, trend_id)
            news_error = session.scalar(select(AuditLog.message).where(AuditLog.run_id == collection_id,
                                                                        AuditLog.event == "source_error")
                                        .order_by(AuditLog.id.desc()).limit(1))
            trend.status = "success" if snapshot and collected["succeeded"] else "failed"
            trend.result = {"snapshot": snapshot, "collection": collected, "trends_error": error,
                            "news_error": news_error, "ai_calls": 0, "facts_verified": False}
            trend.message = ("Google News·Trends 자료 준비 완료 · AI 평가 전" if trend.status == "success"
                             else "RSS 자료 준비 실패 · 자동 재수집/대체 없음")
            trend.finished_at = utcnow()
        return trend_id

    def import_feed(self, payload: bytes, permission: bool = False) -> int:
        """User-supplied RSS only; no HTTP fetch or robots override. Preserve original URLs/dates."""
        if not permission:
            raise ValueError("제공 자료의 이용 권한을 확인해 주세요.")
        articles = parse_feed(payload, "사용자 제공 Google News RSS")
        if not 1 <= len(articles) <= 5:
            raise ValueError("파일에서 기사 1~5개를 제공해 주세요.")
        try:
            with FileLock(str(self.coordinator.lock_path)).acquire(timeout=0):
                current = self.context()
                snapshot = current["snapshot"] if current["fresh"] else None
                with self.sessions.begin() as session:
                    source = session.scalar(select(NewsSource).where(NewsSource.url == GOOGLE_NEWS_URL))
                    if source is None:
                        source = NewsSource(name="Google News · 한국", url=GOOGLE_NEWS_URL, enabled=False)
                        session.add(source)
                        session.flush()
                    stored = self.news.store_articles(session, source.id, articles, rss_metadata=True)
                    from .lifecycle import replace_collection

                    replace_collection(session, stored["article_ids"])
                    self.news.rescore(session)
                    collection = CollectionRun(status="success", added=stored["added"], duplicates=stored["duplicates"],
                                               succeeded=1, failed=0, finished_at=utcnow())
                    session.add(collection)
                    session.flush()
                    trend = IntelligenceRun(kind="trends", provider="google_trends",
                                            status="success" if snapshot else "failed",
                                            options={"collection_run_id": collection.id},
                                            evidence={"region": "KR", "url": TRENDS_URL, "news_origin": "user_file"},
                                            result={"snapshot": snapshot, "collection": {**stored, "succeeded": 1, "failed": 0},
                                                    "trends_error": None, "ai_calls": 0, "facts_verified": False},
                                            message="사용자 제공 RSS + 저장된 Trends 자료 · 새 뉴스 자동 수집 아님",
                                            finished_at=utcnow())
                    session.add(trend)
                    session.flush()
                    return trend.id
        except Timeout:
            raise CollectionBusy from None

    def serpapi(self, keys, token: str, *, consent: bool = False, adapter=None, policy: str = "korea_v1") -> int:
        """One durable authorized attempt, then Trends only. No fallback/replay after any outcome."""
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            raise ValueError("요청 식별자를 확인해 주세요.")
        if not consent:
            raise ValueError("표시된 SerpApi 검색 횟수·사용량과 Google Trends RSS 수신에 동의해 주세요.")
        from .global_collection import GLOBAL_POLICY, collect_global

        if policy not in {"korea_v1", GLOBAL_POLICY}:
            raise ValueError("수집 정책을 확인해 주세요.")
        try:
            with FileLock(str(self.coordinator.lock_path)).acquire(timeout=0):
                with self.sessions() as session:
                    previous = session.get(AppSetting, "serpapi_request:" + token)
                    if previous:
                        run = session.get(IntelligenceRun, json.loads(previous.value)["run_id"])
                        if run.options.get("collection_policy", "korea_v1") != policy:
                            raise ValueError("기존 요청의 수집 범위와 다릅니다. 요청 기록은 보존합니다.")
                        if run.result.get("trends_run_id"):
                            return run.result["trends_run_id"]
                        raise ValueError("이미 요청한 검색입니다. 실패·결과 불명 기록을 보존하며 재전송하지 않습니다.")
                config = serpapi_settings(self.sessions)
                if not config["approved_at"] or not keys.status()["configured"]:
                    raise ValueError("설정에서 SerpApi 키 등록과 사용 승인을 확인해 주세요.")
                adapter = adapter or SerpApiAdapter(keys)
                if policy == GLOBAL_POLICY:
                    return collect_global(self, config, adapter, token)
                with self.sessions.begin() as session:
                    run = IntelligenceRun(kind="news_search", provider="serpapi", status="running",
                                          options={"generation": config["generation"],
                                                   "test_only": bool(getattr(adapter, "test_only", False))},
                                          evidence={"engine": "google_news", "region": "KR", "language": "ko"},
                                          result={}, message="SerpApi 뉴스 검색 1회 진행 중")
                    session.add(run)
                    session.flush()
                    run_id = run.id
                    claim(session, token, run_id)
                try:
                    articles, metadata = adapter.search()
                    with self.sessions.begin() as session:
                        source = session.scalar(select(NewsSource).where(NewsSource.url == SOURCE_URL))
                        if source is None:
                            source = NewsSource(name="Google News · SerpApi", url=SOURCE_URL, enabled=False)
                            session.add(source)
                            session.flush()
                        stored = self.news.store_articles(session, source.id, articles)
                        self.news.rescore(session)
                        collection = CollectionRun(status="success", added=stored["added"], duplicates=stored["duplicates"],
                                                   succeeded=1, failed=0, finished_at=utcnow())
                        session.add(collection)
                        session.flush()
                        collection_id = collection.id
                        run = session.get(IntelligenceRun, run_id)
                        run.status, run.finished_at, run.message = "success", utcnow(), "SerpApi 검색 결과 저장 완료 · 원문 검증 미완료"
                        run.result = {**stored, "metadata": metadata, "searched_at": utcnow().isoformat(),
                                      "ai_calls": 0, "facts_verified": False}
                except Exception as exc:  # noqa: BLE001 - never keep supplier text or key-bearing request URLs
                    code = exc.code if isinstance(exc, SerpApiError) else "bad_response"
                    error = SerpApiError(code)
                    with self.sessions.begin() as session:
                        run = session.get(IntelligenceRun, run_id)
                        run.status = "unknown" if code in {"timeout_unknown", "network_unknown"} else "failed"
                        run.finished_at, run.message = utcnow(), str(error)
                        run.result = {"error_code": error.code, "local_request_attempts": 1, "provider_billed_credits": None}
                    raise error from None
                current = self.context()
                snapshot = current["snapshot"] if current["fresh"] else None
                error = None
                if snapshot is None:
                    try:
                        payload = self.news.collector.adapter.fetch(TRENDS_URL, 10)
                        snapshot = parse_trends(payload, utcnow())
                    except Exception as exc:  # noqa: BLE001 - bounded sanitized RSS diagnostic
                        error = safe_feed_message(exc)
                with self.sessions.begin() as session:
                    trend = IntelligenceRun(kind="trends", provider="google_trends", status="success" if snapshot else "failed",
                                            options={"collection_run_id": collection_id},
                                            evidence={"news_origin": "serpapi", "news_search_run_id": run_id, "url": TRENDS_URL},
                                            result={"snapshot": snapshot, "collection": {**stored, "succeeded": 1, "failed": 0},
                                                    "trends_error": error, "ai_calls": 0, "facts_verified": False},
                                            message="SerpApi Google News + Google Trends · AI 평가 전" if snapshot else
                                                    "뉴스 저장 완료 · Trends 수신 실패 · 자동 재검색 없음", finished_at=utcnow())
                    session.add(trend)
                    session.flush()
                    session.get(IntelligenceRun, run_id).result = {**session.get(IntelligenceRun, run_id).result,
                                                                 "trends_run_id": trend.id}
                    if snapshot:
                        from .lifecycle import replace_collection

                        replace_collection(session, stored["article_ids"])
                    return trend.id
        except Timeout:
            raise CollectionBusy from None

    def context(self, now: datetime | None = None) -> dict:
        now = now or utcnow()
        with self.sessions() as session:
            run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "trends",
                                                               IntelligenceRun.provider == "google_trends")
                                 .order_by(IntelligenceRun.id.desc()).limit(1))
            result = run.result if run else {}
            snapshot = result.get("snapshot")
            fresh = False
            observed = None
            if snapshot:
                observed = datetime.fromisoformat(snapshot["observed_at"])
                age = now - observed
                fresh = 0 <= age.total_seconds() <= MAX_AGE.total_seconds()
            ids = result.get("collection", {}).get("article_ids", [])
            from .lifecycle import visible_news

            articles = list(session.scalars(select(NewsArticle).where(NewsArticle.id.in_(ids))
                                           .where(visible_news())
                                           .order_by(NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc()))) if ids else []
            ready = bool(run and run.status == "success" and fresh and articles and len(articles) == len(set(ids)))
            return {"run_id": run.id if run else None, "status": run.status if run else "not_collected",
                    "message": run.message if run else "Google News·Trends 자료를 먼저 가져오세요.",
                    "error": " / ".join(filter(None, [result.get("news_error"), result.get("trends_error")])),
                    "collection": result.get("collection", {}),
                    "candidate_mix": result.get("candidate_mix"),
                    "snapshot": snapshot, "observed_at": observed, "fresh": fresh, "ready": ready, "articles": articles,
                    "whole_collection_evaluation": True}
