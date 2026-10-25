"""Cohesive UI: archive-only search, preserved categories and isolated route coverage."""
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from jinja2 import FileSystemLoader
from playwright.sync_api import expect
from sqlalchemy import func, select
from test_cloud_workspace_flow import local_server
from test_single_workspace import stored_values
from test_usability_browser import (
    browser,
    instagram_ui,
    studio_ui,
    unified,
    visual,
    youtube_media,
    youtube_ui,
)
from test_youtube_gui import forbid_external_calls  # noqa: F401

from newsflow.db.models import AutopilotJob, NewsArticle, NewsSource
from newsflow.gui.routes import templates

# Imported fixtures are intentionally reused without actual providers/media generation.
__all__ = ['browser', 'instagram_ui', 'studio_ui', 'unified', 'visual', 'youtube_media', 'youtube_ui']


@pytest.fixture(autouse=True)
def no_startup_workers(monkeypatch):
    monkeypatch.setattr('newsflow.scheduler.service.Scheduler.start', lambda self: None)
    monkeypatch.setattr('newsflow.publishing.calendar.PublishingCalendar.start', lambda self: None)


def seed_archive(app, draft):
    with app.state.sessions.begin() as session:
        source = NewsSource(name='합성 자료 출처', url='https://example.com/cohesion/rss', enabled=False)
        session.add(source)
        session.flush()
        articles = []
        for i, category in enumerate(['정치', '경제', '사회', 'IT·과학', '문화', '스포츠', '국제', '미분류']):
            article = NewsArticle(title=f'합성 {category} 보관 기사', summary=f'{category} 분야의 보관된 합성 요약입니다. 외부 요청 없이 검색과 분류를 확인합니다.',
                url=f'https://example.com/cohesion/{i}', canonical_url=f'https://example.com/cohesion/{i}',
                publisher='합성 출처', source_id=source.id, category=category)
            session.add(article)
            articles.append(article)
        session.flush()
        identifier = articles[0].id
        job = AutopilotJob(id='c'*32, mode='guided', source='sample', duration=30, platform='youtube',
            status='waiting_review', current_stage='script', stage_results={'script': {'content_draft_id': draft}},
            message='합성 대본 검토 대기')
        session.add(job)
    return identifier, job.id


