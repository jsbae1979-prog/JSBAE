"""Video layout polish with synthetic records; no render or provider POST allowed."""
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

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

__all__=['browser','instagram_ui','studio_ui','unified','visual','youtube_media','youtube_ui']


@pytest.fixture(autouse=True)
def no_workers(monkeypatch):
    monkeypatch.setattr('newsflow.scheduler.service.Scheduler.start',lambda self:None)
    monkeypatch.setattr('newsflow.publishing.calendar.PublishingCalendar.start',lambda self:None)


def records(app):
    with app.state.sessions() as session:
        return deepcopy((stored_values(app),{model.__name__:[
            {c.name:getattr(row,c.name) for c in model.__table__.columns}
            for row in session.scalars(select(model).order_by(model.id))]
            for model in [ContentDraft,IntelligenceRun,RenderJob]}))


def test_svg_canvas_is_decorative_and_self_contained():
    path=Path(__file__).resolve().parents[1]/'src/newsflow/static/images/video-canvas.svg'
    tree=ElementTree.fromstring(path.read_text(encoding='utf-8-sig'))
    allowed={'svg','defs','linearGradient','stop','radialGradient','pattern','path','ellipse','g','circle'}
    for element in tree.iter():
        assert element.tag.rsplit('}',1)[-1] in allowed
        assert not any(key.startswith('on') or key.endswith('href') for key in element.attrib)


def test_video_inspector_timeline_form_and_settings_preserved(visual,browser):
    app,(draft,_render,_failure)=visual
    before=records(app)
    output=Path(os.environ['NEWSFLOW_VIDEO_MODERN_EVIDENCE'])
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
        for width in [1440,1024,390]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.goto(origin+f'/video?draft_id={draft}').status==200
            form=page.locator('form[action="/video/render"]')
            expect(form).to_have_count(1)
            expect(page.locator('.workstation-video-toolbar')).not_to_have_attribute('open','')
            page.locator('.workstation-video-toolbar>summary').press('Enter')
            expect(page.locator('.workstation-video-toolbar form select')).to_be_visible()
            expect(page.locator('.workstation-video-toolbar form select')).to_have_value(str(draft))
            page.locator('.workstation-video-toolbar>summary').press('Enter')
            expect(page.locator('.workstation-media-panel')).to_have_css('max-height','none')
            expect(page.locator('.workstation-media-panel')).to_have_css('overflow','visible')
            if width==1440:
                monitor=page.locator('.workstation-preview-column').bounding_box()
                inspector=page.locator('.video-modern-inspector').bounding_box()
                assert monitor['x']+monitor['width']<=inspector['x']
                assert abs(monitor['y']-inspector['y'])<1
            frame=page.locator('.composition-preview').bounding_box()
            monitor=page.locator('.workstation-monitor').bounding_box()
            assert abs(frame['width']/frame['height']-9/16)<.01
            assert frame['y']>=monitor['y'] and frame['y']+frame['height']<=monitor['y']+monitor['height']
            assert 'video-canvas.svg' in page.locator('.composition-preview').evaluate('e=>getComputedStyle(e).backgroundImage')
            expect(page.locator('.composition-preview')).to_contain_text('음성·타이밍 미검증')
            page.locator('.track-caption [data-video-scene-select="2"]').focus()
            page.keyboard.press('Enter')
            expect(page.locator('[data-video-scene="2"]')).to_be_visible()
            expect(page.locator('[data-video-scene="0"]')).to_be_hidden()
            expect(page.locator('#video-advanced-editing')).to_have_attribute('open','')
            expect(page.locator('[data-video-scene="2"] .video-scene-copy')).not_to_have_attribute('open','')
            page.locator('[data-video-scene="2"] .video-scene-copy>summary').click()
            expect(page.locator('[data-video-scene="2"] .video-scene-copy')).to_contain_text('내레이션:')
            page.locator('[data-scene-effect="2"]').select_option('fade')
            expect(page.locator('.track-effect [data-video-scene-select="2"]')).to_have_text('부드럽게 · 검정 페이드')
            assert form.evaluate("e=>new FormData(e).getAll('effects')")==['cut','cut','fade']
            assert form.evaluate("e=>new FormData(e).getAll('images').length")==3
            form.locator('[name=font_size]').select_option('56')
            form.locator('[name=subtitle_y]').select_option('1420')
            expect(form.locator('[name=reviewed]')).not_to_be_checked()
            expect(form.locator('[name=reviewed]')).to_have_attribute('required','')
            expect(form.locator('[name=external_tts_consent]')).not_to_be_checked()
            expect(form.locator('[name=asset_permission]')).not_to_be_checked()
            expect(form.locator('[name=csrf_token]')).to_have_count(1)
            expect(form.get_by_role('button',name='영상 제작 실행',exact=True)).to_have_count(1)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            # Reload discards these view-only edits; stored preferences and records stay identical.
            page.reload()
            expect(page.locator('[data-scene-effect="2"]')).to_have_value('cut')
            page.evaluate("()=>window.scrollTo({top:0,behavior:'instant'})")
            page.screenshot(path=str(output/f'video-default-{width}.png'),full_page=True)
            page.get_by_role('link',name='대본·자막 수정 →',exact=True).click()
            expect(page.locator('.script-modern')).to_have_count(1)
        assert not external and not posts and not errors
        context.close()
    assert records(app)==before
