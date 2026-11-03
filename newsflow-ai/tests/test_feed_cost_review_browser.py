"""Visible control behavior against synthetic HTTP only."""
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_top_three_selection import feeds
from test_feed_costs import ready,approve
from bat_distribution.operation import OperatingRequests

def test_cost_status_and_expired_additional_quote(app,ready,browser,monkeypatch,tmp_path):
    s,i,calls=ready;approve(s,i)
    monkeypatch.setattr(s,'_accept',lambda row,item,out:item.update(status='failed',generation_id=out))
    s.step(i,consent=True,reviewed=True)
    with local_server(OperatingRequests(app)) as origin:
        c=browser.new_context(viewport={'width':1366,'height':768})
        c.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        p=c.new_page();posts=[];p.on('request',lambda r:posts.append(r) if r.method=='POST' else None)
        p.goto(origin+f'/studio/images?mode=news&batch_id={i}')
        expect(p.get_by_text('새 배경 생성 · 견적·비용 승인',exact=True)).to_be_visible()
        box=p.locator('.core-feed-cost');box.locator(':scope > summary').click()
        expect(box).to_contain_text('예산 적용됨')
        before=s.get(i);revision=before.result['revision']
        box.get_by_role('button',name='비용 상태 새로고침',exact=True).click()
        expect(box).to_contain_text('예산 적용됨')
        assert not posts and s.get(i).result['revision']==revision
        s.costs.clock=lambda:201
        box.get_by_role('button',name='비용 상태 새로고침',exact=True).click()
        expect(box.get_by_role('button',name='새 견적 준비',exact=True)).to_be_visible()
        expect(p.get_by_role('button',name='TOP 1 새 배경 추가 견적',exact=True)).to_be_enabled()
        p.get_by_role('button',name='TOP 1 새 배경 추가 견적',exact=True).click()
        dialog=p.get_by_role('dialog',name='TOP 3 생성 범위 승인',exact=True)
        expect(dialog).to_contain_text('무료이며 API를 호출하지 않습니다')
        expect(dialog.get_by_role('checkbox')).to_have_count(1)
        dialog.get_by_role('checkbox').check()
        # Closing the dialog starts the asynchronous request; it is not completion.
        with p.expect_response(lambda response:
                response.url == origin + f'/api/feed-batches/{i}/change'
                and response.request.method == 'POST') as completed:
            dialog.get_by_role('button',name='1회 재생성 준비',exact=True).click()
        assert completed.value.status == 200
        assert completed.value.finished() is None
        expect(dialog).not_to_be_visible()
        assert len(posts)==1 and len(calls)==1
        assert s.get(i).result['items'][0]['attempt']==2
        expect(p.get_by_role('button',name='TOP 3 전체 생성 · 비용 승인',exact=True)).to_be_disabled()
        for width,height in [(1366,768),(1920,1080)]:
            p.set_viewport_size({'width':width,'height':height})
            assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
        c.close()
