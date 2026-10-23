"""Local cards and Fake-only Instagram delivery; no production data or provider calls."""
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest
from conftest import csrf
from PIL import Image
from sqlalchemy import select

from newsflow.db.models import (
    ContentDraft,
    ImagePost,
    ImagePostDelivery,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    PlatformAccount,
)
from newsflow.news.lifecycle import replace_collection, used_article_ids
from newsflow.publishing.auth import TokenBundle
from newsflow.publishing.image_artwork import artwork
from newsflow.publishing.image_posts import InstagramImageAdapter, public_image_url
from newsflow.publishing.instagram import InstagramHTTPResponse, InstagramPublishResult, InstagramUploadError
from newsflow.publishing.service import PublishingError


@pytest.fixture(autouse=True)
def deny_live(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("External network forbidden in image tests")
    monkeypatch.setattr("newsflow.publishing.instagram.MetaUploadTransport.request", denied)
    monkeypatch.setattr("newsflow.news.rss_adapter.PublicRSSAdapter.fetch", denied)


def article(app):
    with app.state.sessions.begin() as session:
        source = NewsSource(name="합성 출처", url="https://example.com/image-rss", enabled=False)
        session.add(source)
        session.flush()
        row = NewsArticle(source_id=source.id, title="합성 뉴스: 도서관의 독서 모임",
                          url="https://example.com/image-news", canonical_url="https://example.com/image-news",
                          publisher="합성 출처", summary="테스트용 뉴스 요약입니다.", published_at=None)
        session.add(row)
        session.flush()
        return row.id


def make_post(app):
    return app.state.image_posts.create(article(app), title="새로운 독서 모임",
        body="저장된 자료를 바탕으로 만든 합성 게시물입니다.", hashtags="#합성",
        reviewed=True, rights=True, sources_confirmed=True, ai_disclosure="not_required")


def image_bytes():
    output = BytesIO()
    Image.new("RGB", (640, 800), "#99bbee").save(output, format="PNG")
    return output.getvalue()


class FakeInstagram:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.processing = "FINISHED"

    def create_image(self, url, caption, disclosure, bundle, account):
        self.calls.append("create")
        if self.failure == "create":
            raise TimeoutError("SECRET_RESPONSE")
        return "12345"

    def status(self, bundle, container):
        self.calls.append("status")
        if self.failure == "status":
            raise TimeoutError("SECRET_STATUS")
        return self.processing

    def publish(self, bundle, account, container, *, public_approved):
        assert public_approved
        self.calls.append("publish")
        if self.failure == "publish":
            raise InstagramUploadError("unknown")
        return "67890"

    def result(self, bundle, media, account):
        self.calls.append("result")
        if self.failure == "result":
            raise TimeoutError("SECRET_LINK")
        return InstagramPublishResult(media, "https://www.instagram.com/p/Example1/", account)


def delivery_setup(app, post):
    service = app.state.image_posts
    with app.state.sessions.begin() as session:
        account = PlatformAccount(platform="instagram", label="합성 계정",
            account_type="business", api_ready=True, status="connected")
        session.add(account)
        session.flush()
        account_id = account.id
    service.connections = SimpleNamespace(access_for_upload=lambda *a, **k: SimpleNamespace(
        instagram_id="111", page_id="222", app_id="333", bundle=None))
    service.fetcher = SimpleNamespace(fetch=lambda *a: service.path(post).read_bytes())
    service.adapter = FakeInstagram()
    return service, account_id


def test_gui_create_download_caption_and_preserve_article(app, client):
    identifier = article(app)
    page = client.get(f"/image-posts?article_id={identifier}")
    assert page.status_code == 200 and "합성 출처 · 미확인" in page.text
    assert "미확인" in page.text and "AI 추가 호출 없음" not in page.text
    data = {"csrf_token": csrf(client), "article_id": identifier, "title": "독서 모임 소식",
                "body": "합성 요약", "reviewed": "true", "rights": "true", "sources_confirmed": "true",
                "ai_disclosure": "not_required"}
    response = client.post("/image-posts/create", data=data, follow_redirects=False)
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert "이미지 준비 완료" in page.text and "Instagram 계정 연결이 필요" in page.text
    with app.state.sessions() as session:
        post = session.scalar(select(ImagePost))
        assert post.sources["articles"][0]["published_at"] is None
        assert session.get(NewsArticle, identifier).summary == "테스트용 뉴스 요약입니다."
        assert identifier in used_article_ids(session)
        replace_collection(session, [999])
        assert identifier in used_article_ids(session)
    raw = client.get(f"/image-posts/{post.id}/file?download=true")
    with Image.open(BytesIO(raw.content)) as image:
        assert image.size == (1080, 1350) and image.format == "JPEG"
    text = client.get(f"/image-posts/{post.id}/caption").text
    assert "https://example.com/image-news" in text and "合成" not in text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert "/image-posts" in client.get("/").text
    assert f"/image-posts?article_id={identifier}" in client.get(f"/news/{identifier}").text


def test_reused_draft_keeps_all_sources_and_archives_related_news(app, client):
    identifier = article(app)
    with app.state.sessions.begin() as session:
        primary = session.get(NewsArticle, identifier)
        other = NewsArticle(source_id=primary.source_id, title="함께 읽는 두 번째 자료",
            url="https://example.com/second", canonical_url="https://example.com/second",
            publisher="두 번째 합성 출처", summary="합성 자료", published_at=None)
        session.add(other)
        run = IntelligenceRun(kind="script", status="succeeded", provider="offline",
            options={}, evidence={}, result={}, message="synthetic")
        session.add(run)
        session.flush()
        other_id = other.id
        draft = ContentDraft(run_id=run.id, duration=30, content={
            "title": "두 자료를 활용한 합성 제목", "scenes": [{"narration": "합성 본문"}]},
            sources={"articles": [
                {"id": identifier, "url": primary.url, "publisher": primary.publisher},
                {"id": other_id, "url": other.url, "publisher": other.publisher}]})
        session.add(draft)
        session.flush()
        draft_id = draft.id
    page = client.get(f"/image-posts?article_id={identifier}&draft_id={draft_id}")
    assert f'name="draft_id" value="{draft_id}"' in page.text
    response = client.post("/image-posts/create", data={
        "csrf_token": csrf(client), "article_id": identifier, "draft_id": draft_id,
        "title": "두 자료를 활용한 합성 제목", "body": "합성 본문",
        "reviewed": "true", "rights": "true", "sources_confirmed": "true",
        "ai_disclosure": "not_required"})
    assert response.status_code == 200
    with app.state.sessions() as session:
        post = session.scalar(select(ImagePost))
        assert len(post.sources["articles"]) == 2 and post.sources["draft_id"] == draft_id
        assert "https://example.com/second" in post.caption
        assert {identifier, other_id}.issubset(used_article_ids(session))
    with pytest.raises(PublishingError, match="연결된 대본"):
        app.state.image_posts.create(identifier, title="제목", body="본문",
            reviewed=True, rights=True, sources_confirmed=True,
            ai_disclosure="not_required", draft_id=draft_id + 100)


@pytest.mark.parametrize("missing", ["reviewed", "rights", "sources_confirmed"])
def test_no_local_creation_without_review(app, missing):
    values = {"title": "기사 제목", "body": "본문", "reviewed": True, "rights": True,
                  "sources_confirmed": True, "ai_disclosure": "not_required"}
    values[missing] = False
    with pytest.raises(PublishingError):
        app.state.image_posts.create(article(app), **values)
    assert not app.state.image_posts.recent()


def test_invalid_photo_and_text_never_create_output(app):
    with pytest.raises(PublishingError):
        artwork("제목", "출처", b"<svg><script>secret</script></svg>")
    with pytest.raises(PublishingError):
        artwork("가" * 100, "출처")
    with Image.open(BytesIO(artwork("사진 제목", "출처", image_bytes(), ai=True))) as image:
        assert image.size == (1080, 1350) and not image.getexif()


def test_csrf_origin_and_upload_limits(app, client):
    identifier = article(app)
    token = csrf(client)
    assert client.post("/image-posts/create", data={"article_id": identifier}).status_code == 403
    assert client.post("/image-posts/create", data={"csrf_token": token},
                       headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/image-posts/create", data={"csrf_token": token, "pad": "x" * (8 * 1024 * 1024)}).status_code == 413
    # The larger image form does not relax the limit on existing forms.
    assert client.post("/sources", data={"csrf_token": token, "pad": "x" * 65536}).status_code == 413


@pytest.mark.parametrize("url", ["http://example.com/a.jpg", "https://127.0.0.1/a.jpg",
    "https://user:secret@example.com/a.jpg", "https://example.com/a.jpg?token=secret",
    "https://example.com/a.jpg#x"])
def test_public_image_url_rejects_local_or_secret_values(url):
    with pytest.raises(PublishingError):
        public_image_url(url)


def test_instagram_image_contract_only_uses_image_url_and_publish_separate():
    calls = []
    class Transport:
        def request(self, method, url, headers, body):
            calls.append((method, url, parse_qs(body.decode())))
            return InstagramHTTPResponse(200, b'{"id":"12345"}')
    bundle = TokenBundle(access_token="fake", expires_at=datetime.now(UTC) + timedelta(hours=1),
                         scopes=("instagram_basic", "instagram_content_publish", "pages_read_engagement"))
    result = InstagramImageAdapter(Transport()).create_image("https://example.com/a.jpg",
        "검토한 본문", "not_required", bundle, "111")
    assert result == "12345" and len(calls) == 1
    assert calls[0][2]["image_url"] == ["https://example.com/a.jpg"]
    assert "upload_type" not in calls[0][2] and "media_type" not in calls[0][2]


def test_prepare_check_publish_requires_separate_approval_and_is_idempotent(app):
    post = make_post(app)
    service, account = delivery_setup(app, post)
    with pytest.raises(PublishingError):
        service.prepare(post, account, "https://example.com/final.jpg")
    assert not service.adapter.calls
    identifier = service.prepare(post, account, "https://example.com/final.jpg", consent=True)
    assert service._delivery(identifier).status == "processing"
    assert service.adapter.calls == ["create"]
    with pytest.raises(PublishingError):
        service.publish(identifier, public_consent=True)
    service.check(identifier, consent=True)
    with pytest.raises(PublishingError):
        service.publish(identifier)
    service.publish(identifier, public_consent=True)
    assert service._delivery(identifier).status == "published"
    assert service._delivery(identifier).detail["media_id"] == "67890"
    for _ in range(2):
        with pytest.raises(PublishingError):
            service.publish(identifier, public_consent=True)
        with pytest.raises(PublishingError):
            service.prepare(post, account, "https://example.com/final.jpg", consent=True)
    assert service.adapter.calls.count("publish") == 1


@pytest.mark.parametrize("failure", ["create", "status", "publish", "result"])
def test_uncertain_failures_preserve_record_never_repeat(app, failure):
    post = make_post(app)
    service, account = delivery_setup(app, post)
    service.adapter.failure = failure
    identifier = service.prepare(post, account, "https://example.com/final.jpg", consent=True)
    if failure != "create":
        service.check(identifier, consent=True)
    if failure in {"publish", "result"}:
        service.publish(identifier, public_consent=True)
    state = service._delivery(identifier)
    assert state.status == ("published_no_link" if failure == "result" else "unknown")
    assert "SECRET" not in str(state.detail)
    counts = list(service.adapter.calls)
    service.recover()
    with pytest.raises(PublishingError):
        service.prepare(post, account, "https://example.com/final.jpg", consent=True)
    with pytest.raises(PublishingError):
        service.publish(identifier, public_consent=True)
    assert service.adapter.calls == counts


def test_restart_marks_inflight_unknown_without_provider_call(app):
    post = make_post(app)
    service, account = delivery_setup(app, post)
    with app.state.sessions.begin() as session:
        row = ImagePostDelivery(post_id=post, account_id=account,
            media_sha256=service.get(post).sha256, status="publishing", detail={"container_id":"123"})
        session.add(row)
        session.flush()
        identifier = row.id
    service.recover()
    assert service._delivery(identifier).status == "unknown"
    assert not service.adapter.calls


def test_hosted_image_mismatch_blocks_meta_and_changes_after_review_block_publish(app):
    post = make_post(app)
    service, account = delivery_setup(app, post)
    service.fetcher = SimpleNamespace(fetch=lambda *a: b"different")
    identifier = service.prepare(post, account, "https://example.com/final.jpg", consent=True)
    assert service._delivery(identifier).status == "failed" and not service.adapter.calls
    path = service.path(post)
    path.write_bytes(b"changed")
    with pytest.raises(PublishingError):
        service.path(post)


def test_changed_account_blocks_publication(app):
    post = make_post(app)
    service, account = delivery_setup(app, post)
    identifier = service.prepare(post, account, "https://example.com/final.jpg", consent=True)
    service.check(identifier, consent=True)
    service.connections = SimpleNamespace(access_for_upload=lambda *a, **k: SimpleNamespace(
        instagram_id="999", page_id="222", app_id="333", bundle=None))
    service.publish(identifier, public_consent=True)
    assert service._delivery(identifier).status == "unknown"
    assert "publish" not in service.adapter.calls


@pytest.mark.parametrize("prior", ["0013", "0017"])
def test_migration_adds_only_image_tables_and_preserves_existing_data(tmp_path, prior):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    from newsflow.db.session import make_engine, migrate

    engine = make_engine(tmp_path / "migration.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] /
                        "src/newsflow/db/migrations"))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, prior)
        connection.exec_driver_sql("INSERT INTO app_settings(key,value) VALUES ('synthetic_voice','unchanged')")
        tables = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='alembic_version'"
        ).scalars().all()
        before = {t: connection.exec_driver_sql(f'SELECT * FROM "{t}"').all() for t in tables}
    migrate(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0018"
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
        assert all(connection.exec_driver_sql(f'SELECT * FROM "{t}"').all() == rows
                   for t, rows in before.items())
    engine.dispose()
