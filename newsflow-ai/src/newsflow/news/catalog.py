"""Public feed address shortcuts, not connectivity or reuse-license certification."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedPreset:
    id: str
    name: str
    url: str


FEED_PRESETS = (
    FeedPreset("google_kr", "Google News · 한국", "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"),
    FeedPreset("yonhap", "연합뉴스 · 전체", "https://www.yna.co.kr/rss/news.xml"),
    FeedPreset("hankyung", "한국경제 · 전체", "https://www.hankyung.com/feed/all-news"),
    FeedPreset("khan", "경향신문 · 전체", "https://www.khan.co.kr/rss/rssdata/total_news.xml"),
    FeedPreset("bbc_world", "BBC · 세계 (영문)", "https://feeds.bbci.co.uk/news/world/rss.xml"),
)
