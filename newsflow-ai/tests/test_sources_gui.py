"""Easy news page: RSS registration, edit, connection tests, collection and content flags."""

from __future__ import annotations

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.autopilot.samples import SAMPLE_URL
from newsflow.db.models import AuditLog, NewsArticle, NewsSource, NewsSourceCheck
from newsflow.news.catalog import FEED_PRESETS
from newsflow.news.rss_adapter import ErrorKind, FeedError


def add(client, name="공개 피드", url="https://example.com/rss", permission=True):
    data = {"csrf_token": csrf(client), "name": name, "url": url}
    if permission:
        data["permission"] = "true"
    return client.post("/sources", data=data, follow_redirects=False)


def test_page_lists_sources_and_distinguishes_sample_news(client, app):
    with app.state.sessions.begin() as session:
        sample = NewsSource(name="Synthetic", url=SAMPLE_URL, enabled=False)
        session.add(sample)
        session.flush()
        session.add(NewsArticle(title="[합성] 연습 기사", url="https://example.com/newsflow/synthetic/1",
                                canonical_url="https://example.com/newsflow/synthetic/1", source_id=sample.id,
                                publisher="합성", summary="짧음"))
    page = client.get("/sources")
    assert page.status_code == 200 and "뉴스 출처와 모은 뉴스" in page.text
    assert "체험 뉴스 · 실제 보도 아님" in page.text and "요약 부족" in page.text
    assert SAMPLE_URL not in page.text.split("최근 모은 뉴스")[0]  # sample source is never listed as a feed
    assert "script-src 'self'" in page.headers["content-security-policy"]


def test_register_edit_toggle_require_permission_and_policy(client, app):
    assert add(client, permission=False).status_code == 422
    assert add(client, url="http://127.0.0.1/rss").status_code == 422
    assert add(client, url=SAMPLE_URL).status_code == 422
    created = add(client)
    assert created.status_code == 303
    with app.state.sessions() as session:
        source = session.scalar(select(NewsSource).where(NewsSource.url == "https://example.com/rss"))
        assert source and not source.enabled
    assert add(client).status_code == 409
    token = csrf(client)
    assert client.post(f"/sources/{source.id}/toggle", data={"csrf_token": token}).status_code == 422
    assert client.post(f"/sources/{source.id}/toggle", data={"csrf_token": token, "permission": "true"}, follow_redirects=False).status_code == 303
    edited = client.post(f"/sources/{source.id}/edit", data={"csrf_token": token, "name": "새 이름", "url": "https://example.com/other"})
    assert edited.status_code == 422  # URL change needs renewed permission
    edited = client.post(f"/sources/{source.id}/edit", data={"csrf_token": token, "name": "새 이름", "url": "https://example.com/other", "permission": "true"}, follow_redirects=False)
    assert edited.status_code == 303
    with app.state.sessions() as session:
        source = session.get(NewsSource, source.id)
        assert (source.name, source.url, source.enabled) == ("새 이름", "https://example.com/other", False)
    assert client.post(f"/sources/{source.id}/edit", data={"name": "x", "url": "https://example.com/x"}).status_code == 403


def test_connection_test_stores_counts_and_classified_failures_only(client, app, fake):
    add(client)
    with app.state.sessions() as session:
        source = session.scalar(select(NewsSource).where(NewsSource.url == "https://example.com/rss"))
    token = csrf(client)
    tested = client.post(f"/sources/{source.id}/test", data={"csrf_token": token})
    assert tested.status_code == 200 and "연결 테스트" in tested.text and "기사 3개" in tested.text
    with app.state.sessions() as session:
        check = session.get(NewsSourceCheck, source.id)
        assert check.status == "pass" and check.article_count == 3
        assert session.scalar(select(NewsArticle)) is None  # a test never stores articles
    fake.feeds["https://example.com/rss"] = FeedError("robots.txt 정책에서 이 RSS 경로를 허용하지 않습니다.", ErrorKind.ROBOTS)
    failed = client.post(f"/sources/{source.id}/test", data={"csrf_token": token})
    assert failed.status_code == 200 and "robots" in failed.text
    fake.feeds["https://example.com/rss"] = RuntimeError("SECRET-RAW-ERROR")
    raw = client.post(f"/sources/{source.id}/test", data={"csrf_token": token})
    assert raw.status_code == 200 and "SECRET" not in raw.text
    with app.state.sessions() as session:
        check = session.get(NewsSourceCheck, source.id)
        assert check.status == "fail" and check.kind == "network" and "SECRET" not in check.message
        assert all("SECRET" not in log.message for log in session.scalars(select(AuditLog)))
    assert client.post(f"/sources/{source.id}/test", data={"csrf_token": "forged"}).status_code == 403
    assert client.post("/sources/999/test", data={"csrf_token": token}).status_code == 404


