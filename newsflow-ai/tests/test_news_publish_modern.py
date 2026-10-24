"""Scoped UI checks: synthetic DB, blocked providers, GET-only Chrome interactions."""
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from sqlalchemy import select
from test_cloud_workspace_flow import local_server
from test_dashboard_cohesion import seed_archive
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

from newsflow.db.models import Base, IntelligenceRun, NewsArticle, NewsSource, PublishDraft
from newsflow.intelligence.curation import COMPONENTS, PROFILE

__all__ = ['browser', 'instagram_ui', 'studio_ui', 'unified', 'visual', 'youtube_media', 'youtube_ui']


@pytest.fixture(autouse=True)
def no_workers(monkeypatch):
    monkeypatch.setattr('newsflow.scheduler.service.Scheduler.start', lambda self: None)
    monkeypatch.setattr('newsflow.publishing.calendar.PublishingCalendar.start', lambda self: None)


def snapshot(app):
    with app.state.sessions() as session:
        return deepcopy({table.name: [tuple(row) for row in session.execute(select(table))]
                         for table in Base.metadata.sorted_tables})


def guarded_context(browser, origin):
    context = browser.new_context(viewport={'width':1440,'height':1000}, locale='ko-KR')
    external, mutations, errors = [], [], []
    def guard(route):
        if urlsplit(route.request.url).netloc != urlsplit(origin).netloc:
            external.append(route.request.url)
            route.abort()
        elif route.request.method != 'GET':
            mutations.append(route.request.method + ' ' + urlsplit(route.request.url).path)
            route.abort()
        else:
            route.continue_()
    context.route('**/*', guard)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    return context, page, external, mutations, errors


@pytest.mark.parametrize('path', ['/news','/queue'])
def test_empty_routes_keep_security_and_stored_state(client, app, path):
    before = snapshot(app)
    response = client.get(path)
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert 'news-publish-modern.css' in response.text
    assert '아직 표시할 기사가 없어요.' in response.text if path == '/news' else '게시할 영상을 선택하세요.' in response.text
    assert snapshot(app) == before


