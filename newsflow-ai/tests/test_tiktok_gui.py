"""Cloud browser and GUI contracts; synthetic TikTok only, no real network."""
import os
from pathlib import Path

import pytest
from conftest import csrf
from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_settings_simplification import Document
from test_tiktok_connection import build
from test_youtube_gui import forbid_external_calls as offline_fixture

from newsflow.intelligence.credentials import FakeCipher
from newsflow.oauth.tiktok_credentials import TikTokClientStore

browser = browser_fixture
forbid_external_calls = offline_fixture


@pytest.mark.parametrize("action", ["connect", "accounts/1/refresh", "accounts/1/revoke"])
def test_default_activation_cannot_be_forged(app, client, action):
    response = client.post("/tiktok/" + action, data={"csrf_token": csrf(client), "consent": "true"})
    assert response.status_code == 403
    assert "차단" in response.json()["detail"]
    assert client.post("/tiktok/" + action, data={"consent": "true"}).status_code == 403
    assert client.get("/tiktok/" + action).status_code == 405


def test_client_configuration_encrypted_and_secret_never_reflected(app, client, tmp_path):
    store = TikTokClientStore(tmp_path / "client", FakeCipher())
    app.state.tiktok.client = store
    values = {"csrf_token": csrf(client), "client_key": "nf-synthetic-client", "client_secret": "nf-synthetic-secret-private", "port": "0"}
    result = client.post("/tiktok/client", data=values)
    assert result.status_code == 200
    assert store.config().client_key == "nf-synthetic-client"
    assert "nf-synthetic-secret-private" not in result.text
    assert "nf-synthetic-client" not in result.text
    assert b"nf-synthetic-secret-private" not in store.path.read_bytes()
    doc = Document(result.text)
    connect_form = doc.find("form", action="/tiktok/connect")[0]
    assert all("disabled" in node.attrs for node in doc.find("button") if connect_form in node.ancestors)
    for invalid in ({"port": "8765"}, {"client_secret": "nf-synthetic-secret-private" * 50}, {"client_key": "<script>bad</script>"}):
        response = client.post("/tiktok/client", data={**values, **invalid})
        assert response.status_code == 422
        assert "nf-synthetic-secret-private" not in response.text
    assert client.post("/tiktok/client", data=values, headers={"origin": "https://evil.example"}).status_code == 403


def test_fake_gui_connect_refresh_cancel_revoke(app, client, tmp_path):
    env = build(app.state.sessions, tmp_path / "synthetic")
    app.state.tiktok = env.service
    try:
        data = {"csrf_token": csrf(client), "consent": "true"}
        assert client.post("/tiktok/connect", data=data).status_code == 200
        for worker in env.service._workers.values():
            worker.join(5)
        account = env.service.status()["accounts"][0]["id"]
        page = client.get("/publishing/platforms")
        assert "합성 연결됨" in page.text and "nf-synthetic-access" not in page.text
        assert client.post(f"/tiktok/accounts/{account}/refresh", data=data).status_code == 200
        assert client.post(f"/tiktok/accounts/{account}/revoke", data=data).status_code == 200
        assert "연결 해제됨" in client.get("/publishing/platforms").text
        env.browser.auto = False
        env.service.begin(consent=True)
        account2 = max(env.service._workers)
        assert client.post(f"/tiktok/accounts/{account2}/cancel", data=data).status_code == 200
        env.service._workers[account2].join(5)
        assert "취소됨" in client.get("/publishing/platforms").text
        assert client.post(f"/tiktok/accounts/{account2}/invalid", data=data).status_code == 404
    finally:
        env.service.close()


