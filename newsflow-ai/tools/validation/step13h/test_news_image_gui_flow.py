"""Additional real-click path, synthetic article/AI/TTS, no external provider calls."""
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect
from sqlalchemy import select
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser
from test_news_image_linking import registered
from test_video import video

from newsflow.db.models import ContentDraft, RenderJob, Scene, VideoProject
from newsflow.video.engine import FFmpegAdapter

__all__ = ["browser", "video"]


def test_gui_news_click_selection_to_real_image_video_no_provider_calls(app, video, browser, fake):
    coordinator, original_draft_id = video
    row = registered(app, video)
    coordinator.engine = FFmpegAdapter()
    errors, external = [], []
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 980, "height": 900}, locale="ko-KR")
        def boundary(route):
            if urlsplit(route.request.url).netloc == urlsplit(origin).netloc:
                route.continue_()
            else:
                external.append(route.request.url);route.abort()
        context.route("**/*", boundary)
        page = context.new_page();page.on("pageerror", lambda e: errors.append(str(e)))
        assert page.goto(origin + "/news").status == 200
        page.locator('.suite-news-article[href="/news/1"]').click()
        expect(page).to_have_url(origin + "/news/1")
        page.get_by_role("link", name="이 기사로 쇼츠 만들기", exact=False).click()
        page.wait_for_load_state("networkidle")
        form = page.locator('form[action="/ai/analyze"]')
        # The existing hash-link handler selects the clicked article after page load.
        expect(form.locator('[name="article_ids"][value="1"]')).to_be_checked()
        form.locator('.script-technical > summary').click()
        form.locator('[name="provider"]').select_option("offline")
        form.locator('[name="model"]').fill("offline")
        if form.locator('[name="consent"]').is_visible():form.locator('[name="consent"]').check()
        with page.expect_navigation(wait_until="load"):
            form.get_by_role("button", name="선택 기사 분석", exact=False).click()
        assert "analysis_id=" in page.url
        page.get_by_role("link", name="대본 생성 준비", exact=False).click()
        form = page.locator('form[action="/ai/generate"]')
        form.locator('[name="duration"]').select_option("30")
        form.locator('.script-technical > summary').click()
        form.locator('[name="provider"]').select_option("offline")
        form.locator('[name="model"]').fill("offline")
        if form.locator('[name="consent"]').is_visible():form.locator('[name="consent"]').check()
        with page.expect_navigation(wait_until="load"):
            form.locator('button[type="submit"]').click()
        draft_id = int(parse_qs(urlsplit(page.url).query)["draft_id"][0])
        assert draft_id != original_draft_id
        page.get_by_role("link", name="이 대본으로 영상 구성", exact=False).click()
        expect(page).to_have_url(origin + f"/video?draft_id={draft_id}")
        page.locator('#news-image-links > summary').click()
        expect(page.locator('[data-news-image-state="automatic"]').first).to_be_visible()
        assert page.locator('.news-image-linked-preview').evaluate_all('(images)=>images.every(i=>i.complete && i.naturalWidth>0)')
        # A scene click must expose its actual controls without mutating the draft.
        page.locator('[data-video-scene-select="1"]').first.click()
        expect(page.locator('[data-video-scene="1"]')).to_be_visible()
        expect(page.locator('[data-video-scene="0"]')).to_be_hidden()
        form = page.locator('form[action="/video/render"]')
        form.locator('.video-voice-choice > summary').click()
        form.locator('[name="voice"]').select_option("offline-silence")
        form.locator('[name="reviewed"]').check()
        with page.expect_navigation(wait_until="load"):
            form.get_by_role("button", name="영상 제작 실행", exact=True).click()
        identifier = int(parse_qs(urlsplit(page.url).query)["job_id"][0])
        coordinator.future.result(180)
        page.reload(wait_until="networkidle")
        player = page.locator('video.video-preview')
        expect(player).to_be_visible()
        player.evaluate('async v=>{v.muted=true;await v.play()}')
        page.wait_for_function('document.querySelector("video.video-preview").currentTime>0')
        player.evaluate('v=>v.pause()')
        out = Path(os.environ["NEWSFLOW_VALIDATION_OUTPUT"])
        page.screenshot(path=str(out/'news-selected-to-video.png'), full_page=True)
        with app.state.sessions() as session:
            job = session.get(RenderJob, identifier)
            project = session.get(VideoProject, job.project_id)
            assert job.status == "success" and job.metadata_json["playable"]
            assert (job.metadata_json["width"], job.metadata_json["height"]) == (1080,1920)
            assert project.draft_id == draft_id
            assert all(link["mode"] == "automatic" and link["sha256"] == row["sha256"] for link in project.snapshot["news_images"])
            assert all(scene.material == row["name"] for scene in session.scalars(select(Scene).where(Scene.project_id == project.id)))
            assert session.get(ContentDraft, original_draft_id).revision == 1
        assert not fake.calls and not external and not errors
        (out/'real-click-flow-safe.json').write_text(json.dumps({"news_card_click":True,"article_selected":True,
            "analysis_and_script":"Offline Fake","new_draft":True,"scene_click_controls":True,
            "automatic_image_snapshot":True,"MP4":[1080,1920],"browser_playback":True,
            "provider_calls":0,"OAuth_or_SNS":0,"original_draft_unchanged":True}),encoding="utf-8")
        context.close()
