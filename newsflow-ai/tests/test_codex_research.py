import json

import pytest
from pydantic import ValidationError

from newsflow.research import (
    CodexResearchProvider,
    FakeResearchProvider,
    FakeResearchResult,
    ResearchBlocked,
    ResearchRequest,
)


@pytest.mark.parametrize("count", [5, 10, 20])
def test_synthetic_roundtrip(count):
    result = FakeResearchProvider().research(ResearchRequest(count=count))
    parsed = FakeResearchResult.model_validate_json(result.model_dump_json())
    assert parsed.synthetic and len(parsed.articles) == count
    assert all(a.title.startswith("[합성]") and a.published_at is None for a in parsed.articles)
    assert all({d.seconds for d in a.drafts} == {30, 45, 60} for a in parsed.articles)


def fixture_payload():
    return json.loads(FakeResearchProvider().research(ResearchRequest()).model_dump_json())


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/news", "https://localhost/news", "https://user:pass@example.com/news",
    "javascript:alert(1)", "https://example.com/news?api_key=secret", "https://example.com/\\bad",
])
def test_reject_unsafe_sources(url):
    payload = fixture_payload()
    payload["articles"][0]["url"] = url
    with pytest.raises(ValueError):
        FakeResearchResult.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("case", ["extra", "time", "duration", "duplicate", "real", "text"])
def test_reject_invalid_results(case):
    payload = fixture_payload()
    article = payload["articles"][0]
    if case == "extra":
        article["execute"] = "untrusted command"
    elif case == "time":
        article["researched_at"] = "2026-10-16T12:00:00"
    elif case == "duration":
        article["drafts"][0]["script"]["scenes"][0]["seconds"] = 29
    elif case == "duplicate":
        payload["articles"][1]["url"] = article["url"]
    elif case == "real":
        payload["synthetic"] = False
    else:
        article["facts"] = ["x" * 801]
    with pytest.raises(ValidationError):
        FakeResearchResult.model_validate_json(json.dumps(payload))


def test_live_blocked_and_fake_cancelled():
    with pytest.raises(ResearchBlocked, match="미검증"):
        CodexResearchProvider().research(ResearchRequest())
    with pytest.raises(ResearchBlocked, match="취소"):
        FakeResearchProvider().research(ResearchRequest(), cancelled=True)


@pytest.mark.parametrize("values", [{"count": 100}, {"period": "month"}, {"category": "unknown"}])
def test_request_limits(values):
    with pytest.raises(ValidationError):
        ResearchRequest(**values)
