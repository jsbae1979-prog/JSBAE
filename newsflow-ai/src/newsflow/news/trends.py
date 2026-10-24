"""Official Trending Now RSS signals, kept separate from article facts and AI scores."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from defusedxml import ElementTree

from .collector import plain
from .dedup import canonical_url
from .rss_adapter import MAX_BYTES, ErrorKind, FeedError, validate_url

TRENDS_URL = "https://trends.google.com/trending/rss?geo=KR"
GOOGLE_NEWS_URL = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
TRENDS_HOME = "https://trends.google.com/trending?geo=KR"
HT = "{https://trends.google.com/trending/rss}"
MAX_AGE = timedelta(hours=24)


def parse_trends(payload: bytes, observed_at: datetime, *, region: str = "KR") -> dict:
    if not re.fullmatch(r"[A-Z]{2}", region):
        raise FeedError("Trends 지역 형식을 확인해 주세요.", ErrorKind.POLICY)
    if len(payload) > MAX_BYTES:
        raise FeedError("RSS 응답이 최대 2 MiB를 초과했습니다.")
    try:
        root = ElementTree.fromstring(payload)
        if root.tag != "rss" or root.find("channel") is None:
            raise ValueError
        items = root.findall("./channel/item")
        if len(items) > 200:
            raise ValueError
        signals = []
        for item in items:
            term = plain(item.findtext("title") or "", 200)
            if not term:
                raise ValueError
            started_at = None
            try:
                date = parsedate_to_datetime(item.findtext("pubDate") or "")
                if date.tzinfo:
                    started_at = date.astimezone(UTC).isoformat()
            except (TypeError, ValueError, OverflowError):
                pass
            links = []
            for news in item.findall(HT + "news_item")[:20]:
                url = news.findtext(HT + "news_item_url") or ""
                try:
                    url = validate_url(url)
                except FeedError:
                    continue
                if urlsplit(url).scheme == "https":
                    links.append(url)
            signals.append({"term": term, "traffic": plain(item.findtext(HT + "approx_traffic") or "", 40) or None,
                            "trend_started_at": started_at, "related_urls": links})
        if not signals:
            raise ValueError
    except Exception:  # noqa: BLE001 - XML/library errors must not echo external content
        raise FeedError("Google Trends RSS 형식을 확인하지 못했습니다.", ErrorKind.PARSE) from None
    return {"source": "Google Trends", "source_url": "https://trends.google.com/trending/rss?geo=" + region, "region": region,
            "observed_at": observed_at.astimezone(UTC).isoformat(), "signals": signals,
            "meaning": "Google 검색 관심도 · 버킷 검색량 표기이며 YouTube 조회수·기사 사실 검증이 아님"}


def trend_matches(article: dict, snapshot: dict | None, now: datetime) -> dict:
    """Conservative phrase/related-URL matches only; no translation or semantic guesses."""
    empty = {"status": "unavailable", "matches": [], "source": "Google Trends"}
    if not snapshot:
        return empty
    try:
        observed = datetime.fromisoformat(snapshot["observed_at"])
        age = now - observed
        if age < timedelta(0) or age > MAX_AGE:
            return {**empty, "status": "stale"}
    except (KeyError, TypeError, ValueError):
        return empty
    urls = {canonical_url(s["url"]) for s in article["sources"]}
    title = " ".join(article["title"].casefold().split())
    matches = []
    for signal in snapshot.get("signals", []):
        term = " ".join(signal["term"].casefold().split())
        linked = any(canonical_url(u) in urls for u in signal["related_urls"])
        phrase = len(term) >= 2 and re.search(r"(?<![\w])" + re.escape(term) + r"(?![A-Za-z0-9_])", title)
        if linked or phrase:
            matches.append({"term": signal["term"], "traffic": signal["traffic"],
                            "region": signal.get("region", snapshot.get("region", "KR")),
                            "trend_started_at": signal["trend_started_at"],
                            "match_method": "related_url" if linked else "title_phrase"})
    return {"status": "matched" if matches else "not_matched", "matches": matches[:10],
            "observed_at": snapshot["observed_at"], "region": snapshot.get("region", "KR"), "source": "Google Trends",
            "source_url": snapshot.get("source_url", TRENDS_URL),
            "caution": "일치 후보이며 인과관계·조회수 보장·기사 사실 검증이 아닙니다. 미일치는 관심 없음이 아닙니다."}
