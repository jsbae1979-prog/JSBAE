"""Pending OAuth link controls: synthetic services only, no provider requests."""

from time import monotonic
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import csrf
from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_youtube_connection import CLIENT, FakeListener, connect
from test_youtube_connection import service as service_fixture
from test_youtube_gui import forbid_external_calls as offline_fixture

from newsflow.db.models import OAuthConnection, OAuthLifecycleOperation
from newsflow.oauth.production import BrowserLaunchError, GoogleSystemBrowser
from newsflow.oauth.youtube import YouTubeConnectionError

service = service_fixture
browser = browser_fixture
forbid_external_calls = offline_fixture


class Waiting(FakeListener):
    def wait(self):
        self.cancelled.wait(60)
        raise YouTubeConnectionError("cancelled")


def pending(service):
    service.listener_factory = Waiting
    service.save_client(CLIENT)
    return service.begin(consent=True)


def test_copy_and_reopen_preserve_state_pkce_and_single_operation(service):
    account_id = pending(service)
    original = service.browser.calls[0]
    url, remaining = service.authorization_link(account_id)
    assert url == original and 0 < remaining <= 300
    fields = parse_qs(urlsplit(url.get_secret_value()).query)
    assert fields["code_challenge_method"] == ["S256"]
    assert "client_secret" not in fields and "code_verifier" not in fields
    service.reopen_authorization(account_id)
    assert service.browser.calls == [original, original]
    assert service.authorization_link(account_id)[0] == original
    assert not service.tokens.calls and service.identity.calls == 0
    with service.sessions() as session:
        assert session.query(OAuthLifecycleOperation).count() == 1
    assert fields["state"][0] not in str(service.status())
    assert original.get_secret_value().encode() not in (service.data_dir / "test.db").read_bytes()
    with pytest.raises(YouTubeConnectionError):
        service.authorization_link(account_id + 1)


def test_os_browser_failure_keeps_manual_link_without_new_request(service, monkeypatch):
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: False)
    service.browser = GoogleSystemBrowser()
    account_id = pending(service)
    assert service.accounts()[0]["status"] == "authorizing"
    assert service.authorization_link(account_id)[0]
    with pytest.raises(BrowserLaunchError):
        service.reopen_authorization(account_id)
    assert service.authorization_link(account_id)[0]
    assert not service.tokens.calls


def test_unexpected_browser_error_still_fails_closed(service, monkeypatch):
    monkeypatch.setattr(service.browser, "open", lambda _: (_ for _ in ()).throw(ValueError("secret")))
    with pytest.raises(YouTubeConnectionError):
        pending(service)
    assert service._authorization_links == {}
    assert not service.tokens.calls


@pytest.mark.parametrize("terminal", ["cancel", "expire", "exchanging", "connected", "unknown", "revision", "restart"])
def test_link_rejected_when_attempt_is_no_longer_current(service, terminal):
    account_id = pending(service)
    if terminal == "cancel":
        service.cancel(account_id)
    elif terminal == "expire":
        revision, url, _ = service._authorization_links[account_id]
        service._authorization_links[account_id] = (revision, url, monotonic() - 1)
    elif terminal == "restart":
        service.recover()
    else:
        with service.sessions.begin() as session:
            row = session.get(OAuthConnection, account_id)
            if terminal == "revision":
                row.revision += 1
            else:
                row.status = terminal
    with pytest.raises(YouTubeConnectionError):
        service.authorization_link(account_id)
    with pytest.raises(YouTubeConnectionError):
        service.reopen_authorization(account_id)
    assert account_id not in service._authorization_links
    assert len(service.browser.calls) == 1 and not service.tokens.calls


def test_completed_callback_discards_link(service):
    account_id = connect(service)
    assert account_id not in service._authorization_links
    with pytest.raises(YouTubeConnectionError):
        service.authorization_link(account_id)
    assert len(service.tokens.calls) == 1


@pytest.mark.parametrize("action", ["link", "reopen"])
def test_link_endpoints_require_post_csrf_and_origin(service, app, client, action):
    app.state.youtube = service
    account_id = pending(service)
    path = f"/youtube/connect/{account_id}/{action}"
    token = csrf(client)
    assert client.get(path).status_code == 405
    assert client.post(path, data={"csrf_token": "invalid"}).status_code == 403
    assert client.post(path, data={"csrf_token": token}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert len(service.browser.calls) == 1
    response = client.post(path, data={"csrf_token": token})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "test-desktop-secret" not in response.text
    assert "code_verifier" not in response.text and "access_token" not in response.text
    page = client.get("/simple-settings")
    assert "인증 링크 복사" in page.text and "인증 화면 다시 열기" in page.text
    assert service.browser.calls[0].get_secret_value() not in page.text
    service.cancel(account_id)
    assert client.post(path, data={"csrf_token": token}).status_code == 409
    assert not service.tokens.calls


@pytest.mark.parametrize("clipboard_allowed", [True, False])
def test_browser_pending_link_copy_reopen_and_cancel(service, app, browser, clipboard_allowed):
    app.state.youtube = service
    account_id = pending(service)
    original = service.browser.calls[0].get_secret_value()
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(origin + "/") else route.abort())
        # Deterministic clipboard permission variants; actual UI/HTTP run in Chromium.
        context.add_init_script("""Object.defineProperty(navigator, 'clipboard', {value: {
            writeText: async (value) => { %s }
        }});""" % ("window.copied = value;" if clipboard_allowed else "throw new Error('denied');"))
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(origin + "/simple-settings#youtube")
            controls = page.locator("[data-youtube-link-controls]")
            for width, height in [(1366, 768), (1920, 1080), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                controls.get_by_role("button", name="인증 링크 복사").click()
                if clipboard_allowed:
                    expect(controls.locator('[role="status"]')).to_contain_text("복사했습니다")
                    assert page.evaluate("window.copied") == original
                else:
                    expect(controls.locator("[data-youtube-link-value]")).to_have_value(original)
                    expect(controls.locator("[data-youtube-link-value]")).to_be_focused()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            controls.get_by_role("button", name="인증 화면 다시 열기").click()
            expect(controls.locator('[role="status"]')).to_contain_text("다시 열었습니다")
            assert len(service.browser.calls) == 2
            expect(controls.locator("[data-youtube-link-fallback]")).to_be_hidden()
            service.cancel(account_id)
            controls.get_by_role("button", name="인증 링크 복사").click()
            expect(controls.locator('[role="status"]')).to_contain_text("만료")
            expect(controls.locator("[data-youtube-link-fallback]")).to_be_hidden()
            page.reload()
            expect(page.locator("[data-youtube-link-controls]")).to_have_count(0)
            assert not service.tokens.calls and not errors
        finally:
            context.close()


def test_previous_cancelled_worker_cannot_discard_replacement_link(service):
    import threading

    finishing = threading.Event()
    release = threading.Event()

    class SlowClose(Waiting):
        def close(self):
            finishing.set()
            assert release.wait(10)

    service.listener_factory = SlowClose
    service.save_client(CLIENT)
    account_id = service.begin(consent=True)
    old_worker = service._workers[account_id]
    service.cancel(account_id)
    assert finishing.wait(5)
    try:
        service.listener_factory = Waiting
        assert service.begin(consent=True, account_id=account_id) == account_id
        new_link = service.authorization_link(account_id)[0]
    finally:
        release.set()
        old_worker.join(5)
    assert not old_worker.is_alive()
    assert service.authorization_link(account_id)[0] == new_link
    service.reopen_authorization(account_id)
    assert not service.tokens.calls
