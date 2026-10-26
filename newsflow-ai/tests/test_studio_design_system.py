"""Unified navigation is read-only; no saved selection or approval is inferred."""
import re

import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser as browser  # noqa: PLC0414
from test_single_workspace import stored_values, video_fixture
from test_workspace_access_browser import page as page  # noqa: PLC0414
from test_youtube_gui import forbid_external_calls  # noqa: F401


@pytest.mark.parametrize('path,stage', [('/create','news'),('/news','news'),('/ai','script'),
    ('/voices','voice'),('/video','video'),('/videos','review'),('/queue','publish')])
def test_stage_links_do_not_claim_progress_or_modify_settings(client, app, path, stage):
    before = stored_values(app)
    response = client.get(path)
    nav = re.search(r'<nav data-journey-workspace=.*?</nav>', response.text, re.DOTALL).group()
    assert nav.count('data-journey-step=') == 6
    assert f'data-journey-step="{stage}"' in nav
    assert len(re.findall(r'aria-current="page"', nav)) == 1
    assert '단계별 화면 이동' in nav and '<form' not in nav and '완료' not in nav
    assert stored_values(app) == before


def test_primary_destinations_and_secondary_tools_are_all_reachable(page):
    page.goto('http://127.0.0.1/')
    expect(page.locator('#workspace-videos a[href="/videos"]')).to_be_visible()
    primary = page.locator('.navigation-group a')
    assert primary.evaluate_all('(nodes)=>nodes.map(n=>n.dataset.navId)') == [
        'home','news-create','news','tasks','videos','publish','settings']
    tools = page.locator('[data-sidebar-tools]')
    expect(tools).not_to_have_attribute('open','')
    tools.locator('summary').focus()
    page.keyboard.press('Enter')
    expect(tools).to_have_attribute('open','')
    expect(tools.locator('a')).to_have_count(7)
    expect(tools.locator('a[href="/image-studio"]')).to_be_visible()
    tools.locator('a[href="/schedules"]').click()
    expect(page).to_have_url('http://127.0.0.1/schedules')
    expect(page.locator('.workspace-nav [aria-current=page]')).to_have_attribute('href','/schedules')


def test_review_publish_and_script_keep_selected_video_context(page, app):
    item = video_fixture(app,'합성 영상 · 승인 없음')
    before = stored_values(app)
    path = f'http://127.0.0.1/?video={item["id"]}&publish_platform=unified#workspace-detail'
    page.goto(path,wait_until='networkidle')
    journey = page.locator('.studio-journey')
    expect(journey.locator('[aria-current=page]')).to_have_attribute('data-journey-step','review')
    expect(journey.locator('[data-journey-step=script]')).to_have_attribute('href',f'/ai?draft_id={item["draft_id"]}')
    journey.locator('[data-journey-step=publish]').click()
    expect(journey.locator('[aria-current=page]')).to_have_attribute('data-journey-step','publish')
    expect(page.locator('#publish-workspace')).to_be_visible()
    expect(page.locator('#publish-workspace [name=content_reviewed]')).not_to_be_checked()
    journey.locator('[data-journey-step=review]').click()
    expect(journey.locator('[aria-current=page]')).to_have_attribute('data-journey-step','review')
    assert stored_values(app) == before


def test_shortform_options_stay_inside_video_tab(page):
    page.goto('http://127.0.0.1/simple-settings')
    expect(page.locator('#shortform-settings')).to_be_hidden()
    page.get_by_role('tab',name='AI 영상',exact=True).click()
    expect(page.locator('#video-settings #shortform-settings')).to_be_visible()
    page.get_by_role('tab',name='뉴스·대본 AI',exact=True).click()
    expect(page.locator('#shortform-settings')).to_be_hidden()
