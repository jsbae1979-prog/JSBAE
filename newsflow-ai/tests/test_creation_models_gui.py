"""Real browser, synthetic app and injected image adapter only."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_creation_models import no_network, service
from test_usability_browser import browser, studio_ui

from newsflow.creation.catalog import IMAGE_MODELS

# Explicit pytest fixture exports; do not delete these registration imports.
__all__ = ["browser", "no_network", "service", "studio_ui"]


@pytest.mark.parametrize('width',[1440,980,390])
def test_three_creation_modes_local_draft_to_fake_image_reuse(app,studio_ui,service,browser,tmp_path,width):
    output=Path(os.environ.get('NEWSFLOW_VALIDATION_OUTPUT',str(tmp_path)))/'creation-models'
    output.mkdir(parents=True,exist_ok=True)
    external=[];errors=[]
    with local_server(app) as origin:
        assert urlsplit(origin).port!=8765
        context=browser.new_context(viewport={'width':width,'height':900},locale='ko-KR',reduced_motion='reduce')
        def route_guard(route):
            if urlsplit(route.request.url).netloc!=urlsplit(origin).netloc:
                external.append(route.request.url);route.abort()
            else:route.continue_()
        context.route('**/*',route_guard)
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        for name,path in [('news','/create'),('image','/image-studio'),('character','/character')]:
            assert page.goto(origin+path,wait_until='networkidle').status==200
            expect(page.locator('h1').first).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'),name
            page.screenshot(path=str(output/f'{name}-{width}.png'),animations='disabled')
        page.goto(origin+'/image-studio')
        page.get_by_label('이미지 지시문',exact=True).fill('합성 기하학 일러스트')
        page.get_by_label('이미지 모델',exact=True).select_option(IMAGE_MODELS[-1])
        page.get_by_label('화면 비율·해상도',exact=True).select_option('1024x1024')
        page.get_by_role('button',name='이미지 초안 저장',exact=True).click()
        expect(page.get_by_role('heading',name='이미지 초안 #1')).to_be_visible()
        assert service.generation.adapter.calls==[]
        page.locator('input[name=reviewed]').check();page.locator('input[name=consent]').check()
        page.get_by_role('button',name='이미지 1회 생성',exact=True).click()
        preview=page.get_by_alt_text('생성 결과 · 내용과 사용권 검토 필요')
        expect(preview).to_be_visible()
        assert preview.evaluate('(i)=>i.complete && i.naturalWidth===1024')
        assert len(service.generation.adapter.calls)==1
        page.screenshot(path=str(output/f'image-result-{width}.png'),animations='disabled')
        page.locator('input[name=reviewed]').check()
        page.get_by_role('button',name='캐릭터 참조로 저장',exact=True).click()
        expect(page.get_by_alt_text('선택한 캐릭터 참조')).to_be_visible()
        assert page.locator('select[name=reference_asset]').input_value().startswith('studio-')
        assert not external and not errors
        context.close()
    (output/f'result-{width}.json').write_text(json.dumps({'width':width,'result':'PASS',
        'fake_image_calls':1,'external_page_requests':0,'javascript_errors':0,'real_API_calls':0}))



def test_news_default_button_saves_only_future_model(studio_ui,browser):
    from sqlalchemy import func, select

    from newsflow.creation.catalog import news_video_default, read_defaults
    from newsflow.db.models import AIVideoPlan
    from newsflow.video.ai.settings import save_model
    app=studio_ui
    model='kling-video/v3.0-turbo/text-to-video'
    save_model(app.state.sessions,path=model,label='Kling synthetic contract',price_per_second='',
               durations='3,5,10,15',resolution='720p',confirmed=True)
    before=read_defaults(app.state.sessions,'character')
    with local_server(app) as origin:
        context=browser.new_context()
        context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==urlsplit(origin).netloc else route.abort())
        page=context.new_page();page.goto(origin+'/video/ai')
        page.locator('select[name=model_path]').select_option(model)
        page.get_by_role('button',name='다음 뉴스 영상 모델로 저장',exact=True).click()
        expect(page.locator('select[name=model_path]')).to_have_value(model)
        page.wait_for_load_state('networkidle')
        assert news_video_default(app.state.sessions)==model
        context.close()
    assert read_defaults(app.state.sessions,'character')==before
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AIVideoPlan))==0
