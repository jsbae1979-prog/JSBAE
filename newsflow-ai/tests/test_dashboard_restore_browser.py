"""Established dashboard layout; offline navigation never creates work or approvals."""
import os
from itertools import pairwise
from pathlib import Path

from playwright.sync_api import expect
from test_model_picker_browser import browser as browser  # noqa: PLC0414
from test_single_workspace import stored_values, video_fixture
from test_workspace_access_browser import page as page  # noqa: PLC0414


def test_restored_dashboard_layout_and_readonly_navigation(page, app, tmp_path):
    video_fixture(app, '보존할 30초 합성 뉴스 영상')
    before = stored_values(app)
    shots = Path(os.environ.get('DASHBOARD_RESTORE_PROOF_DIR', tmp_path))
    shots.mkdir(parents=True, exist_ok=True)
    for width in (1440, 1100, 760, 390):
        page.set_viewport_size({'width': width, 'height': 1000})
        page.goto('http://127.0.0.1/')
        expect(page.locator('.dashboard-restored')).to_be_visible()
        expect(page.locator('.workflow-format-links a')).to_have_count(3)
        expect(page.locator('.workflow-format-links a>svg[aria-hidden=true]')).to_have_count(3)
        for name, href in [('쇼츠 영상', '/create'), ('이미지 게시물', '/image-posts'),
                           ('캐릭터 쇼츠', '/character')]:
            expect(page.get_by_role('navigation', name='만들 콘텐츠').get_by_role(
                'link', name=name, exact=True)).to_have_attribute('href', href)
        expect(page.locator('.workflow-steps li')).to_have_count(5)
        expect(page.locator('.workflow-steps .workflow-node>svg')).to_have_count(5)
        for index in range(5):
            expect(page.locator('.workflow-steps li').nth(index)).to_contain_text(f'{index + 1}단계')
        expect(page.locator('.dash-preview video')).to_have_count(1)
        expect(page.locator('.dash-categories a')).to_have_count(9)
        nav = page.locator('.dash-categories').bounding_box()
        for tab in page.locator('.dash-categories a').all():
            box = tab.bounding_box()
            assert box['x'] >= nav['x'] - 1 and box['x'] + box['width'] <= nav['x'] + nav['width'] + 1
        expect(page.locator('#quick-production')).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
        boxes = [page.locator(selector).bounding_box() for selector in (
            '.dash-news', '.dash-workflow', '.dash-preview')]
        assert all(boxes)
        if width == 1440:
            assert boxes[0]['x'] < boxes[1]['x'] < boxes[2]['x']
            assert max(b['y'] for b in boxes) - min(b['y'] for b in boxes) < 2
        for a, b in pairwise(boxes):
            overlap_x = min(a['x'] + a['width'], b['x'] + b['width']) - max(a['x'], b['x'])
            overlap_y = min(a['y'] + a['height'], b['y'] + b['height']) - max(a['y'], b['y'])
            assert overlap_x <= 1 or overlap_y <= 1
        if width == 1100:
            # The right rail is one column within a half-width dashboard lane.
            # A nested two-column rail crushed labels and action buttons vertically.
            preview = page.locator('.dash-preview').bounding_box()
            publish = page.locator('.dash-publish').bounding_box()
            assert preview['width'] >= 300 and publish['width'] >= 300
            assert publish['y'] >= preview['y'] + preview['height'] - 1
            for selector in ('[data-dash-review]', '[data-dash-download]',
                             '[data-dash-youtube]', '[data-dash-instagram]'):
                action = page.locator(selector).bounding_box()
                assert action['width'] >= 120 and action['height'] <= 90, (selector, action)
        page.screenshot(path=str(shots / f'dashboard-{width}.png'), full_page=True)
    page.locator('.workflow-review-link').click()
    expect(page).to_have_url('http://127.0.0.1/create')
    expect(page.locator('[name=script_review]')).to_be_checked()
    assert stored_values(app) == before
