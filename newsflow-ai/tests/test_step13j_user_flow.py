"""Step13J: one synthetic RSS -> browser edits -> local MP4 -> unapproved draft.

No real provider or credentials. FakeTTS produces silent PCM; this does not
claim human Korean voice quality or actual supplier API success.
"""
import hashlib
import json
import os
import shutil
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from PIL import Image
from playwright.sync_api import expect
from sqlalchemy import func, select
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser
from test_news_image_linking import picture

from newsflow.db.models import (
    AppSetting,
    ArticleThumbnail,
    AudioTrack,
    CollectionRun,
    ContentDraft,
    NewsArticle,
    NewsSource,
    PublishAttempt,
    PublishDraft,
    PublishJob,
    RenderJob,
    Scene,
    VideoProject,
)
from newsflow.intelligence.korean import speech_plan
from newsflow.video.engine import FFmpegAdapter
from newsflow.video.tts import FakeTTS, local_process_env

__all__ = ["browser"]
FEED = "https://example.com/step13j/rss"
ARTICLE = "https://example.com/step13j/news"
IMAGE = "https://example.com/step13j/photo.png"
TITLE = "합성 우주 기술 공개 소식"


def _post(page, path, action):
    """Observe POST, the real GET document, and DOM readiness, ignoring hash events."""
    target = {"url": None}
    # Easy forms perform a fetch redirect, then replaceState and reload. A generic
    # navigation wait can resolve on replaceState with no document response.
    with page.expect_event("domcontentloaded"), page.expect_response(
        lambda r: target["url"] is not None
        and r.request.is_navigation_request()
        and r.request.method == "GET"
        and r.url.split("#")[0] == target["url"].split("#")[0]
    ) as redirected:
        with page.expect_response(
            lambda r: urlsplit(r.url).path == path and r.request.method == "POST"
        ) as response:
            action()
        posted = response.value
        assert posted.status == 303
        location = posted.headers.get("location")
        assert location, "protected form must return its real redirect target"
        target["url"] = urljoin(posted.url, location)
        assert urlsplit(target["url"]).netloc == urlsplit(posted.url).netloc
    document = redirected.value
    assert document.status == 200 and document.request.is_navigation_request()
    assert "'unsafe-eval'" not in document.headers["content-security-policy"]
    expect(page).to_have_url(target["url"])
    page.wait_for_load_state("networkidle")

