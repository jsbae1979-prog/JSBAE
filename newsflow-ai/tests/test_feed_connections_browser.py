import os
from pathlib import Path
import pytest
from copy import deepcopy
from io import BytesIO
from PIL import Image
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_feed_library_edit_connections import feeds,completed
from bat_distribution.operation import OperatingRequests

def context(browser,origin):
    c=browser.new_context(viewport={'width':1366,'height':768})
    c.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
    def module(route):
        data=route.fetch().json();data['collections']['selections']=[{'id':42,'status':'success','title':'합성 분석','ranking':[
            {'rank':n,'title':f'합성 뉴스 {n}','body':f'합성 요약 {n}','article_ids':[n]} for n in (1,2,3)]}]
        route.fulfill(json=data)
    c.route('**/api/studio/modules/images',module)
    return c

def test_distinct_background_changes_immediately_without_save_and_keeps_rank(app,feeds,browser,tmp_path):
    s,b,state,d=completed(feeds)
    first=s.save(b,1,state['revision'],state['background'],d,export=True)
    raw=BytesIO();Image.new('RGB',(1080,1350),'#7c2121').save(raw,'PNG')
    uploaded=s.upload(b,1,first['revision'],raw.getvalue(),'photo','새 사진 크레딧')
    second=s.save(b,1,uploaded['revision'],uploaded['background'],{**d,'credit':'새 사진 크레딧'},export=True)
    before=deepcopy(s.state(b,1));batch_before=deepcopy(feeds.get(b).result)
    with local_server(app) as origin:
        ctx=context(browser,origin);p=ctx.new_page();errors=[];posts=[]
        p.on('pageerror',lambda e:errors.append(str(e)))
        p.on('request',lambda r:posts.append(r) if r.method=='POST' else None)
        p.goto(origin+f'/studio/images?mode=top3&batch_id={b}&rank=1')
        expect(p.locator('.photo-feed-canvas img')).to_be_visible()
        p.get_by_text('추가 편집',exact=True).click()
        selector=p.get_by_label('배경 이미지',exact=True)
        expect(selector).to_be_visible()
        # The candidate for the old background may be the original upload (aliases preserved).
        candidate=next(x for x in s.view(b,1)['candidates'] if 'version:1' in x['aliases'])
        p.get_by_label('피드 제목',exact=True).fill('편집한 제목 보존')
        selector.select_option(candidate['id'])
        expect(p.get_by_role('status').filter(has_text='미리보기 반영됨')).to_be_visible()
        one=p.locator('.photo-feed-canvas img').get_attribute('src')
        selector.select_option('version:2')
        expect(p.get_by_role('status').filter(has_text='미리보기 반영됨')).to_be_visible()
        two=p.locator('.photo-feed-canvas img').get_attribute('src')
        assert one!=two and p.request.get(origin+one).body()!=p.request.get(origin+two).body()
        expect(p.get_by_label('피드 제목',exact=True)).to_have_value('편집한 제목 보존')
        p.get_by_text('출처 정보',exact=True).click()
        expect(p.get_by_label('이미지 출처',exact=True)).to_have_value('새 사진 크레딧')
        assert s.state(b,1)==before and feeds.get(b).result==batch_before
        p.get_by_label('저장된 편집 버전',exact=True).select_option('1')
        assert selector.input_value()==candidate['id']
        assert not errors and posts and all(r.url.endswith('/design') and 'action=preview' in r.post_data for r in posts)
        p.screenshot(path=str(tmp_path/'background-immediate.png'),full_page=True)
        ctx.close()

