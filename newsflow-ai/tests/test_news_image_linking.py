"""Synthetic, offline rights/provenance -> immutable scenes -> real MP4 and Chrome."""
from copy import deepcopy
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image
from sqlalchemy import select
from conftest import csrf
from test_video import video
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from newsflow.db.models import ArticleThumbnail, ContentDraft, NewsArticle, RenderJob, Scene, VideoProject
from newsflow.news.collector import parse_feed
from newsflow.news.serpapi import parse_result
from newsflow.video.engine import FFmpegAdapter, RenderError
from newsflow.video.news_images import NewsImages, NewsImageError
from newsflow.video.service import VideoError
from newsflow.video.tts import local_process_env

__all__ = ["video", "browser"]


def picture(color="#d52222", size=(640, 360)):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def local(coordinator, name="fixture.png", color="#d52222"):
    path = coordinator.assets / name
    path.write_bytes(picture(color))
    return path


def registered(app, video, origin="representative", name="fixture.png", color="#d52222"):
    coordinator, draft_id = video
    local(coordinator, name, color)
    with app.state.sessions() as session:
        article = session.get(NewsArticle, 1)
        return coordinator.news_images.remember(article, name, source_url="https://example.com/photo.png",
                                                rights_basis="테스트 직접 제작 이미지", origin=origin)


@pytest.mark.parametrize("source", ["rss", "serpapi", "google-news"])
def test_supplied_thumbnail_needs_rights_and_explicit_import(app, video, fake, source):
    coordinator, draft_id = video
    url = "https://example.com/photo.png"
    if source == "rss":
        item = parse_feed(f'<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>합성</title><link>https://example.com/1</link><media:thumbnail url="{url}"/></item></channel></rss>'.encode(), "합성")[0]
    else:
        item = parse_result({"search_metadata": {"status": "Success"}, "news_results": [
            {"title": "합성 기사", "link": "https://example.com/1", "thumbnail": url}]})[0][0]
    assert item.thumbnail_url == url
    fake.feeds[url] = picture()
    with app.state.sessions() as session:
        article = session.get(NewsArticle, 1)
        metadata = ArticleThumbnail(article_id=1, url=url, source_article_url=article.url, publisher=article.publisher)
        sources = session.get(ContentDraft, draft_id).sources
        assert not any(coordinator.news_images.choose(session, sources, 3)[0])
        assert fake.calls == []
        row = coordinator.news_images.import_thumbnail(article, metadata, fake, rights_basis="직접 제작한 합성 이미지")
        assert fake.calls == [url]
        assert coordinator.news_images.import_thumbnail(article, metadata, fake, rights_basis="직접 제작한 합성 이미지") == row
        assert fake.calls == [url]
        assert coordinator.news_images.choose(session, sources, 3)[0] == [row["name"]] * 3
        assert coordinator.news_images.candidates(article)[0]["source_url"] == url


@pytest.mark.parametrize("order", [("search", "collected", "representative"), ("representative", "search", "collected")])
def test_selection_priority_and_explicit_card_and_manual(app, video, order):
    coordinator, draft_id = video
    rows = {origin: registered(app, video, origin, origin + ".png") for origin in order}
    local(coordinator, "manual.png", "blue")
    with app.state.sessions() as session:
        sources = session.get(ContentDraft, draft_id).sources
        names, metadata = coordinator.news_images.choose(session, sources, 3, ["manual.png", "", "__card__"])
    assert names == ["manual.png", rows["representative"]["name"], ""]
    assert [m["mode"] for m in metadata] == ["manual", "automatic", "card"]
    assert metadata[1]["rights_basis"] == "테스트 직접 제작 이미지"
    assert metadata[2]["reason"] == "사용자가 기본 카드 선택"


@pytest.mark.parametrize("name", ["../secret.png", r"..\secret.png", "C:/secret.png", "https://example.com/a.png",
                                   "file:///a.png", "a.png:secret", "a.svg", "a.gif", "", "a.png\0"])
def test_arbitrary_paths_and_formats_rejected(video, name):
    with pytest.raises((NewsImageError, RenderError)):
        video[0].news_images.asset(name)


@pytest.mark.parametrize("url", ["http://example.com/a", "https://127.0.0.1/a", "file:///secret",
                                  "https://u:p@example.com/a", "https://example.com/a?api_key=secret"])
