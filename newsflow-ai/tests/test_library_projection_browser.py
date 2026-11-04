"""Same-SPA library removal propagates to creation and ready publishing candidates."""
from hashlib import sha256
import re

from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_single_workspace import video_fixture
from test_library_selection_browser import open_trash, check_payload
from test_library_visibility_projections import publication_fixture
from sqlalchemy import select
from newsflow.db.models import AIUsage, APIRequestReservation, PublishJob, SocialMetric
from bat_distribution.operation import OperatingRequests


def nav(page, label):
    page.get_by_role('navigation', name='주 메뉴', exact=True).get_by_role('button', name=label, exact=True).click()
    assert page.evaluate('window.__syntheticSpaSentinel') == 'preserved'


def test_library_remove_restore_updates_creation_and_completed_publish_candidates_in_same_spa(app, browser):
    target_title = '합성 완료 뉴스 하나'; other_title = '합성 완료 뉴스 둘'; pending_title = '합성 제작 중 뉴스'
    target = video_fixture(app, target_title)
    other = video_fixture(app, other_title)
    video_fixture(app, pending_title, status='running', playable=False, exists=False)
    files = {row['output_name']: sha256((app.state.video.outputs / row['output_name']).read_bytes()).hexdigest()
             for row in (target, other)}
    with local_server(OperatingRequests(app)) as origin:
        context = browser.new_context(viewport={'width': 1366, 'height': 768})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
        page = context.new_page(); posts = []; documents = []
        page.on('request', lambda r: posts.append(r) if r.method == 'POST' else None)
        page.on('request', lambda r: documents.append(r.url) if r.resource_type == 'document' else None)
        page.goto(origin + '/studio/create')
        page.evaluate('window.__syntheticSpaSentinel="preserved"')
        for title in (target_title, other_title, pending_title):
            expect(page.locator('.projects-section .project').filter(has=page.get_by_text(title, exact=True))).to_be_visible()
        nav(page, '게시 스튜디오')
        candidates = page.locator('.mg-publish-list')
        expect(candidates.get_by_text(target_title, exact=True)).to_be_visible()
        expect(candidates.get_by_text(other_title, exact=True)).to_be_visible()
        expect(candidates.get_by_text(pending_title, exact=True)).to_have_count(0)
        nav(page, '라이브러리')
        page.locator(f'[data-content-id="own-news:{target["id"]}"]').click()
        page.locator('.mg-library-detail').get_by_role('button', name='이 콘텐츠 삭제', exact=True).click()
        modal = page.get_by_role('dialog', name='라이브러리에서 삭제', exact=True)
        modal.get_by_role('button', name='휴지통으로 이동', exact=True).click()
        expect(page.locator(f'[data-content-id="own-news:{target["id"]}"]')).to_have_count(0)
        assert len(posts) == 1; check_payload(posts[0], 'remove', ['news:' + str(target['id'])])
        nav(page, '콘텐츠 제작')
        expect(page.locator('.projects-section .project').filter(has=page.get_by_text(target_title, exact=True))).to_have_count(0)
        expect(page.locator('.projects-section .project').filter(has=page.get_by_text(other_title, exact=True))).to_be_visible()
        nav(page, '게시 스튜디오')
        expect(candidates.get_by_text(target_title, exact=True)).to_have_count(0)
        expect(candidates.get_by_text(other_title, exact=True)).to_be_visible()
        expect(candidates.get_by_text(pending_title, exact=True)).to_have_count(0)
        nav(page, '라이브러리')
        open_trash(page).get_by_role('button', name=target_title + ' 복원', exact=True).click()
        expect(page.locator(f'[data-content-id="own-news:{target["id"]}"]')).to_be_visible()
        assert len(posts) == 2; check_payload(posts[1], 'restore', ['news:' + str(target['id'])])
        nav(page, '콘텐츠 제작')
        expect(page.locator('.projects-section .project').filter(has=page.get_by_text(target_title, exact=True))).to_be_visible()
        nav(page, '게시 스튜디오')
        expect(candidates.get_by_text(target_title, exact=True)).to_be_visible()
        expect(candidates.get_by_text(pending_title, exact=True)).to_have_count(0)
        assert len(documents) == 1 and len(posts) == 2
        assert files == {name: sha256((app.state.video.outputs / name).read_bytes()).hexdigest() for name in files}
        context.close()


