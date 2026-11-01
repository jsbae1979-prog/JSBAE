"""Collection period filter: recent window, unknown dates kept, fill-to-three; synthetic data only."""

from datetime import UTC, datetime, timedelta

import pytest

from newsflow.db.models import NewsArticle, NewsSource
from newsflow.news.curator import Curator
from newsflow.news.recent_filter import select_recent

NOW = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)


def seed(session, ages):
    source = NewsSource(name="Fixture", url="https://example.com/recent", enabled=False)
    session.add(source)
    session.flush()
    ids = []
    for i, age in enumerate(ages):
        article = NewsArticle(source_id=source.id, title=f"Synthetic {i}", summary="s",
                              url=f"https://example.com/recent/{i}", canonical_url=f"https://example.com/recent/{i}",
                              publisher="Fixture", published_at=None if age is None else NOW - timedelta(hours=age))
        session.add(article)
        session.flush()
        ids.append(article.id)
    return ids


def test_only_recent_and_undated_articles_are_kept_in_collection_order(app):
    with app.state.sessions.begin() as session:
        ids = seed(session, [2, 30, None, 5, 23, 72])
        kept, info = select_recent(session, ids, NOW, 24)
    assert kept == [ids[0], ids[2], ids[3], ids[4]]
    assert info == {"hours": 24, "collected": 6, "recent": 4, "excluded_old": 2, "kept": 4,
                    "unknown_published_at": 1, "recent_shortfall": False, "filled_old": 0}


def test_shortfall_fills_with_newest_older_articles_and_is_flagged(app):
    with app.state.sessions.begin() as session:
        ids = seed(session, [1, 40, 10, 20])
        kept, info = select_recent(session, ids, NOW, 6)
    assert kept == [ids[0], ids[2], ids[3]]
    assert info["recent_shortfall"] and info["filled_old"] == 2 and info["excluded_old"] == 1


@pytest.mark.parametrize("hours", [72, 0, True, "24"])
def test_invalid_hours_are_rejected_before_any_request(app, hours):
    with app.state.sessions.begin() as session, pytest.raises(ValueError):
        select_recent(session, [], NOW, hours)
    with pytest.raises(ValueError, match="6·12·24·48"):
        Curator(app.state.coordinator).refresh(True, hours)
    with pytest.raises(ValueError, match="6·12·24·48"):
        Curator(app.state.coordinator).serpapi(None, "a" * 32, consent=True, hours=hours)
