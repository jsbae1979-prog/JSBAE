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


def dated_rss_item(date_xml: str, *, namespace: str = "http://purl.org/dc/elements/1.1/") -> bytes:
    return (
        f'<rss version="2.0" xmlns:dc="{namespace}"><channel><title>Test feed</title>'
        '<item><title>Test article</title><link>https://example.com/news/1</link>'
        f"{date_xml}</item></channel></rss>"
    ).encode()


def test_explicit_rss_dc_date_not_lost_as_updated():
    # Exact date format observed in Khan's 2026-10-20 RSS response.
    payload = dated_rss_item("<dc:date>2026-10-20T13:31:00+09:00</dc:date>")
    assert parse_feed(payload, "test")[0].published_at == datetime(2026, 10, 20, 4, 31, tzinfo=UTC)


@pytest.mark.parametrize(
    "date_xml",
    [
        "<dc:date>invalid</dc:date>",
        "<dc:date>2026-10-20T13:31:00</dc:date>",
        "<dc:date>2026-10-20</dc:date>",
        "<dc:date></dc:date>",
        "<updated>2026-10-20T13:31:00+09:00</updated>",
    ],
)
def test_rss_date_missing_invalid_or_only_updated_not_guessed(date_xml):
    assert parse_feed(dated_rss_item(date_xml), "test")[0].published_at is None


def test_rss_published_date_takes_precedence_over_dc_date():
    payload = dated_rss_item(
        "<pubDate>Tue, 20 Oct 2026 03:00:00 GMT</pubDate>"
        "<dc:date>2026-10-20T13:31:00+09:00</dc:date>"
    )
    assert parse_feed(payload, "test")[0].published_at == datetime(2026, 10, 20, 3, tzinfo=UTC)


def test_unrelated_date_namespace_not_treated_as_publication():
    payload = dated_rss_item(
        "<dc:date>2026-10-20T13:31:00+09:00</dc:date>", namespace="https://example.com/unrelated"
    )
    assert parse_feed(payload, "test")[0].published_at is None


def test_rss_channel_date_not_assigned_to_articles():
    payload = dated_rss_item("").replace(
        b"<item>", b"<dc:date>2026-10-20T13:31:00+09:00</dc:date><item>"
    )
    assert parse_feed(payload, "test")[0].published_at is None