def cost_snapshot(app):
    with app.state.sessions() as session:
        return (list(session.execute(select(AIUsage.id, AIUsage.total_tokens, AIUsage.status)).all()),
                list(session.execute(select(APIRequestReservation.id, APIRequestReservation.status,
                    APIRequestReservation.reserved_usd)).all()))


def assert_costs_visible(page):
    expect(page.locator('.mg-cost-header').get_by_text('20 tokens', exact=True)).to_be_visible()
    expect(page.locator('.mg-mini-stats > div').filter(has=page.get_by_text('결과 불명·예약', exact=True)).locator('strong')).to_have_text('1')
    usage = page.locator('.mg-panel').filter(has=page.get_by_role('heading', name='AI 사용량 · 비용 근거', exact=True))
    expect(usage.locator('tbody tr')).to_have_count(1)
    expect(usage.locator('tbody tr').get_by_role('cell').nth(3)).to_have_text(re.compile(r'17\s*/\s*3'))
    requests = page.locator('.mg-panel').filter(has=page.get_by_role('heading', name='최근 요청 기록', exact=True))
    expect(requests.locator('.mg-record')).to_have_count(1)


def test_analytics_uses_confirmed_publication_only_and_keeps_all_cost_records(app, browser):
    fixed = publication_fixture(app)
    costs = cost_snapshot(app)
    with local_server(OperatingRequests(app)) as origin:
        context = browser.new_context(viewport={'width': 1366, 'height': 768})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
        page = context.new_page(); posts = []
        page.on('request', lambda r: posts.append(r) if r.method == 'POST' else None)
        page.goto(origin + '/studio/analytics')
        page.evaluate('window.__syntheticSpaSentinel="preserved"')
        cards = page.locator('.mg-performance-cards')
        expect(cards.get_by_text('합성 게시 완료 콘텐츠', exact=True)).to_be_visible()
        expect(cards.get_by_text('합성 미게시 콘텐츠', exact=True)).to_have_count(0)
        expect(cards.get_by_role('button')).to_have_count(1)
        expect(page.locator('.mg-performance-content tbody tr')).to_have_count(1)
        expect(page.locator('.mg-analytics-side h3')).to_have_text('합성 게시 완료 콘텐츠')
        assert_costs_visible(page)
        nav(page, '라이브러리')
        page.locator('.mg-library-selection').get_by_role('button', name='표시 항목 전체 선택', exact=True).click()
        page.locator('.mg-library-selection').get_by_role('button', name='선택 삭제', exact=True).click()
        page.get_by_role('dialog', name='라이브러리에서 삭제', exact=True).get_by_role('button', name='휴지통으로 이동', exact=True).click()
        expect(page.locator('.mg-library-cards > div')).to_have_count(0)
        assert len(posts) == 1
        check_payload(posts[0], 'remove', [fixed['published'], fixed['unpublished']])
        nav(page, '성과 · 비용')
        expect(cards.get_by_text('합성 게시 완료 콘텐츠', exact=True)).to_be_visible()
        expect(cards.get_by_role('button')).to_have_count(1)
        expect(page.locator('.mg-performance-content tbody tr')).to_have_count(1)
        assert_costs_visible(page)
        assert cost_snapshot(app) == costs
        with app.state.sessions() as session:
            assert session.get(PublishJob, fixed['job_id']).status == 'uploaded'
            assert len(list(session.scalars(select(SocialMetric)))) == 3
        # A synthetic change to the receipt's owning job must remove performance,
        # without turning unconfirmed publication into success or deleting costs.
        with app.state.sessions.begin() as session:
            session.get(PublishJob, fixed['job_id']).status = 'unknown'
        page.reload()
        expect(cards.get_by_role('button')).to_have_count(0)
        expect(page.get_by_text('아직 게시 완료된 콘텐츠가 없습니다.', exact=True)).to_be_visible()
        expect(page.locator('.mg-performance-content tbody tr')).to_have_count(0)
        assert_costs_visible(page)
        assert len(posts) == 1 and cost_snapshot(app) == costs
        context.close()
