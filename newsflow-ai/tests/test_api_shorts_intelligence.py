"""API stage wiring on isolated SQLite and intercepted adapters; no real accounts."""

from copy import deepcopy

import pytest
from sqlalchemy import select
from test_api_news_pipeline import MODELS, FixtureKey

from newsflow.db.models import APIRequestReservation, ContentDraft, IntelligenceRun, NewsArticle, NewsSource
from newsflow.intelligence.api_providers import AnthropicProvider, FakeAPIProvider
from newsflow.intelligence.api_settings import FakeAPIBudgetService, save_api_settings
from newsflow.intelligence.news_usage import API_SCRIPT_METHOD, api_news_contract, safe_topic_script
from newsflow.intelligence.provider import (
    OpenAIProvider,
    Options,
    ProviderTimeoutError,
    prompt_instruction,
)
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import write_settings


class MaterialResponse(FakeAPIProvider):
    """Deterministic response fixture, not a production prose generator."""

    def __init__(self, provider):
        super().__init__(provider)
        self.payloads = []

    def analyze(self, evidence, options):
        self.payloads.append(("analysis", deepcopy(evidence), options.model))
        result = super().analyze(evidence, options)
        result["overview"] = evidence["articles"][0]["title"] + " 관련 자료를 검토할 분석 초안입니다."
        return result

    def complete(self, evidence, duration, options):
        self.payloads.append(("script", deepcopy(evidence), options.model))
        result = super().complete(evidence, duration, options)
        topic = evidence["articles"][0]["title"]
        result["title"] = topic + " · 주제 설명"
        result["hook"] = topic + "에서 살펴볼 쟁점은 무엇일까요?"
        result["scenes"][0]["narration"] = topic + "에 관한 자료를 참고해 주제를 설명합니다. 개별 사건은 미확인입니다."
        result["scenes"][0]["caption"] = topic + " · 사실 확인 필요"
        result["scenes"][0]["material"] = topic + " 설명 카드"
        return result


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    monkeypatch.setattr("urllib.request.build_opener", lambda *_a, **_k: pytest.fail("No real HTTP"))
    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: pytest.fail("No CLI or render"))


@pytest.fixture(params=["openai", "claude_api"])
def api(app, request):
    sessions, mode = app.state.sessions, request.param
    options = Options(model=MODELS[mode], max_tokens=3000)
    save_api_settings(sessions, mode, model=options.model, approved=True, search_enabled=True, search_approved=True,
                      request_limit_usd="10", monthly_limit_usd="100", input_price_per_1m="3",
                      output_price_per_1m="15", search_price_per_1k="10", billing_confirmed=True,
                      account_remaining_usd="100")
    if mode == "openai":
        write_settings(sessions, mode, options.model, True, 2_000_000, 20)
    adapter = MaterialResponse(mode)
    service = IntelligenceService(sessions, api_key_stores={mode: FixtureKey()}, api_providers={mode: adapter},
                                  api_budget=FakeAPIBudgetService(sessions))
    with sessions.begin() as session:
        source = NewsSource(name="합성 자료", url="https://example.com/rss", enabled=False)
        session.add(source)
        session.flush()
        ids = []
        for title, path in [("반도체 전력 효율", "technology"), ("스마트폰 수리 접근성", "articles/repair")]:
            article = NewsArticle(title=title, summary=title + "를 살펴보는 합성 참고 자료입니다.",
                                  publisher="합성 출처", source_id=source.id, category="it",
                                  url=f"https://example.com/{path}", canonical_url=f"https://example.com/{path}")
            session.add(article)
            session.flush()
            ids.append(article.id)
    yield service, adapter, sessions, mode, options, ids
    app.state.coordinator.close()
    app.state.video.close()


@pytest.mark.parametrize("level", ["QUICK", "STANDARD"])
@pytest.mark.parametrize("duration", [30, 45, 60])
def test_api_analysis_and_script_use_input_contract_and_independent_reservations(api, level, duration):
    service, adapter, sessions, mode, options, ids = api
    outputs = []
    for identifier in ids:
        analysis = service.analyze([identifier], mode, True, options, news_usage=level)
        draft_id = service.generate(analysis, duration, mode, True, options, news_usage=level)
        with sessions() as session:
            draft = session.get(ContentDraft, draft_id)
            outputs.append(deepcopy(draft.content))
            assert draft.sources["script_method"] == "api_grounded_v2"
            assert draft.sources["script_prompt_version"] == "v2"
            assert draft.sources["news_usage_result"]["verification_status"] == "NOT VERIFIED"
            assert draft.sources["articles"][0]["sources"]
            assert draft.sources["analysis_result"]["overview"] == session.get(IntelligenceRun, analysis).result["overview"]
            assert draft.content != safe_topic_script(draft.sources, duration)
            assert draft.duration == duration and draft.review_status == "review_required"
    assert adapter.calls == ["analysis", "script", "analysis", "script"]
    assert outputs[0]["title"] != outputs[1]["title"]
    assert outputs[0]["scenes"][0] != outputs[1]["scenes"][0]
    for kind, payload, model in adapter.payloads:
        assert model == options.model
        assert payload["news_usage_contract"]["mode"] == level
        if kind == "script":
            contract = payload["news_usage_contract"]
            assert contract["duration_seconds"] == duration
            units = contract["narration_spoken_units_target"]
            assert duration * 3 < units["minimum"] < units["maximum"] < duration * 5
            assert contract["speech_estimate"]["target_seconds_minimum"] == duration * .90
    with sessions() as session:
        rows = list(session.scalars(select(APIRequestReservation)))
        assert len(rows) == 4
        assert [row.kind for row in rows] == ["analysis", "script", "analysis", "script"]
        assert all(row.bounds["search_calls"] == 0 and row.test_only and row.status == "success" for row in rows)


