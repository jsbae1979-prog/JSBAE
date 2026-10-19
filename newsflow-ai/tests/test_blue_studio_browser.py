"""Reference-inspired presentation, original routes and approvals; isolated Fake data only."""
from __future__ import annotations

import importlib.util
import os
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from sqlalchemy import func, select
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import save_values, stored_values

from newsflow.db.models import AutopilotJob, ContentDraft, IntelligenceRun, PublishAttempt
from newsflow.gui import production_routes, production_status
from newsflow.gui.routes import templates
from newsflow.intelligence.settings import write_studio_settings
from newsflow.video.supertonic_tts import SupertonicTTS
from newsflow.video.tts import WindowsTTS

browser = browser_fixture
SIZES = [(1366, 768), (1920, 1080), (390, 844)]


@pytest.fixture
def studio_ui(app, monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Studio UI must never call a real provider")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda _: [])
    monkeypatch.setattr(SupertonicTTS, "voices", lambda _: [])
    catalog = [{"name": "offline-silence", "label": "음성 없음 · 검토용", "engine": "offline", "available": True}]
    for module in (production_routes, production_status):
        monkeypatch.setattr(module, "voice_choice_catalog", lambda: [dict(row) for row in catalog])
    monkeypatch.setitem(templates.env.globals, "ui_demo", True)
    save_values(app, autopilot_source="feeds", autopilot_acquisition_policy="rss")
    write_studio_settings(app.state.sessions, "openai", "gpt-4.1-mini")
    return app


def capture(page, name):
    output = os.environ.get("NEWSFLOW_BLUE_STUDIO_EVIDENCE")
    if output:
        root = Path(output)
        root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / name))


def guarded_page(browser, origin, size):
    context = browser.new_context(viewport={"width": size[0], "height": size[1]}, locale="ko-KR")
    external, errors = [], []

    def guard(route):
        if urlsplit(route.request.url).netloc == urlsplit(origin).netloc:
            route.continue_()
        else:
            external.append(route.request.url)
            route.abort()

    context.route("**/*", guard)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    return context, page, external, errors


@pytest.mark.parametrize("size", SIZES, ids=["1366", "1920", "390"])
def test_home_creation_choices_archive_and_keyboard(studio_ui, browser, size):
    app = studio_ui
    before = stored_values(app)
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, size)
        response = page.goto(origin + "/")
        assert response.status == 200 and "script-src 'self'" in response.headers["content-security-policy"]
        expect(page.locator(".demo-banner")).to_be_visible()
        form = page.locator('form[action="/autopilot/quick-start"]')
        expect(form).to_be_visible()
        expect(page.get_by_role("button", name="쇼츠 만들기", exact=True)).to_be_visible()
        assert page.locator('details:has(form[action="/autopilot/quick-start"])').count() == 0
        expect(page.locator(".studio-phone-empty")).to_be_visible()
        assert page.locator("video, progress, iframe").count() == 0
        expect(page.locator("#archive-search")).not_to_have_attribute("open", "")
        assert page.locator('[name="topic"],option[value="VERIFIED"]').count() == 0
        assert page.locator(".studio-flow [aria-current]").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        primary = page.get_by_role("button", name="쇼츠 만들기", exact=True)
        assert primary.evaluate("e=>getComputedStyle(e).backgroundColor") == "rgb(36, 99, 235)"
        capture(page, f"home-empty-{size[0]}.png")
        # Native keyboard entry, not element presence alone.
        page.goto(origin + "/")
        page.keyboard.press("Tab")
        expect(page.get_by_role("link", name="본문으로 이동")).to_be_focused()
        page.keyboard.press("Enter")
        expect(page.locator("#main-content")).to_be_focused()
        page.locator('#quick-source').select_option('sample')
        expect(page.locator('#quick-category')).to_be_hidden()
        page.locator('#quick-source').select_option('feeds')
        expect(page.locator('#quick-category')).to_be_visible()
        page.locator('#quick-category').select_option('it')
        page.locator('#quick-duration').select_option('45')
        page.locator('#quick-period').select_option('24h')
        page.locator('#quick-voice-method').select_option('elevenlabs')
        page.locator('#quick-video-method').select_option('higgsfield')
        expect(page.locator('[data-external-voice-note]')).to_be_visible()
        expect(page.locator('[data-external-video-note]')).to_contain_text('모든 장면')
        page.locator('[name="script_review"]').uncheck()
        expect(page.locator('.studio-review-note')).to_contain_text('게시 승인')
        assert stored_values(app) == before
        page.locator('#quick-voice-method').select_option('local')
        page.locator('#quick-video-method').select_option('off')
        expect(page.locator('[data-external-voice-note]')).to_be_hidden()
        expect(page.locator('[data-external-video-note]')).to_be_hidden()
        # Expanded option data is still posted through the original form contract.
        values = form.evaluate('f=>Object.fromEntries(new FormData(f))')
        assert {k: values[k] for k in ('category', 'duration', 'period', 'voice_method', 'video_method')} == {
            'category': 'it', 'duration': '45', 'period': '24h', 'voice_method': 'local', 'video_method': 'off'}
        assert 'script_review' not in values
        page.locator('#archive-search > summary').click()
        page.locator('#home-topic').fill('https://example.com/new-article')
        page.get_by_role('button', name='보관 기사 검색', exact=False).click()
        expect(page.locator('[data-topic-error]')).to_be_visible()
        expect(page.locator('#home-topic')).to_be_focused()
        page.locator('#home-topic').fill('합성 자료')
        page.get_by_role('button', name='보관 기사 검색', exact=False).click()
        page.wait_for_url('**/news?q=*')
        expect(page.locator('input[name="q"]')).to_have_value('합성 자료')
        page.goto(origin + '/create')
        expect(page.locator('[name="script_review"]')).to_be_checked()
        assert page.locator('#archive-search').count() == 0
        capture(page, f'create-{size[0]}.png')
        with app.state.sessions() as session:
            assert session.scalar(select(func.count()).select_from(AutopilotJob)) == 0
        assert stored_values(app) == before and not external and not errors
        context.close()


