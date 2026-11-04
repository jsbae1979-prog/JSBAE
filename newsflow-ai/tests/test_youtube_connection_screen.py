"""Read-only status and an offline, explicit YouTube connection UI."""
import os
from pathlib import Path
from urllib.parse import parse_qs
import pytest
from playwright.sync_api import expect
from test_youtube_gui import youtube_ui, forbid_external_calls
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_collection_controls_browser import browser_context

def test_status_is_local_allowlisted_and_no_store(client, youtube_ui):
    connection, uploads, _ = youtube_ui
    connection.channel.update(access_token='SYNTHETIC_SECRET', authorization_url='SYNTHETIC_STATE')
    r=client.get('/api/youtube/status')
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    assert r.json()['accounts'][0]['ready'] is True
    assert 'SYNTHETIC_' not in r.text
    assert connection.calls==[] and uploads.calls==[]

@pytest.fixture(autouse=True)
def built_dist(monkeypatch):
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))

@pytest.mark.parametrize('configured,pending,supported',[(False,False,True),(True,False,True),(True,True,True),(True,False,False)])
def test_channel_connection_form(app,browser,monkeypatch,tmp_path,configured,pending,supported):
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))
    with local_server(app) as origin:
        c=browser_context(browser,origin);p=c.new_page();posts=[];errors=[]
        p.on('pageerror',lambda e:errors.append(str(e)))
        channel={'id':7,'label':'합성 채널','status':'authorizing' if pending else 'connected','ready':not pending,'channel_id':'UC_test','message':'합성 상태'}
        state={'client_configured':configured,'storage_supported':supported,'pending':pending,'accounts':[channel]}
        p.route('**/api/youtube/status',lambda r:r.fulfill(json=state))
        def module(r):
            data=r.fetch().json();data['commandsAvailable']=True;r.fulfill(json=data)
        p.route('**/api/studio/modules/settings',module)
        def submit(r):
            posts.append((r.request.url,parse_qs(r.request.post_data)))
            r.fulfill(status=422,json={'detail':'SYNTHETIC_SECRET_MUST_NOT_APPEAR'})
        p.route(origin+'/youtube/**',submit)
        p.goto(origin+'/studio/settings?tab=accounts')
        p.get_by_role('button',name='youtube 계정 설정',exact=True).click()
        panel=p.locator('.youtube-connection')
        expect(panel.get_by_text('합성 채널',exact=True)).to_be_visible()
        assert not posts
        expect(panel.locator('input[type=password], textarea')).to_have_count(0)
        button=panel.get_by_role('button',name='Google로 채널 연결',exact=True)
        expect(button).to_be_disabled()
        if pending:
            expect(panel.get_by_role('button',name='Google 로그인 창 다시 열기')).to_be_visible()
            expect(panel.get_by_role('button',name='연결 취소',exact=True)).to_be_visible()
        else:
            panel.get_by_role('checkbox').check()
            if configured and supported:
                expect(button).to_be_enabled()
                panel.get_by_label('연결할 채널',exact=True).select_option('7')
                panel.get_by_role('button',name='Google로 다시 연결',exact=True).click()
                expect(panel.get_by_role('alert')).to_contain_text('처리를 완료하지 못했습니다')
                assert len(posts)==1 and posts[0][1]['account_id']==['7'] and posts[0][1]['consent']==['true']
                assert 'SYNTHETIC_SECRET' not in panel.inner_text()
            else:expect(button).to_be_disabled()
        if not configured and supported:
            upload=panel.locator('input[type=file]')
            upload.set_input_files({'name':'invalid.json','mimeType':'application/json','buffer':b'not-json'})
            panel.get_by_role('button',name='설정 파일 저장',exact=True).click()
            expect(panel.get_by_role('alert')).to_contain_text('데스크톱 앱 JSON')
            assert not posts
            raw=b'{"installed":{"client_id":"fake.apps.googleusercontent.com","client_secret":"SYNTHETIC_CLIENT"}}'
            upload.set_input_files({'name':'desktop.json','mimeType':'application/json','buffer':raw})
            panel.get_by_role('button',name='설정 파일 저장',exact=True).click()
            expect(panel.get_by_role('alert')).to_contain_text('처리를 완료하지 못했습니다')
            assert len(posts)==1 and posts[0][0].endswith('/youtube/client')
            assert posts[0][1]['client_json']==[raw.decode()] and posts[0][1]['csrf_token']
            assert 'SYNTHETIC_CLIENT' not in panel.inner_text()
        p.screenshot(path=str(tmp_path/'youtube-channel.png'))
        assert not errors
        p.unroute_all(behavior='wait');c.unroute_all(behavior='wait');c.close()


