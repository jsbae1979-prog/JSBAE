from pathlib import Path
import os
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_collection_controls_browser import browser_context
from test_character_precision import precision
from test_precision_causal import causal,submitted

@pytest.fixture(autouse=True)
def dist(monkeypatch):
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))

def test_review_screen_waits_and_explicit_click_releases_only_next(precision,browser,monkeypatch,tmp_path):
    p=causal(precision);jid=submitted(p);p.owner.check(jid,consent=True)
    p.app.state.character=p.owner;p.app.state.image_studio=p.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:p.s)
    with local_server(p.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/characters?job_id='+jid)
        button=page.get_by_role('button',name='장면 1 확인 · 다음 장면 만들기',exact=True)
        expect(button).to_be_enabled()
        assert len(p.video.sent)==1
        page.get_by_role('button',name='장면 1 재생',exact=True).click()
        preview=page.get_by_role('dialog',name='장면 1 · 5초')
        expect(preview.locator('video')).to_be_visible()
        preview.get_by_role('button',name='장면 1 · 5초 닫기',exact=True).click()
        assert len(p.video.sent)==1
        page.screenshot(path=str(tmp_path/'review-before-next.png'),full_page=True)
        button.click()
        expect(button).to_have_count(0)
        assert len(p.video.sent)==2 and not errors
        ctx.close()

def test_causal_editor_preserves_prop_fields(precision,browser,monkeypatch,tmp_path):
    p=causal(precision);w=p.s.edit(p.w['id'],1,p.story)
    p.app.state.character=p.owner;p.app.state.image_studio=p.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:p.s)
    with local_server(p.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page();page.goto(origin+'/studio/characters?precision='+w['id'])
        page.get_by_role('button',name='스토리 검토·수정',exact=True).click()
        dialog=page.get_by_role('dialog',name='장면 내용 수정')
        expect(dialog.get_by_label('이 행동을 하는 이유',exact=True)).to_have_value('Visible situation 0')
        dialog.get_by_text('소품의 변화',exact=True).click()
        expect(dialog.get_by_label('소품 이름',exact=True)).to_have_value('plate')
        page.screenshot(path=str(tmp_path/'causal-editor.png'),full_page=True)
        dialog.get_by_role('button',name='장면 저장 · 무료').click()
        expect(dialog).to_have_count(0)
        assert p.s.read(w['id'])['scenario']==w['scenario'] and not p.video.sent
        ctx.close()