def test_portrait_library_edit_playback_and_publish_keep_original_boundaries(studio_ui, browser, tmp_path):
    app = studio_ui
    # Existing guarded demo seed: real local silent MP4s, synthetic covers/articles and error state.
    path = Path(__file__).resolve().parents[1] / 'tools' / 'ui_preview.py'
    spec = importlib.util.spec_from_file_location('blue_studio_preview_seed', path)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    demo.seed(app, tmp_path)
    with app.state.sessions() as session:
        original_runs = session.scalar(select(func.count()).select_from(IntelligenceRun))
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, SIZES[0])
        for width, height in SIZES:
            page.set_viewport_size({'width': width, 'height': height})
            for name, url in [('home', '/'), ('videos', '/videos'),
                              ('preview', '/?video=1&publish_platform=unified#workspace-detail'),
                              ('settings', '/simple-settings')]:
                assert page.goto(origin + url).status == 200
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                capture(page, f'{name}-populated-{width}.png')
                if name == 'home':
                    expect(page.locator('.studio-phone-video')).to_be_visible()
                    page.wait_for_function('document.querySelector(".studio-phone-video img").naturalWidth > 0')
                    capture(page, f'home-populated-{width}.png')
                    assert page.locator('video').count() == 0
                if name == 'videos':
                    assert page.locator('video').count() == 0
                    poster = page.locator('.workspace-video-poster').first.bounding_box()
                    assert abs(poster['width'] / poster['height'] - 9 / 16) < .01
                if name == 'preview':
                    player = page.locator('[data-workspace-player]')
                    expect(player).to_be_visible()
                    assert page.locator('.studio-new-production').count() == 1
                    expect(page.locator('.studio-new-production')).not_to_have_attribute('open', '')
                    player.evaluate('async v=>{v.muted=true;await v.play()}')
                    page.wait_for_function('document.querySelector("[data-workspace-player]").currentTime > 0')
                    player.evaluate('v=>v.pause()')
                    page.locator('#workspace-detail').evaluate('e=>e.scrollIntoView({block:"start",behavior:"instant"})')
                    expect(player).to_be_in_viewport()
                    capture(page, f'preview-populated-{width}.png')
                    page.get_by_role('link', name='대본·자막 편집 →', exact=True).click()
                    page.wait_for_url('**/ai?draft_id=1')
                    page.get_by_role('button', name='장면 2', exact=True).click()
                    expect(page.locator('[data-topic-scene]:visible')).to_have_count(1)
                    expect(page.get_by_role('button', name='장면 2', exact=True)).to_have_attribute('aria-pressed', 'true')
                    capture(page, f'editor-{width}.png')
            assert page.goto(origin + '/?video=1&publish_platform=unified#publish-workspace').status == 200
            expect(page.locator('#publish-workspace')).to_be_visible()
            page.locator('#publish-workspace').evaluate('e=>e.scrollIntoView({block:"start",behavior:"instant"})')
            capture(page, f'publish-{width}.png')
        with app.state.sessions() as session:
            assert session.scalar(select(func.count()).select_from(IntelligenceRun)) == original_runs
            assert session.scalar(select(func.count()).select_from(PublishAttempt)) == 0
            assert session.get(ContentDraft, 1).review_status == 'review_required'
        assert not external and not errors
        context.close()
