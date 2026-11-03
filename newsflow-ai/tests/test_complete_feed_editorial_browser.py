from pathlib import Path
import pytest
from copy import deepcopy
from playwright.sync_api import expect
from newsflow.creation.catalog import DEFAULTS
from newsflow.creation.complete_feed import STYLE
from newsflow.creation.feed_designs import FeedDesigns
from test_top_three_selection import feeds
from test_photo_feed_editor import photo
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server


@pytest.fixture(autouse=True)
def editorial_dist(monkeypatch):
    dist=Path(__file__).resolve().parents[1]/'frontend/dist'
    # The runner may supply the separately built clean frontend, without unrelated local changes.
    import os
    if os.environ.get('EDITORIAL_TEST_DIST'):dist=Path(os.environ['EDITORIAL_TEST_DIST'])
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:dist)


def test_complete_feed_local_photo_editor_uses_no_generation(app,feeds,browser,tmp_path):
    batch=feeds.create(42,DEFAULTS['image'],feed_style=STYLE)
    designs=FeedDesigns(feeds);state=designs.upload(batch,1,0,photo(),'photo','직접 만든 검증 사진')
    d={**state['draft'],'title':'새 관측 장비 공개 예정','description':'추가 검토 진행 중'}
    designs.save(batch,1,state['revision'],state['background'],d)
    before=deepcopy(feeds.get(batch).result)
    with local_server(app) as origin:
        ctx=browser.new_context(viewport={'width':1440,'height':1000})
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        def module(route):
            data=route.fetch().json()
            data['collections']['selections']=[{'id':42,'status':'success','title':'합성 분석','ranking':[
                {'rank':n,'title':f'합성 뉴스 {n}','body':f'합성 요약 {n}','article_ids':[n]} for n in (1,2,3)]}]
            route.fulfill(json=data)
        ctx.route('**/api/studio/modules/images',module)
        p=ctx.new_page();errors=[];writes=[]
        p.on('pageerror',lambda e:errors.append(str(e)))
        p.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
        p.goto(origin+f'/studio/images?mode=top3&batch_id={batch}')
        p.get_by_role('button',name='사진 선택·직접 편집 · 무료',exact=True).click()
        expect(p.get_by_label('피드 제목',exact=True)).to_have_value(d['title'])
        p.get_by_label('핵심 설명',exact=True).fill('발표된 계획을 검토합니다')
        expect(p.get_by_role('status').filter(has_text='미리보기 반영됨')).to_be_visible()
        p.get_by_role('button',name='새 버전으로 저장',exact=True).click()
        expect(p.get_by_role('status').filter(has_text='새 버전 저장 완료')).to_be_visible()
        p.screenshot(path=str(tmp_path/'editorial-photo-editor.png'),full_page=True)
        p.get_by_role('button',name='TOP 2',exact=True).click()
        expect(p.get_by_label('피드 제목',exact=True)).to_have_value('합성 뉴스 2')
        p.get_by_role('button',name='TOP 1',exact=True).click()
        expect(p.get_by_label('핵심 설명',exact=True)).to_have_value('발표된 계획을 검토합니다')
        p.get_by_role('button',name='AI 완성 이미지로 돌아가기',exact=True).click()
        expect(p.get_by_role('button',name='사진 선택·직접 편집 · 무료',exact=True)).to_be_visible()
        assert not errors
        assert writes and all(url.endswith('/design') for url in writes),writes
        ctx.close()
    assert feeds.get(batch).result==before
    assert designs.view(batch,2)['versions']==designs.view(batch,3)['versions']==[]