def test_gallery_delete_and_library_restore_no_media_loss(app,feeds,browser,tmp_path):
    s,b,state,d=completed(feeds)
    before=deepcopy(feeds.get(b).result)
    with local_server(OperatingRequests(app)) as origin:
        ctx=context(browser,origin);p=ctx.new_page();errors=[];posts=[]
        p.on('pageerror',lambda e:errors.append(str(e)));p.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        p.goto(origin+'/studio/images?mode=top3')
        expect(p.locator('.feed-image-history-card')).to_have_count(3)
        # Selection overlays the image; no separate per-card selection/delete row.
        entry=p.locator('.feed-history-entry').nth(1)
        box=entry.locator('.feed-history-select').bounding_box()
        image=entry.locator('img').bounding_box()
        assert image['x']<=box['x'] and image['y']<=box['y']
        assert box['x']+box['width']<=image['x']+image['width']
        assert box['y']+box['height']<=image['y']+image['height']
        expect(p.locator('.feed-history-entry .feed-history-actions')).to_have_count(0)
        p.get_by_label(f'작업 {b} TOP 2 선택',exact=True).check()
        expect(p.locator('dialog.feed-image-preview')).not_to_be_visible()
        p.get_by_role('button',name='선택 삭제',exact=True).click()
        dialog=p.get_by_role('dialog',name='최근 생성 이미지 삭제')
        dialog.get_by_role('button',name='취소',exact=True).click()
        assert not any(x.endswith('/remove') for x in posts)
        p.get_by_label(f'작업 {b} TOP 2 선택',exact=True).uncheck()
        p.get_by_label(f'작업 {b} TOP 1 선택',exact=True).check()
        p.get_by_label(f'작업 {b} TOP 3 선택',exact=True).check()
        p.get_by_role('button',name='선택 삭제',exact=True).click()
        dialog.get_by_role('button',name='휴지통으로 이동',exact=True).click()
        expect(p.locator('.feed-image-history-card')).to_have_count(1)
        p.goto(origin+'/studio/library')
        expect(p.locator(f'[data-content-id="own-feed:{b}:2"] img')).to_be_visible()
        expect(p.locator(f'[data-content-id="own-feed:{b}:1"]')).to_have_count(0)
        p.get_by_text('라이브러리 휴지통 · 2개',exact=True).click()
        p.get_by_role('button',name='합성 뉴스 1 복원',exact=True).click()
        expect(p.locator(f'[data-content-id="own-feed:{b}:1"]')).to_be_visible()
        p.locator(f'[data-content-id="own-feed:{b}:2"]').click()
        p.locator('.mg-library-detail').get_by_role('link',name='제작실로 이동').click()
        expect(p).to_have_url(origin+f'/studio/images?mode=top3&batch_id={b}&rank=2')
        expect(p.get_by_label('피드 제목',exact=True)).to_have_value('합성 뉴스 2')
        expect(p.locator('.feed-image-history-card')).to_have_count(2)
        assert feeds.get(b).result==before and not errors
        assert all(x.endswith(('/design','/remove','/restore')) for x in posts)
        assert all(feeds.path(b,n).is_file() for n in (1,2,3))
        p.screenshot(path=str(tmp_path/'recent-image-delete.png'),full_page=True)
        ctx.close()


def test_gallery_acknowledged_delete_refresh_failure_is_not_unknown(app,feeds,browser):
    service,b,state,design=completed(feeds)
    original=deepcopy(feeds.get(b).result)
    with local_server(OperatingRequests(app)) as origin:
        ctx=context(browser,origin);p=ctx.new_page();posts=[]
        p.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        p.goto(origin+'/studio/images?mode=top3')
        expect(p.locator('.feed-image-history-card')).to_have_count(3)
        # Mutation succeeds, only the subsequent listing fails.
        ctx.route('**/api/feed-batches',lambda r:r.fulfill(status=503,json={'detail':'fixture refresh failure'}))
        p.get_by_label(f'작업 {b} TOP 1 선택',exact=True).check()
        p.get_by_role('button',name='선택 삭제',exact=True).click()
        p.get_by_role('dialog',name='최근 생성 이미지 삭제').get_by_role('button',name='휴지통으로 이동',exact=True).click()
        expect(p.get_by_role('status').filter(has_text='목록 새로고침만 실패했습니다')).to_be_visible()
        expect(p.locator('.feed-image-history-card')).to_have_count(2)
        expect(p.get_by_role('dialog',name='최근 생성 이미지 삭제')).not_to_be_visible()
        assert sum(x.endswith('/remove') for x in posts)==1
        assert feeds.get(b).result==original and all(feeds.path(b,n).is_file() for n in (1,2,3))
        ctx.close()


@pytest.fixture(autouse=True)
def gallery_dist(monkeypatch):
    root=Path(os.environ.get('EDITORIAL_TEST_DIST',Path(__file__).resolve().parents[1]/'frontend/dist'))
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:root)
