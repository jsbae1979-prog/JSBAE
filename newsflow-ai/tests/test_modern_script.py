"""Modern script interaction: synthetic records, no provider or generation requests."""
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from sqlalchemy import select
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

from newsflow.db.models import ContentDraft, IntelligenceRun, RenderJob

__all__ = ['browser','instagram_ui','studio_ui','unified','visual','youtube_media','youtube_ui']


@pytest.fixture(autouse=True)
def no_workers(monkeypatch):
    monkeypatch.setattr('newsflow.scheduler.service.Scheduler.start', lambda self:None)
    monkeypatch.setattr('newsflow.publishing.calendar.PublishingCalendar.start',lambda self:None)


def snapshot(app):
    with app.state.sessions() as session:
        return deepcopy((stored_values(app),{model.__name__:[
            {c.name:getattr(row,c.name) for c in model.__table__.columns}
            for row in session.scalars(select(model).order_by(model.id))]
            for model in [ContentDraft,IntelligenceRun,RenderJob]}))


def test_modern_script_scene_navigation_edit_preview_and_video_are_read_only(visual,browser):
    app,(_draft,_render,_failure)=visual
    before=snapshot(app)
    output=Path(os.environ['NEWSFLOW_MODERN_SCRIPT_EVIDENCE'])
    output.mkdir(parents=True,exist_ok=True)
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
        for width in [1440,390]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.goto(origin+'/').status==200
            expect(page.get_by_role('link',name='쇼츠 영상',exact=True)).to_have_count(1)
            expect(page.get_by_role('link',name='이미지 게시물',exact=True)).to_have_count(1)
            page.locator('.dash-preview-more>summary').click()
            page.locator('[data-dash-edit]').click()
            expect(page.locator('.script-modern')).to_have_count(1)
            expect(page.locator('[data-script-read-scene]')).to_have_count(3)
            expect(page.locator('.script-existing-video')).not_to_have_attribute('open','')
            assert page.locator('.script-new-article').evaluate("e=>!!(document.querySelector('.script-reader-layout').compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)")
            page.locator('[data-script-read-scene="3"]').focus()
            page.keyboard.press('Enter')
            expect(page.locator('[data-script-read-scene="3"]')).to_have_attribute('aria-current','location')
            expect(page.locator('#script-scene-3')).to_be_focused()
            expect(page.locator('#script-scene-3')).to_be_in_viewport()
            page.locator('[data-script-edit-scene="1"]').click()
            expect(page.locator('[data-script-editor]')).to_have_attribute('open','')
            expect(page.locator('[data-script-read-scene="2"]')).to_have_attribute('aria-current','location')
            field=page.locator('[data-topic-scene]:visible [name=narration]')
            original=field.input_value()
            field.fill('합성 검증 중 저장하지 않은 수정입니다.')
            expect(page.locator('[data-script-reading-dirty]')).to_be_visible()
            expect(page.locator('[data-script-read-narration="1"]')).to_have_text('합성 검증 중 저장하지 않은 수정입니다.')
            page.reload()
            expect(page.locator('[data-script-read-narration="1"]')).to_have_text(original)
            page.locator('[data-script-source-open]').click()
            expect(page.locator('#script-sources')).to_have_attribute('open','')
            page.locator('.script-existing-video>summary').click()
            expect(page.locator('[data-editor-player]')).to_be_visible()
            expect(page.locator('[data-editor-player]')).to_have_attribute('preload','none')
            page.locator('.script-existing-video>summary').click()
            page.evaluate("()=>window.scrollTo({top:0,behavior:'instant'})")
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.screenshot(path=str(output/f'modern-script-{width}.png'),full_page=True)
            page.get_by_role('link',name='이 대본으로 영상 구성',exact=False).click()
            expect(page.locator('h1')).to_have_text('영상 구성')
            page.locator('.track-caption [data-video-scene-select="1"]').click()
            expect(page.locator('[data-video-scene="1"]')).to_be_visible()
            expect(page.locator('[data-video-scene-status]')).to_have_text('장면 2 선택됨')
            expect(page.locator('[name=reviewed]')).not_to_be_checked()
            expect(page.locator('[name=external_tts_consent]')).not_to_be_checked()
            page.get_by_role('navigation',name='주 메뉴').get_by_role('link',name='대시보드',exact=True).click()
            expect(page.locator('#dash-workflow-title')).to_have_text('AI 제작 워크플로')
        assert not external and not posts and not errors
        context.close()
    assert snapshot(app)==before
