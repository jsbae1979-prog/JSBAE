"""One shared preference source; synthetic data and no external execution."""

from copy import deepcopy
from pathlib import Path

import pytest
from conftest import csrf
from playwright.sync_api import expect
from test_blue_studio_browser import guarded_page
from test_blue_studio_browser import studio_ui as studio_ui_fixture
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import save_values, stored_values
from test_workflow_card import seed_card

from newsflow.db.models import ContentDraft, IntelligenceRun
from newsflow.intelligence.settings import read_studio_settings

studio_ui = studio_ui_fixture
browser = browser_fixture


def change(client, kind, value, **extra):
    return client.post('/production/selection', data={
        'csrf_token': csrf(client), 'kind': kind, 'value': value, 'return_to': '/', **extra,
    }, follow_redirects=False)


@pytest.mark.parametrize('method,provider,policy', [
    ('claude_api|ai_web', 'claude_api', 'ai_web'), ('claude_api|rss', 'claude_api', 'rss'),
    ('claude_code|rss', 'claude_code', 'rss'), ('codex|rss', 'codex', 'rss'),
    ('offline|rss', 'offline', 'rss'), ('openai|rss', 'openai', 'rss'),
])
def test_news_selection_preserves_models_approvals_history_and_job(studio_ui, client, method, provider, policy):
    app = studio_ui
    draft_id = seed_card(app)
    save_values(app, studio_model_claude_api='claude-sonnet-4-6', studio_model_codex='saved-codex',
                ai_approved_at='2026-10-20', api_claude_api_unknown_ack='preserved-synthetic-record')
    before = stored_values(app)
    with app.state.sessions() as session:
        run = session.get(IntelligenceRun, session.get(ContentDraft, draft_id).run_id)
        original = deepcopy(run.options)
    response = change(client, 'news', method)
    assert response.status_code == 303
    after = stored_values(app)
    assert after == {**before, 'studio_provider': provider, 'autopilot_acquisition_policy': policy}
    assert read_studio_settings(app.state.sessions)['provider'] == provider
    with app.state.sessions() as session:
        run = session.get(IntelligenceRun, session.get(ContentDraft, draft_id).run_id)
        assert run.options == original
        assert session.get(ContentDraft, draft_id).review_status == 'review_required'


def test_voice_video_save_only_their_field_and_never_fallback(studio_ui, client):
    app = studio_ui
    before = stored_values(app)
    assert change(client, 'voice', 'elevenlabs').status_code == 303
    assert stored_values(app) == {**before, 'video_default_voice': 'elevenlabs'}
    assert change(client, 'video', 'higgsfield').status_code == 303
    saved = stored_values(app)
    assert saved == {**before, 'video_default_voice': 'elevenlabs', 'video_ai_provider': 'higgsfield'}
    assert change(client, 'voice', 'not-installed').status_code == 422
    assert stored_values(app) == saved


def test_security_and_invalid_method_make_no_changes(studio_ui, client):
    before = stored_values(studio_ui)
    for data in [{'kind': 'news', 'value': 'codex|ai_web'}, {'kind': 'video', 'value': 'anything'},
                 {'kind': 'news', 'value': 'offline|rss', 'return_to': 'https://example.com/'},
                 {'kind': 'news', 'value': 'offline|rss', 'return_to': '//example.com/'}]:
        assert change(client, **data).status_code == 422
    response = client.post('/production/selection', data={'kind': 'video', 'value': 'off'})
    assert response.status_code == 403
    assert stored_values(studio_ui) == before


def test_same_defaults_across_pages_and_existing_context_is_preserved(studio_ui, client):
    app = studio_ui
    draft_id = seed_card(app)
    assert change(client, 'news', 'codex|rss').status_code == 303
    assert change(client, 'voice', 'elevenlabs').status_code == 303
    for path in ('/', '/create', '/news', '/ai', f'/ai?draft_id={draft_id}', f'/video?draft_id={draft_id}'):
        response = client.get(path)
        assert response.status_code == 200
        assert response.text.count('data-production-picker ') == 1
        assert 'value="codex|rss" selected' in response.text
        assert 'value="elevenlabs" selected' in response.text
    video = client.get(f'/video?draft_id={draft_id}').text
    assert 'Windows Korean synthetic selection' in video  # Per-draft voice never silently changes.
    home = client.get('/').text
    assert 'id="quick-production"' not in home and 'href="/create"' in home
    html = client.get('/create').text
    assert 'name="voice_method" value="elevenlabs"' in html
    assert 'name="video_method" value="off"' in html
    assert 'form="quick-production" checked' in html
    assert html.count('name="script_review"') == 1
    assert '영상 제작 전에 대본 확인하기' in html and '이번 음성<select' not in html


