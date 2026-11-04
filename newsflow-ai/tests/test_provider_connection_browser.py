"""Visible verification UI backed by Fake metadata only; no real keys or providers."""
from types import SimpleNamespace
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_provider_connection_tests import probe, terminal, KEY
from newsflow.intelligence.provider_connections import ProviderConnections


def test_all_provider_tabs_test_and_persist_without_generation(probe,browser):
    app=probe.app;terminal(probe)
    before=app.state.character.listing()
    stores={provider:SimpleNamespace(path=store.path,status=lambda:{'configured':True},key=lambda:KEY)
            for provider,store in probe.checker.stores.items()}
    app.state.provider_connections=ProviderConnections(app.state,stores,probe.checker.network)
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':900})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();posts=[];errors=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/settings')
        page.get_by_role('tab',name='AI 모델 · API 키',exact=True).click()
        for category,provider in [('텍스트','Claude'),('텍스트','OpenAI'),('이미지','OpenAI'),('영상','Higgsfield'),('음성','ElevenLabs')]:
            page.get_by_role('button',name=category,exact=True).click()
            row=page.locator('.mg-settings-models tbody tr').filter(has=page.get_by_role('button',name=provider+' 키 설정',exact=True))
            row.get_by_role('button',name='API 키 테스트',exact=True).click()
            expect(row.locator('.mg-badge')).to_have_text('인증 확인')
            expect(row.get_by_role('button',name='API 키 테스트',exact=True)).to_be_enabled()
            assert KEY not in page.locator('body').inner_text()
        page.reload()
        page.get_by_role('button',name='음성',exact=True).click()
        row=page.locator('.mg-settings-models tbody tr')
        expect(row.locator('td').nth(1)).to_contain_text('키 인증·모델 목록 확인')
        assert len(posts)==5 and all('/api/studio/providers/' in url and url.endswith('/check') for url in posts)
        assert len(probe.calls)==6 and not errors
        assert app.state.character.listing()==before
        context.close()


def test_home_refreshes_saved_auth_after_settings_without_another_provider_call(probe,browser):
    app=probe.app
    stores={provider:SimpleNamespace(path=store.path,status=lambda:{'configured':True},key=lambda:KEY)
            for provider,store in probe.checker.stores.items()}
    app.state.provider_connections=ProviderConnections(app.state,stores,probe.checker.network)
    with local_server(app) as origin:
        ctx=browser.new_context()
        ctx.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=ctx.new_page();posts=[]
        page.on('request',lambda req:posts.append(req.url) if req.method=='POST' else None)
        page.goto(origin+'/studio/dashboard')
        home=page.locator('.services')
        expect(home.get_by_role('button',name='Claude 키 저장 · 연결 미확인',exact=True)).to_be_visible()
        page.get_by_role('button',name='설정 · 관리',exact=True).click()
        page.get_by_role('tab',name='AI 모델 · API 키',exact=True).click()
        row=page.locator('.mg-settings-models tbody tr').filter(has=page.get_by_role('button',name='Claude 키 설정',exact=True))
        row.get_by_role('button',name='API 키 테스트',exact=True).click()
        expect(row.locator('.mg-badge')).to_have_text('인증 확인')
        page.get_by_role('button',name='홈',exact=True).click()
        expect(home.get_by_role('button',name='Claude 연결 확인됨',exact=True)).to_be_visible()
        assert len(posts)==1 and len(probe.calls)==1
        # Key invalidation is still reflected; refreshing never invents success.
        (app.state.config.data_dir/probe.kinds['claude'].FILE).write_bytes(b'changed synthetic cipher')
        page.get_by_role('button',name='설정 · 관리',exact=True).click()
        page.get_by_role('button',name='홈',exact=True).click()
        expect(home.get_by_role('button',name='Claude 연결 재확인 필요',exact=True)).to_be_visible()
        assert len(posts)==1 and len(probe.calls)==1
        ctx.close()
