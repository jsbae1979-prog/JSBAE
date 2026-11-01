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
        p.goto(origin+'/studio/images?mode=news')
        box=p.locator('.core-feed-cost');box.locator('summary').click()
        expect(box).to_contain_text('최종 청구 상한을 보장하지 않습니다')
        expect(box).to_contain_text('여유분 2배 포함')
        box.get_by_label('TOP 3 작업 사용 한도').fill('1')
        box.get_by_role('button',name='예상 비용·앱 작업 예산 승인',exact=True).click()
        expect(box).to_contain_text('비용 승인 저장됨')
        expect(p.get_by_role('button',name='TOP 3 전체 생성 · 비용 승인',exact=True)).to_be_enabled()
        for width,height in [(1366,768),(1920,1080)]:
            p.set_viewport_size({'width':width,'height':height})
            assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not b.calls and not errors
        c.close()
