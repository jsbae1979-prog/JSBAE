import urllib.error

import pytest
from sqlalchemy import select

from newsflow.db.models import ContentDraft, IntelligenceRun, NewsArticle, NewsSource
from newsflow.intelligence.capabilities import (
    NEWS_ANALYSIS,
    NEWS_SEARCH,
    SCRIPT_GENERATION,
    provider_capabilities,
    require_acquisition,
)
from newsflow.intelligence.provider import (
    FakeProvider,
    OfflineProvider,
    OpenAIProvider,
    Options,
    ProviderError,
)
from newsflow.intelligence.service import IntelligenceError, IntelligenceService


@pytest.mark.parametrize("provider", ["offline", "claude_code", "codex", "openai", "claude_api"])
def test_capabilities_do_not_claim_live_search_or_authentication(provider):
    contract = provider_capabilities(provider)
    assert contract["features"][NEWS_SEARCH]["available"] is False
    assert contract["features"][NEWS_ANALYSIS]["implemented"] is True
    assert contract["features"][NEWS_SEARCH]["implemented"] is (provider in {"openai", "claude_api"})
    assert contract["features"][SCRIPT_GENERATION]["available"] is (True if provider == "offline" else None)
    for policy in ("ai_web", "hybrid", "unknown"):
        with pytest.raises(ValueError):
            require_acquisition(provider, policy)
    require_acquisition(provider, "rss")


@pytest.fixture
def news(app):
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource))
        articles = [NewsArticle(title=f"합성 연구 소식 {number}", summary="자료의 출처와 확인 필요 사항을 함께 검토합니다.",
                                url=f"https://example.com/research/{number}",
                                canonical_url=f"https://example.com/research/{number}",
                                source_id=source.id, publisher="검증용 합성 출처") for number in range(2)]
        session.add_all(articles)
        session.flush()
        return [article.id for article in articles]


def test_recommendation_and_subset_preserve_only_validated_sources(app, news):
    class Recommendation(FakeProvider):
        def analyze(self, evidence, options):
            result = super().analyze(evidence, options)
            return {**result, "recommended_article_id": news[1], "selection_reason": "자료가 제공하는 주제 비교 후보"}

    fake = Recommendation()
    service = IntelligenceService(app.state.sessions, fake)
    analysis = service.analyze(news, "claude_code", True, Options(model="sonnet"))
    draft_id = service.generate(analysis, 45, "claude_code", True, Options(model="sonnet"), article_ids=[news[1]])
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        assert [item["id"] for item in draft.sources["articles"]] == [news[1]]
        assert draft.sources["groups"] == [[news[1]]]
        assert draft.sources["articles"][0]["published_at"] is None
        assert draft.sources["articles"][0]["verification"] == "unverified"
        assert draft.review_status == "review_required"
        assert session.get(IntelligenceRun, draft.run_id).options["analysis_run_id"] == analysis
        assert len(session.get(IntelligenceRun, analysis).evidence["articles"]) == 2
    assert fake.calls == 2


@pytest.mark.parametrize("selected", [[], [999999], [True], [1, 1]])
def test_invalid_subset_never_sends_generation(app, news, selected):
    fake = FakeProvider()
    service = IntelligenceService(app.state.sessions, fake)
    analysis = service.analyze(news)
    with pytest.raises(IntelligenceError):
        service.generate(analysis, 30, article_ids=selected)
    assert fake.calls == 1


@pytest.mark.parametrize("recommended,reason", [(999999, "선택"), (1, "")])
def test_invalid_recommendation_not_saved_as_success(app, news, recommended, reason):
    class BadRecommendation(FakeProvider):
        def analyze(self, evidence, options):
            return {**OfflineProvider().analyze(evidence, options), "recommended_article_id": recommended,
                    "selection_reason": reason}

    with pytest.raises(IntelligenceError):
        IntelligenceService(app.state.sessions, BadRecommendation()).analyze(news)
    with app.state.sessions() as session:
        assert session.scalar(select(IntelligenceRun)).status == "failed"


@pytest.mark.parametrize("status", [429, 500])
def test_automation_openai_adapter_never_retries(monkeypatch, status):
    calls = []

    def fail(*args):
        calls.append(1)
        raise urllib.error.HTTPError("https://api.openai.com/v1/chat/completions", status, "test", {"Retry-After": "1"}, None)

    provider = OpenAIProvider(lambda: "synthetic-test-key", allow_retry=False)
    monkeypatch.setattr(provider, "_open", fail)
    with pytest.raises(ProviderError):
        provider.analyze({"articles": []}, Options())
    assert len(calls) == 1 and provider.last_retried is False
