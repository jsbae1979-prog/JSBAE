from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_library_purge import ready
from test_provider_connection_tests import probe

def test_trash_multiple_selection_confirmation_cancel_then_purge_synthetic_only(app,browser):
    ids=ready(app)
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':900})
        context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page=context.new_page();posts=[];errors=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/library')
        trash=page.locator('.mg-library-trash').filter(has=page.get_by_text('라이브러리 휴지통 · 5개',exact=True))
        trash.locator('summary').click()
        trash.get_by_role('checkbox',name='합성 캐릭터 작업 완전 삭제 선택',exact=True).check()
        trash.get_by_role('checkbox',name='보관한 참조 파일 · owned-ref 완전 삭제 선택',exact=True).check()
        trash.get_by_role('button',name='선택 완전 삭제',exact=True).click()
        dialog=page.get_by_role('dialog',name='선택 콘텐츠 완전 삭제',exact=True)
        expect(dialog).to_contain_text('선택한 항목 2개')
        expect(dialog).to_contain_text('앱에서 복원할 수 없습니다')
        dialog.get_by_role('button',name='취소',exact=True).click()
        assert not posts
        trash.get_by_role('button',name='선택 완전 삭제',exact=True).click()
        dialog.get_by_role('button',name='완전 삭제',exact=True).click()
        expect(page.get_by_text('라이브러리 휴지통 · 3개',exact=True)).to_be_visible()
        expect(page.locator('.mg-library-trash').filter(has=page.get_by_text('라이브러리 휴지통 · 3개',exact=True)).get_by_role('checkbox')).to_have_count(3)
        assert len(posts)==1 and posts[0].endswith('/api/studio/library/purge') and not errors
        page.reload();expect(page.get_by_text('라이브러리 휴지통 · 3개',exact=True)).to_be_visible()
        context.close()

def test_provider_buttons_align_and_do_not_overlap_at_supported_sizes(probe,browser):
    with local_server(probe.app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page=context.new_page();page.goto(origin+'/studio/settings')
        page.get_by_role('tab',name='AI 모델 · API 키',exact=True).click()
        page.get_by_role('button',name='음성',exact=True).click()
        for w,h in [(1366,768),(1920,1080)]:
            page.set_viewport_size({'width':w,'height':h})
            boxes=page.locator('.mg-provider-actions > button').evaluate_all('(es)=>es.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})')
            assert len(boxes)==3 and all(b['h']>=35 for b in boxes)
            assert max(b['h'] for b in boxes)-min(b['h'] for b in boxes)<2
            for a,b in zip(boxes,boxes[1:]):assert b['y']>=a['y']+a['h']+7 or b['x']>=a['x']+a['w']+7
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not probe.calls
        context.close()
