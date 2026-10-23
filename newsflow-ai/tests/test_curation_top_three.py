"""Top-three selection keeps all inputs and cannot inherit an older video's progress."""
import json
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_curation_all import extend_collection
from test_global_news_policy import GlobalAI
from test_google_news_trends import NOW, article, no_external_calls, prepared
from test_single_workspace import video_fixture

from newsflow.db.models import IntelligenceRun
from newsflow.gui.dashboard_view import dashboard_context
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.curation import enrich, validate_ranking, wire_evidence
from newsflow.intelligence.provider import Options

__all__ = ["no_external_calls", "prepared"]


def test_three_rankings_cover_all_eighty_one_and_keep_safety_contract():
    articles = [{**article(), "id": i, "search_provenance": {"provider":"serpapi", "search_run_id":28,
                "search_status":"success", "searched_at":NOW.isoformat(),
                "edition_appearances":[{"region":"US","role":"global"}]}} for i in range(1,82)]
    evidence = enrich({"articles":articles, "groups":[[i] for i in range(1,82)]},
                       {"collection_policy":"global_trends_v1", "collection_context_id":29}, NOW, top_k=3)
    ai = GlobalAI("claude_api")
    output = ai.analyze(evidence, Options())
    result = validate_ranking(output, evidence)
    assert len(result["ranking"]) == 3 and len(result["comparisons"]) == 81
    assert evidence["curation_contract"]["videos_per_schedule"] == 1
    assert evidence["curation_contract"]["collection_context_id"] == 29
    assert "최대 3개" in evidence["curation_contract"]["instructions"]
    broken = deepcopy(output)
    broken["comparisons"].pop()
    with pytest.raises(ValueError,match="누락"):
        validate_ranking(broken,evidence)
    excessive = deepcopy(output)
    excessive["ranking"].append(deepcopy(excessive["ranking"][-1]))
    with pytest.raises(ValueError):
        validate_ranking(excessive,evidence)


def test_wire_compaction_preserves_all_text_urls_dates_matches_and_region_observations():
    source = article()
    source["search_provenance"] = {"search_run_id":28,"provider":"serpapi","search_status":"success",
                                   "searched_at":NOW.isoformat(), "edition_appearances":[{"region":"US","language":"en"}]}
    evidence = enrich({"articles":[source],"groups":[[1]]},None,NOW,top_k=3)
    before = deepcopy(evidence)
    wire = wire_evidence(evidence)
    for field in ("id","title","summary","published_at","sources","curation_recency"):
        assert wire["articles"][0][field] == evidence["articles"][0][field]
    assert wire["articles"][0]["search_interest"]["matches"] == evidence["articles"][0]["search_interest"]["matches"]
    assert wire["articles"][0]["search_provenance"]["edition_appearances"] == source["search_provenance"]["edition_appearances"]
    assert wire["search_runs"]["28"]["searched_at"] == NOW.isoformat()
    assert evidence == before
    provider = AnthropicProvider(lambda: "fixture")
    bodies = []
    provider._post = lambda body,_options: bodies.append(body) or {}
    provider._message("instruction",{"evidence":evidence},Options("claude-sonnet-4-6"),analysis=True)
    assert "tools" not in bodies[0]
    assert json.loads(bodies[0]["messages"][0]["content"])["evidence"]["articles"][0]["sources"] == source["sources"]
    limit = bodies[0]["output_config"]["format"]["schema"]["properties"]["ranking"]["description"]
    assert json.loads(limit.split("Local validation: ")[1])["maxItems"] == 3


def test_latest_collection_replaces_old_script_and_then_tracks_matching_analysis(client,app,prepared):
    fixture = video_fixture(app,"이전 영상의 대본")
    ctx = extend_collection(app,81)
    with app.state.sessions.begin() as session:
        trend = session.get(IntelligenceRun,ctx["run_id"])
        trend.created_at = datetime.now(UTC) + timedelta(seconds=1)
    tasks = [{"id":"old","kind":"manual","status":"waiting_review","updated_at":datetime.now(UTC).isoformat(),
              "draft_id":fixture["draft_id"],"render_job_id":fixture["id"]}]
    with app.state.sessions() as session:
        view = dashboard_context(session,tasks)
        assert view["focus"]["kind"] == "collection" and view["excerpt"] == ""
        assert [s["state"] for s in view["workflow"]["steps"]] == ["done","current","pending","pending","pending"]
    html = client.get("/").text
    workflow = re.search(r'<div class="workflow-script">.*?</p>', html, re.DOTALL).group()
    assert "이전 영상의 대본" not in workflow and "대본 생성 전" in workflow
    with app.state.sessions.begin() as session:
        trend = session.get(IntelligenceRun,ctx["run_id"])
        row = IntelligenceRun(kind="analysis",provider="claude_api",status="success",options={},
                 evidence={"articles":[{"id":a.id} for a in ctx["articles"]], "curation_contract":{"top_k":3}},
                 result={"ranking":[{"title":"이번 회차 추천 뉴스"}]},message="Synthetic",
                 created_at=trend.created_at+timedelta(seconds=1))
        session.add(row)
    with app.state.sessions() as session:
        view = dashboard_context(session,tasks)
        assert view["focus"]["title"] == "이번 회차 추천 뉴스"
        assert [s["state"] for s in view["workflow"]["steps"]] == ["done","done","current","pending","pending"]
        assert len(list(session.scalars(select(IntelligenceRun).where(IntelligenceRun.kind=="script")))) == 1  # Old fixture only.
