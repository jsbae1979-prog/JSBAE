"""Minimal token entry and truthful automatic checks; synthetic credentials only."""
import json

import pytest
from pydantic import SecretStr
from playwright.sync_api import expect
from test_meta_direct import env, DiscoveryGraph
from test_meta_browser import connected, context
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from newsflow.meta.contracts import MetaError
from newsflow.meta.direct import discover
from newsflow.meta.graph import MetaGraph
from newsflow.meta.service import DEFAULTS

pytestmark = pytest.mark.usefixtures('synthetic_app_isolation')

@pytest.mark.parametrize('change,code', [
    ({'is_valid': False}, 'authentication'),
    ({'type': 'PAGE'}, 'token_type'),
    ({'app_id': '999'}, 'token_app'),
    ({'expires_at': 1}, 'token_expired'),
    ({'data_access_expires_at': 1}, 'data_expired'),
    ({'data_access_expires_at': 0}, 'token_metadata'),
    ({'scopes': []}, 'permission'),
])
def test_automatic_checks_report_specific_cause_without_manual_expiry(change, code):
    graph = DiscoveryGraph()
    graph.invalid = change
    with pytest.raises(MetaError) as error:
        discover(SecretStr('synthetic-user'), DEFAULTS, graph=graph)
    assert error.value.code == code
    assert len(graph.calls) <= 2
    assert not any(path == 'me/accounts' for _, path, _ in graph.calls)

@pytest.mark.parametrize('status,body', [
    (401, {}),
    (400, {'error': {'code': 190, 'error_subcode': 463, 'message': 'synthetic-secret'}}),
    (400, {'error': {'code': 190, 'error_subcode': 467, 'message': 'synthetic-secret'}}),
])
def test_provider_auth_error_is_not_claimed_as_expiry(status, body):
    calls = []
    def transport(*args):
        calls.append(1)
        return status, json.dumps(body).encode()
    with pytest.raises(MetaError) as error:
        discover(SecretStr('synthetic-user'), DEFAULTS, graph=MetaGraph(transport=transport))
    assert error.value.code == 'authentication'
    assert error.value.diagnostics['stage'] == 'user_token'
    assert error.value.diagnostics['http_status'] == status
    assert 'synthetic-secret' not in str(error.value)
    assert calls == [1]

@pytest.mark.parametrize('stage,path', [('permissions','me/permissions'), ('pages','me/accounts'), ('instagram','201')])
def test_lookup_failure_keeps_only_safe_stage_and_numbers(stage, path):
    class Broken(DiscoveryGraph):
        def call(self, method, target, token, values):
            if target == path:
                self.calls.append((method, target, {}))
                raise MetaError('permission', diagnostics={
                    'provider_code': 200, 'stage': 'synthetic-secret',
                    'message': 'synthetic-secret', 'token': 'synthetic-user'})
            return super().call(method, target, token, values)
    graph = Broken()
    with pytest.raises(MetaError) as error:
        discover(SecretStr('synthetic-user'), DEFAULTS, graph=graph)
    assert error.value.diagnostics == {'provider_code': 200, 'stage': stage}
    assert sum(target == path for _,target,_ in graph.calls) == 1


def test_failed_import_returns_safe_diagnostics_and_preserves_saved_connections(app, client, env):
    before = dict(env.a.vault.values)
    prior = env.a.accounts()
    def fail(*args):
        raise MetaError('authentication', diagnostics={'stage':'page_token', 'http_status':401,
            'provider_code':190, 'provider_subcode':467, 'message':'synthetic-private',
            'url':'https://example.invalid/?token=synthetic-private'})
    env.a.direct_factory = fail
    app.state.meta_connections = env.a
    from test_meta_accounts import publisher
    app.state.meta_publishing = publisher(env)[0]
    client.get('/api/meta/status')
    response = client.post('/api/meta/import-token',data={
        'token':'synthetic-user','consent':'true','csrf_token':client.cookies.get('newsflow_csrf')})
    assert response.status_code == 422
    detail = response.json()['detail']
    assert detail['code'] == 'authentication'
    assert detail['diagnostics'] == {'stage':'page_token','http_status':401,'provider_code':190,'provider_subcode':467}
    assert 'synthetic-' not in response.text and 'example.invalid' not in response.text
    assert env.a.vault.values == before and env.a.accounts() == prior
    assert env.a.pending is None and env.a.direct_pending is None


def test_authentication_rejection_disables_only_affected_account(env):
    env.a.invalidate(env.ids[0], 'authentication')
    states = {row['id']: row['state'] for row in env.a.accounts()}
    assert states[env.ids[0]] == 'authentication'
    assert states[env.ids[1]] == 'connected'
    with pytest.raises(MetaError):
        env.a.credential(env.ids[0], 'facebook')


