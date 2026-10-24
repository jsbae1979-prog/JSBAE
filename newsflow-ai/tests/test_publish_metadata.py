"""Local metadata preparation: no inferred facts, approvals, network or existing edits."""

import pytest

from newsflow.publishing.adapters import InstagramAdapter, YouTubeAdapter
from newsflow.publishing.metadata import suggest_metadata
from newsflow.publishing.service import PublishingService


def test_original_uncertainty_and_source_are_preserved_in_platform_fields():
    source = "https://example.com/news/1"
    suggestion = suggest_metadata("우주 연구 결과", {"summary": "성공 여부는 아직 미확인입니다."},
                                  {"articles": [{"sources": [{"url": source}, {"url": source}]}]})
    assert suggestion["description"].count(source) == 1
    assert "성공 여부는 아직 미확인입니다." in suggestion["description"]
    assert suggestion["hashtags"] == "#우주 #연구 #결과"
    assert not any(key in suggestion for key in ("content_reviewed", "ai_disclosure", "youtube_category_id", "consent"))
    payload = PublishingService.input("youtube", suggestion["title"], suggestion["description"], suggestion["hashtags"], "unreviewed")
    youtube = YouTubeAdapter().prepare(payload)
    instagram = InstagramAdapter().prepare(payload)
    assert youtube["snippet"]["title"] == "우주 연구 결과"
    assert youtube["snippet"]["tags"] == ["우주", "연구", "결과"]
    assert source in youtube["snippet"]["description"]
    assert instagram["caption"] == "\n".join([suggestion["title"], suggestion["description"], suggestion["hashtags"]])
    assert not instagram["is_ai_generated"]  # Still unreviewed, not automatically approved.


def test_long_unicode_and_links_fit_caption_without_cutting_sentences_or_urls():
    summary = "미확인😀" * 100
    urls = ["https://example.com/" + str(i) + "x" * 400 for i in range(10)]
    result = suggest_metadata("합성 영상 " * 15, {"summary": summary},
                              {"articles": [{"sources": [{"url": u} for u in urls]}]})
    assert summary in result["description"]
    assert "넣지 못했습니다" in result["notice"]
    caption = "\n".join(result[k] for k in ("title", "description", "hashtags"))
    assert len(caption.encode("utf-16-le")) // 2 + 50 <= 2200
    assert all(u in urls for u in result["description"].splitlines() if u.startswith("https://"))


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///private", "https://user:password@example.com/a", "https://example.com/a\nb"])
def test_unsafe_source_is_not_copied(url):
    result = suggest_metadata("검토 영상", {"summary": "기존 요약"}, {"articles": [{"sources": [{"url": url}]}]})
    assert url not in result["description"] and "1개" in result["notice"]


@pytest.mark.parametrize("where", ["title", "summary", "sources"])
def test_sensitive_content_never_enters_suggestions(monkeypatch, where):
    secret = "SYNTHETIC-NOT-A-REAL-KEY"
    monkeypatch.setenv("NEWSFLOW_AI_KEY", secret)
    title, snapshot, sources = "검토 영상", {"summary": "기존 요약"}, {}
    if where == "title":
        title = secret
    elif where == "summary":
        snapshot["summary"] = secret
    else:
        sources = {"articles": [{"sources": [{"url": "https://example.com/?token=" + secret}]}]}
    result = suggest_metadata(title, snapshot, sources)
    assert secret not in str(result) and result["description"] == result["title"] == result["hashtags"] == ""
    assert "중단" in result["notice"]


def test_missing_or_invalid_legacy_snapshot_does_not_invent_a_summary():
    result = suggest_metadata("이전 영상", {}, {})
    assert "이전 영상" == result["title"] and "사실·출처 확인 필요" in result["description"]
    assert suggest_metadata("영상", {"summary": ["bad"]}, {})["description"] == ""
    assert suggest_metadata("영상", {"summary": "a" * 501}, {})["description"] == ""
