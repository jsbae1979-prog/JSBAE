"""Read-only video information modal: no generation, approvals or external requests."""
from pathlib import Path

from playwright.sync_api import expect
from test_model_picker_browser import browser as browser  # noqa: PLC0414
from test_single_workspace import stored_values, video_fixture
from test_workspace_access_browser import page as page  # noqa: PLC0414

from newsflow.db.models import VideoProject


def test_video_information_modal_keyboard_mobile_and_record_preservation(page, app, tmp_path):
    fixture = video_fixture(app, '합성 영상 검토')
    with app.state.sessions.begin() as session:
        session.get(VideoProject, fixture['project_id']).sources = {'articles': [{'sources': [
            {'publisher': '합성 출처', 'url': 'https://example.com/' + 'reference-' * 30}]}]}
    before = stored_values(app)
    for width in (1280, 390):
        page.set_viewport_size({'width': width, 'height': 850})
        page.goto(f'http://127.0.0.1/video?job_id={fixture["id"]}')
        trigger = page.get_by_role('button', name='영상 정보·출처', exact=True)
        trigger.focus()
        trigger.press('Enter')
        dialog = page.get_by_role('dialog', name='영상 정보·출처', exact=True)
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role('button', name='닫기', exact=True)).to_be_focused()
        expect(dialog).to_contain_text('음성:')
        expect(dialog).to_contain_text('합성 출처')
        expect(dialog.locator('[data-video-technical]')).not_to_have_attribute('open', '')
        dialog.locator('[data-video-technical]>summary').click()
        expect(dialog.locator('[data-video-technical]')).to_have_attribute('open', '')
        dialog.locator('[data-video-technical]>summary').click()
        expect(dialog.get_by_role('link', name='이 영상으로 게시 준비')).to_have_attribute(
            'href', f'/publishing?render_job_id={fixture["id"]}')
        assert dialog.locator('form').count() == 0
        assert page.locator('video').count() == 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
        box = dialog.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1
        assert box['height'] <= 850
        assert box['y'] >= 0 and box['y'] + box['height'] <= 851
        assert dialog.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
        page.screenshot(path=str(Path(tmp_path) / f'video-info-{width}.png'))
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        expect(trigger).to_be_focused()
        trigger.click()
        dialog.get_by_role('button', name='닫기', exact=True).click()
        expect(trigger).to_be_focused()
    assert stored_values(app) == before
