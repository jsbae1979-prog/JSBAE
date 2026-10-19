"""One settings editor, explicit service approvals, retained stored values; no vendor calls."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_settings_simplification import configured, save_values, synthetic_stores, values

from newsflow.gui import production_routes, production_status
from newsflow.gui.routes import templates
from newsflow.intelligence.api_settings import read_api_settings
from newsflow.intelligence.settings import write_studio_settings
from newsflow.video.ai.settings import read_settings, write_settings

browser = browser_fixture


def test_settings_edit_save_reenter_and_creation_without_external_actions(app, browser, monkeypatch, tmp_path):
    output = Path(os.environ.get("NEWSFLOW_SETTINGS_EVIDENCE", os.environ.get("NEWSFLOW_VALIDATION_OUTPUT", str(tmp_path))))
    output.mkdir(parents=True, exist_ok=True)
    write_studio_settings(app.state.sessions, "openai", "gpt-4.1-mini")
    monkeypatch.setitem(templates.env.globals, "ui_demo", True)
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="ko-KR")
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
        for path, name in (("/simple-settings", "settings-after.png"), ("/video-ai-settings", "higgsfield-after.png")):
            assert page.goto(origin + path).status == 200
            page.screenshot(path=str(output / name), full_page=True)
        # Use synthetic key storage; its binding is identical to app initialization.
        stores = synthetic_stores(app)
        configured(app, "openai")
        save_values(app, video_default_voice="supertonic:F1", autopilot_source="feeds",
                    autopilot_acquisition_policy="rss", video_default_rate="0", video_default_pause_ms="250")
        monkeypatch.setattr(production_status, "voice_choice_catalog", lambda: [{
            "name": "supertonic:F1", "label": "Supertonic F1", "engine": "supertonic", "available": True}])
        monkeypatch.setattr(production_routes, "voice_choice_catalog", production_status.voice_choice_catalog)
        page.goto(origin + "/simple-settings")
        expect(page.locator('#openai-key-settings')).not_to_have_attribute('open', '')
        expect(page.locator('#openai-key-settings input[name="api_key"]')).to_be_hidden()
        expect(page.locator('[name="provider"]')).to_have_value('openai')
        assert page.locator('.settings-summary, [data-summary-stage], #settings-advanced-tools').count() == 0
        assert page.locator('.settings-savebar').evaluate("e=>getComputedStyle(e).position") == 'static'
        assert page.locator('a[href="/ai-settings"]').count() == 0
        for text in ('권장', 'SDK', 'Authorization:', 'NEWSFLOW_', '%LOCALAPPDATA%', 'DPAPI'):
            assert text not in page.locator('body').inner_text()
        for width, height in ((1366, 768), (1920, 1080), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.set_viewport_size({"width": 1366, "height": 768})
        before = read_api_settings(app.state.sessions, 'openai')
        key_bytes = {key: store.path.read_bytes() for key, store in stores.items()}
        page.get_by_text('제작 기본값', exact=True).click()
        page.locator('[name="duration"]').select_option('45')
        page.get_by_role('button', name='제작 구성 저장', exact=True).click()
        expect(page.get_by_role('status').filter(has_text='제작 구성을 저장했습니다')).to_be_visible()
        page.reload()
        expect(page.locator('[name="duration"]')).to_have_value('45')
        assert read_api_settings(app.state.sessions, 'openai') == before
        assert {key: store.path.read_bytes() for key, store in stores.items()} == key_bytes
        page.get_by_role("tab", name="비용 관리", exact=True).click()
        costs = page.locator('[data-settings-open="api-costs-openai"]')
        costs.click()
        dialog = page.locator('#api-costs-openai')
        expect(dialog).to_be_visible()
        expect(dialog.locator('[name="billing_confirmed"]')).not_to_be_checked()
        page.keyboard.press('Escape')
        expect(costs).to_be_focused()
        # Old bookmarks reach the canonical editor, not a second preference form.
        page.goto(origin + '/ai-settings')
        assert urlsplit(page.url).path == '/simple-settings'
        assert page.locator('form[action="/production/preferences"]').count() == 1
        page.goto(origin + '/create')
        expect(page.locator('[name="duration"]')).to_have_value('45')
        expect(page.locator('[name="script_review"]')).to_be_checked()
        expect(page.locator('#quick-voice-method')).to_have_value('local')
        expect(page.locator('#quick-video-method')).to_have_value('off')
        # Hidden operational parameters preserve prior saved runtime behavior.
        write_settings(app.state.sessions, provider='higgsfield', host='api.higgsfield.ai', approved=False,
                       monthly_limit='100', job_limit='5', currency='USD', max_active=3, timeout_minutes=42, poll_seconds=17)
        runtime = read_settings(app.state.sessions)
        page.goto(origin + '/video-ai-settings')
        for name in ('host', 'max_active', 'timeout_minutes', 'poll_seconds'):
            field = page.locator(f'#video-ai-settings-form [name="{name}"]')
            expect(field).to_have_attribute('type', 'hidden')
        expect(page.locator('#video-ai-model-management')).not_to_have_attribute('open', '')
        assert '확인된 모델이 없습니다' in page.locator('#video-ai-models').inner_text()
        page.get_by_role('button', name='AI 영상 설정 저장', exact=True).click()
        page.wait_for_url('**/video-ai-settings?saved=settings')
        assert read_settings(app.state.sessions) == runtime
        assert values(app)['autopilot_duration'] == '45'
        expect(page.locator('#video-ai-model-management [name="confirmed"]').last).not_to_be_checked()
        assert not external and not errors
        context.close()


def test_settings_tabs_preserve_pending_values_deep_links_and_validation(app, browser, tmp_path):
    from test_blue_studio_browser import guarded_page

    output = Path(os.environ.get("NEWSFLOW_SETTINGS_EVIDENCE", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366,768))
        posts = []
        page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
        sections = [('뉴스·대본 AI','connections'),('기본 음성','quality'),('AI 영상','video-settings'),
                    ('비용 관리','costs'),('게시 계정','accounts'),('운영 관리','advanced')]
        for width, height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            page.goto(origin+'/simple-settings#connections')
            for label, identifier in sections:
                tab = page.get_by_role('tab', name=label, exact=True)
                tab.click()
                expect(page.locator('[role=tabpanel]:visible')).to_have_count(1)
                expect(page.locator('#'+identifier)).to_be_visible()
                expect(tab).to_have_attribute('aria-selected','true')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output/f'tab-{identifier}-{width}.png'))
        assert not posts
        page.set_viewport_size({'width':1366,'height':768})
        page.get_by_role('tab',name='뉴스·대본 AI',exact=True).click()
        page.get_by_text('제작 기본값',exact=True).click()
        page.locator('[name=duration]').select_option('45')
        page.get_by_role('tab',name='AI 영상',exact=True).click()
        expect(page.locator('#production-unsaved')).to_be_visible()
        assert page.locator('#production-preferences').evaluate("f=>new FormData(f).get('duration')")=='45'
        page.get_by_role('button',name='제작 구성 저장',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='제작 구성을 저장했습니다')).to_be_visible()
        expect(page.locator('#video-settings')).to_be_visible()
        page.reload()
        expect(page.locator('#video-settings')).to_be_visible()
        expect(page.locator('[name=duration]')).to_have_value('45')
        assert values(app)['autopilot_duration']=='45'
        # Browser back/forward and keyboard navigation select only one panel.
        page.get_by_role('tab',name='기본 음성',exact=True).click()
        page.get_by_role('tab',name='게시 계정',exact=True).click()
        page.go_back();expect(page.locator('#quality')).to_be_visible()
        page.go_forward();expect(page.locator('#accounts')).to_be_visible()
        page.get_by_role('tab',name='게시 계정',exact=True).focus()
        page.keyboard.press('Home')
        expect(page.get_by_role('tab',name='뉴스·대본 AI',exact=True)).to_be_focused()
        page.keyboard.press('ArrowRight')
        expect(page.locator('#quality')).to_be_visible()
        # Validation on an off-screen required model opens its owning tab.
        page.locator('[data-model-choice]').evaluate("el=>el.setCustomValidity('모델을 확인하세요')")
        page.get_by_role('button',name='제작 구성 저장',exact=True).click()
        expect(page.locator('#connections')).to_be_visible()
        page.locator('[data-model-choice]').evaluate("el=>el.setCustomValidity('')")
        before_links = len(posts)
        for anchor, panel in [('selected-voice','quality'),('selected-video','video-settings'),
                              ('youtube','accounts'),('instagram','accounts'),('production','connections')]:
            page.goto(origin+'/simple-settings#'+anchor)
            expect(page.locator('#'+panel)).to_be_visible()
            expect(page.locator('[role=tabpanel]:visible')).to_have_count(1)
        page.goto(origin+'/simple-settings#api-costs-openai')
        expect(page.locator('#costs')).to_be_visible()
        expect(page.locator('#api-costs-openai')).to_be_visible()
        expect(page.locator('#api-costs-openai [name=billing_confirmed]')).not_to_be_checked()
        page.keyboard.press('Escape')
        assert len(posts)==before_links
        assert not external and not errors
        context.close()