def test_collect_requires_enabled_sources_and_runs_registered_adapter(client, app):
    token = csrf(client)
    assert client.post("/sources/collect", data={"csrf_token": token}).status_code == 422
    add(client)
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource).where(NewsSource.url == "https://example.com/rss"))
        source.enabled = True
        session.add(NewsSource(name="Synthetic", url=SAMPLE_URL, enabled=True))
    started = client.post("/sources/collect", data={"csrf_token": token}, follow_redirects=False)
    assert started.status_code == 303
    app.state.coordinator.future.result(timeout=10)
    with app.state.sessions() as session:
        articles = session.scalars(select(NewsArticle)).all()
        assert len(articles) == 3 and all(a.source_id == source.id for a in articles)
    page = client.get("/sources")
    assert "실제 RSS" in page.text and "사용 중인 출처 1개" in page.text


@pytest.mark.parametrize("origin", ["https://attacker.example", "null"])
def test_sources_reject_cross_origin(client, origin):
    response = client.post("/sources", data={"csrf_token": csrf(client), "name": "x", "url": "https://example.com/rss", "permission": "true"}, headers={"Origin": origin})
    assert response.status_code == 403


@pytest.mark.parametrize("preset", FEED_PRESETS, ids=lambda item: item.id)
def test_preset_registers_disabled_without_fetching(client, app, fake, monkeypatch, preset):
    def forbidden(*args, **kwargs):
        pytest.fail("Registering a source must not fetch RSS")
    monkeypatch.setattr(fake, "fetch", forbidden)
    with app.state.sessions() as session:
        existing = session.scalar(select(NewsSource).where(NewsSource.url == preset.url))
    data = {"csrf_token": csrf(client), "preset": preset.id, "permission": "true"}
    result = client.post("/sources/preset", data=data, follow_redirects=False)
    assert result.status_code == (409 if existing else 303)
    with app.state.sessions() as session:
        rows = session.scalars(select(NewsSource).where(NewsSource.url == preset.url)).all()
        assert len(rows) == 1 and not rows[0].enabled
        assert session.get(NewsSourceCheck, rows[0].id) is None
    assert client.post("/sources/preset", data=data).status_code == 409
    page = client.get("/sources")
    option = page.text.split(f'<option value="{preset.id}"', 1)[1].split("</option>", 1)[0]
    assert option.startswith(" disabled>") and "등록됨" in option


def test_preset_preserves_permission_csrf_and_existing_sources(client, app):
    token = csrf(client)
    assert client.post("/sources/preset", data={"preset": "yonhap", "permission": "true"}).status_code == 403
    assert client.post("/sources/preset", data={"csrf_token": token, "preset": "yonhap"}).status_code == 422
    assert client.post("/sources/preset", data={
        "csrf_token": token, "preset": "http://127.0.0.1/rss", "permission": "true",
    }).status_code == 422
    add(client)
    with app.state.sessions.begin() as session:
        original = session.scalar(select(NewsSource).where(NewsSource.url == "https://example.com/rss"))
        original.enabled = True
        identifier = original.id
    assert client.post("/sources/preset", data={
        "csrf_token": token, "preset": "bbc_world", "permission": "true",
    }, follow_redirects=False).status_code == 303
    with app.state.sessions() as session:
        original = session.get(NewsSource, identifier)
        assert original.name == "공개 피드" and original.enabled
