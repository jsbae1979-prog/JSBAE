"""Claude connection display reads existing proof; no real keys or vendor calls."""
from datetime import timedelta
import urllib.request

import pytest
from playwright.sync_api import expect
from sqlalchemy import select
from test_blue_studio_browser import guarded_page
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture

from newsflow.db.models import APIRequestReservation, AppSetting, utcnow
from newsflow.intelligence.api_settings import api_readiness
from newsflow.intelligence.settings import _set

browser = browser_fixture
MODEL = 'claude-sonnet-4-6'
CASES = [
    ('not_checked', None, MODEL, True, False),
    ('valid', 1, MODEL, True, True),
    ('expired', 25, MODEL, True, False),
    ('model_changed', 1, 'claude-opus-4-6', True, False),
    ('key_missing', 1, MODEL, False, False),
    ('future_stamp', -1, MODEL, True, False),
]


def values(app):
    with app.state.sessions() as session:
        return dict(session.execute(select(AppSetting.key, AppSetting.value)).all())


@pytest.fixture
def connection_app(app, monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('Connection display must not read a secret or call a vendor')

    for store in app.state.api_keys.values():
        monkeypatch.setattr(store, 'key', denied)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', denied)
    monkeypatch.setattr(urllib.request, 'urlopen', denied)
    return app


def proof(app, monkeypatch, age, verified_model, configured):
    store = app.state.api_keys['claude_api']
    monkeypatch.setattr(store, 'status', lambda: {
        'configured': configured, 'stored': configured, 'environment': False, 'storage_supported': True,
    })
    with app.state.sessions.begin() as session:
        _set(session, 'studio_model_claude_api', MODEL)
        _set(session, 'api_claude_api_verified_model', verified_model)
        stamp = '' if age is None else (utcnow() - timedelta(hours=age)).isoformat()
        _set(session, 'api_claude_api_authentication_verified_at', stamp)
    return store


@pytest.mark.parametrize('name,age,verified_model,configured,expected', CASES)
def test_claude_connection_projection_preserves_gates_and_settings(
    connection_app, client, monkeypatch, name, age, verified_model, configured, expected,
):
    app = connection_app
    store = proof(app, monkeypatch, age, verified_model, configured)
    before = values(app)
    for path in ('/api/studio/workspace', '/api/studio/modules/settings'):
        response = client.get(path)
        assert response.status_code == 200
        rows = response.json()['services']
        claude = next(row for row in rows if row['id'] == 'claude')
        assert claude['configured'] is configured
        assert claude['verified'] is expected
        assert all(not row['verified'] for row in rows if row['id'] != 'claude')
    # A metadata proof must never grant inference, search, or spending approval.
    readiness = api_readiness(app.state.sessions, 'claude_api', store, 'analysis')
    assert not readiness['ready'] and not readiness['settings'].approved
    assert not readiness['settings'].search_approved
    assert not readiness['settings'].request_succeeded_at
    assert values(app) == before
    with app.state.sessions() as session:
        assert not list(session.scalars(select(APIRequestReservation)))


def test_chrome_settings_labels_follow_only_current_claude_proof(connection_app, browser, monkeypatch):
    app = connection_app
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366, 900))
        posts = []
        page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
        try:
            for name, age, verified_model, configured, expected in CASES:
                proof(app, monkeypatch, age, verified_model, configured)
                before = values(app)
                assert page.goto(origin + '/studio/settings').status == 200
                row = page.locator('.mg-settings-models tbody tr').filter(
                    has=page.get_by_role('button', name='Claude 키 설정', exact=True))
                expect(row).to_have_count(1)
                label = ('인증·모델 확인' if expected else
                         '키 저장 · 실제 인증 미검증' if configured else '키 미설정')
                expect(row.locator('td').nth(1)).to_contain_text(label)
                if expected:
                    expect(row.locator('.mg-badge')).to_have_text('인증 확인')
                    expect(row.locator('td').nth(1)).not_to_contain_text('생성 완료')
                    expect(row.locator('td').nth(1)).not_to_contain_text('미검증')
                else:
                    expect(row.locator('td').nth(1)).not_to_contain_text('인증·모델 확인')
                assert values(app) == before
            assert not posts and not external and not errors
        finally:
            context.close()
