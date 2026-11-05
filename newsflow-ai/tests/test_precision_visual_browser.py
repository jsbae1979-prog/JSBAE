"""Real local Chromium UI with only Fake image requests and temporary data."""
from playwright.sync_api import expect
from test_character_precision import precision
from test_character_precision_browser import dist, browser, local_server, browser_context
from test_precision_visual import prepare, all_images, make

def test_first_set_review_then_remaining_images(precision,browser,monkeypatch,tmp_path):
    p=precision;w=prepare(p)
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:p.s)
    p.app.state.image_studio=p.images
    with local_server(p.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/characters?precision='+w['id'])
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        panel.get_by_role('button',name='배경 기준 장면 먼저 만들기',exact=True).click()
        dialog=page.get_by_role('dialog',name='장면 이미지 만들기',exact=True)
        expect(dialog).to_contain_text('장면 1 ·')
        assert not p.adapter.calls
        dialog.get_by_role('button',name='참조 이미지 전송·생성 승인').click()
        expect(panel.locator('.precision-progress')).to_contain_text('1/5장 완료',timeout=20000)
        assert len(p.adapter.calls)==1
        expect(panel.locator('.precision-next-action').get_by_text('첫 장면의 배경·소품을 확정하면 나머지 장면을 만들 수 있습니다.',exact=True)).to_be_visible()
        panel.get_by_role('button',name='확정하고 다음 장면',exact=True).click()
        expect(panel.get_by_role('button',name='나머지 장면 이미지 만들기',exact=True)).to_be_visible()
        assert len(p.adapter.calls)==1
        panel.get_by_role('button',name='나머지 장면 이미지 만들기',exact=True).click()
        expect(dialog).to_contain_text('장면 2, 3, 4, 5 ·')
        dialog.get_by_role('button',name='참조 이미지 전송·생성 승인').click()
        expect(panel.locator('.precision-progress')).to_contain_text('5/5장 완료',timeout=20000)
        expect(panel.get_by_role('button',name='영상 제작으로 이동')).to_have_count(0)
        assert len(p.adapter.calls)==5 and not p.video.sent and not errors
        page.screenshot(path=str(tmp_path/'set-reference-review.png'),full_page=True)
        ctx.close()

def test_changed_anchor_disables_video_handoff_and_stale_confirmation(precision,browser,monkeypatch):
    p=precision;w=all_images(p);w=make(p,w,[1],True)
    w=p.s.confirm(w['id'],w['revision'],1,2,True)
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:p.s)
    p.app.state.image_studio=p.images
    with local_server(p.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page()
        page.goto(origin+'/studio/characters?precision='+w['id'])
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        panel.get_by_role('button',name='장면 2 ·').click()
        expect(panel.get_by_role('button',name='이전 장면 이미지',exact=True)).to_be_disabled()
        expect(panel.get_by_role('button',name='영상 제작으로 이동')).to_have_count(0)
        expect(panel.locator('.precision-progress')).to_contain_text('1장 확정')
        assert len(p.adapter.calls)==6 and not p.video.sent
        ctx.close()


def test_legacy_image_review_can_create_set_reference_draft_without_paid_call(precision,browser,monkeypatch):
    from copy import deepcopy
    p=precision;w=prepare(p);w.pop('visual_reference_policy');p.s.save(w)
    w=make(p,w,[1,2,3,4,5]);original=deepcopy(w)
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:p.s)
    p.app.state.image_studio=p.images
    with local_server(p.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page()
        page.goto(origin+'/studio/characters?precision='+w['id'])
        page.get_by_role('button',name='연결 보완 초안 · 무료',exact=True).click()
        dialog=page.get_by_role('dialog',name='장면 내용 수정',exact=True)
        expect(dialog).to_be_visible()
        dialog.get_by_role('button',name='장면 저장 · 무료',exact=True).click()
        expect(dialog).to_have_count(0)
        expect(page.get_by_role('button',name='배경 기준 장면 먼저 만들기',exact=True)).to_be_visible()
        assert p.s.read(w['id'])==original and len(p.adapter.calls)==5 and not p.video.sent
        draft=p.s.read(page.url.split('precision=')[1])
        assert draft['source_work_id']==w['id'] and draft['visual_reference_policy']=='approved-set-reference-v1'
        assert all(not row['versions'] for row in draft['scenes'])
        page.get_by_role('button',name='배경 기준 장면 먼저 만들기',exact=True).click()
        expect(page.get_by_role('dialog',name='장면 이미지 만들기')).to_contain_text('장면 1 ·')
        assert len(p.adapter.calls)==5 and not p.video.sent
        ctx.close()


def test_edit_then_reuse_image_without_regeneration(precision,browser,monkeypatch):
    from copy import deepcopy
    p=precision;w=make(p,prepare(p),[1]);original=deepcopy(w['scenes'][0]['versions'][0])
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:p.s)
    p.app.state.image_studio=p.images
    with local_server(p.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/characters?precision='+w['id'])
        page.get_by_role('button',name='장면 내용 수정 · 무료',exact=True).click()
        dialog=page.get_by_role('dialog',name='장면 내용 수정',exact=True)
        # Use the visible description label from the established editor.
        dialog.get_by_label('장면 설명',exact=True).fill('기존 이미지에 맞춘 새로운 설명')
        dialog.get_by_role('button',name='장면 저장 · 무료').click()
        expect(dialog).to_have_count(0)
        expect(page.locator('.precision-selected img')).to_have_attribute('src','/image-studio/assets/'+original['asset'])
        page.once('dialog',lambda d:d.dismiss())
        page.get_by_role('button',name='이 이미지 그대로 사용 · 무료').click()
        assert len(p.s.read(w['id'])['scenes'][0]['versions'])==1
        page.once('dialog',lambda d:d.accept())
        page.get_by_role('button',name='이 이미지 그대로 사용 · 무료').click()
        expect(page.get_by_role('button',name='사용 중인 이미지')).to_be_disabled()
        saved=p.s.read(w['id']);assert saved['scenes'][0]['confirmed']['version']==2
        assert saved['scenes'][0]['versions'][0]==original
        assert len(p.adapter.calls)==1 and not p.video.sent and not errors
        ctx.close()
