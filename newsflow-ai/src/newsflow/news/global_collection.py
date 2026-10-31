"""Bounded, explicit multi-edition discovery. All returned candidates and partial outcomes survive."""
from __future__ import annotations

from datetime import datetime

from newsflow.db.models import CollectionRun, IntelligenceRun, NewsSource, utcnow

from .serpapi import SOURCE_URL, SerpApiError
from .serpapi_settings import claim
from .service import safe_feed_message
from .collection_workspace import begin_collection
from .trends import MAX_AGE, parse_trends

GLOBAL_POLICY = "global_trends_v1"
# Edition locations are acquisition coverage, never an assertion about an event's country.
EDITIONS = (("us", "en", "US", "급상승 주제", "trends"),
            ("uk", "en", "GB", "유럽권 주요 뉴스", "global"),
            ("jp", "ja", "JP", "아시아권 주요 뉴스", "global"),
            ("br", "pt", "BR", "남미권 주요 뉴스", "global"),
            ("kr", "ko", "KR", "한국 주요 뉴스", "korea"))


def plan_context() -> dict:
    return {"policy": GLOBAL_POLICY, "maximum_requests": len(EDITIONS),
            "target_global_percent": 80, "target_korea_percent": 20,
            "edition_labels": "미국·영어 / 영국·영어 / 일본·일본어 / 브라질·포르투갈어 / 한국·한국어"}


def _fresh(snapshot: dict, now) -> bool:
    try:
        age = now - datetime.fromisoformat(snapshot["observed_at"])
        return 0 <= age.total_seconds() <= MAX_AGE.total_seconds()
    except (ValueError, TypeError, KeyError):
        return False


def _trends(curator) -> dict:
    now = utcnow()
    previous = curator.context().get("snapshot") or {}
    stored = previous.get("regional_snapshots", [previous])
    cached = {s.get("region"): s for s in stored if s and _fresh(s, now)}
    snapshots, failures = [], []
    # Korean search interest comes first because the viewer is Korean, regardless of event location.
    for region in ("KR", "US", "GB", "JP", "BR"):
        snapshot = cached.get(region)
        if snapshot is None:
            try:
                url = "https://trends.google.com/trending/rss?geo=" + region
                snapshot = parse_trends(curator.news.collector.adapter.fetch(url, 6), now, region=region)
            except Exception as exc:  # noqa: BLE001 - retain sanitized diagnostics, no supplier text
                failures.append({"region": region, "message": safe_feed_message(exc)})
                continue
        snapshots.append(snapshot)
    if not snapshots:
        raise SerpApiError("trends_unavailable")
    return {"source": "Google Trends", "source_url": "https://trends.google.com/trending/", "region": "MULTI",
            "observed_at": min(s["observed_at"] for s in snapshots), "collection_policy": GLOBAL_POLICY,
            "regional_snapshots": snapshots, "regional_failures": failures,
            "signals": [{**signal, "region": s["region"]} for s in snapshots for signal in s["signals"]],
            "meaning": "관측 지역별 급상승 자료 · 세계 검색량/기사 노출/SNS 실측 아님"}


def _query(snapshot):
    # Quotes keep public, untrusted keywords as search text, never commands or prompt instructions.
    seen, terms = set(), []
    regional = snapshot.get("regional_snapshots", [snapshot])
    signals = [rows["signals"][index] for index in range(5) for rows in regional if len(rows["signals"]) > index]
    for signal in signals:
        term = " ".join(signal["term"].replace('"', ' ').replace('\\', ' ').split())[:100]
        if term and term.casefold() not in seen:
            terms.append('"' + term + '"')
            seen.add(term.casefold())
        if len(terms) == 5:
            break
    return " OR ".join(terms) + " when:1d"


