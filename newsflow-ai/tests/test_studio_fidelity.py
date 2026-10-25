"""Reference composition must keep the real form, keyboard and approval contracts."""
from playwright.sync_api import expect
from test_blue_studio_browser import guarded_page
from test_blue_studio_browser import studio_ui as studio_ui_fixture
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import stored_values
from test_studio_pages import seed_suite

from newsflow.db.models import ContentDraft

browser = browser_fixture
studio_ui = studio_ui_fixture


def test_composition_inspector_copy_and_render_controls_preserve_contract(studio_ui, browser):
    app = studio_ui
    draft_id = seed_suite(app)
    before = stored_values(app)
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, draft_id)
        draft.content = {**draft.content, 'scenes': [
            {'seconds':20,'narration':'합성 첫 문장입니다.','caption':'첫 장면','material':'배경'},
            {'seconds':25,'narration':'합성 두 번째 문장입니다.','caption':'둘째 장면','material':'도형'},
        ]}
        original = draft.content.copy()
        scenes = len(original['scenes'])
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366, 768))
        posts = []
        page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
        # Clipboard content is captured locally; no OS/shared clipboard writes in this test.
        page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copiedScript=text}}})")
        for width, height in [(1366, 768), (1920, 1080), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            response = page.goto(origin + f'/ai?draft_id={draft_id}')
            assert response.status == 200, (width, response.status, page.locator('body').inner_text()[:500])
            assert page.locator('[data-script-read-scene]').count() == scenes, (width, page.url, page.locator('body').inner_text()[-600:])
            last = page.locator('[data-script-edit-scene]').last
            last.focus()
            page.keyboard.press('Enter')
            expect(page.locator('[data-script-editor]')).to_have_attribute('open', '')
            expect(page.locator('[data-script-read-scene]').last).to_have_attribute('aria-current', 'location')
            expect(page.locator('[data-topic-scene]:visible')).to_have_count(1)
            editor = page.locator('[data-topic-scene]:visible [name=narration]')
            editor.fill('저장 전 편집한 합성 내레이션입니다.')
            page.locator('[data-copy-script]').click()
            expect(page.locator('[data-copy-feedback]')).to_contain_text('복사했습니다')
            assert '저장 전 편집한 합성' in page.evaluate('window.copiedScript')
            assert page.locator('[data-copy-script]').get_attribute('type') == 'button'
            # Revert before leaving: the existing dirty guard remains intact.
            editor.fill(original['scenes'][-1]['narration'])
            page.locator('.scene-tabs [data-edit-scene]').first.click()
            expect(page.locator('.scene-tabs [data-edit-scene]').first).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('[data-topic-scene]').first).to_be_visible()
            expect(page.locator('[data-topic-scene]').nth(1)).to_be_hidden()
            page.goto(origin + f'/video?draft_id={draft_id}')
            form = page.locator('form[action="/video/render"]')
            fields = form.evaluate('f=>Object.fromEntries(new FormData(f))')
            assert {'csrf_token','draft_id','duration','voice','font_size','subtitle_y','images'} <= fields.keys()
            assert fields['draft_id'] == str(draft_id)
            assert 'reviewed' not in fields and 'external_tts_consent' not in fields
            assert form.evaluate("f=>new FormData(f).getAll('images').length") == scenes
            assert page.locator('option').evaluate_all("es=>es.every(e=>e.closest('select,datalist'))")
            page.locator('.video-voice-choice > summary').click()
            expect(page.locator('.workstation-media-panel select[name=voice]')).to_be_visible()
            expect(page.locator('.workstation-render-controls [name=reviewed]')).not_to_be_checked()
            page.locator('.track-caption [data-video-scene-select]').last.click()
            expect(page.locator('[data-video-scene]:visible')).to_have_count(1)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not posts and not external and not errors
        context.close()
    assert stored_values(app) == before
    with app.state.sessions() as session:
        assert session.get(ContentDraft, draft_id).content == original


def test_copy_denied_reports_failure_without_requests(studio_ui, browser):
    draft_id = seed_suite(studio_ui)
    with local_server(studio_ui) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366, 768))
        page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw Error('denied')}}})")
        page.goto(origin + f'/ai?draft_id={draft_id}')
        page.locator('[data-copy-script]').click()
        expect(page.locator('[data-copy-feedback]')).to_contain_text('복사를 허용하지 않은')
        assert not external and not errors
        context.close()
