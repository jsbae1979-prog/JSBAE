"""Stored metric/category joins, privacy cohorts and responsive actual analytics page."""
import os
from pathlib import Path

from playwright.sync_api import expect
from sqlalchemy import select
from test_blue_studio_browser import guarded_page
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_video import video as video_fixture

from newsflow.db.models import NewsArticle, PlatformAccount, PublishDraft, PublishJob, SocialMetric
from newsflow.gui.routes import templates
from newsflow.publishing.analytics import AnalyticsService

video = video_fixture
browser = browser_fixture


def test_category_persistence_cohort_and_responsive_page(video, app, browser, monkeypatch):
    coordinator, draft_id = video
    render_id = coordinator.start(draft_id, 30, reviewed=True)
    coordinator.future.result(timeout=15)
    with app.state.sessions.begin() as session:
        account = PlatformAccount(platform='youtube', label='합성 채널', account_type='youtube_channel',
                                  status='not_connected', scopes=[], api_ready=False)
        session.add(account); session.flush(); account_id = account.id
        for i, categories in enumerate([['it','AI'], ['경제'], ['경제','사회']]):
            draft = PublishDraft(render_job_id=render_id, platform='youtube', title='합성 성과 자료',
                                 description='실제 게시 아님', hashtags=[], account_id=account.id,
                                 sources={'articles':[{'category': c} for c in categories]}, media_sha256='a'*64)
            session.add(draft); session.flush()
            job = PublishJob(draft_id=draft.id, platform='youtube', status='ext_simulated',
                             message='Fake only', idempotency_key=f'category-fixture-{i}')
            session.add(job); session.flush()
            session.add(SocialMetric(job_id=job.id, account_id=account.id, platform='youtube',
                                     remote_id=f'fake-{i}', metric='views', value=str(100*(i+1)), unit='count',
                                     period_start='2026-10-01', period_end='2026-10-01',
                                     period_basis='America/Los_Angeles', synthetic=True))
        session.scalar(select(NewsArticle)).category = '스포츠'  # Must not rewrite publication evidence.
    analytics = AnalyticsService(app.state.sessions)
    assert analytics.dashboard()['categories'] == []
    assert analytics.dashboard(synthetic=True, account_id=999)['categories'] == []
    assert analytics.dashboard(platform='instagram', synthetic=True)['categories'] == []
    result = analytics.dashboard(synthetic=True, account_id=account_id)
    assert [(item['name'],item['views']) for item in result['categories']] == [
        ('복합 주제',300),('경제',200),('IT·과학',100)]
    assert sum(item['views'] for item in result['categories']) == result['totals']['views']
    monkeypatch.setattr(app.state.social_analytics, 'dashboard',
                        lambda **kw: analytics.dashboard(**{**kw, 'synthetic':True}))
    monkeypatch.setitem(templates.env.globals, 'ui_demo', True)
    with local_server(app) as origin:
        context,page,external,errors = guarded_page(browser,origin,(1366,768))
        for width,height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            page.goto(origin + '/analytics')
            expect(page.locator('.category-performance-row')).to_have_count(3)
            # One measured day must not draw a fabricated decline to a later date.
            polygon = page.locator('.workstation-chart polygon').get_attribute('points')
            assert all(float(point.split(',')[0]) == 20 for point in polygon.split())
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            expect(page.get_by_text('합성 데이터 · 실제 성과가 아닙니다.')).to_be_visible()
            if os.environ.get('NEWSFLOW_CONTROL_EVIDENCE'):
                root = Path(os.environ['NEWSFLOW_CONTROL_EVIDENCE']); root.mkdir(parents=True,exist_ok=True)
                if width < 500:
                    page.locator('.category-performance').scroll_into_view_if_needed()
                page.screenshot(path=str(root / f'analytics-{width}.png'))
        assert not external and not errors
        context.close()
