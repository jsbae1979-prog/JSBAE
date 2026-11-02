"""Synthetic browser checks; all external traffic is blocked."""
import json
from urllib.parse import parse_qs
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_analysis_voice_features import context
from test_workspace_cleanup import articles


@pytest.mark.parametrize('provider,result', [('claude_api','ok'),('openai','denied'),('claude_api','network')])
def test_inline_check_never_submits_paid_analysis(app,browser,provider,result,tmp_path):
    articles(app)
    with local_server(app) as origin:
        ctx=context(browser,origin);page=ctx.new_page();posts=[];errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append((r.url,parse_qs(r.post_data or ''))) if r.method=='POST' else None)
        def module(route):
            data=route.fetch().json()
            data['formDefaults']['intelligence_analyze'].update(provider=provider,model='synthetic-model')
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route(origin+'/api/studio/modules/news',module)
        target='claude' if provider=='claude_api' else 'openai'
        def check(route):
            if result=='network':return route.abort()
            route.fulfill(status=200,content_type='application/json',body=json.dumps({'verified':result=='ok','message':'PRIVATE_NOT_FOR_DISPLAY'}))
        page.route(origin+'/api/studio/providers/'+target+'/check',check)
        page.goto(origin+'/studio/news')
        page.get_by_role('region',name='뉴스 분석 설정',exact=True).get_by_role('button',name='기사 분석 · 승인',exact=True).click()
        dialog=page.get_by_role('dialog',name='기사 분석',exact=True)
        expect(dialog.get_by_role('button',name='API 연결 다시 확인')).to_be_visible()
        assert posts==[]
        dialog.get_by_role('button',name='API 연결 다시 확인').click()
        expected={'ok':'연결을 확인했습니다.','denied':'연결을 확인하지 못했습니다.','network':'연결 응답을 받지 못했습니다.'}[result]
        expect(dialog.get_by_label('분석 API 연결 확인')).to_contain_text(expected)
        expect(dialog.get_by_role('button',name='기사 분석',exact=True)).to_be_disabled()
        expect(dialog.get_by_role('button',name='API 연결 다시 확인')).to_be_enabled()
        expect(dialog).not_to_contain_text('PRIVATE_NOT_FOR_DISPLAY')
        assert len(posts)==1 and posts[0][0].endswith('/'+target+'/check')
        assert posts[0][1]['scope']==['text'] and posts[0][1]['consent']==['true']
        assert posts[0][1]['csrf_token']
        page.screenshot(path=str(tmp_path/f'analysis-check-{result}.png'))
        assert not errors
        ctx.close()
