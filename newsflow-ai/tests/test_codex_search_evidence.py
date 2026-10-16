from copy import deepcopy

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from newsflow.db.models import Base, NewsArticle, NewsSource
from newsflow.research import ResearchBlocked, find_existing_articles, validate_search_evidence

URL = "https://news.ycombinator.com/item?id=12345"


def payload(url=URL):
    # Test-only candidate, never passed to a real provider or stored as a real RSS item.
    return {"articles": [{
        "publisher": "Fixture publisher", "url": url, "evidence": "Observed page action; review required",
        "title": "Fixture research candidate", "summary": "Test-only summary", "published_at": None,
        "facts": ["Test-only fact"], "uncertainties": ["Source contents require human review"],
    }]}


def events(url=URL):
    return [
        {"type": "webSearch", "status": "completed", "action": {"type": "search", "query": "news"}},
        {"type": "webSearch", "status": "completed", "action": {"type": "openPage", "url": url}},
    ]


def test_search_requires_actual_search_and_nonempty_results():
    for observed in ([], events()[1:], [{"type": "agentMessage", "text": "I searched the web"}]):
        with pytest.raises(ResearchBlocked, match="웹 검색"):
            validate_search_evidence(payload(), observed)
    with pytest.raises(ResearchBlocked, match="비어"):
        validate_search_evidence({"articles": []}, events())


def test_candidate_must_match_observed_open_url():
    with pytest.raises(ResearchBlocked, match="일치"):
        validate_search_evidence(payload("https://news.ycombinator.com/item?id=999"), events())
    with pytest.raises(ResearchBlocked, match="일치"):
        validate_search_evidence(payload(), events()[:1])
    result = validate_search_evidence(payload(URL + "&utm_source=search"), events())
    assert result.articles[0].verification == "needs_review"
    assert result.articles[0].published_at is None


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/news", "https://localhost/news", "https://user:pass@news.ycombinator.com/news",
    "https://news.ycombinator.com/news?api_key=secret", "https://example.com/news",
    "https://sub.example.org/news", "https://news.test/news", "javascript:alert(1)", URL + "#fragment",
])
def test_unsafe_or_fixture_sources_never_become_candidates(url):
    with pytest.raises(ResearchBlocked):
        validate_search_evidence(payload(url), events(url))


@pytest.mark.parametrize("case", ["synthetic", "verified", "duplicate", "unknown_field", "naive_time"])
def test_untrusted_result_contract(case):
    value = payload()
    if case == "synthetic":
        value["synthetic"] = True
    elif case == "verified":
        value["articles"][0]["verification"] = "verified"
    elif case == "duplicate":
        value["articles"].append(deepcopy(value["articles"][0]))
        value["articles"][1]["url"] += "&utm_source=duplicate"
    elif case == "unknown_field":
        value["articles"][0]["execute"] = "untrusted command"
    else:
        value["articles"][0]["published_at"] = "2026-10-16T12:00:00"
    with pytest.raises(ResearchBlocked):
        validate_search_evidence(value, events())


def test_incomplete_search_is_not_search_evidence():
    observed = events()
    observed[0]["status"] = "inProgress"
    with pytest.raises(ResearchBlocked, match="웹 검색"):
        validate_search_evidence(payload(), observed)


def test_existing_rss_match_is_read_only_and_canonical():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    try:
        with sessions.begin() as session:
            source = NewsSource(name="Fixture RSS", url="https://news.ycombinator.com/rss")
            session.add(source)
            session.flush()
            article = NewsArticle(title="Stored fixture title", url=URL, canonical_url=URL,
                                  source_id=source.id, publisher="Stored publisher", summary="Preserved")
            session.add(article)
            session.flush()
            article_id = article.id
        value = payload(URL + "&utm_source=research")
        unmatched = payload("https://news.ycombinator.com/item?id=98765")["articles"][0]
        value["articles"].append(unmatched)
        observed = events() + events(unmatched["url"])
        result = validate_search_evidence(value, observed)
        assert find_existing_articles(sessions, result) == {value["articles"][0]["url"]: article_id}
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(NewsArticle)) == 1
            assert session.scalar(select(func.count()).select_from(NewsSource)) == 1
            stored = session.get(NewsArticle, article_id)
            assert stored.title == "Stored fixture title" and stored.summary == "Preserved"
    finally:
        engine.dispose()
