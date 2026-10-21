"""Whole latest collection, never a user-selected subset or automatic paid batches."""
from copy import deepcopy

import pytest
from conftest import csrf
from sqlalchemy import select
from test_google_news_trends import NOW, CuratorResponse, article, no_external_calls, prepared

from newsflow.db.models import ContentDraft, IntelligenceRun, NewsArticle
from newsflow.intelligence.curation import enrich, validate_ranking
from newsflow.intelligence.provider import Options
from newsflow.news.curator import Curator

__all__ = ["no_external_calls", "prepared"]


def extend_collection(app, count):
    ctx = Curator(app.state.coordinator).context()
    ids = [a.id for a in ctx["articles"]]
    with app.state.sessions.begin() as session:
        source_id = session.get(NewsArticle, ids[0]).source_id
        for index in range(count - len(ids)):
            row = NewsArticle(title=f"서로 다른 합성 주제 {index}", url=f"https://example.com/unique/{index}",
                              canonical_url=f"https://example.com/unique/{index}", source_id=source_id,
                              publisher="합성 출처", summary="테스트 주제의 적용 범위를 확인하는 자료입니다.")
            session.add(row)
            session.flush()
            ids.append(row.id)
        row = session.get(IntelligenceRun, ctx["run_id"])
        row.result = {**row.result, "collection": {**row.result["collection"], "article_ids": ids}}
    return Curator(app.state.coordinator).context()


def test_whole_collection_no_selection_no_sixty_article_cutoff(client, app, prepared):
    _, adapter, _, _, _ = prepared
    ctx = extend_collection(app, 65)
    assert len(ctx["articles"]) == 65
    html = client.get("/news").text
    assert "전체 뉴스 화제성 평가" in html and "전체 65개 비교" in html
    assert 'name="article_ids"' not in html
    data = {"csrf_token": csrf(client), "consent": "true", "collection_context_id": ctx["run_id"],
            "article_ids": [ctx["articles"][0].id]}  # Cannot narrow the server-owned whole set.
    response = client.post("/news/curation/analyze", data=data)
    assert response.status_code == 200, response.text
    assert len(adapter.payloads[0]["articles"]) == 65 and adapter.calls == ["analysis"]
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis"))
        assert len(run.result["comparisons"]) == 65 and len(run.result["ranking"]) == 3
        assert run.evidence["curation_contract"]["top_k"] == 3
        assert session.scalar(select(ContentDraft)) is None
    assert client.post("/news/curation/analyze", data=data).status_code == 200
    assert adapter.calls == ["analysis"]


def test_changed_collection_and_no_consent_make_no_calls(client, app, prepared):
    _, adapter, _, _, _ = prepared
    ctx = Curator(app.state.coordinator).context()
    data = {"csrf_token": csrf(client), "collection_context_id": ctx["run_id"]}
    assert client.post("/news/curation/analyze", data=data).status_code == 422
    Curator(app.state.coordinator).refresh(True)
    assert client.post("/news/curation/analyze", data={**data, "consent": "true"}).status_code == 409
    assert adapter.calls == []


def test_collection_too_large_never_silently_truncated_or_split(client, app, prepared):
    _, adapter, _, _, _ = prepared
    ctx = extend_collection(app, 401)
    response = client.post("/news/curation/analyze", data={"csrf_token": csrf(client), "consent": "true",
                                                          "collection_context_id": ctx["run_id"]})
    assert response.status_code == 422 and "자동 추가 호출 없이 중단" in response.text
    assert len(ctx["articles"]) == 401 and adapter.calls == []


def test_ranking_missing_unranked_article_rejected():
    evidence = enrich({"articles": [{**article(), "id": i} for i in range(1, 13)],
                       "groups": [[i] for i in range(1, 13)]}, None, NOW)
    output = CuratorResponse("claude_api").analyze(evidence, Options())
    assert len(validate_ranking(output, evidence)["ranking"]) == 10
    omitted = deepcopy(output)
    omitted["comparisons"].pop()
    with pytest.raises(ValueError, match="누락"):
        validate_ranking(omitted, evidence)


def test_ranked_group_above_ten_still_reaches_script_review(client, app, prepared):
    _, adapter, _, _, _ = prepared
    ctx = extend_collection(app, 12)
    original = adapter.analyze

    def grouped(evidence, options):
        result = original(evidence, options)
        ids = [a["id"] for a in evidence["articles"]]
        result["comparisons"] = [{"article_ids": ids, "reason": "같은 이슈를 비교합니다.",
                                   "uncertainties": "독립 검증 미완료"}]
        result["ranking"] = [{**result["ranking"][0], "article_ids": ids}]
        return result

    adapter.analyze = grouped
    response = client.post("/news/curation/analyze", data={"csrf_token": csrf(client), "consent": "true",
                                                          "collection_context_id": ctx["run_id"]})
    assert response.status_code == 200, response.text
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis"))
        identifier = run.id
    response = client.post("/news/curation/generate", data={"csrf_token": csrf(client), "consent": "true",
                                                           "analysis_id": identifier, "rank": 1, "duration": 30})
    assert response.status_code == 200, response.text
    with app.state.sessions() as session:
        draft = session.scalar(select(ContentDraft))
        assert draft.review_status == "review_required" and len(draft.sources["articles"]) == 12
