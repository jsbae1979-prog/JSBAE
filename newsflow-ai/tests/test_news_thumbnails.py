"""Provided image metadata, safe preview transport and local dashboard filtering."""
from io import BytesIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from sqlalchemy import select, text
from test_google_news_trends import no_external_calls

from newsflow.db.models import ArticleThumbnail, NewsArticle, NewsSource
from newsflow.db.session import make_engine, migrate
from newsflow.news.collector import CollectedArticle, parse_feed
from newsflow.news.rss_adapter import ErrorKind, FeedError, PublicRSSAdapter, Response
from newsflow.news.serpapi import parse_result
from newsflow.news.service import NewsService
from newsflow.news.thumbnails import ThumbnailService, raster_preview, thumbnail_url

__all__ = ["no_external_calls"]


def picture():
    buffer = BytesIO()
    info = PngInfo()
    info.add_text("Comment", "synthetic-private-metadata")
    Image.new("RGB", (640, 360), "#176495").save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


@pytest.mark.parametrize("supplied", [
    '<media:thumbnail url="https://img.example.com/preview.jpg"/>',
    '<media:content medium="image" url="https://img.example.com/preview.jpg"/>',
    '<enclosure type="image/jpeg" url="https://img.example.com/preview.jpg" length="100"/>',
    '<description>&lt;p&gt;요약&lt;/p&gt;&lt;img src="https://img.example.com/preview.jpg"&gt;</description>',
])
def test_rss_images_are_metadata_only(supplied):
    xml = f'<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>합성 뉴스</title><link>https://example.com/a</link>{supplied}</item></channel></rss>'
    item = parse_feed(xml.encode(), "합성 출처")[0]
    assert item.thumbnail_url == "https://img.example.com/preview.jpg"
    assert item.published_at is None and "<img" not in item.summary


@pytest.mark.parametrize("url", ["http://img.example.com/a.jpg", "https://127.0.0.1/a", "https://localhost/a",
                                 "file:///secret", "data:image/png,a", "javascript:alert(1)",
                                 "https://img.example.com/a?api_key=secret", "https://u:p@example.com/a",
                                 "https://serpapi.com/search.json", "https://api.anthropic.com/v1/messages"])
def test_invalid_optional_image_does_not_reject_news(url):
    assert thumbnail_url(url) is None
    articles, _ = parse_result({"search_metadata": {"status": "Success"}, "news_results": [
        {"title": "합성 기사", "link": "https://example.com/a", "thumbnail": url}]})
    assert len(articles) == 1 and articles[0].thumbnail_url is None


def test_serpapi_uses_article_thumbnail_not_author_or_source_icon():
    articles, _ = parse_result({"search_metadata": {"status": "Success"}, "news_results": [
        {"title": "합성 기사", "link": "https://example.com/a", "source": {"icon": "https://img.example.com/logo"},
         "author": {"thumbnail": "https://img.example.com/portrait"},
         "thumbnail": "https://img.example.com/news.jpg", "thumbnail_small": "https://img.example.com/small.jpg"}]})
    assert articles[0].thumbnail_url == "https://img.example.com/news.jpg"


def store(app, *, url="https://img.example.com/news.png", category="IT·과학", title="합성 기사"):
    with app.state.sessions.begin() as session:
        source = NewsSource(name="합성 출처", url="https://example.com/feed", enabled=False)
        session.add(source)
        session.flush()
        result = NewsService.store_articles(session, source.id, [CollectedArticle(
            title, "https://example.com/a", "합성 출처", "합성 요약", None, url)])
        article = session.get(NewsArticle, result["article_ids"][0])
        article.category = category
        return article.id


def test_store_dedup_preserves_existing_news_and_image(app):
    identifier = store(app)
    with app.state.sessions.begin() as session:
        article = session.get(NewsArticle, identifier)
        source_id = article.source_id
        result = NewsService.store_articles(session, source_id, [CollectedArticle(
            article.title, article.url, "다른 이름", "변경하지 않을 요약", None, "https://img.example.com/other.png")])
        assert result["duplicates"] == 1
        assert article.summary == "합성 요약" and article.published_at is None
        assert session.get(ArticleThumbnail, identifier).url == "https://img.example.com/news.png"


