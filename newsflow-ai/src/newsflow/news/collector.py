"""Strict RSS/Atom parsing without article-body downloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

import feedparser
from defusedxml import ElementTree

from .rss_adapter import MAX_BYTES, ErrorKind, FeedError, RSSAdapter, validate_url


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain(value: str, limit: int) -> str:
    parser = PlainText()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())[:limit]


@dataclass(frozen=True)
class CollectedArticle:
    title: str
    url: str
    publisher: str
    summary: str
    published_at: datetime | None


def parse_feed(payload: bytes, source_name: str) -> list[CollectedArticle]:
    if len(payload) > MAX_BYTES:
        raise FeedError("RSS 응답이 최대 2 MiB를 초과했습니다.")
    try:
        root = ElementTree.fromstring(payload)
    except Exception as exc:
        raise FeedError("RSS XML 형식이 잘못되었거나 안전하지 않습니다.", ErrorKind.PARSE) from exc
    if root.tag.split("}")[-1] not in {"rss", "feed", "RDF"}:
        raise FeedError("RSS 또는 Atom 문서가 아닙니다.", ErrorKind.PARSE)
    parsed = feedparser.parse(payload)
    if parsed.bozo:
        raise FeedError("RSS 문서를 정상적으로 파싱하지 못했습니다.", ErrorKind.PARSE)
    result: list[CollectedArticle] = []
    if len(parsed.entries) > 1000:
        raise FeedError("RSS 항목이 최대 1000개를 초과했습니다.")
    for entry in parsed.entries:
        title = plain(entry.get("title", ""), 500)
        url = entry.get("link", "")
        if not title or not url:
            raise FeedError("RSS 항목에 제목 또는 원문 링크가 없습니다.")
        # Validate link syntax only; article links are never fetched.
        validate_url(url)
        published = None
        raw_date = entry.get("published", "")
        if raw_date:
            try:
                try:
                    parsed_date = parsedate_to_datetime(raw_date)
                except (ValueError, TypeError):
                    parsed_date = datetime.fromisoformat(raw_date)
                if parsed_date.tzinfo is not None:
                    published = parsed_date.astimezone(UTC)
            except (ValueError, TypeError, OverflowError):
                pass
        publisher = plain(entry.get("source", {}).get("title", source_name), 200) or source_name
        result.append(
            CollectedArticle(title, url, publisher, plain(entry.get("summary", ""), 2000), published)
        )
    return result


class Collector:
    def __init__(self, adapter: RSSAdapter):
        self.adapter = adapter

    def collect(self, url: str, source_name: str, timeout: int) -> list[CollectedArticle]:
        return parse_feed(self.adapter.fetch(url, timeout), source_name)