def test_bad_thumbnail_url_never_downloaded(app, video, fake, url):
    with app.state.sessions() as session:
        article = session.get(NewsArticle, 1)
        metadata = ArticleThumbnail(article_id=1, url=url, source_article_url=article.url, publisher="합성")
        with pytest.raises(NewsImageError):
            video[0].news_images.import_thumbnail(article, metadata, fake, rights_basis="직접 제작한 테스트")
    assert fake.calls == []


@pytest.mark.parametrize("fault", ["missing", "corrupt", "tamper", "rights", "article-url"])
def test_invalid_cached_image_falls_back_without_mutating_original(app, video, fault):
    row = registered(app, video)
    coordinator, draft_id = video
    original_hash = hashlib.sha256((coordinator.assets / "fixture.png").read_bytes()).hexdigest()
    path = coordinator.assets / row["name"]
    if fault == "missing": path.unlink()
    elif fault == "corrupt": path.write_bytes(b"broken")
    elif fault == "tamper": path.write_bytes(picture("blue"))
    else:
        record = next(coordinator.news_images.records.glob("*.json"))
        value = json.loads(record.read_text())
        value["rights_basis" if fault == "rights" else "article_url"] = "" if fault == "rights" else "https://other.example/a"
        record.write_text(json.dumps(value))
    with app.state.sessions() as session:
        sources = session.get(ContentDraft, draft_id).sources
        assert coordinator.news_images.choose(session, sources, 3)[0] == [""] * 3
    assert hashlib.sha256((coordinator.assets / "fixture.png").read_bytes()).hexdigest() == original_hash


@pytest.mark.parametrize("raw", [b"corrupt", b"<svg><script>unsafe</script></svg>", b"x" * (20 * 1024 * 1024 + 1)], ids=["corrupt", "svg", "oversize"])
def test_import_invalid_bytes_rejected_without_asset(app, video, fake, raw):
    url = "https://example.com/photo.png"; fake.feeds[url] = raw
    with app.state.sessions() as session:
        article = session.get(NewsArticle, 1)
        metadata = ArticleThumbnail(article_id=1, url=url, source_article_url=article.url, publisher="합성")
        with pytest.raises((ValueError, RenderError)):
            video[0].news_images.import_thumbnail(article, metadata, fake, rights_basis="직접 제작한 합성")
    assert not list(video[0].assets.iterdir())


def test_symlink_outside_assets_rejected(video, tmp_path):
    target = tmp_path / "outside.png"; target.write_bytes(picture())
    # Windows permits junctions without developer-mode symlink privileges.
    directory = video[0].assets / "linked"
    from _winapi import CreateJunction
    CreateJunction(str(tmp_path), str(directory))
    try:
        with pytest.raises(NewsImageError):
            video[0].news_images.safe(directory / "outside.png", video[0].assets)
    finally:
        directory.rmdir()


def test_project_snapshot_persists_selection_after_registry_and_defaults_change(app, video):
    row = registered(app, video)
    coordinator, draft_id = video
    identifier = coordinator.start(draft_id, 30, reviewed=True)
    coordinator.future.result(20)
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        project = session.get(VideoProject, job.project_id)
        before = deepcopy(project.snapshot)
        assert all(m["mode"] == "automatic" for m in before["news_images"])
        assert all(s.material == row["name"] for s in session.scalars(select(Scene).where(Scene.project_id == project.id)))
    registered(app, video, "representative", "different.png", "blue")
    restarted = NewsImages(coordinator.root)
    with app.state.sessions() as session:
        assert session.get(VideoProject, job.project_id).snapshot == before
        assert restarted.candidates(session.get(NewsArticle, 1))
        assert session.get(ContentDraft, draft_id).revision == 1


def test_multi_article_mapping_and_foreign_article_rejection(app, video):
    coordinator, draft_id = video
    registered(app, video)
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, draft_id)
        article = NewsArticle(title="두 번째 합성", summary="합성", url="https://example.com/2", canonical_url="https://example.com/2", publisher="합성", source_id=1)
        session.add(article);session.flush()
        other = deepcopy(draft.sources["articles"][0]); other["id"] = article.id
        sources = {**draft.sources, "articles": [*draft.sources["articles"], other]}
        assert coordinator.news_images.choose(session, sources, 2)[0] == ["", ""]
        assert coordinator.news_images.choose(session, sources, 2, article_ids=[1, article.id])[0][0]
        with pytest.raises(NewsImageError):
            coordinator.news_images.choose(session, sources, 2, article_ids=[999, 1])


