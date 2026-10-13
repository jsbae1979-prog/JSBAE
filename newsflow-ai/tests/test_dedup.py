from datetime import UTC, datetime, timedelta

from newsflow.news.dedup import canonical_url, similar_title

NOW = datetime(2026, 10, 13, tzinfo=UTC)


def test_url_tracking_only():
    assert canonical_url("https://example.com/a?id=2&utm_source=x&fbclid=y") == "https://example.com/a?id=2"
    assert canonical_url("https://example.com/a?id=2") != canonical_url("https://example.com/a?id=3")


def test_similar_title_and_numeric_facts():
    assert similar_title("한국 우주 기술 발사 현장 공개", "한국 우주 기술 발사 현장 공개!", NOW, NOW)
    assert similar_title("한국 우주 기술 발사 현장이 공개됐다", "한국 우주 기술 발사 현장 공개됐다", NOW, NOW)
    assert not similar_title("금리가 3퍼센트로 상승했습니다", "금리가 4퍼센트로 상승했습니다", NOW, NOW)
    assert not similar_title(
        "한국 우주 기술 발사 현장 공개", "한국 우주 기술 발사 현장 공개", NOW, NOW + timedelta(days=4)
    )
    assert not similar_title("한국 우주 기술 발사 현장 공개", "한국 우주 기술 발사 현장 공개됐다", None, NOW)
