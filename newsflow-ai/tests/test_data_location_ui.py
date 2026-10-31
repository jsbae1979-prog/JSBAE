from starlette.testclient import TestClient
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from bat_distribution.operation import OperatingRequests
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from playwright.sync_api import expect

def test_authenticated_request_preserves_csrf_origin_and_no_generation(app):
    calls=[];app.state.data_location_request=lambda p:(calls.append(p) or {'state':'pending','destination':p})
    launch=LaunchSession(18779);auth=LocalAccess(app,launch)
    with TestClient(OperatingRequests(auth),base_url=launch.origin,client=('127.0.0.1',10010)) as client:
        assert client.post('/__local/claim',headers={'Origin':launch.origin,'X-NewsFlow-Bootstrap':launch.launch_url().split('#')[1]}).status_code==204
        client.get('/api/studio/modules/settings');csrf=client.cookies['newsflow_csrf']
        assert client.post('/api/studio/data-location',data={'destination':'D:/Synthetic','csrf_token':csrf},headers={'Origin':'http://example.invalid'}).status_code==403
        assert client.post('/api/studio/data-location',data={'destination':'D:/Synthetic'},headers={'Origin':launch.origin}).status_code==403
        assert calls==[]
        response=client.post('/api/studio/data-location',data={'destination':'D:/Synthetic','csrf_token':csrf},headers={'Origin':launch.origin})
        assert response.status_code==200 and calls==['D:/Synthetic']


def test_data_location_setting_requests_move_without_automatic_restart(app,browser):
    calls=[]
    app.state.data_location_request=lambda p:(calls.append(p) or {'state':'pending','destination':p,'message':'이동 예약 완료. 다음 Start에서 이동합니다.'})
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':900})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/settings')
        page.get_by_role('tab',name='시스템 관리',exact=True).click()
        page.get_by_label('새 사용자 데이터 저장 경로',exact=True).fill('D:/SyntheticData')
        page.get_by_role('button',name='저장 위치 변경 예약',exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('이동 예약 완료')
        assert calls==['D:/SyntheticData'] and len(posts)==1 and posts[0].endswith('/api/studio/data-location')
        assert not (app.state.config.data_dir/'data-location-request.private.json').exists()
        context.close()
