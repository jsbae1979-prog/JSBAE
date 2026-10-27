"""Isolated Google RSS + AI response fixtures. No accounts, live HTTP, CLI or renderer."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from conftest import csrf
from sqlalchemy import select
from test_api_news_pipeline import MODELS, FixtureKey

from newsflow.db.models import APIRequestReservation, AppSetting, ContentDraft, IntelligenceRun, NewsSource
from newsflow.intelligence.api_providers import AnthropicProvider, FakeAPIProvider
from newsflow.intelligence.api_settings import FakeAPIBudgetService, save_api_settings
from newsflow.intelligence.curation import enrich, ranking_json, validate_ranking, validate_script
from newsflow.intelligence.provider import Options, ProviderTimeoutError
from newsflow.intelligence.service import IntelligenceService
from newsflow.intelligence.settings import write_settings, write_studio_settings
from newsflow.news.curator import Curator
from newsflow.news.rss_adapter import ErrorKind, FeedError
from newsflow.news.trends import GOOGLE_NEWS_URL, TRENDS_URL, parse_trends, trend_matches

NOW = datetime(2026, 10, 20, 6, tzinfo=UTC)
TREND = b'''<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item>
<title>solar battery</title><pubDate>Tue, 20 Oct 2026 05:00:00 GMT</pubDate>
<ht:approx_traffic>20K+</ht:approx_traffic><ht:news_item>
<ht:news_item_url>https://example.com/solar</ht:news_item_url></ht:news_item></item></channel></rss>'''
FEED = '''<rss version="2.0"><channel><title>Google News fixture</title>
<item><title>solar battery 연구 발표</title><link>https://example.com/solar</link><description>배터리 효율을 높이는 연구 계획과 연구 범위에 대한 합성 자료입니다.</description><source>합성 출처 A</source><pubDate>Tue, 20 Oct 2026 05:00:00 GMT</pubDate></item>
<item><title>배터리 연구 계획 공개</title><link>https://example.org/battery</link><description>배터리 효율 연구에 관한 더 자세한 합성 자료입니다. 연구 목표와 적용 범위를 설명했지만 실제 제품 출시와 성능은 아직 확인하지 않았습니다.</description><source>합성 출처 B</source><pubDate>Tue, 20 Oct 2026 05:30:00 GMT</pubDate></item>
<item><title>문화 공연 접근성 개선</title><link>https://example.net/culture</link><description>공연 접근성을 높이는 계획에 대한 합성 자료입니다. 관람 지원 방식과 적용 범위를 별도로 확인해야 합니다.</description><source>합성 출처 C</source></item>
</channel></rss>'''.encode()


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    monkeypatch.setattr("newsflow.video.tts.WindowsTTS.voice_details", lambda _: [])
    monkeypatch.setattr("newsflow.video.tts.WindowsTTS.voices", lambda _: [])
    monkeypatch.setattr("urllib.request.build_opener", lambda *_a, **_k: pytest.fail("No live API"))
    monkeypatch.setattr("socket.create_connection", lambda *_a, **_k: pytest.fail("No live network"))
    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: pytest.fail("No CLI/rendering"))


def article():
    return {"id": 1, "title": "solar battery 연구 발표", "summary": "연구 계획 설명", "category": "IT·과학",
            "published_at": NOW.isoformat(), "score": {"total": 99},
            "sources": [{"url": "https://example.com/solar", "publisher": "합성 출처"}]}


def test_trends_not_news_or_views_and_matching_provenance():
    snapshot = parse_trends(TREND, NOW)
    assert snapshot["signals"][0]["traffic"] == "20K+"
    match = trend_matches(article(), snapshot, NOW)
    assert match["status"] == "matched" and match["matches"][0]["match_method"] == "related_url"
    assert match["matches"][0]["trend_started_at"] != article()["published_at"]
    assert "조회수" in snapshot["meaning"]
    assert trend_matches(article(), snapshot, NOW + timedelta(hours=25))["status"] == "stale"
    assert trend_matches(article(), snapshot, NOW - timedelta(seconds=1))["status"] == "stale"
    unrelated = {**article(), "title": "다른 소식", "sources": [{"url": "https://example.net/other"}]}
    assert trend_matches(unrelated, snapshot, NOW)["status"] == "not_matched"
    assert trend_matches(article(), None, NOW)["status"] == "unavailable"


@pytest.mark.parametrize("payload", [b"<html/>", b"<rss><channel/></rss>",
                                      b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///private">]><rss>&e;</rss>'])
def test_malformed_xml_and_entities_fail_closed(payload):
    with pytest.raises(FeedError):
        parse_trends(payload, NOW)


def test_unknown_date_traffic_private_related_url_and_phrase_boundary():
    data = TREND.replace(b"Tue, 20 Oct 2026 05:00:00 GMT", b"unknown").replace(b"20K+", b"")
    data = data.replace(b"https://example.com/solar", b"http://127.0.0.1/private")
    snapshot = parse_trends(data, NOW)
    assert snapshot["signals"][0]["traffic"] is None
    assert snapshot["signals"][0]["trend_started_at"] is None
    assert snapshot["signals"][0]["related_urls"] == []
    a = {**article(), "title": "supersolar battery research", "sources": []}
    assert trend_matches(a, snapshot, NOW)["status"] == "not_matched"


def test_enrichment_ignores_category_old_score_and_preserves_unknown_date():
    base = {"articles": [article(), {**article(), "id": 2, "published_at": None}], "groups": [[1], [2]]}
    enriched = enrich(base, parse_trends(TREND, NOW), NOW)
    assert enriched["articles"][0]["score"] is None
    assert enriched["articles"][1]["curation_recency"] is None
    assert base["articles"][0]["score"] == {"total": 99}


def test_refresh_dedup_durable_signals_source_states_and_no_inference(client, app, fake):
    fake.feeds.update({GOOGLE_NEWS_URL: FEED, TRENDS_URL: TREND})
    before = client.get("/news").text
    assert "Google News + Trends 수집" in before and fake.calls == []
    assert client.post("/news/curation/refresh", data={"csrf_token": csrf(client)}).status_code == 422
    assert fake.calls == []
    token = csrf(client)
    assert client.post("/news/curation/refresh", data={"csrf_token": token, "permission": "true"}).status_code == 200
    assert fake.calls == [GOOGLE_NEWS_URL, TRENDS_URL]
    curator = Curator(app.state.coordinator)
    ctx = curator.context()
    assert ctx["ready"] and len(ctx["articles"]) == 3
    assert ctx["collection"]["added"] == 3
    with app.state.sessions() as session:
        assert not session.scalar(select(NewsSource).where(NewsSource.url == GOOGLE_NEWS_URL)).enabled
        assert all(run.kind == "trends" for run in session.scalars(select(IntelligenceRun)))
    curator.refresh(True)
    restored = Curator(app.state.coordinator).context()
    assert restored["collection"]["duplicates"] == 3 and restored["snapshot"]["signals"]
    assert restored["collection"]["added"] == 0
    fake.feeds[TRENDS_URL] = FeedError("secret-token=DO-NOT-LOG")
    curator.refresh(True)
    ctx = curator.context()
    assert not ctx["ready"] and ctx["snapshot"] is None
    assert "DO-NOT-LOG" not in client.get("/news").text


class CuratorResponse(FakeAPIProvider):
    def __init__(self, mode):
        super().__init__(mode)
        self.payloads = []
        self.failure = None

    def analyze(self, evidence, options):
        self.calls.append("analysis")
        self.payloads.append(deepcopy(evidence))
        if self.failure:
            raise self.failure
        ids = [a["id"] for a in evidence["articles"]]
        groups = [ids[:2], ids[2:]] if len(ids) == 3 else [[i] for i in ids]
        items = []
        for index, group in enumerate(groups, 1):
            rep = max((a for a in evidence["articles"] if a["id"] in group),
                      key=lambda a: (len(a["summary"]), -a["id"]))
            components = {"recency": rep["curation_recency"], "public_interest": 16 if index == 1 else 10,
                          "impact": 15, "shareability": 14, "interest": 16}
            items.append({"rank": index, "article_ids": group,
                          "score": sum(v or 0 for v in components.values()), "components": components,
                          "reason": "합성 자료의 대중 관심과 영향 범위를 비교한 편집 평가입니다.",
                          "summary": "제공 자료 안에서 연구 또는 문화 계획의 의미를 살펴봅니다."})
        return {"overview": "합성 자료의 화제성 편집 평가 · 사실 검증 아님",
                "comparisons": [{"article_ids": group, "reason": "같은 이슈 후보로 비교합니다.",
                                 "uncertainties": "발표 내용과 적용 범위는 원문 검토가 필요합니다."} for group in groups],
                "ranking": items[:evidence["curation_contract"].get("top_k", 10)]}

    def complete(self, evidence, duration, options):
        self.calls.append("script")
        self.payloads.append(deepcopy(evidence))
        if self.failure:
            raise self.failure
        hook = "배터리 연구 계획에서 확인해야 할 핵심은 무엇일까요?"
        content = ("제공된 자료는 효율을 높이기 위한 연구의 목표와 적용 범위를 설명합니다. "
                   "연구 계획이 소개됐다는 점과 실제 성능이 확인됐다는 점은 구분해야 합니다. "
                   "자료만으로 제품 출시나 구체적인 성능을 단정하기는 어렵습니다. "
                   "관련 보도를 비교하고 발표 내용과 실제 적용 범위를 따로 살펴볼 필요가 있습니다.")
        ending = "핵심은 연구 계획과 확인된 결과를 구분하는 것입니다."
        return {"title": "배터리 연구 계획의 핵심", "hook": hook, "summary": "연구 목표와 실제 결과를 구분하는 주제입니다.",
                "closing": ending, "scenes": [
                    {"seconds": seconds, "narration": text, "caption": caption, "material": "직접 제작한 설명 그래픽"}
                    for seconds, text, caption in [(5, hook, "연구 계획의 핵심"),
                                                   (duration - 10, content, "계획과 검증 결과 구분"),
                                                   (5, ending, "원문 확인 필요")]]}


@pytest.fixture(params=["claude_api", "openai"])
def prepared(client, app, fake, request, monkeypatch):
    mode = request.param
    fake.feeds.update({GOOGLE_NEWS_URL: FEED, TRENDS_URL: TREND})
    Curator(app.state.coordinator).refresh(True)
    options = Options(MODELS[mode], max_tokens=3000)
    save_api_settings(app.state.sessions, mode, model=options.model, approved=True,
                      search_enabled=False, search_approved=False, monthly_limit_usd="100",
                      input_price_per_1m="3", output_price_per_1m="15", search_price_per_1k="10",
                      billing_confirmed=True)
    if mode == "openai":
        write_settings(app.state.sessions, mode, options.model, True, 2_000_000, 20)
    write_studio_settings(app.state.sessions, mode, options.model)
    adapter = CuratorResponse(mode)
    service = IntelligenceService(app.state.sessions, api_key_stores={mode: FixtureKey()},
                                  api_providers={mode: adapter}, api_budget=FakeAPIBudgetService(app.state.sessions))
    monkeypatch.setattr("newsflow.gui.curation_routes.service", lambda _: service)
    ids = sorted(a.id for a in Curator(app.state.coordinator).context()["articles"])
    return service, adapter, mode, options, ids


@pytest.mark.parametrize("duration", [30, 45, 60])
def test_fake_api_ranking_script_review_json_and_duplicate_post(client, app, prepared, duration):
    _, adapter, _mode, _, ids = prepared
    payload = {"csrf_token": csrf(client), "collection_context_id": Curator(app.state.coordinator).context()["run_id"], "consent": "true"}
    response = client.post("/news/curation/analyze", data=payload)
    assert response.status_code == 200, response.text
    assert "부분 평가" in response.text and "Google Trends" in response.text
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis"))
        run_id = run.id
        assert run.result["ranking"][0]["representative_id"] == ids[1]
        assert len(run.result["ranking"]) == 2
    assert client.post("/news/curation/analyze", data=payload).status_code == 200
    assert adapter.calls == ["analysis"]
    exported = client.get(f"/news/curation/{run_id}/ranking.json").json()
    assert set(exported) == {"ranking"}
    assert set(exported["ranking"][0]) == {"rank", "title", "score", "reason", "summary"}
    draft_data = {"csrf_token": csrf(client), "analysis_id": run_id, "rank": 1,
                  "duration": duration, "consent": "true"}
    response = client.post("/news/curation/generate", data=draft_data)
    assert response.status_code == 200, response.text
    assert client.post("/news/curation/generate", data=draft_data).status_code == 200
    assert adapter.calls == ["analysis", "script"]
    with app.state.sessions() as session:
        draft = session.scalar(select(ContentDraft))
        draft_id = draft.id
        assert draft.review_status == "review_required" and draft.duration == duration
        assert len(draft.sources["articles"]) == 2 and draft.sources["curation_contract"]
        assert sum(s["seconds"] for s in draft.content["scenes"]) == duration
        reservations = list(session.scalars(select(APIRequestReservation)))
        assert [r.kind for r in reservations] == ["analysis", "script"]
        assert all(r.bounds["search_calls"] == 0 and r.test_only for r in reservations)
    output = client.get(f"/news/curation/drafts/{draft_id}/script.json").json()
    assert set(output["script"]) == {"hook", "content", "ending"}
    assert 150 <= len(" ".join(output["script"].values())) <= 300
    assert client.get("/news").status_code == 200 and client.get(f"/video?draft_id={draft_id}").status_code == 200


def test_no_consent_failed_unknown_not_replayed_and_settings_preserved(client, app, prepared):
    _, adapter, _, _, _ids = prepared
    with app.state.sessions() as session:
        original = {r.key: r.value for r in session.scalars(select(AppSetting))}
    data = {"csrf_token": csrf(client), "collection_context_id": Curator(app.state.coordinator).context()["run_id"]}
    assert client.post("/news/curation/analyze", data=data).status_code == 422
    assert adapter.calls == []
    adapter.failure = ProviderTimeoutError()
    data["consent"] = "true"
    assert client.post("/news/curation/analyze", data=data).status_code == 422
    assert client.post("/news/curation/analyze", data=data).status_code == 409
    assert adapter.calls == ["analysis"]
    with app.state.sessions() as session:
        after = {r.key: r.value for r in session.scalars(select(AppSetting))}
        assert all(after[k] == value for k, value in original.items())
        assert session.scalar(select(APIRequestReservation)).status == "unknown"
        assert session.scalar(select(ContentDraft)) is None


def test_contract_rejects_duplicate_sources_bad_scores_and_fabricated_script():
    evidence = enrich({"articles": [article()], "groups": [[1]]}, parse_trends(TREND, NOW), NOW)
    response = CuratorResponse("claude_api").analyze(evidence, Options())
    accepted = validate_ranking(response, evidence)
    assert ranking_json(accepted)["ranking"][0]["title"] == article()["title"]
    for path in ("score", "recency", "duplicate"):
        changed = deepcopy(response)
        if path == "score":
            changed["ranking"][0]["score"] -= 1
        elif path == "recency":
            changed["ranking"][0]["components"]["recency"] = 10
        else:
            changed["comparisons"].append(deepcopy(changed["comparisons"][0]))
        with pytest.raises(ValueError):
            validate_ranking(changed, evidence)
    script = CuratorResponse("claude_api").complete(evidence, 30, Options())
    validate_script(script, evidence)
    script["scenes"][1]["narration"] += " 999억 투자했습니다."
    with pytest.raises(ValueError):
        validate_script(script, evidence)


def test_robots_blocked_news_has_explicit_local_import_no_hidden_http(client, app, fake):
    fake.feeds.update({GOOGLE_NEWS_URL: FeedError("robots.txt 정책에서 이 RSS 경로를 허용하지 않습니다.",
                                                ErrorKind.ROBOTS), TRENDS_URL: TREND})
    curator = Curator(app.state.coordinator)
    curator.refresh(True)
    assert not curator.context()["ready"] and "[robots]" in curator.context()["error"]
    calls = list(fake.calls)
    data = {"csrf_token": csrf(client), "rss_xml": FEED.decode(), "permission": "true"}
    response = client.post("/news/curation/import", data=data)
    assert response.status_code == 200
    ctx = curator.context()
    assert ctx["ready"] and "사용자 제공" in ctx["message"] and fake.calls == calls
    with app.state.sessions() as session:
        assert session.get(IntelligenceRun, ctx["run_id"]).evidence["news_origin"] == "user_file"
        assert not session.scalar(select(NewsSource).where(NewsSource.url == GOOGLE_NEWS_URL)).enabled
    data["rss_xml"] = FEED.decode().replace("https://example.com/solar", "http://127.0.0.1/private")
    assert client.post("/news/curation/import", data=data).status_code == 422
    assert fake.calls == calls


def test_csrf_and_origin_protection_still_block_import_and_refresh(client, fake):
    assert client.post("/news/curation/refresh", data={"permission": "true"}).status_code == 403
    token = csrf(client)
    assert client.post("/news/curation/refresh", data={"csrf_token": token, "permission": "true"},
                       headers={"Origin": "https://external.example.com"}).status_code == 403
    assert fake.calls == []


def test_approval_gate_blocks_before_any_ai_and_provider_switch_is_not_a_fallback(client, app, prepared):
    _, adapter, mode, options, _ids = prepared
    save_api_settings(app.state.sessions, mode, model=options.model, approved=False,
                      search_enabled=False, search_approved=False, monthly_limit_usd="100",
                      input_price_per_1m="3", output_price_per_1m="15", search_price_per_1k="10",
                      billing_confirmed=True)
    data = {"csrf_token": csrf(client), "collection_context_id": Curator(app.state.coordinator).context()["run_id"], "consent": "true"}
    assert client.post("/news/curation/analyze", data=data).status_code == 422
    assert adapter.calls == []
    write_studio_settings(app.state.sessions, "offline", "offline")
    assert client.post("/news/curation/analyze", data=data).status_code == 422
    assert adapter.calls == []


def test_draft_generation_bound_to_ranked_group_model_and_review(client, app, prepared):
    svc, adapter, mode, options, ids = prepared
    ctx = Curator(app.state.coordinator).context()
    run_id = svc.analyze(ids, mode, True, options, curate=True, trend_snapshot=ctx["snapshot"])
    data = {"csrf_token": csrf(client), "analysis_id": run_id, "rank": 1, "duration": 30, "consent": "true"}
    assert client.post("/news/curation/generate", data={**data, "consent": "false"}).status_code == 422
    write_studio_settings(app.state.sessions, "offline", "offline")
    assert client.post("/news/curation/generate", data=data).status_code == 422
    assert adapter.calls == ["analysis"]
    write_studio_settings(app.state.sessions, mode, options.model)
    assert client.post("/news/curation/generate", data=data).status_code == 200
    with app.state.sessions() as session:
        draft = session.scalar(select(ContentDraft))
        identifier, revision, bad = draft.id, draft.revision, deepcopy(draft.content)
    bad["scenes"][1]["narration"] = "근거 없는 888억 투자 소식입니다."
    with pytest.raises(Exception) as error:
        svc.edit(identifier, revision, bad)
    assert error.value.code == "news_usage_blocked"
    with app.state.sessions() as session:
        assert session.get(ContentDraft, identifier).review_status == "review_required"


def test_claude_wire_schema_contains_required_ranking_only_for_curator(monkeypatch):
    provider = AnthropicProvider(lambda: "fixture")
    calls = []
    monkeypatch.setattr(provider, "_post", lambda body, _: calls.append(body) or {})
    evidence = enrich({"articles": [article()], "groups": [[1]]}, parse_trends(TREND, NOW), NOW)
    provider._message("instruction", {"evidence": evidence}, Options("claude-sonnet-4-6"), analysis=True)
    schema = calls[0]["output_config"]["format"]["schema"]
    assert "ranking" in schema["required"] and "tools" not in calls[0]
    provider._message("instruction", {"evidence": {}}, Options("claude-sonnet-4-6"), analysis=True)
    assert "ranking" not in calls[1]["output_config"]["format"]["schema"]["properties"]
