"""Simple AI script UI with synthetic data; views never grant consent or make paid requests."""
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect
from test_blue_studio_browser import guarded_page
from test_blue_studio_browser import studio_ui as studio_ui_fixture
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import stored_values

from newsflow.db.models import ContentDraft, IntelligenceRun, NewsArticle, NewsSource
from newsflow.intelligence.service import IntelligenceService
from newsflow.intelligence.settings import write_studio_settings

browser = browser_fixture
studio_ui = studio_ui_fixture


@pytest.fixture
def script_ui(studio_ui):
    app = studio_ui
    write_studio_settings(app.state.sessions, 'claude_api', 'claude-sonnet-4-6')
    with app.state.sessions.begin() as session:
        source = NewsSource(name='합성 출처', url='https://example.com/rss', enabled=False)
        session.add(source)
        session.flush()
        ids = []
        for n in range(9):
            article = NewsArticle(source_id=source.id, title=f'합성 뉴스 {n} — 지역 문화 소식',
                                  summary='실제 보도가 아닌 화면 검증용 합성 뉴스입니다.', publisher='합성 출처',
                                  url=f'https://example.com/{n}', canonical_url=f'https://example.com/{n}')
            session.add(article)
            session.flush()
            ids.append(article.id)
    service = IntelligenceService(app.state.sessions)
    analysis = service.analyze(ids[:1])
    draft = service.generate(analysis, 30)
    return app, analysis, draft


def evidence(page, name):
    path = os.environ.get('NEWSFLOW_SCRIPT_UI_EVIDENCE')
    if path:
        root = Path(path)
        root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / name))


def test_template_forms_routes_and_source_escaping(client, app):
    # Empty and old drafts must stay readable, including preserved empty-scene fixtures.
    from test_single_workspace import draft_fixture
    before = stored_values(app)
    response = client.get('/ai')
    assert response.status_code == 200 and 'script-simple.css' in response.text
    assert 'script-workflow.svg' in response.text
    assert "script-src 'self'" in response.headers['content-security-policy']
    old = draft_fixture(app, '<script>untrusted</script>')
    response = client.get(f'/ai?draft_id={old}')
    assert response.status_code == 200 and '<script>untrusted</script>' not in response.text
    assert '&lt;script&gt;untrusted&lt;/script&gt;' in response.text
    assert stored_values(app) == before


def test_article_selection_modal_keyboard_and_no_implicit_calls(script_ui, browser):
    app, analysis, _draft = script_ui
    before = stored_values(app)
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366, 900))
        posts = []
        page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
        page.goto(origin + '/ai')
        expect(page.locator('[data-script-article]:visible')).to_have_count(6)
        page.get_by_label('보관한 기사 찾기').fill('합성 뉴스 0')
        expect(page.locator('[data-script-article]:visible')).to_have_count(1)
        page.locator('[data-script-article]:visible input').check()
        expect(page.locator('[data-script-selection-count]')).to_contain_text('1개 선택')
        page.get_by_label('보관한 기사 찾기').fill('')
        expect(page.locator('[data-script-article] input:checked')).to_have_count(1)
        page.locator('[data-script-more]').click()
        expect(page.locator('[data-script-article]:visible')).to_have_count(9)
        evidence(page, 'article-selection.png')
        page.goto(origin + f'/ai?analysis_id={analysis}')
        with app.state.sessions() as session:
            overview = session.get(IntelligenceRun, analysis).result['overview']
        assert page.locator('.script-analysis-overview').inner_text() == overview
        assert page.locator('body').inner_text().count(overview) == 1
        dialog = page.locator('#script-create-dialog')
        expect(dialog).not_to_be_visible()
        trigger = page.locator('[data-script-dialog-open]')
        trigger.focus()
        page.keyboard.press('Enter')
        expect(dialog).to_be_visible()
        expect(dialog.locator('a[href="https://example.com/0"]')).to_be_visible()
        form = dialog.locator('form[action="/ai/generate"]')
        assert form.locator('[name=consent]').is_checked() is False
        form.locator('select[name=duration]').select_option('45')
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        expect(trigger).to_be_focused()
        trigger.click()
        expect(form.locator('[name=duration]')).to_have_value('45')
        form.locator('.script-technical summary').click()
        form.locator('[name=provider]').select_option('claude_api')
        expect(form.locator('[name=model]')).to_have_value('claude-sonnet-4-6')
        form.locator('[name=consent]').check()
        form.locator('[name=model]').fill('claude-haiku-4-5-20251001')
        form.locator('[name=model]').dispatch_event('change')
        expect(form.locator('[name=consent]')).not_to_be_checked()
        for width, height in [(1366, 900), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert dialog.evaluate('d=>d.scrollWidth <= d.clientWidth + 1')
            evidence(page, f'create-dialog-{width}.png')
        page.keyboard.press('Escape')
        page.goto(origin + f'/ai?analysis_id={analysis}#analysis-result')
        expect(dialog).to_be_visible()
        assert not posts and not external and not errors
        context.close()
    assert stored_values(app) == before


def test_read_edit_save_and_video_link_on_desktop_and_mobile(script_ui, browser):
    app, _, draft_id = script_ui
    with app.state.sessions() as session:
        original = session.get(ContentDraft, draft_id).content.copy()
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366, 900))
        for width, height in [(1988, 1204), (1366, 900), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.goto(origin + f'/ai?draft_id={draft_id}')
            expect(page.locator('.script-reading-scene')).to_have_count(3)
            expect(page.locator('.script-reading-scene').first).to_contain_text(original['scenes'][0]['narration'])
            expect(page.locator('[data-script-editor]')).not_to_have_attribute('open', '')
            expect(page.get_by_role('link', name='이 대본으로 영상 구성 →')).to_have_attribute('href', f'/video?draft_id={draft_id}')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if width >= 1366:
                reader = page.locator('.script-reader').bounding_box()
                preview = page.locator('.script-next-step').bounding_box()
                assert reader['width'] > preview['width']
                assert abs(reader['y'] - preview['y']) < 2
            evidence(page, f'draft-reading-{width}.png')
        page.locator('[data-script-edit-scene="1"]').click()
        editor = page.locator('[data-script-editor]')
        expect(editor).to_have_attribute('open', '')
        field = editor.locator('[data-topic-scene]:visible [name=narration]')
        field.fill('직접 수정한 합성 내레이션입니다.')
        expect(page.locator('[data-script-read-narration="1"]')).to_have_text('직접 수정한 합성 내레이션입니다.')
        expect(editor.locator('[data-editor-dirty]')).to_be_visible()
        expect(page.locator('[data-script-reading-dirty]')).to_be_visible()
        with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith(f'/ai/drafts/{draft_id}')) as saved:
            editor.get_by_role('button', name='수정 초안 저장', exact=True).click()
        assert saved.value.status == 303
        page.wait_for_url(f'**/ai?draft_id={draft_id}')
        with app.state.sessions() as session:
            draft = session.get(ContentDraft, draft_id)
            assert draft.revision == 2 and draft.review_status == 'review_required'
            assert draft.content['scenes'][1]['narration'] == '직접 수정한 합성 내레이션입니다.'
            assert draft.content['scenes'][0] == original['scenes'][0]
        assert not external and not errors
        context.close()