def test_browser_app_registration_reentry_and_synthetic_login(app, browser, tmp_path):
    env = build(app.state.sessions, tmp_path / "synthetic")
    env.service.client.clear()
    app.state.tiktok = env.service
    output = Path(os.environ.get("NEWSFLOW_TIKTOK_EVIDENCE", str(tmp_path / "screens")))
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        remote, errors = [], []
        def intercept(route):
            if not route.request.url.startswith(origin + "/"):
                remote.append(route.request.url)
                route.abort()
            else:
                route.continue_()
        context.route("**/*", intercept)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(origin + "/publishing/platforms#tiktok")
            section = page.locator("#tiktok")
            expect(section.get_by_role("button", name="TikTok으로 연결")).to_be_disabled()
            section.get_by_text("Desktop 앱 설정 · 등록 필요", exact=True).click()
            section.get_by_label("Client key", exact=True).fill("nf-synthetic-client")
            section.get_by_label("Client secret", exact=True).fill("nf-synthetic-secret-private")
            section.get_by_role("button", name="앱 설정 저장", exact=True).click()
            expect(section.get_by_text("Desktop 앱 설정 · 등록됨", exact=True)).to_be_visible()
            assert env.wire.calls == []
            page.goto(origin + "/simple-settings")
            page.goto(origin + "/publishing/platforms#tiktok")
            expect(section.get_by_role("button", name="TikTok으로 연결")).to_be_enabled()
            assert "nf-synthetic-secret-private" not in page.content()
            section.locator('form[action="/tiktok/connect"] input[name="consent"]').check()
            # Synchronize on the real POST and redirected document, without CSP eval.
            with page.expect_response(lambda r: r.request.is_navigation_request() and r.request.method == 'GET' and (r.url.split('#')[0] == origin + '/publishing/platforms')) as redirected, page.expect_response(lambda r: r.url.endswith('/tiktok/connect') and r.request.method == 'POST') as sent:
                section.get_by_role("button", name="TikTok으로 연결").click()
            assert redirected.value.status == 200
            assert redirected.value.request.is_navigation_request()
            assert "'unsafe-eval'" not in redirected.value.headers["content-security-policy"]
            page.wait_for_load_state("domcontentloaded")
            assert sent.value.status == 303
            for worker in env.service._workers.values():
                worker.join(5)
            page.reload()
            expect(section.get_by_text("합성 연결됨", exact=True)).to_be_visible()
            for width, height in ((1366, 768), (1920, 1080), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                section.scroll_into_view_if_needed()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(output / f"tiktok-connected-{width}.png"))
            page.set_viewport_size({"width": 1366, "height": 768})
            section.get_by_text("Desktop 앱 설정 · 등록됨", exact=True).click()
            field = section.get_by_label("Client key", exact=True)
            field.focus()
            page.keyboard.press("Tab")
            expect(section.get_by_label("Client secret", exact=True)).to_be_focused()
            page.screenshot(path=str(output / "tiktok-app-settings.png"))
            assert not remote and not errors
        finally:
            context.close()
            env.service.close()


def test_browser_production_gate_stays_closed_after_synthetic_app_save(app, browser, tmp_path):
    store = TikTokClientStore(tmp_path / "client-only", FakeCipher())
    app.state.tiktok.client = store
    output = Path(os.environ.get("NEWSFLOW_TIKTOK_EVIDENCE", str(tmp_path / "screens")))
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        remote = []
        def intercept(route):
            if not route.request.url.startswith(origin + "/"):
                remote.append(route.request.url)
                route.abort()
            else:
                route.continue_()
        context.route("**/*", intercept)
        page = context.new_page()
        try:
            page.goto(origin + "/publishing/platforms#tiktok")
            section = page.locator("#tiktok")
            expect(section.get_by_role("button", name="TikTok으로 연결")).to_be_disabled()
            section.scroll_into_view_if_needed()
            page.screenshot(path=str(output / "tiktok-default-blocked.png"))
            section.get_by_text("Desktop 앱 설정 · 등록 필요", exact=True).click()
            section.get_by_label("Client key", exact=True).fill("nf-synthetic-client")
            section.get_by_label("Client secret", exact=True).fill("nf-synthetic-secret-private")
            section.get_by_role("button", name="앱 설정 저장", exact=True).click()
            expect(section.get_by_text("Desktop 앱 설정 · 등록됨", exact=True)).to_be_visible()
            section.locator('form[action="/tiktok/connect"] input[name="consent"]').check()
            expect(section.get_by_role("button", name="TikTok으로 연결")).to_be_disabled()
            page.set_viewport_size({"width": 390, "height": 844})
            section.scroll_into_view_if_needed()
            page.screenshot(path=str(output / "tiktok-default-blocked-mobile.png"))
            assert not remote
            assert app.state.tiktok.status()["enabled"] is False
        finally:
            context.close()
