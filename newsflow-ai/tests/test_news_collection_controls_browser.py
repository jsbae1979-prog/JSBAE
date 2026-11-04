import json
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_serpapi_news import setup_serpapi

def browser_context(browser,origin):
    context=browser.new_context(viewport={'width':1366,'height':768})
    context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
    return context

def test_one_box_selects_rss_or_serpapi_without_sending_requests(app,browser):
    app.state.serpapi_registration_available=True
    with local_server(app) as origin:
        c=browser_context(browser,origin);p=c.new_page();posts=[]
        p.on('request',lambda r:posts.append(r) if r.method=='POST' else None)
        p.goto(origin+'/studio/news');box=p.get_by_role('region',name='뉴스 수집',exact=True)
        picker=box.get_by_role('combobox',name='뉴스 수집 방식',exact=True)
        expect(picker).to_have_value('rss')
        expect(box.get_by_role('button',name='수집 시작',exact=True)).to_be_visible()
        expect(box.get_by_role('button',name='SerpApi 키·수집 설정',exact=True)).to_have_count(0)
        expect(picker.locator('option')).to_have_text(['RSS 수집','SerpApi 수집'])
        source=box.get_by_role('combobox',name='RSS 출처',exact=True)
        analysis=p.get_by_role('region',name='뉴스 분석 설정',exact=True)
        expect(analysis).to_contain_text('등록 RSS')
        expect(source).to_have_value('rss')
        source.select_option('popular')
        expect(analysis).to_contain_text('분야별 뉴스 RSS')
        expect(analysis).not_to_contain_text('등록 RSS')
        expect(picker).to_have_value('rss')
        expect(source).to_have_value('popular')
        picker.select_option('serpapi')
        expect(analysis).to_contain_text('SerpApi')
        expect(source).to_have_count(0)
        expect(box.get_by_role('button',name='수집 시작',exact=True)).to_be_disabled()
        expect(box.get_by_role('link',name='설정·관리에서 수집 설정')).to_have_attribute('href','/studio/settings?tab=sources')
        expect(box.get_by_role('button',name='SerpApi 키·수집 설정',exact=True)).to_have_count(0)
        picker.select_option('rss')
        expect(source).to_have_value('popular')
        expect(analysis).to_contain_text('분야별 뉴스 RSS')
        source.select_option('rss')
        expect(analysis).to_contain_text('등록 RSS')
        for w,h in [(1366,768),(1920,1080)]:
            p.set_viewport_size({'width':w,'height':h});expect(picker).to_be_visible()
            assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not posts;c.close()

@pytest.mark.parametrize('end',['success','partial','failed'])
def test_collection_request_has_running_and_final_counts_without_resubmission(app,browser,end):
    with local_server(app) as origin:
        c=browser_context(browser,origin);p=c.new_page();state={'started':False,'finished':False,'posts':0,'reads':0}
        def status(route):
            state['reads']+=1
            data={'status':end if state['finished'] else 'running' if state['started'] else 'idle',
                  'run_id':900 if state['started'] else None,'added':3 if end!='failed' else 0,
                  'succeeded':0 if end=='failed' else 2,'failed':1 if end!='success' else 0}
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        def submit(route):
            state['posts']+=1;state['started']=True
            route.fulfill(status=303,headers={'Location':'/dashboard'},body='')
        p.route('**/api/collection',status);p.route(origin+'/collection',submit)
        p.goto(origin+'/studio/news');box=p.get_by_role('region',name='뉴스 수집',exact=True)
        box.get_by_role('button',name='수집 시작',exact=True).click()
        p.get_by_role('dialog',name='등록 RSS 수집',exact=True).get_by_role('button',name='등록 RSS 수집',exact=True).click()
        expect(box).to_contain_text('뉴스 수집 중…')
        expect(box.get_by_role('progressbar')).to_have_attribute('aria-label','뉴스 수집 진행 중')
        assert box.get_by_role('progressbar').get_attribute('value') is None
        expect(box.get_by_role('button',name='수집 시작',exact=True)).to_be_disabled()
        state['finished']=True
        expected={'success':'최근 수집 완료','partial':'일부 출처 수집 완료','failed':'수집 실패'}[end]
        expect(box).to_contain_text(expected)
        expect(box).to_contain_text('실패 '+('0' if end=='success' else '1')+'개')
        expect(box.get_by_role('progressbar')).to_have_count(0)
        assert state['posts']==1 and state['reads']>=2
        c.close()

def test_unknown_post_only_reads_status_and_never_replays(app,browser):
    with local_server(app) as origin:
        c=browser_context(browser,origin);p=c.new_page();posts=[];reads=[]
        p.route('**/api/collection',lambda r:(reads.append(True),r.fulfill(status=200,content_type='application/json',
            body=json.dumps({'status':'idle','run_id':None,'added':0,'succeeded':0,'failed':0}))))
        p.route(origin+'/collection',lambda r:(posts.append(True),r.abort('failed')))
        p.goto(origin+'/studio/news');box=p.get_by_role('region',name='뉴스 수집',exact=True)
        box.get_by_role('button',name='수집 시작',exact=True).click()
        d=p.get_by_role('dialog',name='등록 RSS 수집',exact=True)
        d.get_by_role('button',name='등록 RSS 수집',exact=True).click()
        expect(d.get_by_role('alert')).to_be_visible();d.get_by_role('button',name='취소',exact=True).click()
        expect(box).to_contain_text('수집 요청 결과 확인 필요')
        box.get_by_role('button',name='수집 상태 새로고침',exact=True).click()
        assert len(posts)==1 and len(reads)>=1
        c.close()


def test_serpapi_start_has_bounded_usage_confirmation_no_key_form(app,client,browser,setup_serpapi):
    from test_serpapi_news import register
    from urllib.parse import parse_qs
    register(client)
    with local_server(app) as origin:
        c=browser_context(browser,origin);p=c.new_page();posts=[]
        def submit(route):
            posts.append(parse_qs(route.request.post_data))
            route.fulfill(status=303,headers={'Location':'/news'},body='')
        p.route(origin+'/news/curation/serpapi',submit)
        p.goto(origin+'/studio/news');box=p.get_by_role('region',name='뉴스 수집',exact=True)
        box.get_by_role('combobox',name='뉴스 수집 방식',exact=True).select_option('serpapi')
        box.get_by_role('button',name='수집 시작',exact=True).click()
        d=p.get_by_role('dialog',name='Google News + Trends 수집',exact=True)
        expect(d).to_contain_text('SerpApi 검색 최대 5회')
        expect(d.get_by_role('textbox')).to_have_count(0)
        expect(d.get_by_role('checkbox')).to_have_count(1)
        expect(d.get_by_role('button',name='Google News + Trends 수집',exact=True)).to_be_disabled()
        d.get_by_role('checkbox',name='SerpApi 수집 사용량 승인').check()
        d.get_by_role('button',name='Google News + Trends 수집',exact=True).click()
        expect(d).to_have_count(0)
        assert len(posts)==1 and posts[0]['collection_policy']==['global_trends_v1']
        assert posts[0]['maximum_requests']==['5'] and posts[0]['consent']==['true']
        assert len(posts[0]['request_token'][0])==32 and 'api_key' not in posts[0]
        assert setup_serpapi[1].calls==0
        c.close()
