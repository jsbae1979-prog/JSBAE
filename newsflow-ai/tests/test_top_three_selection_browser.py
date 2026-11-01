from urllib.parse import parse_qs
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_top_three_selection import feeds
from bat_distribution.operation import OperatingRequests

def test_selected_news_rank_and_plain_error_in_browser(app,feeds,browser,tmp_path):
    with local_server(OperatingRequests(app)) as origin:
        ctx=browser.new_context(viewport={'width':1366,'height':768})
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        def module(route):
            response=route.fetch();data=response.json()
            data['collections']['selections']=[{'id':42,'status':'success','title':'합성 TOP3 분석','ranking':[
                {'rank':n,'title':f'합성 뉴스 {n}','body':f'합성 요약 {n}','article_ids':[]} for n in (1,2,3)]}]
            route.fulfill(json=data)
        ctx.route('**/api/studio/modules/images',module)
        page=ctx.new_page();requests=[]
        page.on('request',lambda r:requests.append(r) if r.method=='POST' else None)
        page.goto(origin+'/studio/images?mode=news')
        scope=page.get_by_role('combobox',name='제작 범위',exact=True)
        expect(scope).to_have_value('all');scope.select_option('selected')
        page.locator('.core-top3-news-list button').filter(has_text='합성 뉴스 3').click()
        page.get_by_role('button',name='선택 뉴스 제작 준비',exact=True).click()
        expect(page.locator('.core-feed-results article')).to_have_count(1)
        expect(page.locator('.core-copy-output')).to_contain_text('TOP 3')
        assert parse_qs(requests[0].post_data)['rank']==['3']
        expect(page.get_by_role('button',name='선택 뉴스 생성 · 비용 승인',exact=True)).to_be_disabled()
        page.reload();expect(page.locator('.core-copy-output')).to_contain_text('TOP 3')
        for w,h in [(1366,768),(1920,1080)]:
            page.set_viewport_size({'width':w,'height':h})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(tmp_path/f'news-image-selection-{w}.png'),full_page=True)
        page.route(origin+'/api/feed-batches',lambda r:r.fulfill(status=403,body='Restored profile boundary denied') if r.request.method=='POST' else r.continue_())
        page.get_by_role('button',name='선택 뉴스 제작 준비',exact=True).click()
        expect(page.locator('.core-notice')).to_contain_text('현재 실행 모드')
        expect(page.locator('.core-notice')).not_to_contain_text('Unexpected token')
        assert len(requests)==2
        ctx.close()
