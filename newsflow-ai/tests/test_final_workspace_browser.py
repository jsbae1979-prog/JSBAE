"""Offline Chrome user path: same workspace, explicit choices and image-only local save."""
import os
from pathlib import Path

from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_final_production import full, new_plan, no_external
from test_image_posts import article
from test_model_picker_browser import browser

__all__=['browser', 'full', 'no_external']


def test_final_choices_and_feed_local_save_in_chrome(full,browser,tmp_path):
    app=full.app
    identifier=article(app)
    plan=new_plan(full)
    output=Path(os.environ.get('NEWSFLOW_VALIDATION_OUTPUT',str(tmp_path/'screens')))
    output.mkdir(parents=True,exist_ok=True)
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':900},locale='ko-KR')
        external=[]
        def route(request):
            if request.request.url.startswith(origin+'/'): request.continue_()
            else:
                external.append(request.request.url)
                request.abort()
        context.route('**/*',route)
        page=context.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        for width in [1366,390]:
            page.set_viewport_size({'width':width,'height':900})
            for name,path in [('video',f'/video/ai/plans/{plan}'),('feed',f'/image-posts?article_id={identifier}'),
                              ('settings','/simple-settings')]:
                assert page.goto(origin+path).status==200
                expect(page.locator('h1').first).to_be_visible()
                if name=='feed':
                    assert page.locator('form[action="/image-posts/generate-background"]').count()==1
                    # Collapsed opt-in remains separate from local saving.
                    expect(page.get_by_role('button',name='이미지로 저장',exact=True)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+2')
                # Bound compositor allocation on Windows runners; functional checks still cover the document.
                page.screenshot(path=str(output/f'final-{name}-{width}.png'),full_page=False, animations='disabled')
        page.goto(origin+f'/image-posts?article_id={identifier}')
        form=page.locator('form[action="/image-posts/create"]')
        form.locator('[name="title"]').fill('새로운 독서 모임')
        form.locator('[name="body"]').fill('합성 뉴스의 저장된 요약을 확인합니다.')
        form.locator('[name="ai_disclosure"]').select_option('not_required')
        for name in ['reviewed','rights','sources_confirmed']: form.locator(f'[name="{name}"]').check()
        form.get_by_role('button',name='이미지로 저장',exact=True).click()
        expect(page.locator('#image-result')).to_be_visible()
        expect(page.get_by_role('link',name='JPG 저장',exact=True)).to_be_visible()
        assert len(app.state.image_posts.recent())==1
        assert app.state.image_generation.recent(identifier)==[]
        assert not external and not errors and not full.provider.calls
        context.close()
