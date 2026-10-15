from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from newsflow.db.models import ArticleMention, ArticleScore, CollectionRun, NewsArticle, NewsSource
from newsflow.db.session import migrate


def test_version_and_repeat_migration(app):
    with app.state.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"
    migrate(app.state.engine)
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(NewsSource)) == 1


def test_transaction_rollback_and_unique(app):
    with pytest.raises(IntegrityError), app.state.sessions.begin() as session:
        session.add(NewsSource(name="A", url="https://example.com/rss"))
        session.add(NewsSource(name="B", url="https://example.com/rss"))
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(NewsSource)) == 1


def test_utc_roundtrip_naive_rejected(app):
    with app.state.sessions.begin() as session:
        source = NewsSource(
            name="A",
            url="https://example.com/rss",
            created_at=datetime(2026, 10, 13, 9, tzinfo=timezone(timedelta(hours=9))),
        )
        session.add(source)
    with app.state.sessions() as session:
        actual = session.scalar(select(NewsSource).where(NewsSource.name == "A"))
        assert actual.created_at == datetime(2026, 10, 13, tzinfo=UTC)
    with pytest.raises(StatementError), app.state.sessions.begin() as session:
        session.add(NewsSource(name="bad", url="https://example.com/bad", created_at=datetime(2026, 1, 1)))


def test_collect_duplicate_urls_and_provenance(app, fake, rss):
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="A", url="https://example.com/rss"))
        session.add(NewsSource(name="B", url="https://other.example.com/rss"))
    fake.feeds["https://other.example.com/rss"] = rss.replace(
        b"https://example.com/news/", b"https://other.example.com/news/"
    ).replace("테스트언론 A".encode(), "테스트언론 B".encode())
    coordinator = app.state.coordinator
    coordinator.start()
    coordinator.future.result(timeout=5)
    coordinator.start()
    coordinator.future.result(timeout=5)
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(NewsArticle)) == 3
        assert session.scalar(select(func.count()).select_from(ArticleMention)) == 6
        assert session.scalar(select(func.count()).select_from(ArticleScore)) == 3
        runs = list(session.scalars(select(CollectionRun).order_by(CollectionRun.id)))
        assert [r.added for r in runs] == [3, 0]
        assert runs[1].duplicates == 6
        assert session.get(ArticleScore, 1).components["복수 출처"]["value"] == 15
    coordinator.close()
