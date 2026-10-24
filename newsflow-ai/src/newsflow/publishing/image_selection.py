"""Read stored selections/scripts only. Preparing feeds never invokes an AI provider."""
from copy import deepcopy

from sqlalchemy import select

from newsflow.db.models import ContentDraft, ImagePost, IntelligenceRun, NewsArticle

from .service import PublishingError


def references(articles):
    """Support both draft evidence (nested sources) and image snapshots (flat URL)."""
    result, seen = [], set()
    for article in articles:
        links = article.get("sources") or [{"url": article.get("url"),
                                            "publisher": article.get("publisher")}]
        for link in links:
            url = link.get("url")
            if not url:
                raise PublishingError("출처 주소가 부족합니다. 원문을 확인해 주세요.")
            if url not in seen:
                result.append({**deepcopy(article), "url": url,
                               "publisher": link.get("publisher") or article.get("publisher")})
                seen.add(url)
    return result


def selection(session, analysis_id=None):
    if analysis_id is None:
        analysis = session.scalar(select(IntelligenceRun).where(
            IntelligenceRun.kind == "analysis", IntelligenceRun.status == "success",
            IntelligenceRun.evidence["curation_contract"]["top_k"].as_integer() == 3
        ).order_by(IntelligenceRun.id.desc()).limit(1))
    else:
        analysis = session.get(IntelligenceRun, analysis_id)
    if (not analysis or analysis.kind != "analysis" or analysis.status != "success"
            or not analysis.evidence.get("curation_contract")):
        raise PublishingError("성공한 상위 뉴스 선정 결과가 필요합니다. 재평가는 자동 실행하지 않습니다.")
    ranked = analysis.result.get("ranking", [])
    if len(ranked) < 3 or {row.get("rank") for row in ranked[:3]} != {1, 2, 3}:
        raise PublishingError("상위 3건이 모두 있는 선정 결과를 선택하세요.")
    evidence = {a["id"]: a for a in analysis.evidence.get("articles", [])}
    items, used = [], set()
    for row in sorted(ranked[:3], key=lambda r: r["rank"]):
        ids = row.get("article_ids", [])
        if (not ids or len(ids) != len(set(ids)) or used.intersection(ids)
                or any(i not in evidence or not session.get(NewsArticle, i) for i in ids)):
            raise PublishingError("선정 뉴스와 저장된 출처 연결을 확인할 수 없습니다.")
        used.update(ids)
        linked = [evidence[i] for i in ids]
        refs = references(linked)
        draft = None
        candidates = session.execute(select(ContentDraft, IntelligenceRun).join(
            IntelligenceRun, ContentDraft.run_id == IntelligenceRun.id).where(
            IntelligenceRun.kind == "script", IntelligenceRun.status == "success",
            IntelligenceRun.provider == analysis.provider,
            IntelligenceRun.options["analysis_run_id"].as_integer() == analysis.id
        ).order_by(ContentDraft.id.desc()))
        for candidate, run in candidates:
            source_ids = {a.get("id", a.get("article_id"))
                          for a in (candidate.sources or {}).get("articles", [])}
            if set(run.options.get("selected_article_ids", [])) == set(ids) == source_ids:
                draft = candidate
                break
        body = "\n\n".join(s.get("narration", "") for s in draft.content.get("scenes", [])) if draft else row.get("summary", "")
        title = draft.content.get("title", row["title"]) if draft else row["title"]
        saved = list(session.scalars(select(ImagePost).where(
            ImagePost.sources["selection"]["analysis_id"].as_integer() == analysis.id,
            ImagePost.sources["selection"]["rank"].as_integer() == row["rank"]
        ).order_by(ImagePost.id.desc())))
        items.append({"rank": row["rank"], "score": row.get("score"), "title": title,
                      "body": body, "article_id": ids[0], "article_ids": ids, "references": refs,
                      "draft": draft, "saved": saved,
                      "origin": "기존 대본 재사용" if draft else "저장된 평가 요약 · 대본 미생성",
                      "selection": {"analysis_id": analysis.id, "rank": row["rank"],
                                    "article_ids": ids, "score": row.get("score"),
                                    "draft_id": draft.id if draft else None}})
    return {"run": analysis, "items": items}