def test_api_script_edit_does_not_require_local_strings_but_remains_review_required(api):
    service, adapter, sessions, mode, options, ids = api
    analysis = service.analyze(ids[:1], mode, True, options, news_usage="QUICK")
    draft_id = service.generate(analysis, 30, mode, True, options, news_usage="QUICK")
    with sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        changed, revision = deepcopy(draft.content), draft.revision
    changed["scenes"][0]["narration"] = "반도체의 전력 효율을 이해할 때 사용 목적과 소비 전력을 함께 살펴볼 수 있습니다."
    changed["scenes"][0]["caption"] = "전력 효율을 이해하는 관점"
    service.edit(draft_id, revision, changed)
    with sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.content == changed and draft.review_status == "review_required"
        assert any(note["code"] == "total_narration_too_short" for note in draft.review_notes)
    changed["scenes"][0]["narration"] = "판매가 9876억 원을 기록했습니다."
    with pytest.raises(IntelligenceError, match="해석형 대본의 수치·날짜·인용 근거") as rejected:
        service.edit(draft_id, revision + 1, changed)
    assert rejected.value.code == "news_usage_blocked"
    with sessions() as session:
        stored = session.get(ContentDraft, draft_id)
        assert stored.revision == revision + 1 and stored.review_status == "review_required"
        assert "9876" not in stored.content["scenes"][0]["narration"]
    assert adapter.calls == ["analysis", "script"]


def test_verified_and_missing_consent_never_invoke_api(api):
    service, adapter, sessions, mode, options, ids = api
    for level, consent in [("QUICK", False), ("VERIFIED", True)]:
        with pytest.raises(IntelligenceError):
            service.analyze(ids[:1], mode, consent, options, news_usage=level)
    with sessions() as session:
        assert session.scalar(select(APIRequestReservation)) is None
    assert adapter.calls == []


@pytest.mark.parametrize("stage", ["analysis", "script"])
def test_api_failure_has_no_local_fallback_or_extra_request(api, stage):
    service, adapter, sessions, mode, options, ids = api
    if stage == "script":
        analysis = service.analyze(ids[:1], mode, True, options, news_usage="STANDARD")
    adapter.result = ProviderTimeoutError()
    with pytest.raises(IntelligenceError):
        if stage == "analysis":
            service.analyze(ids[:1], mode, True, options, news_usage="STANDARD")
        else:
            service.generate(analysis, 30, mode, True, options, news_usage="STANDARD")
    assert adapter.calls == (["analysis"] if stage == "analysis" else ["analysis", "script"])
    with sessions() as session:
        runs = list(session.scalars(select(IntelligenceRun).order_by(IntelligenceRun.id)))
        assert all(run.provider == mode for run in runs)
        assert runs[-1].status == "failed"
        rows = list(session.scalars(select(APIRequestReservation).order_by(APIRequestReservation.created_at)))
        assert rows[-1].status == "unknown"
        assert session.scalar(select(ContentDraft)) is None


def test_api_provider_or_model_or_level_cannot_change_between_stages(api):
    service, adapter, _, mode, options, ids = api
    analysis = service.analyze(ids[:1], mode, True, options, news_usage="QUICK")
    for kwargs in [{"mode": "offline"}, {"options": Options(model="other-model")}, {"news_usage": "STANDARD"}]:
        arguments = {"mode": mode, "consent": True, "options": options, "news_usage": "QUICK", **kwargs}
        with pytest.raises(IntelligenceError):
            service.generate(analysis, 30, **arguments)
    assert adapter.calls == ["analysis"]


def test_legacy_local_drafts_keep_strict_gate_and_never_call_an_api(api):
    service, adapter, sessions, mode, _, ids = api
    analysis = service.create_topic_analysis(ids[:1], "STANDARD", selected_provider=mode)
    draft_id = service.generate_topic(analysis, 30, "STANDARD")
    with sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        changed, revision = deepcopy(draft.content), draft.revision
    changed["title"] = "새로운 자유 대본"
    with pytest.raises(IntelligenceError):
        service.edit(draft_id, revision, changed)
    assert adapter.calls == []