def test_manual_permission_still_required_and_never_auto_overwritten(app, video):
    coordinator, draft_id = video
    registered(app, video)
    local(coordinator, "manual.png", "blue")
    count = len(coordinator.timings(_draft(app, draft_id).content, 30))
    with pytest.raises(VideoError):
        coordinator.start(draft_id, 30, reviewed=True, images=["manual.png"] * count)
    identifier = coordinator.start(draft_id, 30, reviewed=True, images=["manual.png"] * count, asset_permission=True)
    coordinator.future.result(20)
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        assert all(row["mode"] == "manual" for row in session.get(VideoProject, job.project_id).snapshot["news_images"])
        assert all(scene.material == "manual.png" for scene in session.scalars(select(Scene).where(Scene.project_id == job.project_id)))


def _draft(app, identifier):
    with app.state.sessions() as session:
        return session.get(ContentDraft, identifier)


def test_gui_local_linking_requires_csrf_permission_and_no_fetch(client, app, video, fake):
    coordinator, draft_id = video
    local(coordinator)
    form = {"draft_id": draft_id, "article_id": 1, "name": "fixture.png", "rights_basis": "직접 제작한 합성", "permission": "true"}
    assert client.post("/video/news-image", data=form).status_code == 403
    form["csrf_token"] = csrf(client)
    assert client.post("/video/news-image", data={**form, "permission": "false"}).status_code == 422
    assert client.post("/video/news-image", data={**form, "article_id": 999}).status_code == 422
    response = client.post("/video/news-image", data=form)
    assert response.status_code == 200 and 'data-news-image-state="automatic"' in response.text
    assert fake.calls == []


def test_real_mp4_every_auto_scene_has_expected_pixels(app, video, tmp_path):
    coordinator, draft_id = video
    colors = ["#d52222", "#22b533", "#2456dc", "#d2ab22"]
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, draft_id)
        count = len(draft.content["scenes"]); assert 1 <= count <= 4
        sources = deepcopy(draft.sources)
        first = session.get(NewsArticle, 1)
        articles = [first]
        for index in range(1, count):
            article = NewsArticle(title=f"합성 장면 {index}", summary="합성", url=f"https://example.com/{index+1}", canonical_url=f"https://example.com/{index+1}", publisher="합성", source_id=1)
            session.add(article);session.flush();articles.append(article)
            copy = deepcopy(sources["articles"][0]);copy["id"] = article.id
            sources["articles"].append(copy)
        draft.sources = sources
        for index, article in enumerate(articles):
            name = f"color-{index}.png";local(coordinator, name, colors[index])
            coordinator.news_images.remember(article, name, source_url=article.url, rights_basis="테스트용 직접 제작", origin="representative")
        ids = [a.id for a in articles]
    coordinator.engine = FFmpegAdapter()
    identifier = coordinator.start(draft_id, 30, reviewed=True, image_article_ids=ids)
    coordinator.future.result(180)
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        assert job.status == "success", job.message
        assert (job.metadata_json["width"], job.metadata_json["height"]) == (1080, 1920)
        scenes = list(session.scalars(select(Scene).where(Scene.project_id == job.project_id).order_by(Scene.position)))
        output = coordinator.output_path(job.output_name)
        evidence = Path(os.environ["NEWSFLOW_VALIDATION_OUTPUT"]) / "news-image-mp4"
        evidence.mkdir(exist_ok=True);shutil.copyfile(output, evidence / "automatic-scenes.mp4")
        checks = []
        for index, scene in enumerate(scenes):
            frame = evidence / f"scene-{index+1}.png"
            result = subprocess.run([str(FFmpegAdapter.executable("ffmpeg", None)), "-nostdin", "-v", "error", "-ss", str((scene.start_ms+scene.end_ms)/2000), "-i", str(output), "-frames:v", "1", "-threads", "1", str(frame)], shell=False, env=local_process_env(), capture_output=True, timeout=30)
            assert result.returncode == 0
            with Image.open(frame) as image:
                pixel = image.getpixel((500, 900))[:3]
                wanted = tuple(bytes.fromhex(colors[index][1:]))
                assert max(abs(a-b) for a,b in zip(pixel, wanted)) < 15, (pixel, wanted)
            checks.append({"scene": index, "pixel": pixel, "expected": wanted, "PASS": True})
        (evidence / "pixel-proof.json").write_text(json.dumps({"size": [1080, 1920], "all_scenes": checks}), encoding="utf-8")


