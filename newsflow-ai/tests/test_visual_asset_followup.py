"""Neutral news previews and accurate AI mode guidance; synthetic sources only."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect
from sqlalchemy import select
from test_cloud_workspace_flow import local_server
from test_final_production import full, new_plan, no_external, rows
from test_model_picker_browser import browser
from test_news_thumbnails import picture

from newsflow.db.models import AIVideoPlan, ArticleThumbnail, NewsArticle, NewsSource

__all__ = ['browser', 'full', 'no_external']


def seed_news(app, fake):
    ids = {}
    with app.state.sessions.begin() as session:
        source = NewsSource(name='합성 출처', url='https://example.com/visual-feed', enabled=False)
        session.add(source)
        session.flush()
        for key, title in [('source', '출처 제공 이미지'), ('missing', '원본 이미지 없음'), ('failed', '이미지 로딩 실패')]:
            url = f'https://example.com/visual-{key}'
            article = NewsArticle(source_id=source.id, title=f'[합성 검증] {title}', url=url,
                                  canonical_url=url, publisher='합성 출처', category='IT·과학',
                                  summary='시각 검증용 합성 기사입니다. 실제 보도 자료가 아닙니다.')
            session.add(article)
            session.flush()
            ids[key] = article.id
            if key != 'missing':
                image_url = f'https://img.example.com/{key}.png'
                session.add(ArticleThumbnail(article_id=article.id, url=image_url, source_article_url=url, publisher="합성 출처"))
                fake.feeds[image_url] = picture() if key == 'source' else b'not an image'
    return ids


def capture(app, fake, browser, tmp_path, *, check=True):
    ids = seed_news(app, fake)
    output = Path(os.environ.get('NEWSFLOW_VALIDATION_OUTPUT', str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    blocked, errors, observations = [], [], []
    with app.state.sessions() as session:
        before = [(a.id, a.title, a.url, a.summary) for a in session.scalars(select(NewsArticle))]
    with local_server(app) as origin:
        context = browser.new_context(locale='ko-KR', reduced_motion='reduce')
        def guard(route):
            if urlsplit(route.request.url).netloc == urlsplit(origin).netloc and route.request.method == 'GET':
                route.continue_()
            else:
                blocked.append(route.request.url)
                route.abort()
        context.route('**/*', guard)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        for width, height in [(1366, 768), (1920, 1080), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            for name, path in [('home', '/'), ('news', '/news'), ('ai-video', '/video/ai')]:
                assert page.goto(origin + path, wait_until='networkidle').status == 200
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
                if name != 'ai-video':
                    container = '.dash-news-art' if name == 'home' else '.suite-topic-art'
                    for key, identifier in ids.items():
                        article = page.locator(f'a[href="/news/{identifier}"]').filter(has=page.locator(container)).first
                        article.scroll_into_view_if_needed()
                        if key == 'source':
                            image = article.locator('img[data-news-thumbnail]')
                            expect(image).to_be_visible()
                            expect(image).to_have_js_property('complete', True)
                            assert image.evaluate('(e)=>e.naturalWidth > 0')
                        if check:
                            expect(article.locator('.news-thumbnail-fallback')).to_be_hidden() if key == 'source' else expect(article.locator('.news-thumbnail-fallback')).to_be_visible()
                            assert article.locator(container).evaluate('(e)=>getComputedStyle(e).backgroundImage') == 'none'
                            if key == 'failed':
                                expect(article.locator('img[data-news-thumbnail]')).to_be_hidden()
                    # Home category replacement uses the existing fragment route.
                    if name == 'home':
                        page.locator('[data-dash-news-category="IT·과학"]').click()
                        expect(page.locator('[data-dash-news-status]')).to_contain_text('IT·과학 · 보관 뉴스')
                        expect(page.locator('.dash-news-item')).to_have_count(3)
                        if check:
                            expect(page.locator('.dash-news-art .news-thumbnail-fallback:visible')).to_have_count(2)
                    page.locator(container).first.scroll_into_view_if_needed()
                elif check:
                    expect(page.locator('#video-ai-modes')).to_contain_text('모든 시각 장면')
                    expect(page.locator('#video-ai-modes')).to_contain_text('카드·로컬 이미지·AI 생성')
                    expect(page.locator('#video-ai-new')).to_contain_text('계획 저장만으로는 유료 생성을 시작하지 않습니다')
                    expect(page.locator('[name=mode]')).to_have_value('full')
                    page.locator('[name=mode]').select_option('mixed')
                    expect(page.locator('[name=mode]')).to_have_value('mixed')
                    page.locator('[name=mode]').select_option('full')
                page.screenshot(path=str(output / f'{name}-{width}.png'), animations='disabled')
                observations.append({'page': name, 'viewport': f'{width}x{height}', 'horizontal_overflow': 0})
        context.close()
    with app.state.sessions() as session:
        assert before == [(a.id, a.title, a.url, a.summary) for a in session.scalars(select(NewsArticle))]
        assert session.scalar(select(AIVideoPlan.id)) is None
    assert not blocked and not errors
    assert fake.calls.count('https://img.example.com/source.png') == 1
    assert fake.calls.count('https://img.example.com/failed.png') == 1
    assert set(fake.calls) == {'https://img.example.com/source.png', 'https://img.example.com/failed.png'}
    (output / 'audit.json').write_text(json.dumps({'screens': observations, 'external_or_post': blocked,
        'js_errors': errors, 'news_preserved': True, 'new_ai_plans': 0,
        'synthetic_image_fetches': fake.calls, 'real_external_calls': 0}, ensure_ascii=False, indent=2), encoding='utf-8')


def test_news_fallback_and_mode_guidance_browser(app, fake, browser, tmp_path):
    capture(app, fake, browser, tmp_path)


def test_mixed_plan_stays_card_without_paid_calls(full):
    plan = full.service.create_plan(full.draft_id, 30, mode='mixed')
    assert {scene.source for scene in rows(full, plan)} == {'card'}
    assert full.provider.calls == []


def test_full_plan_stays_all_generated_without_paid_calls(full):
    plan = new_plan(full)
    assert {scene.source for scene in rows(full, plan)} == {'generated'}
    assert full.provider.calls == []