def test_quick_and_standard_have_distinct_api_instructions():
    payload = {"articles": [{"id": 1, "title": "기술", "sources": [{"url": "https://example.com/technology"}]}]}
    quick = api_news_contract(payload, "QUICK", 60)
    standard = api_news_contract(payload, "STANDARD", 60)
    assert quick["structure"] != standard["structure"]
    assert standard["role_orders"] == [["fact", "meaning", "meaning", "action"], ["fact", "meaning", "action", "next"]]
    assert quick["role_orders"] == [["fact", "meaning", "action"]]
    assert "배경·핵심 쟁점" in standard["structure"] and "최대 2문장" in quick["structure"]
    legacy_quick = api_news_contract(payload, "QUICK", 60, version="v1")
    legacy_standard = api_news_contract(payload, "STANDARD", 60, version="v1")
    assert legacy_quick["structure"] != legacy_standard["structure"]
    assert "배경 → 핵심 쟁점" in legacy_standard["structure"]
    assert "간결하게" in legacy_quick["structure"]


def test_saved_speech_rate_and_pause_reach_api_planning_contract(api):
    service, adapter, sessions, mode, options, ids = api
    service.speech = {"rate": 3, "pause_ms": 500}
    analysis = service.analyze(ids[:1], mode, True, options, news_usage="STANDARD")
    draft_id = service.generate(analysis, 60, mode, True, options, news_usage="STANDARD")
    contract = adapter.payloads[-1][1]["news_usage_contract"]
    assert contract["speech_estimate"]["rate"] == 3
    assert contract["speech_estimate"]["pause_ms"] == 500
    assert contract["prompt_version"] == "v2"
    # Independent version-specific expectations: seconds, not speech rate.
    for version, sentences, pauses, minimum in (("v1", 8, 4.8, 284), ("v2", 6, 3.1, 294)):
        expected = api_news_contract({"articles": [{"id": 1, "title": "합성", "sources": []}]},
                                     "STANDARD", 60, speech={"rate": 3, "pause_ms": 500}, version=version)
        estimate = expected["speech_estimate"]
        assert estimate["scene_count_hint"] == 4 and estimate["sentence_count_hint"] == sentences
        assert estimate["rate"] == 3 and estimate["pause_ms"] == 500
        assert estimate["estimated_pauses_seconds"] == pauses
        assert expected["narration_spoken_units_target"]["minimum"] == minimum
    assert contract["speech_estimate"]["estimated_pauses_seconds"] == 3.1
    assert contract["narration_spoken_units_target"]["minimum"] == 294
    with sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        assert any(note["code"] == "total_narration_too_short" for note in draft.review_notes)
    assert adapter.calls == ["analysis", "script"]


def test_new_api_policy_rejects_unmanaged_service_before_any_request(app):
    adapter = FakeAPIProvider("openai")
    service = IntelligenceService(app.state.sessions, provider=adapter)
    with pytest.raises(IntelligenceError) as failure:
        service.analyze([1], "openai", True, Options(), news_usage="QUICK")
    assert failure.value.code == "ai_budget"
    with app.state.sessions.begin() as session:
        analysis = IntelligenceRun(kind="analysis", provider="openai", status="success", options={"model": "gpt-4o-mini"},
                                   evidence={"script_method": API_SCRIPT_METHOD}, result={}, message="합성 저장 분석")
        session.add(analysis)
        session.flush()
        identifier = analysis.id
    with pytest.raises(IntelligenceError) as failure:
        service.generate(identifier, 30, "openai", True, Options(), news_usage="QUICK")
    assert failure.value.code == "ai_budget"
    assert adapter.calls == []
    with app.state.sessions() as session:
        assert session.scalar(select(APIRequestReservation)) is None
        assert session.scalar(select(ContentDraft)) is None
    app.state.coordinator.close()
    app.state.video.close()


@pytest.mark.parametrize("factory", [OpenAIProvider, AnthropicProvider])
def test_existing_api_adapters_send_news_contract_without_search_tool(factory, monkeypatch):
    provider = factory(lambda: "synthetic")
    payload = {"articles": [{"title": "주제", "sources": [{"url": "https://example.com/technology"}]}]}
    payload["news_usage_contract"] = api_news_contract(payload, "STANDARD", 45)
    calls = []

    def capture(instruction, body, options, **kwargs):
        calls.append((instruction, body, kwargs))
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "{}"}]}

    if factory is OpenAIProvider:
        monkeypatch.setattr(provider, "request", capture)
    else:
        monkeypatch.setattr(provider, "_message", capture)
    provider.analyze(payload, Options())
    provider.complete(payload, 45, Options())
    assert calls[0][0] == prompt_instruction("analysis", payload)
    assert calls[1][0] == prompt_instruction("script", payload)
    assert payload["news_usage_contract"]["prompt_version"] == "v2"
    assert calls[1][1] == {"duration": 45, "evidence": payload}
    assert not any(call[2].get("search") for call in calls)
