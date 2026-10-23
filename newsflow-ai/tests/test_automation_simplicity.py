"""Automation UI uses saved choices without writing approvals or starting work."""
from playwright.sync_api import expect
from test_model_picker_browser import browser as browser  # noqa: PLC0414
from test_workspace_access_browser import page as page  # noqa: PLC0414

from newsflow.gui.navigation import navigation_context


def test_nine_primary_items_keep_four_tools_and_reveal_current_tool():
    menu = navigation_context('/', {})
    assert sum(not item['secondary'] for group in menu['groups'] for item in group['items']) == 9
    assert len(menu['tools']) == 4 and not menu['tools_open']
    for path in ('/ai', '/videos', '/voices', '/analytics'):
        assert navigation_context(path, {})['tools_open']


def test_home_has_one_creation_entry_per_type_without_duplicate_forms(client):
    html = client.get('/').text
    assert html.count('class="studio-format-card ') == 3
    assert 'id="quick-production"' not in html
    assert 'class="workflow-formats"' not in html
    assert 'studio-publish-shortcut' not in html
    assert 'studio-status-strip' in html
    assert 'action="/news" method="get"' in html
    create = client.get('/create').text
    assert create.count('id="quick-production"') == 1
    assert 'name="csrf_token"' in create and 'name="script_review"' in create
    assert 'data-production-picker' in create


def test_closed_job_options_preserve_payload_and_review_without_a_post(page):
    page.goto('http://127.0.0.1/create')
    form = page.locator('#quick-production')
    assert page.locator('.production-hero-auto').evaluate('(el) => el.querySelector(".production-start").clientWidth / el.clientWidth > 0.9')
    options = page.locator('[data-production-options]')
    expect(options).not_to_have_attribute('open', '')
    expect(form.locator('select:visible')).to_have_count(1)
    expect(page.locator('[name=script_review]')).to_be_checked()
    before = form.evaluate('(el) => Object.fromEntries(new FormData(el))')
    assert all(name in before for name in ('source', 'category', 'period', 'news_usage', 'duration',
                                          'voice_method', 'video_method', 'acquisition_policy', 'csrf_token', 'script_review'))
    options.locator('summary').click()
    page.locator('#quick-source').select_option('feeds')
    expect(page.locator('#quick-category')).to_be_visible()
    expect(page.locator('[data-production-options-summary]')).to_contain_text('새 뉴스 수집·검색')
    options.locator('summary').click()
    after = form.evaluate('(el) => Object.fromEntries(new FormData(el))')
    assert after == dict(before, source='feeds')
    expect(page.get_by_role('button', name='자동 제작 시작')).to_be_visible()


def test_sidebar_tools_stay_reachable_and_current_tool_opens_itself(page):
    page.goto('http://127.0.0.1/')
    expect(page.locator('.workspace-nav a:visible')).to_have_count(9)
    page.locator('[data-sidebar-tools]>summary').click()
    expect(page.locator('.workspace-nav a:visible')).to_have_count(13)
    page.locator('.workspace-nav [href="/analytics"]').click()
    expect(page.locator('[data-sidebar-tools]')).to_have_attribute('open', '')
    expect(page.locator('.workspace-nav [aria-current=page]')).to_have_attribute('href', '/analytics')


def test_schedule_shows_only_relevant_date_fields_and_preserves_values(page):
    page.goto('http://127.0.0.1/schedules')
    weekly = page.locator('[data-schedule-kind=weekly]')
    once = page.locator('[data-schedule-kind=once]')
    expect(weekly).not_to_be_visible()
    expect(once).not_to_be_visible()
    page.locator('.schedule-editor [name=kind]').select_option('weekly')
    expect(weekly).to_be_visible()
    expect(once).not_to_be_visible()
    weekly.locator('[name=weekdays]').first.check()
    page.locator('.schedule-editor [name=kind]').select_option('once')
    expect(weekly).not_to_be_visible()
    expect(once).to_be_visible()
    once.locator('input').fill('2026-12-25')
    page.locator('.schedule-editor [name=kind]').select_option('daily')
    expect(once).not_to_be_visible()
    expect(weekly.locator('[name=weekdays]').first).to_be_checked()
    expect(once.locator('input')).to_have_value('2026-12-25')
    expect(page.locator('#schedule-list')).to_contain_text('첫 예약')