@pytest.mark.parametrize("width", [1440, 980, 390])
def test_browser_news_to_video_and_manual_scene_controls(app, video, browser, width):
    coordinator, draft_id = video
    registered(app, video)
    local(coordinator, "manual.png", "blue")
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": width, "height": 900}, locale="ko-KR")
        requests = []; errors = []
        def route_handler(route):
            if route.request.url.startswith(origin + "/"):
                route.continue_()
            else:
                requests.append(route.request.url);route.abort()
        context.route("**/*", route_handler)
        page = context.new_page();page.on("pageerror", lambda exc: errors.append(str(exc)))
        assert page.goto(origin + "/news").status == 200
        assert page.get_by_text("한국어 영상 제작 합성 뉴스", exact=False).first.is_visible()
        assert page.goto(origin + f"/video?draft_id={draft_id}").status == 200
        page.locator("#news-image-links > summary").click()
        assert page.locator('[data-news-image-state="automatic"]').count() > 0
        page.locator("#video-advanced-editing > summary").click()
        first = page.locator('[name="images"]').first
        first.select_option("manual.png")
        assert first.input_value() == "manual.png"
        first.select_option("__card__")
        assert first.input_value() == "__card__"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+2")
        output = Path(os.environ["NEWSFLOW_VALIDATION_OUTPUT"]) / f"news-images-{width}.png"
        page.screenshot(path=str(output), full_page=True)
        assert not requests and not errors
        context.close()


@pytest.mark.parametrize("origin", ["collected", "search"])
def test_invalid_primary_uses_next_licensed_candidate(app, video, origin):
    coordinator, draft_id = video
    top = registered(app, video, "representative", "primary.png")
    next_row = registered(app, video, origin, "secondary.png", "blue")
    (coordinator.assets / top["name"]).write_bytes(b"broken")
    with app.state.sessions() as session:
        names, rows = coordinator.news_images.choose(session, session.get(ContentDraft, draft_id).sources, 2)
    assert names == [next_row["name"]] * 2
    assert all(row["origin"] == origin for row in rows)


def test_thumbnail_download_failure_and_forged_url_do_not_write_or_retry(client, app, video, fake):
    coordinator, draft_id = video
    url = "https://example.com/missing.png"
    with app.state.sessions.begin() as session:
        article = session.get(NewsArticle, 1)
        session.add(ArticleThumbnail(article_id=1, url=url, source_article_url=article.url, publisher=article.publisher))
    token = csrf(client)
    response = client.post("/video/news-image", data={"csrf_token": token, "draft_id": draft_id,
        "article_id": 1, "name": "__thumbnail__", "permission": "true", "rights_basis": "테스트 이용 허락",
        "url": "https://evil.invalid/should-not-be-used"})
    assert response.status_code == 422
    assert fake.calls == [url]
    assert not coordinator.news_images.records.exists()
    assert not list(coordinator.assets.iterdir())


def test_approved_preview_uses_only_local_image(client, app, video, fake):
    registered(app, video)
    response = client.get("/video/news-images/articles/1")
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(response.content)) as image:
        assert image.size == (320, 180)
    assert client.get("/video/news-images/articles/999").status_code == 404
    assert not fake.calls


def test_auto_image_hash_change_after_job_snapshot_stops_render(app, video, monkeypatch):
    from concurrent.futures import Future
    coordinator, draft_id = video
    row = registered(app, video)
    pending = []
    def hold(function, *args):
        pending.append((function, args))
        future = Future();future.set_result(None);return future
    monkeypatch.setattr(coordinator.executor, "submit", hold)
    identifier = coordinator.start(draft_id, 30, reviewed=True)
    (coordinator.assets / row["name"]).write_bytes(picture("blue"))
    function, args = pending[0];function(*args)
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        assert job.status == "failed"
        assert not job.metadata_json.get("playable")
    assert not list(coordinator.outputs.glob("*.mp4"))


@pytest.mark.parametrize("value", [[], None, {"rights_basis": 123}, "broken-metadata"])
def test_malformed_registration_is_safe_card_fallback(app, video, value):
    coordinator, draft_id = video
    coordinator.news_images.records.mkdir()
    (coordinator.news_images.records / "1-malformed.json").write_text(json.dumps(value), encoding="utf-8")
    with app.state.sessions() as session:
        names, rows = coordinator.news_images.choose(session, session.get(ContentDraft, draft_id).sources, 3)
    assert names == [""] * 3 and all(row["mode"] == "card" for row in rows)



