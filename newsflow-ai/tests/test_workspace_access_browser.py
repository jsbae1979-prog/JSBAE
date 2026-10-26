"""Offline Chrome interactions against the real temporary-data templates and assets."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser as browser  # noqa: PLC0414


@pytest.fixture
def page(browser, client):
    context = browser.new_context(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
    rejected = []
    errors = []

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != '127.0.0.1' or request.method != 'GET':
            rejected.append(request.url)
            route.abort()
            return
        response = client.get(url.path + ('?' + url.query if url.query else ''))
        headers = {'content-type': response.headers.get('content-type', 'text/plain')}
        if 'content-security-policy' in response.headers:
            headers['content-security-policy'] = response.headers['content-security-policy']
        route.fulfill(status=response.status_code, headers=headers, body=response.content)

    context.route('**/*', serve)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    yield page
    context.close()
    assert not rejected, 'Interaction attempted a POST or non-loopback request'
    assert not errors


def test_finder_search_empty_state_escape_and_focus_restore_without_submit(page):
    page.goto('http://127.0.0.1/character')
    trigger = page.locator('[data-access-open]')
    trigger.click()
    search = page.locator('[data-access-search]')
    expect(search).to_be_focused()
    expect(search).to_have_css('border-top-width', '0px')
    search.fill('음성')
    links = page.locator('[data-access-destination]:visible')
    expect(links).to_have_count(3)  # Includes video setup, whose description also mentions voice.
    expect(page.locator('[data-access-destination][href="/voices"]')).to_be_visible()
    expect(page.locator('[data-access-destination][href="/simple-settings#quality"]')).to_be_visible()
    search.fill('클로드')
    expect(links).to_have_count(1)
    expect(links).to_have_attribute('href', '/simple-settings#connections')
    search.fill('<script>alert(1)</script>')
    expect(page.locator('[data-access-empty]')).to_be_visible()
    expect(links).to_have_count(0)
    page.keyboard.press('Escape')
    expect(page.locator('#access-dialog')).not_to_be_visible()
    expect(trigger).to_be_focused()
    page.keyboard.press('Alt+k')
    expect(search).to_be_focused()
    expect(search).to_have_value('')
    page.locator('[data-access-close]').click()


def test_finder_navigates_to_character_and_settings_anchor_with_no_generation(page):
    page.goto('http://127.0.0.1/news')
    page.locator('[data-access-open]').click()
    page.locator('[data-access-search]').fill('캐릭터')
    page.locator('[data-access-destination][href="/character"]:visible').click()
    expect(page).to_have_url('http://127.0.0.1/character')
    expect(page.locator('.workspace-nav [aria-current=page]')).to_have_attribute('href', '/character')
    page.locator('[data-access-open]').click()
    page.locator('[data-access-search]').fill('기본 음성')
    page.locator('[data-access-destination]:visible').click()
    expect(page).to_have_url('http://127.0.0.1/simple-settings#quality')
    expect(page.locator('#quality')).to_be_visible()
    expect(page.locator('#connections')).not_to_be_visible()


def test_outline_reveals_original_settings_tab_and_preserves_form_values(page):
    page.goto('http://127.0.0.1/simple-settings')
    before = page.locator('[name=model][form=production-preferences]').input_value()
    page.locator('[data-access-outline] summary').click()
    page.locator('[data-access-outline-links] a', has_text='기본 음성').first.click()
    expect(page.locator('#quality')).to_be_visible()
    assert page.locator('[name=model][form=production-preferences]').input_value() == before
    expect(page.locator('[data-access-outline]')).not_to_have_attribute('open', '')


@pytest.mark.parametrize('width', [390, 640, 980, 1440])
def test_all_main_destinations_fit_small_windows(page, width, tmp_path):
    page.set_viewport_size({'width': width, 'height': 900})
    for path in ('/', '/news', '/ai', '/videos', '/video', '/queue', '/image-posts', '/analytics', '/simple-settings', '/character'):
        page.goto('http://127.0.0.1' + path)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), (path, width)
        if width <= 760:
            expect(page.locator('[data-sidebar-menu]')).not_to_have_attribute('open', '')
            page.locator('[data-sidebar-menu]>summary').click()
        tools = page.locator('[data-sidebar-tools]')
        assert page.locator('.workspace-nav a:visible').count() == (14 if tools.get_attribute('open') is not None else 7)
        if tools.get_attribute('open') is None:
            tools.locator('summary').click()
        assert page.locator('.workspace-nav a:visible').count() == 14
        expect(page.locator('.workspace-nav [href="/image-studio"]')).to_be_visible()
        for label in page.locator('.workspace-nav a>span:visible').all():
            assert label.evaluate('(el) => el.getBoundingClientRect().width > 80'), (path, width, label.text_content())
            assert label.evaluate('''(el) => {
                const style = getComputedStyle(el);
                return el.getBoundingClientRect().height <= parseFloat(style.lineHeight) * 2 + 1
                    && el.scrollWidth <= el.clientWidth + 1 && el.scrollHeight <= el.clientHeight + 1;
            }'''), (path, width, label.text_content())
        if width <= 760:
            assert page.locator('.navigation-catalog').evaluate('(el) => el.scrollWidth <= el.clientWidth + 2')
            page.keyboard.press('Escape')
            expect(page.locator('[data-sidebar-menu]')).not_to_have_attribute('open', '')
        page.locator('[data-access-open]').click()
        expect(page.locator('#access-dialog')).to_be_visible()
        assert page.locator('#access-dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth + 2')
        page.locator('[data-access-close]').click()
    # Test artifacts contain synthetic screens only.
    page.screenshot(path=str(tmp_path / f'character-{width}.png'), full_page=True)


def test_decorative_icons_preserve_button_name_and_required_consent(page):
    page.goto('http://127.0.0.1/character')
    button = page.get_by_role('button', name='주제·원본 저장', exact=True)
    expect(button).to_be_visible()
    expect(button.locator('svg')).to_have_attribute('aria-hidden', 'true')
    assert page.locator('.character-form input[required]').count() == 4
    assert page.locator('.character-form [name=reference]').get_attribute('accept') == 'image/png'
    assert page.locator('.character-form [name=csrf_token]').input_value()


def test_character_reference_preview_is_local_without_a_post(page):
    import io

    from PIL import Image

    image = io.BytesIO()
    Image.new('RGB', (144, 256), 'brown').save(image, format='PNG')
    page.goto('http://127.0.0.1/character')
    page.locator('[data-character-reference]').set_input_files({
        'name': 'synthetic-character.png', 'mimeType': 'image/png', 'buffer': image.getvalue()})
    preview = page.locator('[data-character-preview]')
    expect(preview).to_be_visible()
    assert preview.evaluate('(canvas) => canvas.tagName === "CANVAS" && canvas.width === 144 && canvas.height === 256')
    expect(page.locator('[data-character-file-status]')).to_contain_text('아직 저장하거나 전송하지')
    page.locator('[data-character-reference]').set_input_files([])
    expect(preview).not_to_be_visible()


def test_video_delete_confirmation_stays_visible_and_cancel_preserves_file(page, app):
    from test_single_workspace import video_fixture

    item = video_fixture(app, '삭제하지 않을 합성 영상')
    path = app.state.video.outputs / item['output_name']
    original = path.read_bytes()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto('http://127.0.0.1/videos')
    page.get_by_label('영상 삭제', exact=True).click()
    dialog = page.get_by_role('dialog', name='삭제 확인')
    expect(dialog).to_be_visible()
    confirm = dialog.locator('[name=confirm]')
    expect(confirm).not_to_be_checked()
    assert confirm.get_attribute('required') is not None
    assert dialog.evaluate('(el) => {const r=el.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth;}')
    dialog.get_by_role('button', name='취소', exact=True).click()
    expect(dialog).not_to_be_visible()
    assert path.read_bytes() == original
