"""Explicit opt-in only. No live service can fail the offline default suite."""

import os

import pytest

from newsflow.news.collector import Collector
from newsflow.news.rss_adapter import PublicRSSAdapter


@pytest.mark.network
@pytest.mark.skipif(
    os.getenv("NEWSFLOW_LIVE_TEST") != "1", reason="opt-in live RSS: set NEWSFLOW_LIVE_TEST=1"
)
def test_google_news_live():
    articles = Collector(PublicRSSAdapter()).collect(
        "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko", "Google News", 10
    )
    assert articles and all(a.title and a.url for a in articles)
