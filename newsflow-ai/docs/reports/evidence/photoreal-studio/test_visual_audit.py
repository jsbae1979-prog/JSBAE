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
    paths=[('home','/'),('news','/news'),('video',f'/video?draft_id={draft}'),('library','/videos')]
    external,posts,errors=[],[],[]
    downloads=[]
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
        page.on('response',lambda response: downloads.append(response.url) if '/static/images/' in response.url else None)
        for width,height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            for name,path in paths:
                image_start=len(downloads)
                response=page.goto(origin+path,wait_until='networkidle')
                assert response.status==200
                expect(page.locator('h1').first).to_be_attached()
                overflow=page.evaluate('document.documentElement.scrollWidth-innerWidth')
                audit.append({'screen':name,'viewport':f'{width}x{height}','overflow':overflow,'image_requests':downloads[image_start:]})
                assert overflow<=2,(name,width,overflow)
                if os.environ.get('UX_PHASE') == 'after':
                    if name == 'home':
                        assert not any('newsflow-earth-generated' in url for url in downloads[image_start:])
                        art=page.locator('.studio-hero-art')
                        expect(art.locator('figcaption')).to_contain_text('실제 보도 사진 아님')
                        assert art.locator('img').evaluate('(img)=>img.complete && img.naturalWidth>0')
                        assert art.locator('img').get_attribute('alt')==''
                        assert art.locator('a,button,input').count()==0
                        copy=page.locator('.studio-hero-copy').bounding_box()
                        caption=art.locator('figcaption').bounding_box()
                        assert caption['y']>=copy['y']+copy['height'] or caption['x']>=copy['x']+copy['width']
                        audit[-1]['image']=art.locator('img').evaluate('(img)=>({src:img.currentSrc,naturalWidth:img.naturalWidth})')
                    else:
                        expect(page.locator('img[src*="studio-concepts"]')).to_have_count(0)
                page.screenshot(path=str(OUT/f'{name}-{width}.png'),animations='disabled')
        context.close()
    assert not external and not posts and not errors
    assert before==(records(app),stored_values(app))
    assert media=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in app.state.video.outputs.glob('*') if p.is_file()}
    (OUT/'audit.json').write_text(json.dumps({'screens':audit,'external':external,'posts':posts,'errors':errors,'records_settings_media_preserved':True,'image_requests':downloads},ensure_ascii=False,indent=2))


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
            for label,path in [('library','/videos')]:
                page.goto(origin+path,wait_until='networkidle')
                expect(page.locator('.gentle-empty').first).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+2')
                if os.environ.get('UX_PHASE') == 'after':
                    art=page.locator('.library-concept-art')
                    art.scroll_into_view_if_needed()
                    expect(art.locator('figcaption')).to_contain_text('실제 보도 사진 아님')
                    expect(art.locator('img')).to_be_visible()
                    page.wait_for_function('document.querySelector(".library-concept-art img").naturalWidth > 0')
                    assert art.locator('img').get_attribute('loading')=='lazy'
                    assert page.locator('.library-empty video').count()==0
                    page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(OUT/f'empty-{label}-{width}.png'),animations='disabled')
                if width==390:
                    page.screenshot(path=str(OUT/f'empty-{label}-{width}-full.png'),animations='disabled',full_page=True)
            expect(page.locator('.library-empty .button')).to_be_visible()
            page.locator('.library-empty .button').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#quick-production')).to_be_visible()
        context.close()
        assert not external