def test_large_approved_local_image_preview_does_not_use_RSS_response_limit(client, app, video):
    coordinator, _ = video
    path = coordinator.assets / "large.png"
    Image.frombytes("RGB", (1200, 800), os.urandom(1200 * 800 * 3)).save(path)
    assert 2 * 1024 * 1024 < path.stat().st_size < 20 * 1024 * 1024
    with app.state.sessions() as session:
        row = coordinator.news_images.remember(session.get(NewsArticle, 1), path.name,
            source_url="https://example.com/own-photo", rights_basis="직접 제작한 합성 이미지")
    assert (coordinator.assets / row["name"]).stat().st_size > 2 * 1024 * 1024
    response = client.get("/video/news-images/articles/1")
    assert response.status_code == 200
    with Image.open(BytesIO(response.content)) as image:
        assert image.width <= 320 and image.height <= 180
        assert image.format == "JPEG" and not image.getexif() and "icc_profile" not in image.info


def test_registered_clean_image_strips_metadata_and_preserves_original(app, video):
    coordinator, _ = video
    path = coordinator.assets / "metadata.png"
    Image.new("RGB", (640, 360), "red").save(path, icc_profile=b"SYNTHETIC_PRIVATE_PROFILE")
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    with app.state.sessions() as session:
        row = coordinator.news_images.remember(session.get(NewsArticle, 1), path.name,
            source_url="https://example.com/own-photo", rights_basis="직접 제작한 합성 이미지")
    with Image.open(coordinator.assets / row["name"]) as image:
        assert "icc_profile" not in image.info and not image.getexif()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original


@pytest.mark.parametrize("fault", ["cleared", "junction", "corrupt", "missing"])
def test_frozen_job_rechecks_image_binding_and_parent_junction(app, video, monkeypatch, tmp_path, fault):
    from concurrent.futures import Future
    from _winapi import CreateJunction
    coordinator, draft_id = video
    row = registered(app, video);pending=[]
    def hold(function, *args):
        pending.append((function,args));future=Future();future.set_result(None);return future
    monkeypatch.setattr(coordinator.executor,"submit",hold)
    identifier=coordinator.start(draft_id,30,reviewed=True)
    saved=None
    if fault=="cleared":
        with app.state.sessions.begin() as session:
            job=session.get(RenderJob,identifier)
            scene=session.scalar(select(Scene).where(Scene.project_id==job.project_id))
            scene.material=""
    elif fault in ("corrupt", "missing"):
        target=coordinator.assets/row["name"]
        if fault=="corrupt":target.write_bytes(b"corrupt")
        else:target.unlink()
    else:
        outside=tmp_path/'outside-assets';outside.mkdir()
        (outside/row["name"]).write_bytes((coordinator.assets/row["name"]).read_bytes())
        saved=coordinator.root/'saved-assets'
        assert saved.resolve().is_relative_to(coordinator.root)
        coordinator.assets.rename(saved)
        CreateJunction(str(outside),str(coordinator.assets))
    try:
        function,args=pending[0];function(*args)
        with app.state.sessions() as session:
            job=session.get(RenderJob,identifier)
            assert job.status=="failed" and job.metadata_json["failure_stage"]=="image"
        assert not list(coordinator.outputs.glob("*.mp4"))
    finally:
        if saved is not None:
            coordinator.assets.rmdir();saved.rename(coordinator.assets)


def test_image_failure_has_specific_local_recovery_action():
    from types import SimpleNamespace
    from newsflow.gui.video_presentation import video_presentation
    shown=video_presentation(SimpleNamespace(status="failed", metadata_json={"failure_stage":"image"},message="합성 실패"))
    assert shown["stage"]=="뉴스 이미지" and shown["action"]=="/video"
    assert "새 작업" in shown["message"]


@pytest.mark.parametrize("format", ["JPEG", "WEBP"])
def test_jpeg_and_webp_supplied_images_become_clean_local_png(app, video, fake, format):
    output=BytesIO();Image.new("RGB",(640,360),"#2468ac").save(output,format=format)
    url="https://example.com/owned."+format.lower();fake.feeds[url]=output.getvalue()
    with app.state.sessions() as session:
        article=session.get(NewsArticle,1)
        metadata=ArticleThumbnail(article_id=1,url=url,source_article_url=article.url,publisher=article.publisher)
        row=video[0].news_images.import_thumbnail(article,metadata,fake,rights_basis="직접 제작한 합성 이미지")
    with Image.open(video[0].assets/row["name"]) as image:
        assert image.format=="PNG" and image.size==(640,360)
        assert not image.getexif() and "icc_profile" not in image.info
    assert fake.calls==[url]
