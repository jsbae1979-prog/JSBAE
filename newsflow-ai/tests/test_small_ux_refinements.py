"""Small UI refinements: local fixtures, blocked external traffic, no generation."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from test_ai_script_simple_ui import browser, script_ui, studio_ui
from test_cloud_workspace_flow import local_server
from test_single_workspace import stored_values, video_fixture
from test_youtube_gui import forbid_external_calls  # noqa: F401

__all__ = ['browser', 'script_ui', 'studio_ui']


@pytest.fixture(autouse=True)
def no_workers(monkeypatch):
    monkeypatch.setattr('newsflow.scheduler.service.Scheduler.start', lambda self: None)
    monkeypatch.setattr('newsflow.publishing.calendar.PublishingCalendar.start', lambda self: None)


def test_small_changes_keep_category_state_consent_and_one_preview(script_ui, browser):
    app, analysis, _draft = script_ui
    videos = [video_fixture(app, f'보존할 합성 영상 {i}') for i in range(3)]
    before = stored_values(app)
    output = Path(os.environ['NEWSFLOW_SMALL_UX_EVIDENCE'])
    output.mkdir(parents=True, exist_ok=True)
    external, posts, errors = [], [], []
    with local_server(app) as origin:
        context = browser.new_context(viewport={'width':1440, 'height':1000}, locale='ko-KR')
        def guard(route):
            if urlsplit(route.request.url).netloc != urlsplit(origin).netloc:
                external.append(route.request.url)
                route.abort()
            elif route.request.method != 'GET':
                posts.append(urlsplit(route.request.url).path)
                route.abort()
            else:
                route.continue_()
        context.route('**/*', guard)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        for width in [1440,390]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.goto(origin+'/news').status == 200
            expect(page.locator('select[name=category]')).to_have_count(0)
            expect(page.locator('input[name=category]')).to_have_attribute('type','hidden')
            page.get_by_role('button',name='정치',exact=True).click()
            expect(page.locator('input[name=category]')).to_have_value('정치')
            page.locator('.suite-search-line input[name=q]').fill('보관')
            page.get_by_role('button',name='검색',exact=True).click()
            expect(page.locator('input[name=category]')).to_have_value('정치')
            expect(page.locator('[data-news-category="정치"]')).to_have_attribute('aria-pressed','true')
            assert 'category=' in page.url and 'q=' in page.url
            page.screenshot(path=str(output/f'news-{width}.png'),full_page=True)
            assert page.goto(origin+'/').status == 200
            expect(page.locator('.dash-preview video')).to_have_count(1)
            expect(page.locator('.dashboard-video-strip,[data-dash-video]')).to_have_count(0)
            expect(page.locator('.dash-preview video')).to_have_attribute('preload','none')
            expect(page.locator('.dash-preview-actions>a')).to_have_count(2)
            expect(page.locator('.dash-preview-actions a').first).to_have_text('영상 확인')
            expect(page.locator('.dash-preview-actions a').last).to_contain_text('MP4 저장')
            expect(page.locator('.dash-player-ambient')).to_have_count(0)
            frame=page.locator('.dash-preview .dash-player-stage').bounding_box()
            assert abs(frame['width']/frame['height']-9/16)<.01
            more=page.locator('.dash-preview-more')
            expect(more).not_to_have_attribute('open','')
            more.locator('>summary').click()
            expect(page.locator('[data-dash-edit]')).to_be_visible()
            page.locator('.dash-preview .cleanup-control>summary').click()
            dialog=page.get_by_role('dialog',name='삭제 확인')
            expect(dialog).to_be_visible()
            expect(dialog.locator('[name=confirm]')).not_to_be_checked()
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            more.locator('>summary').click()
            latest = videos[-1]['id']
            expect(page.locator('[data-dashboard-player] source')).to_have_attribute('src',f'/video/jobs/{latest}/file')
            expect(page.locator('[data-dash-download]')).to_have_attribute('href',f'/video/jobs/{latest}/file?download=true')
            expect(page.locator('[data-dash-review]')).to_have_attribute('href',f'/?video={latest}&publish_platform=unified#workspace-detail')
            assert 'newsflow-earth-generated.png' in page.locator('.mockup-dashboard').evaluate("e=>getComputedStyle(e,'::before').backgroundImage")
            page.screenshot(path=str(output/f'dashboard-{width}.png'),full_page=True)
            assert page.goto(origin+f'/ai?analysis_id={analysis}').status == 200
            trigger=page.get_by_role('link',name='대본 생성 준비',exact=False)
            trigger.click()
            dialog=page.locator('#script-create-dialog')
            expect(dialog).to_be_visible()
            form=dialog.locator('form[action="/ai/generate"]')
            form.locator('.script-technical summary').click()
            provider=form.locator('[name=provider]')
            provider.select_option('claude_api')
            expect(form.locator('[data-script-generate-label]')).to_have_text('Claude API로 대본 생성')
            expect(form.locator('[name=consent]')).not_to_be_checked()
            expect(form.locator('[name=consent]')).to_have_attribute('required','')
            form.locator('[name=consent]').check()
            form.locator('[name=duration]').select_option('45')
            expect(form.locator('[name=consent]')).not_to_be_checked()
            provider.select_option('openai')
            expect(form.locator('[data-script-generate-label]')).to_have_text('OpenAI API로 대본 생성')
            provider.select_option('offline')
            expect(form.locator('[data-script-generate-label]')).to_have_text('체험 대본 생성')
            provider.select_option('claude_api')
            expect(form.locator('[name=consent]')).not_to_be_checked()
            page.screenshot(path=str(output/f'script-ready-{width}.png'))
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            expect(trigger).to_be_focused()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        context.close()
    assert stored_values(app) == before
    assert not posts and not external and not errors
