import os,json,re,time
import urllib.request
from PIL import Image
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect

def test_user_demo_modes_and_download():
    out=Path(os.environ['NEWSFLOW_VALIDATION_OUTPUT'])/'user-demo';out.mkdir(parents=True)
    origin='http://127.0.0.1:18765';external=[];errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);context=browser.new_context(locale='ko-KR',viewport={'width':1440,'height':960},accept_downloads=True)
        def guard(route):
            if urlsplit(route.request.url).netloc!=urlsplit(origin).netloc:external.append(route.request.url);route.abort()
            else:route.continue_()
        context.route('**/*',guard);page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        for name,path in [('news','/news'),('create','/create'),('image','/image-studio'),('character','/character'),('video','/video?job_id=1'),('settings','/settings')]:
            assert page.goto(origin+path,wait_until='networkidle').status==200
            expect(page.locator('h1').first).to_be_visible()
            page.screenshot(path=str(out/(name+'.png')),animations='disabled')
        page.goto(origin+'/image-studio')
        page.get_by_label('이미지 모델',exact=True).select_option('gpt-image-2.5-sunburst-2026-09-08')
        page.get_by_label('화면 비율·해상도',exact=True).select_option('1024x1024')
        page.get_by_label('품질',exact=True).select_option('low')
        page.get_by_role('button',name='다음 이미지 기본값 저장',exact=True).click()
        page.reload();expect(page.get_by_label('품질',exact=True)).to_have_value('low')
        page.get_by_label('이미지 지시문',exact=True).fill('합성 체험용 파란 도형. 실제 뉴스와 무관한 테스트입니다.')
        page.get_by_role('button',name='이미지 초안 저장',exact=True).click()
        expect(page.get_by_role('heading',name=re.compile('이미지 초안 #'))).to_be_visible()
        page.locator('input[name=reviewed]').check();page.locator('input[name=consent]').check()
        page.get_by_role('button',name='이미지 1회 생성',exact=True).click()
        preview=page.get_by_alt_text('생성 결과 · 내용과 사용권 검토 필요');expect(preview).to_be_visible()
        assert preview.evaluate('(i)=>i.complete && i.naturalWidth===1024')
        href=page.get_by_role('link',name='이미지 다운로드',exact=True).get_attribute('href')
        assert href.startswith('/image-studio/') and href.endswith('/file?download=true')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(origin+href,timeout=10) as response:
            assert response.status==200 and 'attachment' in response.headers.get('Content-Disposition','')
            content=response.read(8*1024*1024+1)
        assert len(content)<=8*1024*1024
        assert Image.open(BytesIO(content)).size==(1024,1024)
        (out/'fake-image.jpg').write_bytes(content)
        page.screenshot(path=str(out/'fake-image-result.png'))
        page.locator('input[name=reviewed]').check();page.get_by_role('button',name='캐릭터 참조로 저장',exact=True).click()
        expect(page.get_by_alt_text('선택한 캐릭터 참조')).to_be_visible()
        page.locator('select[name=script_model]').select_option('claude-opus-4-6')
        page.get_by_role('button',name='다음 캐릭터 기본값 저장',exact=True).click()
        page.reload();expect(page.locator('select[name=script_model]')).to_have_value('claude-opus-4-6')
        page.screenshot(path=str(out/'character-model-saved.png'))
        page.goto(origin+'/image-studio');expect(page.get_by_label('이미지 모델',exact=True)).to_have_value('gpt-image-2.5-sunburst-2026-09-08');expect(page.get_by_label('품질',exact=True)).to_have_value('low')
        page.goto(origin+'/video?job_id=1');video=page.locator('video').first;expect(video).to_be_visible()
        video.evaluate('(v)=>{v.muted=true;return v.play()}');deadline=time.monotonic()+10
        while video.evaluate('(v)=>v.currentTime')<.2:
            assert time.monotonic()<deadline;page.wait_for_timeout(50)
        assert video.evaluate('(v)=>[v.videoWidth,v.videoHeight]')==[1080,1920]
        video.evaluate('(v)=>v.pause()')
        assert not external and not errors
        context.close();browser.close()
    (out/'result-safe.json').write_text(json.dumps({'pages':6,'image_defaults_saved':True,'image_Fake_generation':True,'download_endpoint':True,'browser_download_not_verified':True,'reuse':True,'character_model_saved':True,'mode_defaults_independent':True,'news_video_playback':True,'external_page_requests':0,'JavaScript_errors':0,'paid_API':0},indent=2))