def test_thumbnail_is_same_origin_bounded_and_cached(client, app, fake):
    identifier = store(app)
    fake.feeds["https://img.example.com/news.png"] = picture()
    assert client.get(f"/news/{identifier}/thumbnail").status_code == 403  # No prior local session.
    html = client.get("/news").text
    assert f'src="/news/{identifier}/thumbnail"' in html and 'loading="lazy"' in html
    assert 'src="https://img.example.com' not in html and fake.calls == []
    response = client.get(f"/news/{identifier}/thumbnail")
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert "img-src 'self'" in response.headers["content-security-policy"]
    with Image.open(BytesIO(response.content)) as image:
        assert image.size == (320, 180) and image.format == "JPEG"
        assert not image.getexif() and "comment" not in image.info
    assert b"synthetic-private-metadata" not in response.content
    assert client.get(f"/news/{identifier}/thumbnail").status_code == 200
    assert fake.calls == ["https://img.example.com/news.png"]
    assert client.get(f"/news/{identifier}/thumbnail", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


@pytest.mark.parametrize("payload", [b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                                     b'<html>not an image</html>', b'x' * (2 * 1024 * 1024 + 1),
                                     FeedError("never expose secret", ErrorKind.ROBOTS)],
                         ids=["svg", "html", "oversized", "robots"])
def test_failed_images_keep_fallback_and_do_not_retry(client, app, fake, payload):
    identifier = store(app)
    fake.feeds["https://img.example.com/news.png"] = payload
    client.get("/")
    for _ in range(2):
        response = client.get(f"/news/{identifier}/thumbnail")
        assert response.status_code == 404 and "secret" not in response.text
    assert len(fake.calls) == 1


def test_public_image_transport_honors_robots_and_https_redirects():
    class Transport:
        def __init__(self, robots, location=None):
            self.robots, self.location, self.calls = robots, location, []

        def get(self, url, timeout):
            self.calls.append(url)
            if url.endswith("/robots.txt"):
                return Response(200, self.robots)
            return Response(302, b"", self.location) if self.location else Response(200, picture())

    blocked = Transport(b"User-agent: *\nDisallow: /")
    assert ThumbnailService(PublicRSSAdapter(blocked)).get("https://img.example.com/a") is None
    assert blocked.calls == ["https://img.example.com/robots.txt"]
    downgrade = Transport(b"User-agent: *\nAllow: /", "http://img.example.com/a")
    assert ThumbnailService(PublicRSSAdapter(downgrade)).get("https://img.example.com/a") is None
    assert all(url.startswith("https://") for url in downgrade.calls)


def test_large_pixel_image_rejected_before_decode():
    buffer = BytesIO()
    Image.new("1", (4100, 4000)).save(buffer, "PNG")
    with pytest.raises(ValueError, match="dimensions"):
        raster_preview(buffer.getvalue())


def test_dashboard_filters_all_stored_news_locally_and_removes_duplicate_cta(client, app, fake):
    identifier = store(app)
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource).where(NewsSource.url == "https://example.com/feed"))
        for index in range(8):
            session.add(NewsArticle(title=f"다른 경제 뉴스 {index}", url=f"https://example.com/e/{index}",
                                    canonical_url=f"https://example.com/e/{index}", source_id=source.id,
                                    publisher="합성 출처", category="경제", summary="합성 자료"))
    home = client.get("/")
    assert "지금 영상 만들기" not in home.text and "data-dash-news-category" in home.text
    tech = client.get("/dashboard/news?category=IT·과학")
    assert tech.status_code == 200 and "합성 기사" in tech.text and "다른 경제 뉴스" not in tech.text
    assert f'/news/{identifier}/thumbnail' in tech.text and "<html" not in tech.text
    economy = client.get("/dashboard/news?category=경제")
    assert economy.status_code == 200 and economy.text.count("다른 경제 뉴스") == 5
    assert "이 분야의 보관 뉴스가 없어요" in client.get("/dashboard/news?category=국제").text
    assert "합성 기사" in client.get("/?news_category=IT·과학").text
    assert client.get("/dashboard/news?category=bad").status_code == 422
    assert fake.calls == []


def test_additive_migration_preserves_synthetic_legacy_tables(tmp_path):
    engine = make_engine(tmp_path / "legacy.db")
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "src/newsflow/db/migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0015")
        connection.execute(text("INSERT INTO news_sources (id,name,url,enabled,created_at) VALUES (1,'synthetic','https://example.com/feed',0,'2026-10-20')"))
        connection.execute(text("INSERT INTO app_settings (key,value) VALUES ('keep','synthetic-only')"))
        names = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='alembic_version' ORDER BY name")).scalars().all()
        before = {name: connection.execute(text(f'SELECT * FROM "{name}"')).all() for name in names}
    migrate(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0017"
        assert connection.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        for name, rows in before.items():
            assert connection.execute(text(f'SELECT * FROM "{name}"')).all() == rows
        assert connection.execute(text("SELECT count(*) FROM article_thumbnails")).scalar() == 0
        assert connection.execute(text("SELECT count(*) FROM news_list_states")).scalar() == 0
        assert connection.execute(text("SELECT count(*) FROM workspace_removals")).scalar() == 0
    engine.dispose()
