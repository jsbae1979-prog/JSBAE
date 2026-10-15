"""Collection error audit lines: FeedError kind plus its fixed Korean text; raw exceptions redacted."""

from __future__ import annotations

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import AuditLog, CollectionRun, NewsSource
from newsflow.news.rss_adapter import ErrorKind, FeedError

URL = "https://example.com/rss"
GENERIC = "RSS 수집 또는 저장에 실패했습니다."


def register_enabled(client, app) -> int:
    response = client.post(
        "/sources",
        data={"csrf_token": csrf(client), "name": "공개 피드", "url": URL, "permission": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource).where(NewsSource.url == URL))
        source.enabled = True
        return source.id


def collect(app) -> int:
    run_id = app.state.coordinator.start()
    app.state.coordinator.future.result(timeout=10)
    return run_id


def source_error(app, run_id: int) -> AuditLog | None:
    with app.state.sessions() as session:
        return session.scalar(
            select(AuditLog).where(AuditLog.run_id == run_id, AuditLog.event == "source_error")
        )


@pytest.mark.parametrize(
    ("failure", "prefix", "fragment"),
    [
        (
            FeedError("압축 응답은 Phase 1 RSS 정책에서 지원하지 않습니다."),
            "[network]",
            "압축 응답은 Phase 1 RSS 정책에서 지원하지 않습니다.",
        ),
        (FeedError("RSS 서버가 HTTP 503을 반환했습니다.", ErrorKind.HTTP), "[http]", "HTTP 503"),
        (
            FeedError("robots.txt 정책에서 이 RSS 경로를 허용하지 않습니다.", ErrorKind.ROBOTS),
            "[robots]",
            "robots.txt 정책",
        ),
    ],
)
def test_feed_error_audit_message_carries_kind_and_fixed_text(client, app, fake, failure, prefix, fragment):
    source_id = register_enabled(client, app)
    fake.feeds[URL] = failure
    run_id = collect(app)
    log = source_error(app, run_id)
    assert log is not None and log.source_id == source_id and log.level == "error"
    assert log.message.startswith(prefix) and fragment in log.message
    assert len(log.message) <= 500
    with app.state.sessions() as session:
        assert session.get(CollectionRun, run_id).status == "failed"


def test_raw_exception_is_redacted(client, app, fake):
    register_enabled(client, app)
    fake.feeds[URL] = RuntimeError("SECRET-RAW")
    run_id = collect(app)
    log = source_error(app, run_id)
    assert log is not None and log.message == GENERIC
    with app.state.sessions() as session:
        assert all("SECRET" not in entry.message for entry in session.scalars(select(AuditLog)))
    assert "SECRET" not in client.get("/sources").text


def test_sources_page_shows_last_collection_error_with_kind(client, app, fake):
    register_enabled(client, app)
    fake.feeds[URL] = FeedError("RSS 서버가 HTTP 503을 반환했습니다.", ErrorKind.HTTP)
    collect(app)
    page = client.get("/sources")
    assert page.status_code == 200
    assert "최근 수집 오류: [http] RSS 서버가 HTTP 503을 반환했습니다." in page.text
