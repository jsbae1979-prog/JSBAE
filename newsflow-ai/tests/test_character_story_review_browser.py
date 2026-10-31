"""Visible new-story review flow; only synthetic local data and mocked paid endpoints."""
import os
from pathlib import Path
from urllib.parse import parse_qs

from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_story_feedback_browser import setup, open_story, assert_one_story_message

CAPTURE_DIR = os.environ.get('NEWSFLOW_STORY_REVIEW_CAPTURE_DIR')
TOKEN = 'a' * 64


def prepare(page):
    page.get_by_label('영상 길이', exact=True).select_option('30')
    page.get_by_text('스토리 세부 설정', exact=True).click()
    page.get_by_label('편당 최대 승인 한도 (USD)', exact=True).fill('5')


def review(context, reads, *, ready=True, token=TOKEN, message=''):
    def respond(route):
        reads.append(route.request.url)
        route.fulfill(json={'ready': ready, 'review': {'token': token, 'count': 1 if token else 0,
            'held_usd': '0.252'}, 'message': message})
    context.route('**/api/studio/characters/*/story-review', respond)


def test_unknown_review_cancel_never_dispatches_and_reuses_draft(app, browser, tmp_path):
    saved = setup(app)
    with local_server(app) as origin:
        context, page, posts = open_story(browser, origin, saved)
        reads = []; review(context, reads); prepare(page)
        trigger = page.get_by_role('button', name='스토리 자동 생성하기', exact=False)
        trigger.click()
        dialog = page.get_by_role('dialog', name='이전 요청 결과 미확인', exact=True)
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text('30초')
        expect(dialog).to_contain_text('US$5')
        expect(dialog).to_contain_text('실제 청구액 아님')
        expect(dialog.get_by_role('checkbox')).not_to_be_checked()
        assert dialog.locator('.character-story-review-consent').evaluate('(e)=>getComputedStyle(e).flexDirection') == 'row'
        expect(dialog.get_by_role('button', name='이번 새 스토리 요청', exact=True)).to_be_disabled()
        jobs = app.state.character.listing()
        assert len(jobs) == 1 and page.url.endswith('?job_id=' + jobs[0]['id'])
        assert len(posts) == 1 and posts[0].endswith('/character')
        captures = Path(CAPTURE_DIR or tmp_path / 'captures')
        captures.mkdir(parents=True, exist_ok=True)
        for width, height in ((1366, 768), (1920, 1080)):
            page.set_viewport_size({'width': width, 'height': height})
            expect(dialog.get_by_role('button', name='이번 새 스토리 요청', exact=True)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(captures / f'synthetic-new-story-review-{width}x{height}.png'))
        dialog.get_by_role('button', name='취소', exact=True).click()
        expect(dialog).to_have_count(0)
        expect(page.get_by_label('영상 길이', exact=True)).to_have_value('30')
        expect(page.get_by_label('편당 최대 승인 한도 (USD)', exact=True)).to_have_value('5')
        trigger.click(); expect(dialog).to_be_visible()
        expect(dialog.get_by_role('checkbox')).not_to_be_checked()
        assert len(app.state.character.listing()) == 1 and len(posts) == 1 and len(reads) == 2
        context.close()


def test_confirm_sends_only_current_draft_and_token_once(app, browser):
    saved = setup(app)
    with local_server(app) as origin:
        context, page, posts = open_story(browser, origin, saved)
        reads = []; submissions = []; review(context, reads); prepare(page)
        def refuse(route):
            submissions.append(parse_qs(route.request.post_data))
            route.fulfill(status=409, json={'error': '확인 정보가 변경되었습니다. 유료 요청은 보내지 않았습니다.'})
        context.route('**/api/studio/characters/auto-story', refuse)
        page.get_by_role('button', name='스토리 자동 생성하기', exact=False).click()
        dialog = page.get_by_role('dialog', name='이전 요청 결과 미확인', exact=True)
        expect(dialog).to_be_visible()
        dialog.get_by_role('checkbox').check()
        dialog.get_by_role('button', name='이번 새 스토리 요청', exact=True).click()
        expect(dialog).to_have_count(0)
        assert_one_story_message(page, '확인 정보가 변경되었습니다.')
        assert len(submissions) == 1
        form = submissions[0]; job = app.state.character.listing()[0]
        assert form['job_id'] == [job['id']] and form['review_token'] == [TOKEN]
        assert form['consent'] == form['review_consent'] == ['true']
        assert form['csrf_token'][0] and page.url.endswith('?job_id=' + job['id'])
        expect(page.get_by_role('button', name='스토리 자동 생성하기', exact=False)).to_be_disabled()
        assert len(posts) == 2 and len(reads) == 1
        context.close()


def test_active_request_review_stops_before_paid_post(app, browser):
    saved = setup(app)
    with local_server(app) as origin:
        context, page, posts = open_story(browser, origin, saved)
        reads = []; review(context, reads, ready=False, token='', message='진행 중인 요청을 먼저 확인하세요.')
        prepare(page)
        page.get_by_role('button', name='스토리 자동 생성하기', exact=False).click()
        assert_one_story_message(page, '진행 중인 요청을 먼저 확인하세요.')
        expect(page.get_by_role('dialog', name='이전 요청 결과 미확인', exact=True)).to_have_count(0)
        assert len(posts) == 1 and posts[0].endswith('/character') and len(reads) == 1
        context.close()


def test_normal_review_keeps_single_request_without_extra_confirmation(app, browser):
    saved = setup(app)
    with local_server(app) as origin:
        context, page, posts = open_story(browser, origin, saved)
        reads = []; submissions = []; review(context, reads, token=''); prepare(page)
        def refuse(route):
            submissions.append(parse_qs(route.request.post_data))
            route.fulfill(status=409, json={'error': '합성 요청을 중단했습니다.'})
        context.route('**/api/studio/characters/auto-story', refuse)
        page.get_by_role('button', name='스토리 자동 생성하기', exact=False).click()
        assert_one_story_message(page, '합성 요청을 중단했습니다.')
        expect(page.get_by_role('dialog', name='이전 요청 결과 미확인', exact=True)).to_have_count(0)
        assert len(submissions) == 1 and 'review_token' not in submissions[0] and 'review_consent' not in submissions[0]
        assert len(posts) == 2 and len(reads) == 1
        context.close()


def test_changed_duration_requires_fresh_review_and_keeps_old_draft(app, browser):
    saved = setup(app)
    with local_server(app) as origin:
        context, page, posts = open_story(browser, origin, saved)
        reads = []; review(context, reads); prepare(page)
        trigger = page.get_by_role('button', name='스토리 자동 생성하기', exact=False)
        trigger.click()
        dialog = page.get_by_role('dialog', name='이전 요청 결과 미확인', exact=True)
        expect(dialog).to_be_visible(); dialog.get_by_role('checkbox').check()
        dialog.get_by_role('button', name='취소', exact=True).click()
        page.get_by_label('영상 길이', exact=True).select_option('35')
        trigger.click(); expect(dialog).to_be_visible()
        expect(dialog).to_contain_text('35초')
        expect(dialog.get_by_role('checkbox')).not_to_be_checked()
        assert len(reads) == 2 and reads[0] != reads[1]
        assert len(posts) == 2 and all(url.endswith('/character') for url in posts)
        assert sorted(row['duration'] for row in app.state.character.listing()) == [30, 35]
        context.close()
