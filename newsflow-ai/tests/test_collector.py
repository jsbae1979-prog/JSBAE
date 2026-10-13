from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsflow.news.collector import Collector, parse_feed
from newsflow.news.rss_adapter import FakeRSSAdapter, FeedError, PublicRSSAdapter, Response


def test_normal_rss_and_dates(rss):
    articles = parse_feed(rss, "RSS 출처")
    assert len(articles) == 3
    assert articles[0].title == "한국 우주 기술 발사 현장 공개"
    assert articles[0].publisher == "테스트언론 A"
    assert articles[0].published_at == datetime(2026, 10, 13, 8, tzinfo=UTC)
    assert articles[1].published_at == datetime(2026, 10, 13, 7, 30, tzinfo=UTC)
    assert articles[2].published_at is None


def test_atom_and_updated_not_guessed():
    articles = parse_feed((Path(__file__).parent / "fixtures/atom.xml").read_bytes(), "Atom")
    assert articles[0].published_at == datetime(2026, 10, 13, 7, tzinfo=UTC)
    assert articles[1].published_at is None


@pytest.mark.parametrize(
    "payload",
    [
        b"<rss><bad>",
        b"<html>not rss</html>",
        b"",
        b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel>&x;</channel></rss>',
    ],
)
def test_malformed_and_entities(payload):
    with pytest.raises(FeedError):
        parse_feed(payload, "test")


def test_bad_date_not_estimated(rss):
    items = parse_feed(rss.replace(b"Tue, 13 Oct 2026 08:00:00 GMT", b"invalid"), "test")
    assert items[0].published_at is None


def test_timeout():
    fake = FakeRSSAdapter({"https://example.com/rss": TimeoutError("secret-token")})
    with pytest.raises(TimeoutError):
        Collector(fake).collect("https://example.com/rss", "test", 1)


class Transport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def test_robots_allowed(rss):
    transport = Transport(
        {
            "https://example.com/robots.txt": Response(200, b"User-agent: *\nAllow: /"),
            "https://example.com/rss": Response(200, rss),
        }
    )
    assert PublicRSSAdapter(transport).fetch("https://example.com/rss", 5) == rss
    assert all(timeout == 5 for _, timeout in transport.calls)


def test_robots_denied(rss):
    transport = Transport({"https://example.com/robots.txt": Response(200, b"User-agent: *\nDisallow: /rss")})
    with pytest.raises(FeedError, match="robots.txt"):
        PublicRSSAdapter(transport).fetch("https://example.com/rss", 5)
    assert len(transport.calls) == 1


def test_http_failure_and_robots_fail_closed():
    transport = Transport({"https://example.com/robots.txt": Response(403, b"")})
    with pytest.raises(FeedError):
        PublicRSSAdapter(transport).fetch("https://example.com/rss", 5)


def test_public_transport_timeout(monkeypatch):
    from newsflow.news import rss_adapter

    monkeypatch.setattr(rss_adapter, "public_addresses", lambda *a: ["8.8.8.8"])

    def timed_out(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(rss_adapter.PinnedConnection, "request", timed_out)
    with pytest.raises(FeedError, match="시간이 초과"):
        rss_adapter.PublicTransport().get("https://example.com/rss", 1)


def test_missing_entry_and_response_limit(rss):
    from newsflow.news.rss_adapter import MAX_BYTES

    with pytest.raises(FeedError):
        parse_feed(rss.replace(b"<link>https://example.com/news/1</link>", b""), "test")
    with pytest.raises(FeedError):
        parse_feed(b"x" * (MAX_BYTES + 1), "test")


def test_timezone_missing_not_guessed(rss):
    articles = parse_feed(rss.replace(b"Tue, 13 Oct 2026 08:00:00 GMT", b"Tue, 13 Oct 2026 08:00:00"), "test")
    assert articles[0].published_at is None
