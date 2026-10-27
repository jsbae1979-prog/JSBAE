"""Actual bundled server, synthetic profile, reviewed Chrome/Node boundary."""
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def test_frozen_gui_assets_models_video_and_reuse():
    output=Path(os.environ['NEWSFLOW_VALIDATION_OUTPUT'])/'frozen-gui';output.mkdir(parents=True)
    origin='http://127.0.0.1:18765'
    pages=[];external=[];errors=[];bad_assets=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(locale='ko-KR',reduced_motion='reduce')
        def route_guard(route):
            if urlsplit(route.request.url).netloc!=urlsplit(origin).netloc:
                external.append(route.request.url);route.abort()
            else:route.continue_()
        context.route('**/*',route_guard)
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('response',lambda r:bad_assets.append(r.url) if '/static/' in r.url and r.status>=400 else None)
        for width in (1440,980,390):
            page.set_viewport_size({'width':width,'height':900})
            for name,path in [('home','/'),('news','/news'),('create','/create'),('script','/ai'),('video','/video?job_id=1'),('video-ai','/video/ai'),('image','/image-studio?draft_id=3'),('character','/character'),('publish','/publishing'),('settings','/settings')]:
                assert page.goto(origin+path,wait_until='networkidle').status==200
                expect(page.locator('h1').first).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'),(name,width)
                page.screenshot(path=str(output/f'{name}-{width}.png'),animations='disabled')
                pages.append({'page':name,'width':width,'status':'PASS'})
        page.set_viewport_size({'width':1440,'height':900})
        page.goto(origin+'/video?job_id=1',wait_until='networkidle')
        video=page.locator('video').first
        expect(video).to_be_visible()
        video.evaluate('(v)=>{v.muted=true;return v.play()}')
        deadline=time.monotonic()+10
        while video.evaluate('(v)=>v.currentTime')<=0.2:
            assert time.monotonic()<deadline,"Video playback did not advance"
            page.wait_for_timeout(50)
        assert video.evaluate('(v)=>[v.videoWidth,v.videoHeight]')==[1080,1920]
        video.evaluate('(v)=>v.pause()')
        page.screenshot(path=str(output/'video-playing.png'),animations='disabled')
        page.goto(origin+'/image-studio?draft_id=3',wait_until='networkidle')
        preview=page.get_by_alt_text('생성 결과 · 내용과 사용권 검토 필요')
        expect(preview).to_be_visible()
        assert preview.evaluate('(i)=>i.complete && i.naturalWidth===1024')
        page.locator('input[name=reviewed]').check()
        page.get_by_role('button',name='캐릭터 참조로 저장',exact=True).click()
        expect(page.get_by_alt_text('선택한 캐릭터 참조')).to_be_visible()
        assert page.locator('select[name=reference_asset]').input_value().startswith('studio-')
        page.screenshot(path=str(output/'image-reuse-character.png'),animations='disabled')
        assert not external and not errors and not bad_assets
        context.close();browser.close()
    (output/'result-safe.json').write_text(json.dumps({'pages':pages,'video_playback':True,'image_reuse':True,'external_page_requests':0,'javascript_errors':0,'static_failures':0,'real_API':False},indent=2))
