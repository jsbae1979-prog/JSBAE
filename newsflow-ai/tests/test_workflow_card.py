"""Reference workflow presentation, verified stages and immutable task choices (synthetic only)."""
import os
from pathlib import Path

from playwright.sync_api import expect
from sqlalchemy import select
from test_blue_studio_browser import guarded_page
from test_blue_studio_browser import studio_ui as studio_ui_fixture
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import draft_fixture, save_values, stored_values

from newsflow.db.models import AutopilotJob, ContentDraft, IntelligenceRun
from newsflow.gui.dashboard_view import workflow_context

browser = browser_fixture
studio_ui = studio_ui_fixture


def seed_card(app):
    draft_id = draft_fixture(app, '도시를 바꾸는 에너지 기술')
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, draft_id)
        run = session.get(IntelligenceRun, draft.run_id)
        analysis = IntelligenceRun(kind='analysis', provider='claude_api', status='success',
            options={}, evidence={}, result={'synthetic': True}, message='Synthetic record only; no API call')
        session.add(analysis)
        session.flush()
        run.provider = 'claude_api'
        run.evidence = {'articles': [{'title': '합성 기사', 'url': 'https://example.com/synthetic'}]}
        run.options = {'production_context': {'source': 'feeds', 'initial_duration': 45,
            'initial_voice': 'Windows Korean synthetic selection', 'initial_provider': 'claude_api',
            'initial_model': 'claude-sonnet-4-6', 'production_options_version': 2, 'script_review': True,
            'initial_video': 'off', 'analysis_id': analysis.id}}
        draft.content = {**draft.content, 'summary': '도시는 지금, 새로운 에너지로 전환하고 있습니다. 태양광과 저장 기술, 그리고 스마트 에너지 관리가 만나 도시의 내일을 바꾸고 있습니다.'}
    return draft_id


def test_workflow_uses_task_records_not_new_global_defaults(app):
    draft_id = seed_card(app)
    save_values(app, video_default_voice='elevenlabs', video_ai_provider='higgsfield')
    before = stored_values(app)
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        view = workflow_context(session, {'status': 'waiting_review'}, draft)
        assert [s['state'] for s in view['steps']] == ['done', 'done', 'current', 'pending', 'pending']
        assert view['provider'] == 'Claude API' and view['voice'] == 'Windows 음성'
        assert view['video'] == '기본 영상' and view['review'] is True
        run = session.get(IntelligenceRun, draft.run_id)
        run.options = {**run.options, 'production_context': {**run.options['production_context'], 'script_review': False}}
        session.flush()
        assert workflow_context(session, {'status': 'waiting_review'}, draft)['review'] is False
        session.rollback()
    assert stored_values(app) == before


def test_legacy_and_failed_workflow_never_invent_analysis_or_approval(app):
    draft_id = draft_fixture(app, 'legacy')
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, draft_id)
        view = workflow_context(session, {'status': 'waiting_review'}, draft)
        assert [s['state'] for s in view['steps']] == ['pending', 'pending', 'current', 'pending', 'pending']
        assert view['review'] is True and view['review_legacy'] is True
        assert view['voice'] == '음성 미정' and view['video'] == '방식 미정'
        job = AutopilotJob(id='d' * 32, mode='guided', source='sample', duration=30, platform='youtube',
            status='failed', current_stage='render', stage_results={})
        session.add(job)
        session.flush()
        view = workflow_context(session, {'task_id': job.id, 'status': 'failed'}, None)
        assert [s['state'] for s in view['steps']] == ['pending', 'pending', 'pending', 'error', 'pending']


def test_reference_card_browser_popovers_keyboard_and_no_mutation(studio_ui, browser):
    app = studio_ui
    draft_id = seed_card(app)
    before = stored_values(app)
    output = os.environ.get('NEWSFLOW_WORKFLOW_EVIDENCE')
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1920, 1080))
        posts = []
        page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
        for width, height in [(1920,1080), (1366,768), (390,844)]:
            page.set_viewport_size({'width': width, 'height': height})
            assert page.goto(origin + '/').status == 200
            card = page.locator('[data-workflow-card]')
            expect(card.locator('li.is-done')).to_have_count(2)
            expect(card.locator('[aria-current="step"]')).to_contain_text('대본 작성')
            expect(card.locator('.workflow-review-link')).to_have_attribute('href', '/create')
            expect(card.get_by_role('link', name='대본 검토하기')).to_have_attribute('href', f'/ai?draft_id={draft_id}')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            labels = card.locator('.production-picker-option summary strong').evaluate_all(
                'nodes=>nodes.map(n=>({text:n.textContent,scroll:n.scrollWidth,width:n.clientWidth,ellipsis:getComputedStyle(n).textOverflow,full:n.closest("summary").title}))')
            assert all(label['scroll'] <= label['width'] or (label['ellipsis'] == 'ellipsis' and label['full'])
                       for label in labels), (width, labels)
            if output:
                root = Path(output); root.mkdir(parents=True, exist_ok=True)
                card.screenshot(path=str(root / f'workflow-{width}.png'))
                page.screenshot(path=str(root / f'home-{width}.png'))
            controls = card.locator('.production-picker-option')
            controls.nth(0).locator('summary').focus()
            page.keyboard.press('Enter')
            expect(controls.nth(0).locator('.production-picker-popover')).to_be_visible()
            controls.nth(1).locator('summary').click()
            expect(controls.nth(0)).not_to_have_attribute('open', '')
            expect(controls.nth(1).locator('.production-picker-popover')).to_be_visible()
            page.keyboard.press('Escape')
            expect(controls.nth(1).locator('summary')).to_be_focused()
            expect(controls.nth(1)).not_to_have_attribute('open', '')
            for control in [controls.nth(2)]:
                control.locator('summary').click()
                expect(control.locator('.production-picker-popover')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.keyboard.press('Escape')
            card.locator('.workflow-review-link').click()
            expect(page.locator('[name=script_review]')).to_be_checked()
            assert page.locator('#quick-production').evaluate('form=>new FormData(form).get("script_review")') == 'true'
            page.goto(origin + '/')
            card.get_by_role('link', name='대본 검토하기').click()
            page.wait_for_url(f'**/ai?draft_id={draft_id}')
        assert not posts and not external and not errors
        context.close()
    assert stored_values(app) == before
    with app.state.sessions() as session:
        assert session.get(ContentDraft, draft_id).review_status == 'review_required'
        assert len(list(session.scalars(select(IntelligenceRun)))) == 2
