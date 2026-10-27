"""Interact with implemented controls in Chromium; all adapters/data are synthetic."""
import os
from pathlib import Path

from playwright.sync_api import expect
from test_api_shorts_intelligence import api as api_fixture
from test_blue_studio_browser import guarded_page
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture

from newsflow.db.models import ContentDraft, RenderJob, VideoProject
from newsflow.gui.routes import templates
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.tts import FakeTTS

api = api_fixture
browser = browser_fixture


def test_style_generation_scene_effects_and_layout(api, app, browser, monkeypatch):
    service, adapter, sessions, mode, options, ids = api
    monkeypatch.setitem(templates.env.globals, "ui_demo", True)
    analysis = service.analyze(ids, mode, True, options, news_usage='QUICK')
    first = service.generate(analysis, 30, mode, True, options, article_ids=ids[:1])
    monkeypatch.setattr('newsflow.gui.intelligence_routes.service', lambda _request, _context=None: service)
    app.state.video.engine = FakeRenderAdapter()
    app.state.video.tts = FakeTTS()
    with sessions() as session:
        original = session.get(ContentDraft, first).content.copy()
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366, 768))
        for width, height in [(1366, 768), (1920, 1080), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.goto(origin + f'/ai?draft_id={first}')
            page.locator('.script-style-panel summary').click()
            style = page.locator('.script-style-panel [name=script_style]')
            style.select_option('explainer')
            page.locator('.script-style-panel [name=script_tone]').select_option('friendly')
            page.locator('.script-style-panel [name=script_audience]').select_option('beginner')
            # Native required consent and server checks remain distinct from changing options.
            page.locator('.script-style-panel button').click()
            assert page.locator('.script-style-panel input[name=consent]').evaluate('e=>!e.checkValidity()')
            assert adapter.calls == ['analysis', 'script']
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            style.focus()
            expect(style).to_be_focused()
            if os.environ.get('NEWSFLOW_CONTROL_EVIDENCE') and mode == 'openai':
                root = Path(os.environ['NEWSFLOW_CONTROL_EVIDENCE']); root.mkdir(parents=True, exist_ok=True)
                page.locator('.script-style-panel').scroll_into_view_if_needed()
                page.screenshot(path=str(root / f'script-{width}.png'))
            page.goto(origin + f'/video?draft_id={first}')
            page.locator('[data-video-scene-select="0"]').first.click()
            page.locator('[data-scene-effect="0"]').select_option('fade')
            expect(page.locator('.track-effect button').first).to_contain_text('페이드')
            page.locator('.track-effect button').last.click()
            expect(page.locator('[data-video-scene]:visible')).to_have_count(1)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if os.environ.get('NEWSFLOW_CONTROL_EVIDENCE') and mode == 'openai':
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(root / f'video-{width}.png'))
        # Explicit action: a NEW draft with the same selected subset, provider and source evidence.
        page.goto(origin + f'/ai?draft_id={first}')
        page.locator('.script-style-panel summary').click()
        page.locator('.script-style-panel [name=script_style]').select_option('briefing')
        page.locator('.script-style-panel [name=consent]').check()
        page.locator('.script-style-panel button').click()
        page.wait_for_url('**/ai?analysis_id=**&draft_id=*')
        assert adapter.calls == ['analysis', 'script', 'script']
        second = int(page.url.split('draft_id=')[-1])
        assert first != second
        with sessions() as session:
            draft = session.get(ContentDraft, second)
            assert draft.sources['presentation']['style'] == 'briefing'
            assert [article['id'] for article in draft.sources['articles']] == ids[:1]
            assert draft.review_status == 'review_required'
            assert session.get(ContentDraft, first).content == original
        page.goto(origin + f'/video?draft_id={second}')
        page.locator('.video-voice-choice > summary').click()
        page.locator('[name=voice]').select_option('offline-silence')
        page.locator('[data-video-scene-select="0"]').first.click()
        page.locator('[data-scene-effect="0"]').select_option('fade')
        page.locator('[name=reviewed]').check()
        page.get_by_role('button', name='영상 제작 실행', exact=True).click()
        page.wait_for_url('**/video?job_id=*')
        app.state.video.future.result(timeout=15)
        job_id = int(page.url.split('job_id=')[-1])
        with sessions() as session:
            job = session.get(RenderJob, job_id)
            assert job.status == 'simulated'
            project = session.get(VideoProject, job.project_id)
            assert project.snapshot['effects'][0] == 'fade'
        assert not external and not errors
        context.close()
