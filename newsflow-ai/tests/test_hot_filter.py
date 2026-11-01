"""HOT collection filter: recent window, Trends or multi-publisher signal, fill-to-three; synthetic data only."""

from datetime import UTC, datetime, timedelta

import pytest

from newsflow.db.models import ArticleMention, ArticleScore, NewsArticle, NewsSource
from newsflow.news.curator import Curator
from newsflow.news.hot_filter import select_hot

NOW = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
SNAPSHOT = {"observed_at": NOW.isoformat(), "region": "KR",
            "signals": [{"term": "Synthetic Trend", "traffic": "10K+", "trend_started_at": NOW.isoformat(),
                         "related_urls": []}]}


def seed(session, rows):
    source = NewsSource(name="Fixture", url="https://example.com/hot", enabled=False)
    session.add(source)
    session.flush()
    ids = []
    for i, (title, age, others, score) in enumerate(rows):
        article = NewsArticle(source_id=source.id, title=title, summary="s", url=f"https://example.com/hot/{i}",
                              canonical_url=f"https://example.com/hot/{i}", publisher="Fixture",
                              published_at=None if age is None else NOW - timedelta(hours=age))
        session.add(article)
        session.flush()
        for j, publisher in enumerate(others):
            session.add(ArticleMention(article_id=article.id, source_id=source.id, publisher=publisher,
                                       url=f"https://example.org/hot/{i}/{j}"))
        session.add(ArticleScore(article_id=article.id, total=score, assessed_max=100, components={}))
        ids.append(article.id)
    session.flush()
    return ids


def test_recent_signalled_articles_are_kept_and_old_ones_dropped(app):
    with app.state.sessions.begin() as session:
        trend, multi, unknown, plain, old = seed(session, [
            ("Synthetic Trend rises", 2, [], 10),
            ("Shared story", 5, ["Other Desk"], 20),
            ("Undated but covered", None, ["Third Desk"], 30),
            ("Plain recent", 3, [], 90),
            ("Synthetic Trend old", 30, ["Other Desk"], 99),
        ])
        hot, info = select_hot(session, [trend, multi, unknown, plain, old], SNAPSHOT, NOW, 24)
    assert hot == [trend, multi, unknown]
    assert info["recent"] == 4 and info["unknown_published_at"] == 1 and not info["signal_shortfall"]
    assert info["reasons"][str(trend)] == ["trends"] and info["reasons"][str(multi)] == ["publishers"]


def test_shortfall_fills_by_score_and_is_flagged(app):
    with app.state.sessions.begin() as session:
        trend, low, high, stale = seed(session, [
            ("Synthetic Trend rises", 1, [], 5),
            ("Plain low", 2, [], 10),
            ("Plain high", 2, [], 80),
            ("Plain stale", 10, [], 99),
        ])
        hot, info = select_hot(session, [trend, low, high, stale], SNAPSHOT, NOW, 6)
    assert hot == [trend, high, low]
    assert info["signal_shortfall"] and info["signalled"] == 1 and info["kept"] == 3 and info["hours"] == 6


def test_invalid_hours_are_rejected(app):
    with app.state.sessions.begin() as session:
        with pytest.raises(ValueError):
            select_hot(session, [], SNAPSHOT, NOW, 72)
    with pytest.raises(ValueError, match="6·12·24·48"):
        Curator(app.state.coordinator).refresh(True, 72)