def test_token_only_screen_reports_stage_clears_secret_and_never_retries(app,browser,connected):
    accounts,publisher,_ = connected
    calls=[]
    def fail(*args):
        calls.append(1)
        raise MetaError('authentication', diagnostics={'stage':'user_token','provider_code':190})
    accounts.direct_factory=fail
    with local_server(app) as origin:
        ctx=context(browser,origin);page=ctx.new_page()
        page.goto(origin+'/studio/settings?tab=accounts')
        panel=page.locator('section').filter(has=page.get_by_role('heading',name='Facebook · Instagram 연결',exact=True)).last
        expect(panel.get_by_text('Synthetic 101',exact=True)).to_be_visible()
        expect(panel.get_by_text('계정·권한·만료일은 자동으로 확인합니다.',exact=False)).to_be_visible()
        # The only initially visible entry is the user's token, not manual dates/IDs/secrets.
        expect(panel.locator('input:visible')).to_have_count(1)
        token=panel.get_by_label('본인 사용자 토큰',exact=True)
        expect(token).to_have_attribute('type','password')
        token.fill('synthetic-user')
        panel.get_by_role('button',name='토큰 확인 · 페이지 조회',exact=True).click()
        expect(panel.get_by_role('alert')).to_contain_text('사용자 토큰 확인: Meta가 인증을 거절했습니다.')
        expect(token).to_have_value('')
        expect(panel.get_by_role('button',name='토큰 확인 · 페이지 조회',exact=True)).to_be_disabled()
        expect(panel.get_by_text('Synthetic 101',exact=True)).to_be_visible()
        assert calls == [1] and not publisher.graph.calls
        assert 'synthetic-user' not in page.content()
        ctx.close()


def test_platform_settings_separate_targets_without_requests(app,browser,connected,tmp_path):
    from test_meta_accounts import grant
    accounts,publisher,_=connected
    accounts.accept(grant('103',None),app_id=DEFAULTS['appId'])
    with local_server(app) as origin:
        ctx=context(browser,origin);page=ctx.new_page();posts=[];reads=[]
        page.on('request',lambda r: posts.append(r.url) if r.method=='POST' else reads.append(r.url))
        page.goto(origin+'/studio/settings?tab=accounts')
        panel=page.locator('section').filter(has=page.get_by_role('heading',name='Facebook · Instagram 연결',exact=True)).last
        expect(panel.get_by_text('Synthetic 101',exact=True)).to_be_visible()
        expect(panel.get_by_text('Synthetic 103',exact=True)).to_have_count(0)
        cards=page.locator('.mg-accounts')
        expect(cards.get_by_role('button',name='instagram 계정 설정',exact=True)).to_have_count(2)
        expect(cards.get_by_role('button',name='facebook 계정 설정',exact=True)).to_have_count(3)
        expect(cards.get_by_text('연결됨 · 게시 전 권한 확인',exact=True)).to_have_count(5)
        cards.get_by_role('button',name='facebook 계정 설정',exact=True).first.click()
        expect(panel.get_by_text('설정 대상: Facebook 페이지',exact=True)).to_be_visible()
        expect(panel.get_by_text('Synthetic 103',exact=True)).to_be_visible()
        expect(panel.get_by_text('Instagram 이미지 자동 업로드',exact=True)).to_have_count(0)
        cards.get_by_role('button',name='youtube 계정 설정',exact=True).click()
        expect(page.get_by_role('heading',name='YouTube 계정 설정',exact=True)).to_be_visible()
        expect(page.get_by_role('button',name='Google 로그인 · YouTube 연결',exact=True)).to_be_visible()
        expect(page.get_by_label('본인 사용자 토큰',exact=True)).not_to_be_visible()
        cards.get_by_role('button',name='tiktok 계정 설정',exact=True).click()
        expect(page.get_by_role('heading',name='TikTok 계정 설정',exact=True)).to_be_visible()
        expect(page.get_by_text('TikTok 직접 연결·게시 기능은 아직 지원하지 않습니다.',exact=False)).to_be_visible()
        expect(page.get_by_label('본인 사용자 토큰',exact=True)).not_to_be_visible()
        cards.get_by_role('button',name='instagram 계정 설정',exact=True).first.click()
        expect(panel.get_by_text('설정 대상: Instagram 전문 계정',exact=True)).to_be_visible()
        expect(panel.get_by_text('Synthetic 103',exact=True)).to_have_count(0)
        expect(panel.locator('input:visible')).to_have_count(1)
        assert not posts and not publisher.graph.calls
        assert reads.count(origin+'/api/meta/status') == 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path/'platform-settings-synthetic.png'),full_page=True)
        ctx.close()
