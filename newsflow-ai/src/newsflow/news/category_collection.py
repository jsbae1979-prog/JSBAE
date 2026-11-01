"""Selected-category collection. Fixed plans, sequential attempts, no retry/fallback."""
from sqlalchemy import select
from newsflow.db.models import CollectionRun, IntelligenceRun, NewsSource, utcnow
from .collection_workspace import begin_collection
from .ranking import category_feeds, category_query
from .recent_filter import select_recent
from .serpapi import SOURCE_URL, SerpApiError
from .serpapi_settings import claim
from .service import safe_feed_message
from .trends import TRENDS_URL, parse_trends


def _store(curator, url, category, articles, *, rss=False):
    with curator.sessions.begin() as session:
        source = session.scalar(select(NewsSource).where(NewsSource.url == url))
        if source is None:
            source = NewsSource(name="Google News · " + category, url=url, enabled=False)
            session.add(source)
            session.flush()
        return curator.news.store_articles(session, source.id, articles, rss_metadata=rss, category=category)


def _snapshot(curator):
    current = curator.context()
    if current["fresh"]:
        return current["snapshot"], None
    try:
        return parse_trends(curator.news.collector.adapter.fetch(TRENDS_URL, 10), utcnow()), None
    except Exception as exc:
        return None, safe_feed_message(exc)


def _finish(curator, collection_id, rows, totals, hours, *, run_id=None, failed=False):
    snapshot, error = (None, "분야 수집 실패 · 자동 재요청 없음") if failed else _snapshot(curator)
    ids = list(dict.fromkeys(i for row in rows for i in row["article_ids"]))
    with curator.sessions.begin() as session:
        recent, info = select_recent(session, ids, utcnow(), hours)
        counts = [{"category": r["category"], "collected": len(set(r["article_ids"])),
                   "kept": len(set(r["article_ids"]) & set(recent)), "status": r["status"],
                   **({"skipped_items": r["skipped_items"]} if r.get("skipped_items") else {})} for r in rows]
        result = {**totals, "article_ids": recent, "recent_filter": info, "category_counts": counts}
        collection = session.get(CollectionRun, collection_id)
        for key in ("added", "duplicates", "succeeded", "failed"):
            setattr(collection, key, totals[key])
        collection.status = "partial" if failed and totals["succeeded"] else "failed" if failed else "success"
        collection.finished_at = utcnow()
        curator.news.rescore(session)
        if not failed and snapshot and recent:
            from .lifecycle import replace_collection
            replace_collection(session, recent)
        trend = IntelligenceRun(kind="trends", provider="google_trends",
            status="success" if not failed and snapshot else "failed",
            options={"collection_run_id": collection_id, "categories": [r["category"] for r in rows], "hours": hours},
            evidence={"region": "KR", "url": TRENDS_URL, "news_origin": "serpapi" if run_id else "category_rss",
                      "news_search_run_id": run_id},
            result={"snapshot": snapshot, "collection": result, "trends_error": error,
                    "ai_calls": 0, "facts_verified": False},
            message="분야별 뉴스 수집 완료 · AI 평가 전" if not failed and snapshot else "분야 수집·Trends 확인 필요 · 자동 재요청 없음",
            finished_at=utcnow())
        session.add(trend)
        session.flush()
        if run_id:
            run = session.get(IntelligenceRun, run_id)
            run.result = {**run.result, **result, "trends_run_id": trend.id}
        return trend.id


def collect_rss(curator, categories, hours):
    with curator.sessions.begin() as session:
        collection = CollectionRun(status="running")
        session.add(collection)
        session.flush()
        identifier = collection.id
        begin_collection(session)
    rows = [{"category": c, "article_ids": [], "status": "pending"} for c in categories]
    totals = dict(added=0, duplicates=0, succeeded=0, failed=0)
    for row in rows:
        row["status"] = "success"
        for url in category_feeds(row["category"]):
            try:
                articles = curator.news.collector.collect(url, "Google News · " + row["category"], 10)
                stored = _store(curator, url, row["category"], articles, rss=True)
                row["article_ids"].extend(stored["article_ids"])
                totals["added"] += stored["added"]
                totals["duplicates"] += stored["duplicates"]
                totals["succeeded"] += 1
            except Exception as exc:
                row["status"] = "failed"
                row["error"] = safe_feed_message(exc)
                totals["failed"] += 1
    return _finish(curator, identifier, rows, totals, hours, failed=bool(totals["failed"]))


def collect_serpapi(curator, config, adapter, token, categories, hours):
    rows = [{"category": c, "article_ids": [], "status": "pending"} for c in categories]
    totals = dict(added=0, duplicates=0, succeeded=0, failed=0)
    with curator.sessions.begin() as session:
        run = IntelligenceRun(kind="news_search", provider="serpapi", status="running",
            options={"generation": config["generation"], "collection_policy": "korea_v1", "categories": categories,
                     "hours": hours, "maximum_requests": len(categories), "test_only": bool(getattr(adapter,"test_only",False))},
            evidence={"engine": "google_news", "region": "KR", "language": "ko"},
            result={"requests": [], "local_request_attempts": 0, "provider_billed_credits": None},
            message=f"SerpApi 분야 검색 최대 {len(categories)}회 진행 중")
        collection = CollectionRun(status="running")
        session.add_all([run, collection]); session.flush()
        run_id, collection_id = run.id, collection.id
        claim(session, token, run_id)
        begin_collection(session)
    for index, row in enumerate(rows):
        # Persist intent before sending. A process crash or timeout never replays a query.
        with curator.sessions.begin() as session:
            run = session.get(IntelligenceRun, run_id)
            run.result = {**run.result, "local_request_attempts": index + 1,
                          "requests": [*run.result["requests"], {"category": row["category"], "status": "submitted"}]}
        try:
            stage = "response"
            articles, metadata = adapter.search(query=category_query(row["category"]))
            stage = "storage"
            stored = _store(curator, SOURCE_URL, row["category"], articles)
            row.update(article_ids=stored["article_ids"], status="success", skipped_items=metadata.get("skipped_items", 0))
            for key in ("added", "duplicates"):
                totals[key] += stored[key]
            totals["succeeded"] += 1
            with curator.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                requests = list(run.result["requests"])
                requests[-1] = {"category": row["category"], "status": "success", "article_ids": stored["article_ids"], "metadata": metadata}
                run.result = {**run.result, "requests": requests}
        except Exception as exc:
            code = exc.code if isinstance(exc, SerpApiError) else "bad_response"
            error = exc if isinstance(exc, SerpApiError) else SerpApiError(code, reason="storage" if stage == "storage" else "unknown")
            outcome = "unknown" if code in {"timeout_unknown", "network_unknown"} else "failed"
            row["status"] = outcome; totals["failed"] += 1
            with curator.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.finished_at, run.message = outcome, utcnow(), str(error)
                requests = list(run.result["requests"])
                requests[-1] = {"category": row["category"], "status": outcome, "error_code": code, "diagnostic": error.diagnostics()}
                run.result = {**run.result, "requests": requests, "error_code": code, "diagnostic": error.diagnostics()}
            _finish(curator, collection_id, rows, totals, hours, run_id=run_id, failed=True)
            raise error from None
    with curator.sessions.begin() as session:
        run = session.get(IntelligenceRun, run_id)
        run.status, run.finished_at, run.message = "success", utcnow(), "SerpApi 분야별 검색 결과 저장 완료"
    return _finish(curator, collection_id, rows, totals, hours, run_id=run_id)
