"""Isolated visual audit; phase=before records accepted PR baseline, after asserts decoration."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from conftest import app, fake, rss
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser
from test_single_workspace import video_fixture
from test_youtube_gui import forbid_external_calls

PHASE = os.environ.get('STORYFLOW_PHASE', 'after')
OUT = Path(os.environ['STORYFLOW_EVIDENCE']) / PHASE
ASSET = '/static/images/newsflow-storyflow-illustration.svg'

@pytest.mark.parametrize('populated', [False, True], ids=['empty', 'populated'])
def test_library_flow(app, browser, populated):
    # Only synthetic video record bytes; this is not a rendering/playback test.
    if populated:
        video_fixture(app, '[합성 검증] 긴 한글 제목으로 확인하는 뉴스 영상과 출처 보존')
    OUT.mkdir(parents=True, exist_ok=True)
    before = (app.state.config.data_dir / 'newsflow.db').read_bytes()
    external, mutations, errors = [], [], []
    metrics = []
    with local_server(app) as origin:
        context = browser.new_context(locale='ko-KR')
        def guard(route):
            if urlsplit(route.request.url).netloc != urlsplit(origin).netloc:
                external.append(route.request.url)
                route.abort()
            elif route.request.method != 'GET':
                mutations.append(route.request.url)
                route.abort()
            else:
                route.continue_()
        context.route('**/*', guard)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        for width, height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            response = page.goto(origin+'/videos', wait_until='networkidle')
            assert response.status == 200
            assert "script-src 'self'" in response.headers['content-security-policy']
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            if not populated:
                expect(page.get_by_role('heading',name='첫 번째 이야기를 기다리고 있어요.')).to_be_visible()
                cta = page.get_by_role('link', name='첫 영상 만들기 →', exact=True)
                image = page.locator(f'img[src="{ASSET}"]')
                expect(image).to_have_count(1 if PHASE == 'after' else 0)
                if PHASE == 'after':
                    expect(image).to_have_attribute('alt','')
                    expect(image).to_have_attribute('aria-hidden','true')
                    assert image.evaluate('(e)=>e.complete && e.naturalWidth > 0')
                    assert image.evaluate('(e)=>getComputedStyle(e).objectFit') == 'contain'
                    assert image.bounding_box()['width'] <= 440
                cta.focus()
                expect(cta).to_be_focused()
                page.keyboard.press('Shift+Tab')
                page.keyboard.press('Tab')
                expect(cta).to_be_focused()
                assert cta.evaluate('(e)=>getComputedStyle(e).outlineStyle') != 'none'
                metrics.append({'viewport':f'{width}x{height}', 'cta':cta.bounding_box(),
                                'outline':cta.evaluate('(e)=>getComputedStyle(e).outlineColor'),
                                'text':page.get_by_role('heading',name='첫 번째 이야기를 기다리고 있어요.').evaluate('(e)=>getComputedStyle(e).color'),
                                'colors':cta.evaluate('''(e)=>({button:getComputedStyle(e).color, buttonBackground:getComputedStyle(e).backgroundColor, body:getComputedStyle(e.parentElement.querySelector("p")).color, panel:getComputedStyle(e.closest(".gentle-empty")).backgroundColor})''')})
                # Focus and navigation must work without click-only interactions.
                page.screenshot(path=str(OUT/f'empty-{width}-focus.png'))
                page.keyboard.press('Enter')
                page.wait_for_url(origin+'/create')
                expect(page.locator('form[action="/autopilot/quick-start"]')).to_be_visible()
                page.goto(origin+'/videos',wait_until='networkidle')
            else:
                expect(page.locator(f'img[src="{ASSET}"]')).to_have_count(0)
                expect(page.locator('.workspace-video-card')).to_have_count(1)
                expect(page.get_by_role('link',name='대본·자막 편집',exact=True)).to_be_visible()
                expect(page.get_by_role('link',name='게시 준비',exact=True)).to_be_visible()
            page.screenshot(path=str(OUT/f'{"populated" if populated else "empty"}-{width}.png'))
            if not populated:
                page.locator('.creator-library').screenshot(path=str(OUT/f'empty-{width}-detail.png'))
        context.close()
    assert not external and not mutations and not errors
    assert (app.state.config.data_dir/'newsflow.db').read_bytes() == before
    (OUT/f'{"populated" if populated else "empty"}-audit.json').write_text(json.dumps({
        'phase':PHASE,'metrics':metrics,'external_requests':external,'mutations':mutations,'page_errors':errors,
        'database_bytes_preserved':True},ensure_ascii=False,indent=2))
