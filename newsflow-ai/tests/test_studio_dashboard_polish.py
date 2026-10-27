"""Approved studio/dashboard polish, isolated records and GET-only browser checks."""
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from sqlalchemy import select
from test_cloud_workspace_flow import local_server
from test_dashboard_cohesion import seed_archive
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

from newsflow.db.models import ContentDraft, IntelligenceRun, RenderJob

__all__ = ['browser', 'instagram_ui', 'studio_ui', 'unified', 'visual', 'youtube_media', 'youtube_ui']


@pytest.fixture(autouse=True)
def no_startup_workers(monkeypatch):
    monkeypatch.setattr('newsflow.scheduler.service.Scheduler.start', lambda self: None)
    monkeypatch.setattr('newsflow.publishing.calendar.PublishingCalendar.start', lambda self: None)


def records(app):
    with app.state.sessions() as session:
        return deepcopy({model.__name__: [
            {column.name:getattr(row,column.name) for column in model.__table__.columns}
            for row in session.scalars(select(model).order_by(model.id))]
            for model in [ContentDraft,IntelligenceRun,RenderJob]})


def test_studio_dashboard_polish_keeps_real_state_forms_and_reviews(visual,browser):
    app,(draft,_render,_failure)=visual
    _article, task = seed_archive(app,draft)
    before=records(app),stored_values(app)
    evidence=Path(os.environ['NEWSFLOW_STUDIO_POLISH_EVIDENCE'])
    evidence.mkdir(parents=True,exist_ok=True)
    external,posts,errors=[],[],[]
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1440,'height':1000},locale='ko-KR')
        def guard(route):
            if urlsplit(route.request.url).netloc!=urlsplit(origin).netloc:
                external.append(route.request.url);route.abort()
            elif route.request.method!='GET':
                posts.append(route.request.url);route.abort()
            else:route.continue_()
        context.route('**/*',guard)
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        for width in [1440,1920,390]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.goto(origin+'/').status==200
            expect(page.locator('h1')).to_have_text('오늘의 뉴스를, 다음 영상으로.')
            expect(page.locator('#dash-workflow-title')).to_have_text('AI 제작 워크플로')
            expect(page.get_by_role('link',name='쇼츠 영상',exact=True)).to_have_count(1)
            expect(page.get_by_role('link',name='이미지 게시물',exact=True)).to_have_count(1)
            expect(page.locator('[data-dash-news-category]')).to_have_count(9)
            assert page.locator('.dash-center').evaluate("e=>[...e.children].map(n=>n.className)")==[
                'dash-panel dash-workflow','studio-disclosure dashboard-history','dash-panel dash-recent']
            expect(page.locator('.dashboard-history')).not_to_have_attribute('open','')
            page.locator('.dashboard-history>summary').click()
            expect(page.locator('.dashboard-history .dash-activity')).to_be_visible()
            assert page.locator('.workflow-steps').evaluate("e=>!!(e.compareDocumentPosition(document.querySelector('.workflow-current')) & Node.DOCUMENT_POSITION_FOLLOWING)")
            expect(page.locator('[data-dashboard-player]')).to_have_count(1)
            expect(page.locator('[data-workflow-next-action]')).to_have_attribute('href',f'/?task={task}#workspace-detail')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.evaluate("()=>window.scrollTo({top:0,behavior:'instant'})")
            page.screenshot(path=str(evidence/f'dashboard-{width}.png'),full_page=True)
            assert page.goto(origin+f'/ai?draft_id={draft}').status==200
            expect(page.locator(f'.script-next-step a[href="/video?draft_id={draft}"]')).to_have_count(1)
            expect(page.get_by_role('region',name='장면별 보완 필요')).to_contain_text('보완 필요 1건')
            expect(page.locator('.scene-review-notes')).to_contain_text('관련 용어와 기사 근거를 확인하세요.')
            page.locator('[data-script-source-open]').click()
            expect(page.locator('#script-sources')).to_have_attribute('open','')
            expect(page.locator('#script-sources>summary')).to_be_focused()
            page.locator('[data-script-edit-scene="1"]').click()
            expect(page.locator('[data-script-editor]')).to_have_attribute('open','')
            expect(page.locator('[data-topic-scene]:visible [name=scene_review_notes]')).to_contain_text('관련 용어와 기사 근거를 확인하세요.')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.goto(origin+f'/ai?draft_id={draft}')
            page.evaluate("()=>window.scrollTo({top:0,behavior:'instant'})")
            page.screenshot(path=str(evidence/f'script-{width}.png'),full_page=True)
            page.get_by_role('link',name='이 대본으로 영상 구성',exact=False).click()
            page.wait_for_load_state('networkidle')  # Wait for deferred scene controls before keyboard input.
            expect(page.locator('.workstation-scene-list')).to_have_count(0)
            expect(page.locator(f'.workstation-timeline a[href="/ai?draft_id={draft}"]')).to_have_count(1)
            expect(page.locator('#video-advanced-editing')).not_to_have_attribute('open','')
            page.get_by_role('button',name='자막 장면 2 · 10초',exact=True).focus()
            page.keyboard.press('Enter')
            expect(page.locator('#video-advanced-editing')).to_have_attribute('open','')
            expect(page.locator('[data-video-scene="1"]')).to_be_visible()
            expect(page.locator('[data-video-scene="0"]')).to_be_hidden()
            expect(page.locator('[data-video-selected-scene]')).to_have_text('장면 2')
            expect(page.locator('[data-video-scene-status]')).to_have_text('장면 2 선택됨')
            expect(page.locator('[data-composition-caption]')).to_have_text(page.locator('.track-caption [data-video-scene-select="1"]').inner_text())
            expect(page.locator('[data-video-scene-select="1"]')).to_have_count(4)
            form=page.locator('form[action="/video/render"]')
            assert form.evaluate("e=>new FormData(e).getAll('images').length")==3
            assert form.evaluate("e=>new FormData(e).getAll('effects').length")==3
            expect(form.locator('[name=reviewed]')).not_to_be_checked()
            expect(form.locator('[name=reviewed]')).to_have_attribute('required','')
            expect(form.locator('[name=external_tts_consent]')).not_to_be_checked()
            expect(form.locator('[name=asset_permission]')).not_to_be_checked()
            expect(form.locator('[name=csrf_token]')).to_have_count(1)
            expect(page.locator('.composition-preview')).to_contain_text('음성·타이밍 미검증')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.evaluate("()=>window.scrollTo({top:0,behavior:'instant'})")
            page.screenshot(path=str(evidence/f'video-{width}.png'),full_page=True)
        assert not external and not posts and not errors
        context.close()
    assert (records(app),stored_values(app))==before
