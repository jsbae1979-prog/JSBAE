from pathlib import Path
import json,os
from urllib.parse import parse_qs
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_collection_controls_browser import browser_context

@pytest.fixture(autouse=True)
def dist(monkeypatch):
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))

@pytest.mark.parametrize('failed',[False,True])
def test_standalone_selection_trash_and_preview(app,browser,monkeypatch,failed):
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))
    with local_server(app) as origin:
        c=browser_context(browser,origin);p=c.new_page();posts=[];errors=[]
        p.on('pageerror',lambda e:errors.append(str(e)))
        rows=[{'id':i,'title':f'그림 {i}','status':'success','outputId':i+100,'mediaUrl':f'/image-studio/{i}/file','selection':{}} for i in (5,6)]
        def module(route):
            data=route.fetch().json();data['commandsAvailable']=True;data['collections']['drafts']=rows;route.fulfill(json=data)
        p.route('**/api/studio/modules/images',module)
        p.route(origin+'/image-studio/*/file',lambda r:r.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="blue"/></svg>'))
        def remove(route):
            ids=json.loads(parse_qs(route.request.post_data)['items'][0]);posts.append(ids)
            if failed:route.fulfill(status=409,json={'detail':'busy'});return
            rows[:]=[x for x in rows if f"image:{x['id']}" not in ids]
            route.fulfill(json={'removed':ids})
        p.route(origin+'/api/studio/library/remove',remove)
        p.goto(origin+'/studio/images?mode=ai');history=p.locator('.core-recent-panel')
        expect(history.get_by_role('checkbox')).to_have_count(2)
        history.get_by_role('button',name='전체 선택',exact=True).click()
        expect(history.get_by_label('작업 5 선택',exact=True)).to_be_checked()
        expect(history.get_by_label('작업 6 선택',exact=True)).to_be_checked()
        history.get_by_role('button',name='선택 해제',exact=True).click()
        expect(history.get_by_role('button',name='선택 삭제',exact=True)).to_be_disabled()
        history.get_by_label('작업 5 선택',exact=True).check()
        expect(p.get_by_role('dialog',name='AI 이미지 크게 보기')).to_have_count(0)
        history.locator('.feed-image-history-card').filter(has_text='작업 #6').click()
        preview=p.get_by_role('dialog',name='AI 이미지 크게 보기')
        expect(preview.get_by_role('img')).to_have_attribute('src','/image-studio/6/file')
        p.keyboard.press('Escape')
        history.get_by_role('button',name='선택 삭제',exact=True).click()
        dialog=p.get_by_role('dialog',name='최근 생성 이미지 삭제',exact=True)
        dialog.get_by_role('button',name='취소',exact=True).click();assert not posts
        history.get_by_role('button',name='선택 삭제',exact=True).click()
        dialog.get_by_role('button',name='휴지통으로 이동',exact=True).click()
        if failed:
            expect(dialog.get_by_role('status')).to_contain_text('삭제 결과를 확인하지 못했습니다')
            expect(history.get_by_label('작업 5 선택',exact=True)).to_be_checked()
            expect(history.get_by_role('checkbox')).to_have_count(2)
        else:
            expect(dialog).not_to_be_visible()
            expect(history.get_by_role('checkbox')).to_have_count(1)
            expect(history.get_by_label('작업 6 선택',exact=True)).not_to_be_checked()
            p.reload();expect(history.get_by_role('checkbox')).to_have_count(1)
        assert posts==[['image:5']] and not errors
        if not failed:p.screenshot(path=str(Path(os.environ['EDITORIAL_TEST_DIST']).parents[1]/'gallery-verified.png'))
        p.unroute_all(behavior='wait');c.unroute_all(behavior='wait');c.close()
