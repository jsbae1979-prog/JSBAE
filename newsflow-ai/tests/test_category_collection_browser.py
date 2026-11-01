from urllib.parse import parse_qs
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_collection_controls_browser import browser_context
from test_serpapi_news import setup_serpapi, register


def test_category_selection_counts_and_consent_browser(app,client,browser,setup_serpapi,tmp_path):
    register(client)
    with local_server(app) as origin:
        context=browser_context(browser,origin);page=context.new_page();posts=[];errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def submit(route):
            posts.append((route.request.url,parse_qs(route.request.post_data)))
            route.fulfill(status=303,headers={'Location':'/news'},body='')
        page.route(origin+'/news/curation/refresh',submit)
        page.route(origin+'/news/curation/serpapi',submit)
        page.goto(origin+'/studio/news')
        expect(page.get_by_role('combobox',name='기사 분야').locator('option').filter(has_text='연예')).to_have_count(1)
        box=page.get_by_role('region',name='뉴스 수집',exact=True)
        box.get_by_role('combobox',name='RSS 출처').select_option('popular')
        expect(box.get_by_role('checkbox')).to_have_count(0)
        expect(box.get_by_role('combobox',name='수집 범위')).to_have_count(0)
        assert not posts
        box.get_by_role('button',name='수집 시작',exact=True).click()
        dialog=page.get_by_role('dialog',name='공개 뉴스 갱신')
        expect(dialog.get_by_role('checkbox',name='전체 분야',exact=True)).to_be_checked()
        expect(dialog.get_by_role('checkbox',name='연예 분야',exact=True)).not_to_be_checked()
        dialog.get_by_role('checkbox',name='연예 분야',exact=True).check()
        dialog.get_by_role('checkbox',name='IT·과학 분야',exact=True).check()
        dialog.get_by_role('checkbox',name='공개 분야 RSS 수집 승인',exact=True).check()
        dialog.get_by_role('button',name='공개 뉴스 갱신',exact=True).click()
        expect(dialog).to_have_count(0)
        assert posts[0][1]['categories']==['연예','IT·과학'] and posts[0][1]['permission']==['true']
        page.reload()
        box.get_by_role('combobox',name='뉴스 수집 방식').select_option('serpapi')
        box.get_by_role('button',name='수집 시작',exact=True).click()
        dialog=page.get_by_role('dialog',name='Google News + Trends 수집')
        expect(dialog).to_contain_text('SerpApi 검색 최대 5회')
        expect(dialog.get_by_role('checkbox',name='전체 분야')).to_have_count(0)
        dialog.get_by_role('combobox',name='수집 범위',exact=True).select_option('korea_v1')
        expect(dialog).to_contain_text('SerpApi 검색 최대 1회')
        dialog.get_by_role('checkbox',name='경제 분야',exact=True).check()
        dialog.get_by_role('checkbox',name='SerpApi 수집 사용량 승인',exact=True).check()
        dialog.get_by_role('checkbox',name='연예 분야',exact=True).check()
        expect(dialog.get_by_role('checkbox',name='SerpApi 수집 사용량 승인')).not_to_be_checked()
        expect(dialog).to_contain_text('SerpApi 검색 최대 2회')
        for w,h in [(1366,768),(1920,1080)]:
            page.set_viewport_size({'width':w,'height':h})
            page.screenshot(path=str(tmp_path/f'category-dialog-{w}.png'))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        dialog.get_by_role('checkbox',name='SerpApi 수집 사용량 승인',exact=True).check()
        dialog.get_by_role('button',name='Google News + Trends 수집',exact=True).click()
        expect(dialog).to_have_count(0)
        assert posts[1][1]['maximum_requests']==['2'] and posts[1][1]['categories']==['경제','연예']
        assert len(posts)==2 and setup_serpapi[1].calls==0 and not errors
        context.close()


def test_failure_and_unrequested_are_not_presented_as_zero_articles(app,browser):
    import json
    with local_server(app) as origin:
        context=browser_context(browser,origin);page=context.new_page();posts=[]
        def module(route):
            data=route.fetch().json()
            data['catalog']['categoryCollection']=[
                {'category':'IT·과학','collected':98,'kept':98,'status':'success'},
                {'category':'문화','collected':0,'kept':0,'status':'failed'},
                {'category':'연예','collected':0,'kept':0,'status':'pending'},
                {'category':'스포츠','collected':0,'kept':0,'status':'unknown'},
                {'category':'경제','collected':0,'kept':0,'status':'success'}]
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route(origin+'/api/studio/modules/news',module)
        page.on('request',lambda r:posts.append(r) if r.method=='POST' else None)
        page.goto(origin+'/studio/news')
        results=page.get_by_role('list',name='최근 분야별 수집 결과')
        expect(results).to_contain_text('IT·과학 · 수집 98건 · 기간 내 98건')
        expect(results).to_contain_text('문화 · 수집 실패 · 기사 수 미확인')
        expect(results).to_contain_text('연예 · 요청하지 않음 · 앞선 분야 수집 중단')
        expect(results).to_contain_text('스포츠 · 응답 확인 필요 · 기사 수 미확인')
        expect(results).to_contain_text('경제 · 수집 0건 · 기간 내 0건')
        assert not posts
        context.close()
