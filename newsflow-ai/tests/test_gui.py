import threading

import pytest
from conftest import csrf
from sqlalchemy import func, select

from newsflow.db.models import AuditLog, CollectionRun, NewsArticle, NewsSource
from newsflow.news.rss_adapter import FeedError
from newsflow.news.service import CollectionBusy


@pytest.mark.parametrize(
    "path,title", [("/", "뉴스 흐름을 한눈에"), ("/news", "뉴스 탐색"), ("/settings", "워크스페이스 설정")]
)
def test_render(client, path, title):
    response = client.get(path)
    assert response.status_code == 200
    assert title in response.text
    assert "개발 예정" in response.text
    assert "Content-Security-Policy" in response.headers


def add_source(client, name="테스트출처", url="https://example.com/rss"):
    return client.post(
        "/settings/sources", data={"csrf_token": csrf(client), "name": name, "url": url, "permission": "true"}
    )


def collect_sync(client, app):
    assert client.post("/collection", data={"csrf_token": csrf(client)}).status_code == 200
    app.state.coordinator.future.result(timeout=5)


def test_add_toggle_collect_filters_detail(client, app):
    assert add_source(client).status_code == 200
    collect_sync(client, app)
    assert client.get("/news?q=우주").text.count('href="/news/1"') == 1
    assert "국회 경제 정책" not in client.get("/news?q=우주").text
    assert "한국 우주" in client.get("/news?category=IT%C2%B7%EA%B3%BC%ED%95%99").text
    assert "시각이 없는 문화" not in client.get("/news?start=2026-10-13&end=2026-10-13").text
    assert "한국 우주" in client.get("/news?source=2").text
    assert "한국 우주" not in client.get("/news?source=1").text
    assert client.get("/news?source=&start=&end=&category=&q=&sort=score").status_code == 200
    assert client.get("/news/1").status_code == 200
    assert "내부 추천 평가 근거" in client.get("/news/1").text
    assert client.get("/news/999").status_code == 404
    assert client.get("/news?start=2026-10-14&end=2026-10-13").status_code == 422
    assert client.get("/news?q=%27%20OR%201%3D1--").status_code == 200
    assert "검색 조건에 맞는" in client.get("/news?q=%27%20OR%201%3D1--").text
    assert client.post("/settings/sources/2/toggle", data={"csrf_token": csrf(client)}).status_code == 200
    with app.state.sessions() as session:
        assert not session.get(NewsSource, 2).enabled


def test_partial_and_failures_keep_data_no_secrets(client, app, fake):
    add_source(client)
    add_source(client, "나쁜 출처", "https://bad.example.com/rss")
    fake.feeds["https://bad.example.com/rss"] = FeedError("RSS secret-token=DO-NOT-LOG")
    collect_sync(client, app)
    with app.state.sessions() as session:
        run = session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()))
        assert run.status == "partial"
        assert run.succeeded == 1 and run.failed == 1
        assert session.scalar(select(func.count()).select_from(NewsArticle)) == 3
        messages = " ".join(session.scalars(select(AuditLog.message)))
        assert "DO-NOT-LOG" not in messages
    fake.feeds["https://example.com/rss"] = TimeoutError("secret")
    collect_sync(client, app)
    assert client.get("/api/collection").json()["status"] == "failed"
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(NewsArticle)) == 3
        assert (
            session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.level == "error")) == 3
        )
    assert "RSS 수집" in client.get("/settings").text


def test_duplicate_run_lock(client, app, fake):
    add_source(client)
    entered, release = threading.Event(), threading.Event()
    original = fake.fetch

    def blocking(url, timeout):
        entered.set()
        assert release.wait(5)
        return original(url, timeout)

    fake.fetch = blocking
    app.state.coordinator.start()
    assert entered.wait(5)
    try:
        with pytest.raises(CollectionBusy):
            app.state.coordinator.start()
        assert (
            client.post("/collection", data={"csrf_token": csrf(client)}, follow_redirects=False).status_code
            == 409
        )
    finally:
        release.set()
    app.state.coordinator.future.result(timeout=5)


def test_empty_run_and_settings(client, app):
    collect_sync(client, app)
    assert client.get("/api/collection").json()["status"] == "empty"
    token = csrf(client)
    assert client.post("/settings/collection", data={"csrf_token": token, "timeout": 0}).status_code == 422
    assert client.post("/settings/collection", data={"csrf_token": token, "timeout": 7}).status_code == 200
    assert 'value="7"' in client.get("/settings").text


def test_html_escape(client):
    assert add_source(client, '<script>alert("x")</script>').status_code == 200
    text = client.get("/settings").text
    assert "&lt;script&gt;" in text
    assert "<script>alert(" not in text


def test_cross_coordinator_and_crash_recovery(app):
    from filelock import FileLock

    with app.state.sessions.begin() as session:
        run = CollectionRun(status="running")
        session.add(run)
    lock = FileLock(str(app.state.coordinator.lock_path))
    with lock:
        app.state.coordinator.recover_interrupted()
        with pytest.raises(CollectionBusy):
            app.state.coordinator.start()
        with app.state.sessions() as session:
            assert session.get(CollectionRun, 1).status == "running"
    app.state.coordinator.recover_interrupted()
    with app.state.sessions() as session:
        assert session.get(CollectionRun, 1).status == "interrupted"
        assert session.scalar(select(AuditLog).where(AuditLog.event == "collection_interrupted"))
