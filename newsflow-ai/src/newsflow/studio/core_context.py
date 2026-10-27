"""Read-only, allowlisted production context shared by the five rebuilt studios.

No provider, vault, file download, migration, retry, or persistence on GET.
"""
import ipaddress
import re
from urllib.parse import urlsplit

from sqlalchemy import select
from newsflow.db.models import IntelligenceRun, NewsArticle
from newsflow.news.lifecycle import visible_news
from newsflow.publishing.image_selection import selection
from newsflow.publishing.service import PublishingError


def text(value, limit=600):
    if not isinstance(value, str):
        return ""
    return re.sub(r"(?i)(sk-[a-z0-9_-]{16,}|ghp_[a-z0-9]{20,}|Bearer\s+[a-z0-9._-]{16,})", "[보호된 값]", value[:limit])


def public_reference(ref):
    if not isinstance(ref, dict):
        return None
    url = ref.get("url", "")
    if not isinstance(url, str) or len(url) > 2048:
        return None
    try:
        u = urlsplit(url)
        if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.port not in {None, 80, 443}:
            return None
        host = u.hostname.lower()
        if host == "localhost" or host.endswith(".localhost") or "%" in host:
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
    except ValueError:
        return None
    return {"url": url, "publisher": text(ref.get("publisher"), 120)}


def production_context(session):
    collection = session.scalar(select(IntelligenceRun).where(
        IntelligenceRun.kind == "trends", IntelligenceRun.provider == "google_trends"
    ).order_by(IntelligenceRun.id.desc()).limit(1))
    result = {"schemaVersion": 1, "selection": None, "top3": [],
              "collection": {"id": collection.id, "createdAt": collection.created_at.isoformat()} if collection else None,
              "blockedReason": None}
    try:
        group = selection(session)
        run = group["run"]
        if len(group["items"]) != 3 or run.evidence["curation_contract"].get("top_k") != 3:
            raise PublishingError("완료된 TOP 3 분석이 필요합니다.")
        ids = {i for item in group["items"] for i in item["article_ids"]}
        articles = {a.id: a for a in session.scalars(select(NewsArticle).where(NewsArticle.id.in_(ids), visible_news()))}
        if set(articles) != ids:
            raise PublishingError("숨김·보관 상태가 바뀐 기사 연결을 확인하세요.")
        ranks = {row["rank"]: row for row in run.result.get("ranking", [])}
        items = []
        for item in group["items"]:
            rank = ranks[item["rank"]]
            article = articles[item["article_id"]]
            refs = [safe for ref in item["references"] if (safe := public_reference(ref))]
            if not refs:
                raise PublishingError("검토 가능한 공개 원문 출처가 필요합니다.")
            items.append({"rank": item["rank"], "articleId": item["article_id"],
                          "articleIds": item["article_ids"], "title": text(rank.get("title"), 200),
                          "summary": text(rank.get("summary"), 600), "reason": text(rank.get("reason"), 600),
                          "score": item.get("score"), "category": text(article.category, 80),
                          "thumbnailUrl": f"/news/{article.id}/thumbnail", "references": refs,
                          "draftId": item["selection"]["draft_id"],
                          "draftRevision": item["draft"].revision if item["draft"] else None,
                          "body": text(item["body"], 4000), "origin": item["origin"]})
        stale = bool(collection and collection.created_at > run.created_at)
        result.update(selection={"id": run.id, "provider": text(run.provider, 80),
                                  "model": text((run.options or {}).get("model"), 160),
                                  "createdAt": run.created_at.isoformat(), "overview": text(run.result.get("overview")),
                                  "stale": stale}, top3=items)
        if stale:
            result["blockedReason"] = "새 수집 회차의 분석이 대기 중입니다. 아래는 이전 완료 분석이며 최신 결과가 아닙니다."
    except PublishingError as exc:
        result["blockedReason"] = str(exc)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        result.update(selection=None, top3=[], blockedReason="저장된 분석·출처 형식을 확인하세요. 자동 재분석하지 않습니다.")
    return result
