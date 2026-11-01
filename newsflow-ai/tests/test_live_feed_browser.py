from copy import deepcopy
from hashlib import sha256
import json
from urllib.parse import parse_qs
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_photo_feed_editor import feeds, prepared, photo


def test_live_preview_latest_edit_no_autosave_and_exact_saved_pixels(app, feeds, browser, tmp_path):
    service, batch, state, design = prepared(feeds)
    saved = service.save(batch, 1, state['revision'], state['background'], design, export=True)
    before = deepcopy(service.state(batch, 1))
    before_batch = deepcopy(feeds.get(batch).result)
    original = service.path(saved['versions'][0]['filename'], saved['versions'][0]['sha256']).read_bytes()
    feeds.generation._generate = lambda *a, **k: (_ for _ in ()).throw(AssertionError('Paid call forbidden'))
    with local_server(app) as origin:
        context = browser.new_context(viewport={'width':1920, 'height':1080})
        outside=[]
        def network(route):
            if route.request.url.startswith(origin+'/'): route.continue_()
            else: outside.append(route.request.url); route.abort()
        context.route('**/*', network)
        def module(route):
            data=route.fetch().json()
            data['collections']['selections']=[{'id':42,'status':'success','title':'합성 분석','ranking':[
                {'rank':n,'title':f'합성 뉴스 {n}','body':f'합성 요약 {n}','article_ids':[n]} for n in (1,2,3)]}]
            route.fulfill(json=data)
        context.route('**/api/studio/modules/images',module)
        page=context.new_page();errors=[];writes=[]
        page.on('pageerror',lambda e: errors.append(str(e)))
        page.on('request', lambda r: writes.append((r.url,parse_qs(r.post_data or '') if 'application/x-www-form-urlencoded' in r.headers.get('content-type','') else {})) if r.method=='POST' else None)
        # Hold the first completed preview response. It must never overwrite a newer edit.
        page.add_init_script('''(() => {
          const original = window.fetch; window.previewResponses = [];
          window.fetch = async (...args) => {
            const r = await original(...args);
            if (String(args[0]).endsWith('/design') && args[1]?.body?.get?.('action') === 'preview') {
              const data = await r.clone().json();
              window.previewResponses.push(data);
              if (window.previewResponses.length === 1) await new Promise(resolve => setTimeout(resolve, 1100));
            }
            return r;
          };
        })();''')
        page.goto(origin+'/studio/images?mode=top3')
        expect(page.get_by_label('피드 제목',exact=True)).to_have_value(design['title'])
        expect(page.get_by_role('button',name='새 버전으로 저장',exact=True)).to_be_visible()
        expect(page.get_by_label('배경 이미지',exact=True)).not_to_be_visible()
        expect(page.get_by_role('button',name='미리보기 적용 · 무료',exact=True)).to_have_count(0)
        for width,height in [(1920,1080),(1366,768)]:
            page.set_viewport_size({'width':width,'height':height})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(tmp_path/f'simple-feed-{width}.png'),full_page=True)
        page.get_by_text('배치·색상·자르기',exact=True).click()
        page.get_by_label('텍스트 세로 위치',exact=True).fill('0.59')
        page.wait_for_function('() => window.previewResponses.length === 1')
        page.get_by_label('텍스트 세로 위치',exact=True).fill('0.54')
        page.wait_for_function('() => window.previewResponses.length === 2')
        expect(page.get_by_role('status').filter(has_text='미리보기 반영됨')).to_be_visible()
        latest=page.evaluate('window.previewResponses[1].previewUrl')
        expect(page.locator('.photo-feed-canvas img')).to_have_attribute('src',latest)
        page.wait_for_timeout(1200)
        expect(page.locator('.photo-feed-canvas img')).to_have_attribute('src',latest)
        # Multiple rapid changes coalesce; color/crop/layout all affect the same local preview.
        page.get_by_label('강조 단어',exact=True).fill('공개')
        page.get_by_label('강조색',exact=True).fill('#ffcc44')
        page.get_by_label('자르기 왼쪽 (%)',exact=True).fill('10')
        page.get_by_label('그라데이션 강도',exact=True).fill('0.65')
        expect(page.get_by_role('status').filter(has_text='미리보기 반영됨')).to_be_visible()
        latest=page.locator('.photo-feed-canvas img').get_attribute('src')
        assert latest != page.evaluate('window.previewResponses[1].previewUrl')
        assert service.state(batch,1)==before
        assert feeds.get(batch).result==before_batch
        # Invalid edits keep the last good image and cannot silently produce a clipped saved version.
        page.get_by_label('피드 제목',exact=True).fill('아주 긴 제목 '*40)
        expect(page.get_by_role('alert')).to_contain_text('글자 수')
        expect(page.locator('.photo-feed-canvas img')).to_have_attribute('src',latest)
        expect(page.get_by_role('button',name='새 버전으로 저장',exact=True)).to_be_disabled()
        page.get_by_label('피드 제목',exact=True).fill('관측 장비 공개\n추가 검토 진행 중')
        expect(page.get_by_role('status').filter(has_text='미리보기 반영됨')).to_be_visible()
        # Switching background retains unsaved text/layout and refreshes the preview/credit.
        page.get_by_text('고급 편집',exact=True).click()
        page.get_by_text('다른 이미지 선택',exact=True).click()
        page.get_by_label('새 이미지 크레딧',exact=True).fill('두 번째 합성 이미지')
        page.get_by_label('로컬 이미지 업로드',exact=True).set_input_files({'name':'local.png','mimeType':'image/png','buffer':photo()})
        expect(page.get_by_role('status').filter(has_text='배경 이미지 변경 완료')).to_be_visible()
        expect(page.get_by_role('status').filter(has_text='미리보기 반영됨')).to_be_visible()
        expect(page.get_by_label('피드 제목',exact=True)).to_have_value('관측 장비 공개\n추가 검토 진행 중')
        expect(page.get_by_label('텍스트 세로 위치',exact=True)).to_have_value('0.54')
        expect(page.get_by_label('자르기 왼쪽 (%)',exact=True)).to_have_value('10')
        live_path=page.locator('.photo-feed-canvas img').get_attribute('src')
        preview_raw=page.request.get(origin+live_path).body()
        page.get_by_role('button',name='새 버전으로 저장',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='새 버전 저장 완료')).to_be_visible()
        saved2=service.state(batch,1);v=saved2['versions'][-1]
        assert v['version']==2
        assert service.path(v['filename'],v['sha256']).read_bytes()==preview_raw
        assert service.path(saved2['versions'][0]['filename'],saved2['versions'][0]['sha256']).read_bytes()==original
        page.reload()
        expect(page.get_by_label('피드 제목',exact=True)).to_have_value('관측 장비 공개\n추가 검토 진행 중')
        page.get_by_label('저장된 편집 버전',exact=True).select_option('1')
        expect(page.get_by_text('저장하지 않은 편집이 있습니다.',exact=True)).to_have_count(0)
        expect(page.get_by_role('button',name='새 버전으로 저장',exact=True)).to_be_disabled()
        prior_writes=len(writes)
        page.wait_for_timeout(400)
        assert len(writes)==prior_writes  # Viewing a saved version does not render or save.
        page.get_by_label('피드 제목',exact=True).fill('다시 편집한 제목')
        expect(page.get_by_role('link',name='이 버전 이미지 저장',exact=True)).to_have_count(0)
        expect(page.get_by_role('status').filter(has_text='미리보기 반영됨')).to_be_visible()
        expect(page.get_by_role('button',name='새 버전으로 저장',exact=True)).to_be_enabled()
        page.get_by_label('저장된 편집 버전',exact=True).select_option('1')
        expect(page.locator('.photo-feed-canvas img')).to_have_attribute('src',f'/api/feed-batches/{batch}/items/1/design-file/1')
        page.get_by_role('button',name='TOP 2 결과 선택',exact=True).click()
        expect(page.get_by_label('피드 제목',exact=True)).to_have_value('합성 뉴스 2')
        assert service.state(batch,2)['revision']==0 and service.state(batch,3)['revision']==0
        assert not errors and not outside
        assert all(url.endswith(('/design','/design-upload')) for url,_ in writes),writes
        assert all(body.get('action',['preview'])[0] in ('preview','render') for _,body in writes)
        context.close()
