"""New estimate labels and approval flow, synthetic HTTP/Fake key only."""
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_top_three_selection import feeds
from test_feed_budget import budget_setup
from bat_distribution.operation import OperatingRequests


def test_app_budget_review_in_react(app,budget_setup,browser):
    b=budget_setup;s=b.service
    assert b.post('cost-review',{'revision':s.get(b.id).result['revision']}).status_code==200
    with local_server(OperatingRequests(app)) as origin:
        c=browser.new_context(viewport={'width':1366,'height':768})
        c.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        p=c.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
        p.goto(origin+f'/studio/images?mode=news&batch_id={b.id}')
        expect(p.locator('.core-feed-cost')).to_have_count(0)
        p.get_by_role('button',name='이미지 생성',exact=True).click()
        expect(p.get_by_role('dialog',name='이미지 생성 비용 확인')).to_be_visible()
        box=p.locator('.core-feed-cost')
        expect(box).to_contain_text('실제 청구액은 다를 수 있습니다')
        expect(box).to_contain_text('여유분 2배 포함')
        box.get_by_label('TOP 3 작업 사용 한도').fill('1')
        box.get_by_role('button',name='예산 적용',exact=True).click()
        expect(box).to_contain_text('예산 적용됨')
        expect(p.get_by_role('button',name='TOP 3 전체 생성 · 비용 승인',exact=True)).to_be_enabled()
        for width,height in [(1366,768),(1920,1080)]:
            p.set_viewport_size({'width':width,'height':height})
            assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not b.calls and not errors
        c.close()
