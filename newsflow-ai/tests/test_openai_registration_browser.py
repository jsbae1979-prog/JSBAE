"""Synthetic key entered only into isolated React; external requests blocked."""
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from newsflow.intelligence.credentials import FakeCipher,AIKeyStore
from bat_distribution.openai_key_registration import install
from bat_distribution.operation import OperatingRequests


def test_openai_key_visible_and_exact_provider_saved(app,browser):
    from dataclasses import replace
    from newsflow.distribution.windows_profile import private_directory
    root=private_directory(app.state.config.data_dir / "private-keys")
    app.state.config=replace(app.state.config,data_dir=root)
    cipher=FakeCipher();app.state.ai_keys=AIKeyStore(root,cipher=cipher)
    app.state.api_keys["openai"]=app.state.ai_keys
    owner=install(app,root,lambda:cipher)
    with local_server(owner.wrap(OperatingRequests(app),app)) as origin:
        c=browser.new_context(viewport={'width':1366,'height':768})
        c.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        p=c.new_page();posts=[];p.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        p.goto(origin+'/studio/settings?tab=models')
        p.get_by_role('button',name='이미지',exact=True).click()
        p.get_by_role('button',name='OpenAI 키 설정',exact=True).click()
        dialog=p.get_by_role('dialog',name='API 키 저장',exact=True)
        field=dialog.locator('input[type=password]')
        expect(field).to_be_visible()
        key='synthetic-openai-browser-key-0123456789'
        field.fill(key)
        dialog.get_by_role('button',name='API 키 저장',exact=True).click()
        expect(dialog).not_to_be_visible()
        assert posts==[origin+'/api-settings/openai/key']
        store=AIKeyStore(app.state.config.data_dir,cipher=cipher)
        assert store.key()==key
        assert key not in p.locator('body').inner_text()
        c.close()