def collect_global(curator, config: dict, adapter, token: str) -> int:
    """Caller holds the collection lock and has checked the key, approval and durable token."""
    sessions = curator.sessions
    with sessions.begin() as session:
        run = IntelligenceRun(kind="news_search", provider="serpapi", status="running",
                              options={"generation": config["generation"], "collection_policy": GLOBAL_POLICY,
                                       "maximum_requests": len(EDITIONS), "test_only": bool(getattr(adapter, "test_only", False))},
                              evidence={"engine": "google_news", "coverage": plan_context(), "event_country": "unassessed"},
                              result={"requests": []}, message="지역별 Trends 자료 확인 중 · AI 호출 없음")
        session.add(run)
        session.flush()
        identifier = run.id
        claim(session, token, identifier)
        begin_collection(session)
    requests, ids, origins = [], [], {}
    added = duplicates = succeeded = 0
    snapshot, collection_id, error = None, None, None
    try:
        snapshot = _trends(curator)
        with sessions.begin() as session:
            collection = CollectionRun(status="running")
            session.add(collection)
            session.flush()
            collection_id = collection.id
        for region, language, _geo, label, role in EDITIONS:
            query = _query(snapshot) if role == "trends" else None
            request = {"region": region.upper(), "language": language, "role": role, "label": label,
                       "query": query, "status": "running"}
            requests.append(request)
            with sessions.begin() as session:
                row = session.get(IntelligenceRun, identifier)
                row.result = {**row.result, "requests": [dict(r) for r in requests]}
            articles, metadata = adapter.search(region=region, language=language, query=query)
            with sessions.begin() as session:
                from sqlalchemy import select

                url = SOURCE_URL + "?gl=" + region + "&hl=" + language
                source = session.scalar(select(NewsSource).where(NewsSource.url == url))
                if source is None:
                    source = NewsSource(name=f"Google News · SerpApi · {region.upper()}/{language}", url=url, enabled=False)
                    session.add(source)
                    session.flush()
                result = curator.news.store_articles(session, source.id, articles)
                curator.news.rescore(session)
                added += result["added"]
                duplicates += result["duplicates"]
                succeeded += 1
                ids = list(dict.fromkeys([*ids, *result["article_ids"]]))
                for article_id in result["article_ids"]:
                    origins.setdefault(str(article_id), []).append({"region": region.upper(), "language": language,
                                                                    "role": role, "event_country": None})
                request.update(status="success", article_ids=result["article_ids"], metadata=metadata)
                row = session.get(IntelligenceRun, identifier)
                row.result = {**row.result, "requests": [dict(r) for r in requests], "article_ids": ids,
                              "article_origins": origins}
                collection = session.get(CollectionRun, collection_id)
                collection.added, collection.duplicates, collection.succeeded = added, duplicates, succeeded
    except Exception as exc:  # noqa: BLE001 - stop the batch, retain partial data, never replay or switch provider
        error = SerpApiError(exc.code if isinstance(exc, SerpApiError) else "bad_response")
        if requests and requests[-1]["status"] == "running":
            requests[-1].update(status="unknown" if error.code in {"timeout_unknown", "network_unknown"} else "failed",
                                error_code=error.code)
    with sessions.begin() as session:
        if collection_id is not None:
            collection = session.get(CollectionRun, collection_id)
            collection.status, collection.finished_at = "failed" if error else "success", utcnow()
            collection.failed = int(error is not None)
        if not error:
            from .lifecycle import replace_collection

            replace_collection(session, ids)
        overseas = {i for i, rows in origins.items() if any(r["role"] != "korea" for r in rows)}
        korea = {i for i, rows in origins.items() if any(r["role"] == "korea" for r in rows)}
        mix = {"target_global_percent": 80, "target_korea_percent": 20,
               "global_edition_unique": len(overseas), "korea_edition_unique": len(korea),
               "both_editions": len(overseas & korea), "total_unique": len(ids),
               "global_edition_percent": round(100 * len(overseas) / len(ids), 1) if ids else None,
               "meaning": "조회 배분 4:1 · 실제 후보 수는 응답/중복에 따라 다름 · 사건 발생 국가를 추정하지 않음"}
        row = session.get(IntelligenceRun, identifier)
        row.status = "unknown" if error and error.code in {"timeout_unknown", "network_unknown"} else "failed" if error else "success"
        row.finished_at = utcnow()
        row.message = (str(error) + " 저장된 일부 기사·요청 기록 보존 · 남은 조회 중단" if error else
                       "Trends 우선 한국+글로벌 후보 저장 · 실제 노출/SNS 확산·사실 검증 미완료")
        row.result = {"requests": requests, "article_ids": ids, "article_origins": origins,
                      "collection_policy": GLOBAL_POLICY, "candidate_mix": mix, "added": added, "duplicates": duplicates,
                      "searched_at": utcnow().isoformat(), "local_request_attempts": len(requests),
                      "provider_billed_credits": None, "ai_calls": 0, "facts_verified": False,
                      **({"error_code": error.code} if error else {})}
        trend = IntelligenceRun(kind="trends", provider="google_trends", status="failed" if error else "success",
                                options={"collection_run_id": collection_id},
                                evidence={"news_origin": "serpapi", "news_search_run_id": identifier,
                                          "collection_policy": GLOBAL_POLICY},
                                result={"snapshot": snapshot, "collection": {"article_ids": ids, "added": added,
                                        "duplicates": duplicates, "succeeded": succeeded, "failed": int(error is not None)},
                                        "candidate_mix": mix, "ai_calls": 0, "news_error": str(error) if error else None},
                                message=row.message, finished_at=utcnow())
        session.add(trend)
        session.flush()
        row.result = {**row.result, "trends_run_id": trend.id}
        trend_id = trend.id
    if error:
        raise error
    return trend_id
