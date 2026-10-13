from datetime import UTC, datetime, timedelta

from newsflow.news.ranking import classify, rank

NOW = datetime(2026, 10, 13, 10, tzinfo=UTC)


def test_unknown_remains_unassessed():
    score = rank("알려지지 않은 내용", "", None, {"한 출처"}, NOW)
    assert score.total == 0
    assert score.assessed_max == 0
    assert all(c["value"] is None and c["status"] == "미평가" for c in score.components.values())


def test_all_evidence_and_bounds():
    score = rank("한국 국회 정책 현장 영상", "", NOW - timedelta(hours=2), {"A", "B", "C"}, NOW)
    assert score.total == 100
    assert score.assessed_max == 100
    assert all(c["reason"] for c in score.components.values())


def test_recency_future_and_old():
    score = rank("테스트", "", NOW + timedelta(hours=1), {"A"}, NOW)
    assert score.components["최신성"]["value"] is None
    score = rank("테스트", "", NOW - timedelta(days=7), {"A"}, NOW)
    assert score.components["최신성"]["value"] == 0
    assert score.components["최신성"]["status"] == "평가"
    assert score.assessed_max == 30


def test_two_publishers_not_duplicate_feeds():
    assert rank("", "", None, {"A", " a "}, NOW).components["복수 출처"]["value"] is None
    assert rank("", "", None, {"A", "B"}, NOW).components["복수 출처"]["value"] == 15


def test_classification():
    assert classify("한국 반도체 기술") == "IT·과학"
    assert classify("근거 없는 내용") == "미분류"
