"""Multi-edition discovery and Korean-audience ranking. All transport/accounting is Fake."""
from copy import deepcopy
from uuid import uuid4

import pytest
from conftest import csrf
from sqlalchemy import select
from test_api_news_pipeline import FixtureKey
from test_google_news_trends import TREND, CuratorResponse, no_external_calls

from newsflow.db.models import AppSetting, ContentDraft, IntelligenceRun, NewsArticle, NewsSource
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.api_settings import FakeAPIBudgetService, save_api_settings
from newsflow.intelligence.credentials import FakeCipher
from newsflow.intelligence.curation import GLOBAL_COMPONENTS, GLOBAL_PROFILE, validate_ranking
from newsflow.intelligence.provider import Options
from newsflow.intelligence.service import IntelligenceService
from newsflow.intelligence.settings import write_studio_settings
from newsflow.news.curator import Curator
from newsflow.news.global_collection import EDITIONS, GLOBAL_POLICY
from newsflow.news.serpapi import SerpApiAdapter, SerpApiError, SerpApiKeys, parse_result
from newsflow.news.serpapi_settings import save

__all__ = ["no_external_calls"]
TITLES = ["OpenAI research tools", "Museum access and public arts", "Fusion laboratory experiment",
          "Football international competition", "지역 의료 공공 서비스"]
TERMS = {"KR": "의료", "US": "OpenAI", "GB": "Museum", "JP": "Fusion", "BR": "Football"}


class GlobalAdapter:
    test_only = True

    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at

    def search(self, **params):
        self.calls.append(params)
        if len(self.calls) == self.fail_at:
            raise SerpApiError("timeout_unknown")
        index = len(self.calls) - 1
        return parse_result({"search_metadata": {"status": "Success"}, "news_results": [
            {"title": TITLES[index], "link": f"https://example.com/story/{index}",
             "snippet": "합성 뉴스 자료의 범위와 영향은 원문 검토가 필요합니다.", "source": {"name": "합성 출처"}}]},
            region=params["region"], language=params["language"])


class GlobalAI(CuratorResponse):
    def analyze(self, evidence, options):
        self.calls.append("analysis")
        self.payloads.append(deepcopy(evidence))
        ids = [a["id"] for a in evidence["articles"]]
        ranking = []
        for index, article in enumerate(evidence["articles"]):
            # Deliberately rank the Korean item first: 80:20 is not a final-ranking quota.
            high = article["id"] == max(ids)
            values = {name: 20 if high else 10 for name in GLOBAL_COMPONENTS}
            if not article["search_interest"].get("matches"):
                values["search_growth"] = None
            ranking.append({"rank": 1, "article_ids": [article["id"]], "components": values,
                            "score": round(sum(v or 0 for v in values.values()) * 100 / 120),
                            "reason": "관측된 급상승과 수집 응답을 참고한 한국 시청자 관심도 AI 추정입니다.",
                            "summary": "제공 자료의 주제와 적용 범위를 확인합니다."})
        ranking.sort(key=lambda item: item["score"], reverse=True)
        for index, item in enumerate(ranking, 1):
            item["rank"] = index
        return {"overview": "전체 후보에 대한 한국 시청자 관점의 AI 추정 · 사실 검증 아님",
                "comparisons": [{"article_ids": [i], "reason": "다른 사건으로 비교합니다.",
                                 "uncertainties": "실제 노출수와 SNS 공유수 미확인"} for i in ids],
                "ranking": ranking[:evidence["curation_contract"].get("top_k", 10)]}


@pytest.fixture
def global_setup(app, fake):
    for region, term in TERMS.items():
        fake.feeds[f"https://trends.google.com/trending/rss?geo={region}"] = TREND.replace(b"solar battery", term.encode())
    keys = SerpApiKeys(app.state.config.data_dir, FakeCipher())
    save(app.state.sessions, keys, key="b" * 64, approved=True)
    adapter = GlobalAdapter()
    app.state.serpapi_keys, app.state.serpapi_adapter = keys, adapter
    return keys, adapter


def request(client, token=None, **overrides):
    data = {"csrf_token": csrf(client), "consent": "true", "request_token": token or uuid4().hex,
            "collection_policy": GLOBAL_POLICY, "maximum_requests": 5, **overrides}
    return client.post("/news/curation/serpapi", data=data)