def test_archive_filters_visual_system_and_auxiliary_routes(visual, browser):
    app, (draft, _render, _failure) = visual
    article, job = seed_archive(app, draft)
    settings = stored_values(app)
    output = Path(os.environ['NEWSFLOW_USABILITY_EVIDENCE'])
    output.mkdir(parents=True, exist_ok=True)
    external, mutations, errors = [], [], []
    with local_server(app) as origin:
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ko-KR')
        # The parent harness supplies accepted Step13I source assets, never operating files.
        original = Path(os.environ['NEWSFLOW_BASELINE_GUI_SOURCE']).resolve()
        assert original.is_dir() and (original / 'gui/templates').is_dir()
        phase = {'before': False}
        def guard(route):
            request = route.request
            if urlsplit(request.url).netloc != urlsplit(origin).netloc:
                external.append(request.url)
                route.abort()
            elif request.method != 'GET':
                mutations.append(request.method + ' ' + urlsplit(request.url).path)
                route.abort()
            elif phase['before'] and urlsplit(request.url).path.startswith('/static/'):
                source = original / urlsplit(request.url).path.lstrip('/')
                if source.is_file():
                    route.fulfill(body=source.read_bytes(), content_type=mimetypes.guess_type(source.name)[0] or 'application/octet-stream')
                else:
                    route.fulfill(status=404)
            else:
                route.continue_()
        context.route('**/*', guard)
        page = context.new_page()
        page.set_default_timeout(8000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        old_loader = templates.env.loader
        try:
            phase['before'] = True
            templates.env.loader = FileSystemLoader(str(original / 'gui' / 'templates'))
            templates.env.cache.clear()
            for url, name in [('/', 'dashboard-populated'), ('/news','news'),('/queue','queue'),('/analytics','analytics'),('/simple-settings','settings'),('/operations','operations'),('/image-posts','image-posts')]:
                assert page.goto(origin + url).status == 200
                page.screenshot(path=str(output / f'cohesion-before-{name}.png'), full_page=True)
        finally:
            phase['before'] = False
            templates.env.loader = old_loader
            templates.env.cache.clear()
        page.goto(origin + '/')
        expect(page.locator('.dash-metric strong')).to_have_text(['8', '1', '1', '0'])
        expect(page.get_by_role('navigation', name='뉴스 분야', exact=True)).to_have_count(1)
        categories = ['', '정치', '경제', '사회', 'IT·과학', '문화', '스포츠', '국제', '미분류']
        assert page.locator('.workflow-script .button.primary').evaluate('e=>getComputedStyle(e).backgroundImage') == 'none'
        assert page.locator('[data-dash-news-category]').evaluate_all('(els)=>els.map(e=>e.dataset.dashNewsCategory)') == categories
        art = page.locator('.studio-hero-art img')
        expect(art).to_be_visible()
        expect(art).to_have_attribute('src', '/static/images/studio-concepts/hero_news_studio-1024.webp')
        assert art.evaluate('e=>e.complete && e.naturalWidth > 0')
        expect(page.locator('.studio-hero-art figcaption')).to_contain_text('AI 생성 콘셉트 이미지')
        expect(page.locator('.dash-search')).to_have_attribute('action', '/news')
        expect(page.locator('#quick-production')).to_have_count(0)
        # Filtering only replaces news rows. Preserve unrelated unsaved controls.
        video_choice = page.locator('[data-production-kind=video]')
        video_choice.locator('summary').click()
        video_choice.locator('select').select_option('higgsfield')
        expect(video_choice.locator('[data-selection-pending]')).to_be_visible()
        page.keyboard.press('Escape')
        page.locator('#home-topic').fill('유지할 검색어')
        for category in categories[1:]:
            page.locator(f'[data-dash-news-category="{category}"]').click()
            expect(page.locator('[data-dash-news-status]')).to_contain_text(category + ' · 보관 뉴스')
            expect(page.locator('[data-dash-news-list]')).to_contain_text(f'합성 {category} 보관 기사')
            expect(page.locator('[data-dash-news-list] .dash-news-item')).to_have_count(1)
            expect(page.locator('[data-dash-news-category][aria-current=true]')).to_have_attribute('data-dash-news-category', category)
            assert page.url == origin + '/'
            expect(video_choice.locator('select')).to_have_value('higgsfield')
            expect(page.locator('#home-topic')).to_have_value('유지할 검색어')
        page.locator('[data-dash-news-category=""]').click()
        expect(page.locator('[data-dash-news-status]')).to_contain_text('전체 · 보관 뉴스')
        # The creation form remains available at its current route, without saving.
        page.goto(origin + '/create')
        page.locator('#quick-duration').select_option('45')
        expect(page.locator('#quick-duration')).to_have_value('45')
        assert page.locator('#quick-production').evaluate("f=>new FormData(f).get('duration')") == '45'
        assert stored_values(app) == settings
        page.goto(origin + '/')
        # A GET of stored data, never a collection or paid AI operation.
        page.locator('#home-topic').fill('합성 경제')
        page.locator('#archive-search button').click()
        expect(page).to_have_url(origin + '/news?q=' + '%ED%95%A9%EC%84%B1+%EA%B2%BD%EC%A0%9C')
        expect(page.locator('.suite-news-article')).to_have_count(1)
        expect(page.locator('.suite-news-article')).to_contain_text('합성 경제 보관 기사')
        expect(page.locator('[name=q]')).to_have_value('합성 경제')
        expect(page.locator('h1')).to_have_text('뉴스 수집')
        # Collection controls remain reachable in one click; not executed.
        page.get_by_role('link', name='뉴스 수집·평가', exact=False).click()
        expect(page.locator('#curation')).to_be_in_viewport()
        urls = [('/', 'dashboard-populated'), ('/news','news'), ('/queue','queue'),
                ('/analytics','analytics'), ('/simple-settings','settings'),
                ('/operations','operations'), ('/publishing','advanced-publishing'),
                ('/image-posts','image-posts'), (f'/image-posts?article_id={article}','image-editor'),
                ('/image-posts/selection','top-three'), ('/publishing/platforms','platforms'),
                ('/guides/platforms','platform-guide'), ('/video-ai-settings/preflight','ai-preflight'),
                (f'/autopilot/jobs/{job}','task-detail'), ('/autopilot/jobs','task-list'),
                ('/autopilot/start','start'), ('/setup','setup'), (f'/news/{article}','article')]
        for width in [1440, 390, 320]:
            page.set_viewport_size({'width': width, 'height': 1000})
            for url, name in urls:
                response = page.goto(origin + url)
                assert response.status == 200, url
                assert page.locator('link[href="/static/css/usability.css"]').count() == 1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (width, url)
                # Shared palette and readable feedback are actual computed styles, not file presence.
                assert page.locator('#main-content').evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(8, 17, 31)'
                if url == '/analytics':
                    expect(page.locator('.analytics-empty')).to_be_visible()
                    expect(page.locator('.social-kpis,.workstation-analytics-grid')).to_have_count(0)
                if url == '/queue':
                    for card in page.locator('.social-platforms .suite-platform-card').all():
                        assert card.bounding_box()['width'] > 180
                if width != 320:
                    page.screenshot(path=str(output / f'cohesion-{width}-{name}.png'), full_page=True)
            page.goto(origin + '/')
            page.keyboard.press('Tab')
            expect(page.get_by_role('link', name='본문으로 이동')).to_be_focused()
            assert page.get_by_role('link', name='본문으로 이동').evaluate('e=>getComputedStyle(e).outlineStyle') != 'none'
            menu = page.locator('[data-sidebar-menu]')
            if menu.get_attribute('open') is None:
                menu.locator('>summary').click()
            assert page.locator('.workspace-nav a:visible').count() == 7
        assert not external and not mutations and not errors
        assert stored_values(app) == settings
        with app.state.sessions() as session:
            assert session.scalar(select(func.count()).select_from(NewsArticle)) == 8
        (output / 'cohesion-browser-results.json').write_text(json.dumps({'routes': urls, 'widths':[1440,390,320],
            'chrome': browser.version, 'external_requests':0, 'mutation_requests':0, 'errors':errors,
            'categories':categories, 'search_scope':'stored_articles', 'operating_app_used':False}, ensure_ascii=False, indent=2), encoding='utf-8')
        context.close()


def test_analytics_saved_data_remains_visible(studio_ui, client, monkeypatch):
    app = studio_ui
    data = app.state.social_analytics.dashboard()
    data['synthetic'] = True
    data['rows'] = [{'job_id': 7, 'metric': 'views', 'value': 123, 'unit': 'views',
        'period_start': '2026-10-01', 'period_end': '2026-10-07', 'period_basis': 'synthetic', 'fetched_at': None}]
    data['totals'] = {key: None for key in data['metrics']}
    data['totals']['views'] = 123
    data['categories'] = [{'name': 'IT·과학', 'views': 123, 'videos': 1, 'percent': 100}]
    monkeypatch.setattr(app.state.social_analytics, 'dashboard', lambda **kwargs: data)
    page = client.get('/analytics')
    assert page.status_code == 200
    assert '합성 데이터 · 실제 성과가 아닙니다.' in page.text
    assert '123' in page.text and 'IT·과학' in page.text
    assert '영상 성과 기록' in page.text and 'workstation-analytics-grid' in page.text
    assert 'analytics-empty' not in page.text