def test_quick_start_freezes_saved_engines_and_review_without_running(studio_ui, client, monkeypatch):
    from fastapi.responses import JSONResponse

    from newsflow.gui import autopilot_routes

    seen = []
    def capture(_request, flow, **_):
        seen.append(flow)
        return JSONResponse({'captured': True})
    monkeypatch.setattr(autopilot_routes, '_start_production', capture)
    assert change(client, 'news', 'claude_api|rss').status_code == 303
    assert change(client, 'voice', 'elevenlabs').status_code == 303
    assert change(client, 'video', 'higgsfield').status_code == 303
    for review in (True, False):
        data = {'csrf_token': csrf(client), 'source': 'feeds', 'duration': 45,
                'production_options_version': 2, 'voice_method': 'elevenlabs', 'video_method': 'higgsfield',
                'acquisition_policy': 'rss', 'news_usage': 'STANDARD'}
        if review:
            data['script_review'] = 'true'
        assert client.post('/autopilot/quick-start', data=data).status_code == 200
        assert seen[-1]['initial_provider'] == 'claude_api'
        assert seen[-1]['initial_model'] == 'claude-sonnet-4-6'
        assert seen[-1]['initial_voice'] == 'elevenlabs' and seen[-1]['initial_video'] == 'higgsfield'
        assert seen[-1]['initial_duration'] == 45 and seen[-1]['script_review'] is review


def test_click_change_save_shared_defaults_keyboard_mobile_and_no_inference(studio_ui, browser):
    app = studio_ui
    seed_card(app)
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366, 900))
        posts = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        page.goto(origin + '/')
        picker = page.locator('[data-production-picker]')
        news = picker.locator('[data-production-kind=news]')
        news.locator('summary').focus()
        page.keyboard.press('Enter')
        expect(news.locator('select')).to_be_visible()
        news.locator('select').select_option('claude_api|rss')
        assert not posts
        news.get_by_role('button', name='선택 저장').click()
        page.wait_for_url('**/?selection_saved=true')
        expect(page.locator('[data-production-kind=news] summary')).to_contain_text('Claude API + RSS')
        page.goto(origin + '/news')
        page.locator('.page-preferences > summary').click()
        expect(page.locator('[data-production-kind=news] summary')).to_contain_text('Claude API + RSS')
        voice = page.locator('[data-production-kind=voice]')
        voice.locator('summary').click()
        expect(voice.locator('select')).to_be_visible()
        page.keyboard.press('Escape')
        expect(voice.locator('summary')).to_be_focused()
        for width, height in [(1366, 900), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.goto(origin + '/')
            voice = page.locator('[data-production-kind=voice]')
            voice.locator('summary').click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            expect(voice.locator('select')).to_be_visible()
            proof = Path('validation-output/production-picker-20261020/isolated')
            proof.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(proof / f'picker-{width}.png'))
        assert len(posts) == 1 and posts[0].endswith('/production/selection')
        assert not external and not errors
        context.close()


def test_review_switch_does_not_overlap_text_or_exceed_track(studio_ui, browser):
    with local_server(studio_ui) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366, 900))
        for width, height in [(1920, 1080), (1366, 900), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.goto(origin + '/create')
            label = page.locator('.production-review-choice')
            switch = label.locator('input')
            text = label.locator('span')
            for checked in (True, False):
                switch.set_checked(checked)
                box, words = switch.bounding_box(), text.bounding_box()
                # The current /create control is a native checkbox, not the retired dashboard slider.
                assert box['width'] == 18 and box['height'] == 18
                assert switch.evaluate('e=>getComputedStyle(e).appearance') == 'auto'
                assert switch.evaluate('e=>getComputedStyle(e).accentColor') == 'rgb(56, 125, 255)'
                assert switch.is_checked() is checked
                assert words['x'] >= box['x'] + box['width'] + 7
                assert box['x'] >= 0 and words['x'] + words['width'] <= width
                assert switch.evaluate('e=>e.scrollWidth <= e.clientWidth')
                assert page.locator('#quick-production').evaluate(
                    'form=>new FormData(form).get("script_review")') == ('true' if checked else None)
            switch.focus()
            page.keyboard.press('Space')
            expect(switch).to_be_checked()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not external and not errors
        context.close()