def test_news_filters_curation_consents_and_read_only_state(visual, browser, monkeypatch, tmp_path):
    app, (draft, _render, _failure) = visual
    article, _task = seed_archive(app, draft)
    with app.state.sessions.begin() as session:
        session.add(IntelligenceRun(kind='analysis', status='success', provider='claude_api',
            options={'model':'fixture-only'}, evidence={'articles':[{'id':article}],
            'curation_contract':{'profile':PROFILE,'top_k':3}},
            result={'ranking':[{'rank':i,'title':f'합성 선정 뉴스 {i}', 'score':70-i,
                'assessed_max':100,'reason':'합성 편집 평가이며 실제 인기도가 아닙니다.',
                'summary':'저장된 합성 자료에 기반한 요약입니다.',
                'components':dict.fromkeys(COMPONENTS, 14), 'search_interest':[],
                'sources':[{'publisher':'합성 출처','url':'https://example.com/synthetic'}]}
                for i in range(1,4)]}, message='합성 저장 결과'))
    from newsflow.gui import curation_routes
    original_context = curation_routes.context
    def context(request):
        value = original_context(request)
        with app.state.sessions() as session:
            value['articles'] = list(session.scalars(select(NewsArticle)))
        return {**value,'ready':True,'whole_collection_evaluation':True,'api_selected':True,
                'run_id':1,'snapshot':{'collection_policy':'global_trends_v1'}}
    monkeypatch.setattr(curation_routes, 'context', context)
    with app.state.sessions() as session:
        source_count = len(list(session.scalars(select(NewsSource))))
    before = snapshot(app)
    output = Path(os.environ.get('NEWSFLOW_NEWS_PUBLISH_EVIDENCE', str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        context, page, external, mutations, errors = guarded_context(browser, origin)
        for width in [1440,1024,390]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.goto(origin+'/news').status == 200
            expect(page.locator('.news-modern')).to_have_count(1)
            expect(page.locator('[data-news-category]')).to_have_count(9)
            expect(page.locator('[data-news-category=""]')).to_have_attribute('aria-pressed','true')
            expect(page.locator('.suite-news-article')).to_have_count(8)
            for action in ['serpapi','analyze','generate','import']:
                forms = page.locator(f'form[action="/news/curation/{action}"]')
                assert forms.count() >= 1
                for form in forms.all():
                    expect(form.locator('[name=csrf_token]')).to_have_count(1)
                    consent = form.locator('[type=checkbox]')
                    expect(consent).not_to_be_checked()
                    expect(consent).to_have_attribute('required','')
            expect(page.locator('.curation-item')).to_have_count(3)
            expect(page.locator('#curation-results')).to_contain_text('독립 사실 검증 미완료')
            if width == 1440:
                main = page.locator('.suite-news-main').bounding_box()
                side = page.locator('.news-modern>.suite-news-layout>aside').bounding_box()
                assert main['x'] + main['width'] <= side['x']
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(output/f'news-{width}.png'), full_page=True)
            page.get_by_role('button', name='경제', exact=True).press('Enter')
            expect(page.locator('.suite-news-article')).to_have_count(1)
            expect(page.locator('.suite-news-article')).to_contain_text('합성 경제 보관 기사')
            page.get_by_role('textbox', name='보관 기사 검색', exact=True).fill('없는 합성 검색어')
            page.get_by_role('button', name='검색', exact=True).click()
            expect(page.locator('.suite-empty')).to_be_visible()
            page.goto(origin+'/news')
            page.locator('.news-filter-options>summary').press('Enter')
            page.locator('.suite-extra-filters>summary').press('Enter')
            expect(page.locator('[name=start]')).to_be_visible()
            page.locator('[name=sort]').select_option('newest')
            page.get_by_role('button',name='검색',exact=True).click()
            expect(page.locator('[name=sort]')).to_have_value('newest')
            page.locator('.news-source-list>summary').press('Enter')
            expect(page.locator('.news-source-list a')).to_have_count(source_count)
            page.get_by_role('link',name='영상에 사용한 뉴스',exact=True).click()
            assert 'view=used' in page.url
            expect(page.locator('.news-collection-tabs a[aria-current=true]')).to_have_text('영상에 사용한 뉴스')
        assert not external and not mutations and not errors
        context.close()
    assert snapshot(app) == before


def test_queue_review_calendar_targets_and_records_preserved(visual, browser, tmp_path):
    app, (_draft, render, failure) = visual
    with app.state.sessions.begin() as session:
        for video, state, title in [(render,'local_draft','합성 로컬 게시 초안'),
                (failure,'unknown','합성 결과 불명 · 자동 재시도 금지')]:
            session.add(PublishDraft(render_job_id=video, platform='youtube', title=title,
                description='합성 게시 설명입니다. 외부 전송하지 않습니다.', hashtags=['합성'], sources={},
                media_sha256='0'*64, state=state, content_reviewed=True, sources_confirmed=False,
                copyright_confirmed=False))
    before = snapshot(app)
    output = Path(os.environ.get('NEWSFLOW_NEWS_PUBLISH_EVIDENCE', str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        context, page, external, mutations, errors = guarded_context(browser, origin)
        for width in [1440,1024,390]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.goto(origin+'/queue').status == 200
            expect(page.locator('.publish-modern')).to_have_count(1)
            expect(page.locator('.queue-card')).to_have_count(2)
            unknown = page.locator('.queue-card[data-draft-state=unknown]')
            expect(unknown.locator('.easy-badge')).to_contain_text('결과 불명')
            expect(unknown.locator('video')).to_have_count(0)
            expect(unknown.locator('.review-done')).to_have_text('내용 확인 완료')
            expect(unknown.locator('.review-needed')).to_have_count(2)
            local = page.locator('.queue-card[data-draft-state=local_draft]')
            expect(local.locator('video')).to_have_count(1)
            expect(local.locator('.queue-review-action')).to_have_attribute('href',
                f'/?video={render}&publish_platform=unified#publish-workspace')
            expect(page.locator('.social-platforms>a')).to_have_count(4)
            expect(page.locator('#publishing-calendar')).not_to_have_attribute('open','')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(output/f'queue-{width}.png'), full_page=True)
            local.locator('.queue-row-details>summary').press('Enter')
            expect(local.get_by_role('link',name='영상 저장',exact=True)).to_have_attribute('href',
                f'/video/jobs/{render}/file?download=true')
            page.locator('#publishing-calendar>summary').press('Enter')
            page.get_by_role('link',name='다음 달',exact=True).click()
            expect(page.locator('.social-calendar')).to_have_count(1)
            page.goto(origin+'/queue')
            page.locator('.queue-card[data-draft-state=local_draft] .queue-review-action').click()
            expect(page.locator('[data-publish-local-save]')).to_be_enabled()
            for checkbox in page.locator('[data-unified-publish-form] input[name=consent], [data-unified-publish-form] input[name=youtube_public_consent], [data-unified-publish-form] input[name=instagram_public_consent]').all():
                expect(checkbox).not_to_be_checked()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not external and not mutations and not errors
        context.close()
    assert snapshot(app) == before