def test_trends_first_multi_edition_all_candidates_and_no_automatic_ai(client, app, fake, global_setup):
    keys, adapter = global_setup
    with app.state.sessions() as session:
        original = {r.key: r.value for r in session.scalars(select(AppSetting))}
    assert "최대 5회 조회" in client.get("/news").text
    assert fake.calls == adapter.calls == []
    token = uuid4().hex
    assert request(client, token).status_code == 200
    assert [(r["region"], r["language"]) for r in adapter.calls] == [(r, lang) for r, lang, *_ in EDITIONS]
    assert all(term in adapter.calls[0]["query"] for term in TERMS.values())
    assert all(r["query"] is None for r in adapter.calls[1:])
    assert fake.calls == [f"https://trends.google.com/trending/rss?geo={r}" for r in TERMS]
    ctx = Curator(app.state.coordinator).context()
    assert ctx["ready"] and len(ctx["articles"]) == 5
    assert ctx["candidate_mix"]["global_edition_unique"] == 4
    assert ctx["candidate_mix"]["korea_edition_unique"] == 1
    assert ctx["candidate_mix"]["global_edition_percent"] == 80
    assert ctx["snapshot"]["region"] == "MULTI"
    assert request(client, token).status_code == 200 and len(adapter.calls) == 5
    with app.state.sessions() as session:
        search = session.scalar(select(IntelligenceRun).where(IntelligenceRun.provider == "serpapi"))
        assert search.result["provider_billed_credits"] is None
        assert search.result["local_request_attempts"] == 5 and search.result["ai_calls"] == 0
        assert all(r["status"] == "success" for r in search.result["requests"])
        assert all(source.enabled is False for source in session.scalars(select(NewsSource)))
        assert all(session.get(AppSetting, name).value == value for name, value in original.items())
        assert session.scalar(select(ContentDraft)) is None
        assert session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis")) is None
    assert keys.status()["configured"]


def test_count_consent_and_policy_change_block_before_transport(client, app, fake, global_setup):
    _, adapter = global_setup
    assert request(client, maximum_requests=1).status_code == 422
    assert request(client, consent="false").status_code == 422
    assert adapter.calls == fake.calls == []
    token = uuid4().hex
    assert request(client, token).status_code == 200
    assert request(client, token, collection_policy="korea_v1", maximum_requests=1).status_code == 422
    assert len(adapter.calls) == 5


def test_failure_preserves_partial_unknown_history_no_retry_or_provider_switch(client, app, global_setup):
    _, adapter = global_setup
    adapter.fail_at = 2
    token = uuid4().hex
    response = request(client, token)
    assert response.status_code == 422
    assert len(adapter.calls) == 2
    assert request(client, token).status_code == 200  # Stored failed result, no network replay.
    assert len(adapter.calls) == 2
    assert not Curator(app.state.coordinator).context()["ready"]
    with app.state.sessions() as session:
        assert len(list(session.scalars(select(NewsArticle)))) == 1
        run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.provider == "serpapi"))
        assert run.status == "unknown" and run.result["local_request_attempts"] == 2
        assert [r["status"] for r in run.result["requests"]] == ["success", "unknown"]
        assert run.result["provider_billed_credits"] is None and len(run.result["article_ids"]) == 1


def test_no_trends_blocks_before_paid_news_request(client, app, fake, global_setup):
    _, adapter = global_setup
    fake.feeds.clear()
    response = request(client)
    assert response.status_code == 422 and "유료 뉴스 조회를 시작하지 않았습니다" in response.text
    assert adapter.calls == []


def test_fresh_trends_reused_without_hidden_rss_or_ratio_refill(client, app, fake, global_setup):
    _, adapter = global_setup
    original = adapter.search

    def repeated_story(**params):
        if params["region"] == "kr":
            adapter.calls.append(params)
            return parse_result({"search_metadata": {"status": "Success"}, "news_results": [
                {"title": TITLES[0], "link": "https://example.com/story/0", "source": {"name": "합성 한국 출처"}}]})
        return original(**params)

    adapter.search = repeated_story
    assert request(client).status_code == 200
    rss_calls = list(fake.calls)
    ctx = Curator(app.state.coordinator).context()
    assert len(ctx["articles"]) == 4
    assert ctx["candidate_mix"]["both_editions"] == 1
    assert ctx["candidate_mix"]["global_edition_percent"] == 100  # Actual response mix, no manufactured 80%.
    # A separate explicit authorized batch reuses fresh observations, not automatic replenishment.
    adapter.search = lambda **params: (adapter.calls.append(params) or parse_result({
        "search_metadata": {"status": "Success"}, "news_results": [
            {"title": "기존 합성 주제", "link": "https://example.com/story/0"}]}))
    assert request(client).status_code == 200
    assert len(adapter.calls) == 10 and fake.calls == rss_calls


