import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from conftest import app, fake, rss
from test_cloud_workspace_flow import local_server
from test_usability_browser import visual, studio_ui, unified, youtube_ui, instagram_ui, youtube_media, browser
from test_youtube_gui import forbid_external_calls
from test_studio_dashboard_polish import records
from test_single_workspace import stored_values

OUT=Path(os.environ['UX_EVIDENCE'])/os.environ.get('UX_PHASE','after')


def test_all_screens(visual,browser):
    app,(draft,render,failure)=visual
    OUT.mkdir(parents=True,exist_ok=True)
    before=records(app),stored_values(app)
    media={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in app.state.video.outputs.glob('*') if p.is_file()}
    paths=[('home','/'),('create','/create'),('tasks','/?show=tasks'),('library','/videos'),
           ('script',f'/ai?draft_id={draft}'),('video',f'/video?draft_id={draft}'),
           ('settings','/simple-settings'),('queue','/queue'),
           ('publish',f'/?video={render}&publish_platform=unified#publish-workspace'),
           ('error',f'/video?job_id={failure}'),('operations','/operations')]
    external,posts,errors=[],[],[]
    audit=[]
    with local_server(app) as origin:
        context=browser.new_context(locale='ko-KR',reduced_motion='reduce')
        def guard(route):
            if urlsplit(route.request.url).netloc!=urlsplit(origin).netloc:
                external.append(route.request.url);route.abort()
            elif route.request.method!='GET':
                posts.append(route.request.url);route.abort()
            else:route.continue_()
        context.route('**/*',guard)
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        for width,height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            for name,path in paths:
                response=page.goto(origin+path,wait_until='networkidle')
                assert response.status==200
                expect(page.locator('h1').first).to_be_attached()
                overflow=page.evaluate('document.documentElement.scrollWidth-innerWidth')
                audit.append({'screen':name,'viewport':f'{width}x{height}','overflow':overflow})
                assert overflow<=2,(name,width,overflow)
                if name == 'error' and os.environ.get('UX_PHASE') == 'after':
                    notice = page.locator('.studio-error')
                    expect(notice).to_contain_text('음성')
                    notice.scroll_into_view_if_needed()
                    actions=page.locator('.studio-recovery-actions a')
                    boxes=[actions.nth(i).bounding_box() for i in range(actions.count())]
                    for first,second in zip(boxes,boxes[1:]):
                        assert second['y'] >= first['y']+first['height']+8 or second['x'] >= first['x']+first['width']+8
                page.screenshot(path=str(OUT/f'{name}-{width}.png'),animations='disabled')
        context.close()
    assert not external and not posts and not errors
    assert before==(records(app),stored_values(app))
    assert media=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in app.state.video.outputs.glob('*') if p.is_file()}
    (OUT/'audit.json').write_text(json.dumps({'screens':audit,'external':external,'posts':posts,'errors':errors,'records_settings_media_preserved':True},ensure_ascii=False,indent=2))


def test_empty_states(app,browser):
    OUT.mkdir(parents=True,exist_ok=True)
    with local_server(app) as origin:
        context=browser.new_context(locale='ko-KR',reduced_motion='reduce')
        external=[]
        def guard(route):
            if route.request.url.startswith(origin+'/') and route.request.method=='GET': route.continue_()
            else: external.append(route.request.url);route.abort()
        context.route('**/*',guard)
        page=context.new_page()
        for width,height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            for label,path in [('library','/videos'),('queue','/queue')]:
                page.goto(origin+path,wait_until='networkidle')
                expect(page.locator('.gentle-empty').first).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+2')
                page.screenshot(path=str(OUT/f'empty-{label}-{width}.png'),animations='disabled')
            page.locator('.gentle-empty a[href="/videos"]').click()
            expect(page.locator('.library-empty .button')).to_be_visible()
            page.locator('.library-empty .button').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#quick-production')).to_be_visible()
        context.close()
        assert not external