def test_synthetic_rss_to_manual_image_video_and_unapproved_local_publish_draft(app, fake, browser):
    fake.feeds.clear()
    fake.feeds.update({FEED: (f'''<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>합성 출처</title><item><title>{TITLE}</title><link>{ARTICLE}</link>
<description>합성 기관이 우주 기술의 공개 시연을 진행했습니다. 공개 자료에는 기술 소개와 안전 확인 절차가 포함되어 있으며, 실제 사건이나 성능 보장을 뜻하지 않습니다.</description>
<pubDate>Sun, 25 Oct 2026 00:00:00 GMT</pubDate><media:thumbnail url="{IMAGE}"/>
</item></channel></rss>''').encode(), IMAGE: picture("#d52222")})
    with app.state.sessions.begin() as session:
        for source in session.scalars(select(NewsSource)):
            source.enabled = False
        session.add(NewsSource(name="Step13J 합성 RSS", url=FEED, enabled=True))
        assert session.scalar(select(func.count()).select_from(NewsArticle)) == 0
        defaults_before = {row.key: row.value for row in session.scalars(select(AppSetting))}
    coordinator = app.state.video
    coordinator.engine = FFmpegAdapter()
    tts = FakeTTS()
    coordinator.tts = tts
    automatic_file = coordinator.assets / "j-automatic.png"
    manual_file = coordinator.assets / "j-manual.png"
    automatic_file.write_bytes(picture("#d52222"))
    manual_file.write_bytes(picture("#2456dc"))
    originals = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (automatic_file, manual_file)}
    evidence = Path(os.environ["NEWSFLOW_VALIDATION_OUTPUT"]) / "step13j-user-flow"
    evidence.mkdir(parents=True, exist_ok=True)
    external, errors, mutations = [], [], []
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 980, "height": 900}, locale="ko-KR")
        try:
            def boundary(route):
                if urlsplit(route.request.url).netloc == urlsplit(origin).netloc:
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()
            context.route("**/*", boundary)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: mutations.append(urlsplit(request.url).path)
                    if request.method not in {"GET", "HEAD", "OPTIONS"} else None)
            assert page.goto(origin + "/sources").status == 200
            _post(page, "/sources/collect", lambda: page.locator("#collect-button").click())
            app.state.coordinator.future.result(30)
            with app.state.sessions() as session:
                run = session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()))
                assert run.status == "success" and run.added == 1
                article = session.scalar(select(NewsArticle))
                article_id = article.id
                assert article.title == TITLE and article.url == ARTICLE
                assert session.get(ArticleThumbnail, article_id).url == IMAGE
                # Register only the locally generated, explicitly licensed fixture.
                automatic = coordinator.news_images.remember(
                    article, automatic_file.name, source_url=IMAGE,
                    rights_basis="테스트에서 직접 제작한 합성 이미지", origin="representative")
            assert fake.calls.count(FEED) == 1
            assert page.goto(origin + "/news").status == 200
            page.locator(f'.suite-news-article[href="/news/{article_id}"]').click()
            expect(page).to_have_url(origin + f"/news/{article_id}")
            page.get_by_role("link", name="이 기사로 쇼츠 만들기", exact=False).click()
            page.wait_for_load_state("networkidle")
            form = page.locator('form[action="/ai/analyze"]')
            expect(form.locator(f'[name="article_ids"][value="{article_id}"]')).to_be_checked()
            form.locator('.script-technical > summary').click()
            form.locator('[name="provider"]').select_option("offline")
            form.locator('[name="model"]').fill("offline")
            if form.locator('[name="consent"]').is_visible():
                form.locator('[name="consent"]').check()
            _post(page, "/ai/analyze", lambda: form.get_by_role("button", name="선택 기사 분석", exact=False).click())
            assert "analysis_id=" in page.url
            page.get_by_role("link", name="대본 생성 준비", exact=False).click()
            form = page.locator('form[action="/ai/generate"]')
            form.locator('[name="duration"]').select_option("30")
            form.locator('.script-technical > summary').click()
            form.locator('[name="provider"]').select_option("offline")
            form.locator('[name="model"]').fill("offline")
            if form.locator('[name="consent"]').is_visible():
                form.locator('[name="consent"]').check()
            _post(page, "/ai/generate", lambda: form.locator('button[type="submit"]').click())
            draft_id = int(parse_qs(urlsplit(page.url).query)["draft_id"][0])
            with app.state.sessions() as session:
                draft = session.get(ContentDraft, draft_id)
                draft_before = deepcopy((draft.content, draft.sources, draft.revision))
                estimate = speech_plan(draft.content, 30)
                assert estimate["duration"] == 30 and estimate["estimated_total_seconds"] > 0
                assert len(estimate["scenes"]) == len(draft.content["scenes"])
                assert round(sum(row["estimated_seconds"] for row in estimate["scenes"]), 2) == estimate["estimated_total_seconds"]
            page.get_by_role("link", name="이 대본으로 영상 구성", exact=False).click()
            expect(page).to_have_url(origin + f"/video?draft_id={draft_id}")
            page.locator('#news-image-links > summary').click()
            expect(page.locator('[data-news-image-state="automatic"]').first).to_be_visible()
            assert page.locator('.news-image-linked-preview').evaluate_all('(images)=>images.length>0 && images.every(i=>i.complete && i.naturalWidth>0)')
            form = page.locator('form[action="/video/render"]')
            page.locator('#video-advanced-editing > summary').click()
            form.locator('[data-video-scene="0"] [name="images"]').select_option(manual_file.name)
            page.locator('[data-video-scene-select="1"]').first.click()
            expect(form.locator('[data-video-scene="1"]')).to_be_visible()
            expect(form.locator('[data-video-scene="0"]')).to_be_hidden()
            assert form.locator('[data-video-scene="0"] [name="images"]').input_value() == manual_file.name
            permission = form.locator('[name="asset_permission"]')
            permission.locator('xpath=ancestor::details[1]').locator(':scope > summary').click()
            permission.check()
            form.locator('.video-voice-choice > summary').click()
            form.locator('[name="voice"]').select_option("offline-silence")
            expect(form.locator('[name="external_tts_consent"]')).not_to_be_checked()
            form.locator('[name="reviewed"]').check()
            _post(page, "/video/render", lambda: form.get_by_role("button", name="영상 제작 실행", exact=True).click())
            render_id = int(parse_qs(urlsplit(page.url).query)["job_id"][0])
            coordinator.future.result(240)
            with app.state.sessions() as session:
                job = session.get(RenderJob, render_id)
                assert job.status == "success", job.message
                assert job.metadata_json["playable"]
                assert (job.metadata_json["width"], job.metadata_json["height"]) == (1080, 1920)
                project = session.get(VideoProject, job.project_id)
                snapshot = deepcopy(project.snapshot)
                assert project.duration == 30 and project.draft_id == draft_id
                assert snapshot["news_images"][0]["mode"] == "manual"
                assert snapshot["news_images"][0]["sha256"] == originals[manual_file.name]
                assert all(row["mode"] == "automatic" and row["sha256"] == automatic["sha256"]
                           for row in snapshot["news_images"][1:])
                scenes = list(session.scalars(select(Scene).where(Scene.project_id == project.id).order_by(Scene.position)))
                assert scenes[0].material == manual_file.name
                assert all(scene.material == automatic["name"] for scene in scenes[1:])
                assert scenes[0].start_ms == 0 and scenes[-1].end_ms == 30000
                audio = session.scalar(select(AudioTrack).where(AudioTrack.project_id == project.id))
                assert audio.voice == "offline-silence" and audio.status == "success"
                assert len(tts.calls) == len(scenes)
                output = coordinator.output_path(job.output_name)
                media_sha = hashlib.sha256(output.read_bytes()).hexdigest()
                shutil.copyfile(output, evidence / "synthetic-rss-manual-scene.mp4")
                pixel_checks = []
                for index, scene in enumerate(scenes):
                    frame = evidence / f"scene-{index+1}.png"
                    result = subprocess.run([str(FFmpegAdapter.executable("ffmpeg", None)), "-nostdin", "-v", "error",
                        "-ss", str((scene.start_ms + scene.end_ms) / 2000), "-i", str(output),
                        "-frames:v", "1", "-threads", "1", str(frame)], shell=False,
                        env=local_process_env(), capture_output=True, timeout=30, check=False)
                    assert result.returncode == 0
                    with Image.open(frame) as image:
                        pixel = image.getpixel((500, 900))[:3]
                    expected = (36, 86, 220) if index == 0 else (213, 34, 34)
                    assert max(abs(a-b) for a, b in zip(pixel, expected)) < 15
                    pixel_checks.append({"scene": index, "pixel": pixel, "expected": expected})
            page.reload(wait_until="networkidle")
            player = page.locator('video.video-preview')
            expect(player).to_be_visible()
            player.evaluate('async video=>{video.muted=true;await video.play()}')
            deadline = time.monotonic() + 15
            while player.evaluate('video=>video.currentTime') <= 0 and time.monotonic() < deadline:
                time.sleep(.1)
            assert player.evaluate('video=>video.currentTime') > 0
            player.evaluate('video=>video.pause()')
            page.screenshot(path=str(evidence / "video-preview.png"), full_page=True)
            page.get_by_role("button", name="영상 정보·출처", exact=True).click()
            dialog = page.get_by_role("dialog", name="영상 정보·출처")
            expect(dialog).to_be_visible()
            dialog.get_by_role("link", name="이 영상으로 게시 준비", exact=True).click()
            page.wait_for_load_state("networkidle")
            form = page.locator('#publish-create')
            form.locator('[name="platform"]').select_option("youtube")
            form.locator('[name="youtube_category_id"]').select_option("25")
            form.locator('[name="title"]').fill("Step13J 합성 영상 로컬 초안")
            assert form.locator('[name="account_id"]').input_value() == ""
            for field in ("content_reviewed", "copyright_confirmed", "sources_confirmed"):
                expect(form.locator(f'[name="{field}"]')).not_to_be_checked()
            _post(page, "/publishing/drafts", lambda: form.get_by_role("button", name="게시 초안 저장", exact=True).click())
            publish_id = int(parse_qs(urlsplit(page.url).query)["draft_id"][0])
            _post(page, f"/publishing/drafts/{publish_id}/validate", lambda: page.locator('#publish-validate button').click())
            expect(page.locator('#publish-readiness')).to_have_attribute("data-state", "blocked")
            page.screenshot(path=str(evidence / "unapproved-local-publish-draft.png"), full_page=True)
            with app.state.sessions() as session:
                publish = session.get(PublishDraft, publish_id)
                assert publish.render_job_id == render_id and publish.media_sha256 == media_sha
                assert publish.account_id is None and publish.state == "blocked"
                assert not publish.content_reviewed and not publish.copyright_confirmed and not publish.sources_confirmed
                assert publish.ai_disclosure == "unreviewed" and publish.sources == draft_before[1]
                assert session.scalar(select(func.count()).select_from(PublishJob)) == 0
                assert session.scalar(select(func.count()).select_from(PublishAttempt)) == 0
                saved = session.get(ContentDraft, draft_id)
                assert (saved.content, saved.sources, saved.revision) == draft_before
                assert session.get(VideoProject, project.id).snapshot == snapshot
                assert {row.key: row.value for row in session.scalars(select(AppSetting))} == defaults_before
            assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (automatic_file, manual_file)} == originals
            assert fake.calls.count(FEED) == 1 and all(url in {FEED, IMAGE} for url in fake.calls)
            assert mutations == ["/sources/collect", "/ai/analyze", "/ai/generate", "/video/render",
                                 "/publishing/drafts", f"/publishing/drafts/{publish_id}/validate"]
            assert not external and not errors
            (evidence / "flow-safe.json").write_text(json.dumps({
                "RSS": "one Fake feed collected and persisted", "selected_article": True,
                "analysis_script": "Offline provider, no paid request", "automatic_images": True,
                "manual_first_scene_preserved": True, "voice": "FakeTTS silent PCM, not actual speech",
                "speech_estimate": estimate, "MP4": [1080, 1920, 30], "pixels": pixel_checks,
                "browser_playback": True, "local_publish_draft": True, "public_approval": False,
                "publish_validation": "blocked", "publish_jobs": 0, "publish_attempts": 0,
                "defaults_and_source_draft_preserved": True, "page_external_requests": 0,
                "real_API_OAuth_SNS_calls": 0,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            context.close()
