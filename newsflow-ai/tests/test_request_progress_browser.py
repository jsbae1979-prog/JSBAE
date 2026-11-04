from pathlib import Path
import os
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_collection_controls_browser import browser_context

@pytest.fixture(autouse=True)
def dist(monkeypatch):
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))

@pytest.mark.parametrize('ending',['failed','success','disconnected'])
def test_analysis_visible_progress_no_replay(app,browser,tmp_path,ending):
    with local_server(app) as origin:
        c=browser_context(browser,origin);p=c.new_page();pending=[];reads=[];errors=[];state={'phase':'pending'}
        p.on('pageerror',lambda e:errors.append(str(e)))
        def module(route):
            data=route.fetch().json()
            data['catalog']['newsAnalysis']={'provider':'claude_api','model':'claude-sonnet-4-6','collectionReady':True,'collectionContextId':21,'candidateCount':60,'collectedCount':60}
            route.fulfill(json=data)
        def read(route):
            reads.append(route.request.url)
            if state['phase']=='disconnected':route.abort();return
            route.fulfill(json={'state':state['phase'],'elapsedSeconds':12,'runId':93,'detail':'AI 응답을 받았지만 결과 형식 검사를 통과하지 못했습니다.'})
        def submit(route):pending.append(route);state['phase']='running'
        p.route('**/api/studio/modules/news',module)
        p.route('**/api/curation/analysis-status?*',read)
        p.route(origin+'/news/curation/analyze',submit)
        p.goto(origin+'/studio/news')
        p.get_by_label('뉴스 분석 범위',exact=True).select_option('collection')
        p.get_by_role('button',name='TOP 3 분석 · 승인',exact=True).click()
        d=p.get_by_role('dialog',name='기사 분석',exact=True)
        button=d.get_by_role('button',name='기사 분석',exact=True)
        expect(button).to_be_disabled();assert not pending
        d.get_by_role('checkbox').check();button.click()
        panel=d.get_by_role('status',name='요청 진행 상태')
        expect(panel).to_contain_text('기사 분석 중')
        expect(panel).to_contain_text('마지막 상태 확인')
        expect(panel.get_by_role('progressbar')).not_to_have_attribute('value')
        expect(d.get_by_role('button',name='처리 중…',exact=True)).to_be_disabled()
        p.clock.install();p.clock.fast_forward(4000)
        assert len(pending)==1 and reads
        state['phase']=ending;p.clock.fast_forward(4000)
        expected={'failed':'분석 실패','success':'분석 완료','disconnected':'서버 상태 확인이 지연되고 있습니다'}[ending]
        expect(panel).to_contain_text(expected)
        if ending in {'success','failed'}:
            expect(d.locator('footer').get_by_role('button',name='닫기',exact=True)).to_be_enabled()
            if ending=='failed':expect(d.locator('footer button.primary')).to_have_count(0)
            else:expect(d.get_by_role('button',name=expected,exact=True)).to_be_disabled()
        p.screenshot(path=str(tmp_path/('request-'+ending+'.png')))
        assert len(pending)==1
        if ending=='success':pending[0].fulfill(status=303,headers={'Location':'/news'},body='');expect(d).not_to_be_visible()
        else:
            pending[0].fulfill(status=422,json={'detail':'저장된 실패 기록을 확인하세요.'})
            expect(d.get_by_role('alert')).to_contain_text('저장된 실패 기록')
            if ending=='failed':expect(d.locator('footer button.primary')).to_have_count(0)
            else:expect(d.get_by_role('button',name='기사 분석',exact=True)).to_be_disabled()
        assert len(pending)==1 and not errors
        p.unroute_all(behavior="wait")
        c.close()