def test_global_wire_uses_exact_region_language_query_and_no_search_addons(monkeypatch, tmp_path):
    keys = SerpApiKeys(tmp_path, FakeCipher())
    keys.save("b" * 64)
    adapter = SerpApiAdapter(keys)
    seen = []
    import json
    from urllib.parse import parse_qs, urlsplit

    payload = {"search_metadata": {"status": "Success"}, "news_results": [{"title": "Fixture", "link": "https://example.com/a"}]}
    monkeypatch.setattr(adapter, "_open", lambda req, timeout: seen.append(req) or json.dumps(payload).encode())
    _, metadata = adapter.search(region="jp", language="ja", query='"Fusion" when:1d')
    query = parse_qs(urlsplit(seen[0].full_url).query)
    assert query["gl"] == ["jp"] and query["hl"] == ["ja"] and query["q"] == ['"Fusion" when:1d']
    assert "topic_token" not in query and metadata["region"] == "JP" and metadata["language"] == "ja"


def test_all_global_candidates_korean_audience_six_scores_and_script_review(client, app, global_setup, monkeypatch):
    assert request(client).status_code == 200
    save_api_settings(app.state.sessions, "claude_api", model="claude-sonnet-4-6", approved=True,
                      search_enabled=False, search_approved=False, monthly_limit_usd="100", request_limit_usd="10",
                      input_price_per_1m="3", output_price_per_1m="15", search_price_per_1k="10", billing_confirmed=True)
    write_studio_settings(app.state.sessions, "claude_api", "claude-sonnet-4-6")
    ai = GlobalAI("claude_api")
    svc = IntelligenceService(app.state.sessions, api_key_stores={"claude_api": FixtureKey()},
                              api_providers={"claude_api": ai}, api_budget=FakeAPIBudgetService(app.state.sessions))
    monkeypatch.setattr("newsflow.gui.curation_routes.service", lambda _: svc)
    ctx = Curator(app.state.coordinator).context()
    data = {"csrf_token": csrf(client), "collection_context_id": ctx["run_id"], "consent": "true"}
    response = client.post("/news/curation/analyze", data=data)
    assert response.status_code == 200, response.text
    assert "한국 시청자 관심도" in response.text and "실제 SNS 확산·기사 노출수 미측정" in response.text
    assert len(ai.payloads[0]["articles"]) == 5
    assert ai.payloads[0]["curation_contract"]["profile"] == GLOBAL_PROFILE
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis"))
        identifier = run.id
        assert run.result["ranking"][0]["representative_id"] == max(a["id"] for a in run.evidence["articles"])
        assert set(run.result["ranking"][0]["components"]) == set(GLOBAL_COMPONENTS)
        assert all(a["search_provenance"]["edition_appearances"] for a in run.evidence["articles"])
    assert client.post("/news/curation/analyze", data=data).status_code == 200
    assert ai.calls == ["analysis"]
    response = client.post("/news/curation/generate", data={"csrf_token": csrf(client), "analysis_id": identifier,
                                                           "rank": 1, "duration": 30, "consent": "true"})
    assert response.status_code == 200, response.text
    with app.state.sessions() as session:
        assert session.scalar(select(ContentDraft)).review_status == "review_required"
    provider = AnthropicProvider(lambda: "fixture")
    wire = []
    monkeypatch.setattr(provider, "_post", lambda body, options: wire.append(body) or {})
    provider._message("instruction", {"evidence": ai.payloads[0]}, Options("claude-sonnet-4-6"), analysis=True)
    schema = wire[0]["output_config"]["format"]["schema"]
    assert "GlobalComponents" in schema["$defs"] and "tools" not in wire[0]


def test_no_observation_must_not_be_invented_as_measured_growth_or_frequency(client, app, global_setup):
    assert request(client).status_code == 200
    svc = IntelligenceService(app.state.sessions)
    ctx = Curator(app.state.coordinator).context()
    from newsflow.db.models import utcnow
    from newsflow.intelligence.curation import enrich

    evidence = enrich(svc.evidence_for([a.id for a in ctx["articles"]]), ctx["snapshot"], utcnow())
    output = GlobalAI("claude_api").analyze(evidence, Options())
    validate_ranking(output, evidence)
    missing = deepcopy(evidence)
    for article in missing["articles"]:
        article["search_interest"]["matches"] = []
    with pytest.raises(ValueError, match="검색 관심 관측"):
        validate_ranking(output, missing)
    missing = deepcopy(evidence)
    for article in missing["articles"]:
        article["search_provenance"]["edition_appearances"] = []
    with pytest.raises(ValueError, match="등장 빈도"):
        validate_ranking(output, missing)
