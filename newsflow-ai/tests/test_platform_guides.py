"""Read-only platform onboarding documentation and real Cloud browser navigation."""

import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from conftest import csrf
from playwright.sync_api import expect
from sqlalchemy import select
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_youtube_gui import forbid_external_calls as offline_fixture

from newsflow.db.models import AppSetting, PlatformAccount, PublishJob

browser = browser_fixture
forbid_external_calls = offline_fixture


@pytest.mark.parametrize("platform", ["", "/youtube", "/instagram", "/tiktok"])
def test_guides_are_read_only_and_keep_security(app, client, platform, monkeypatch):
    for name in ("youtube", "instagram", "unified_publishing"):
        sentinel = Mock()
        for method in ("begin", "status", "execute", "publish", "prepare"):
            getattr(sentinel, method).side_effect = AssertionError("Guides must not access accounts or publish")
        monkeypatch.setattr(app.state, name, sentinel)
    with app.state.sessions() as session:
        before = [list(session.execute(select(model.__table__)).mappings())
                  for model in (AppSetting, PlatformAccount, PublishJob)]
    result = client.get("/guides/platforms" + platform)
    assert result.status_code == 200
    assert "직접 업로드" in result.text
    assert "<form" not in result.text
    assert "script-src 'self'" in result.headers["content-security-policy"]
    assert result.headers["cache-control"] == "no-store"
    if platform == "/tiktok":
        assert "현재 계정 연결·실제 업로드 불가" in result.text
    if platform == "/instagram":
        assert "HTTPS 인증 중계" in result.text and "App Secret은 Windows 앱에" in result.text
    if platform == "/youtube":
        assert "인증 링크 복사" in result.text and "데스크톱 앱" in result.text
    with app.state.sessions() as session:
        after = [list(session.execute(select(model.__table__)).mappings())
                 for model in (AppSetting, PlatformAccount, PublishJob)]
    assert before == after


def test_unknown_guide_not_template_path(client):
    assert client.get("/guides/platforms/unknown").status_code == 404
    assert client.get("/guides/platforms/base.html").status_code == 404
    assert client.post("/guides/platforms/youtube", data={"csrf_token": csrf(client)}).status_code == 405


def test_settings_and_extra_platform_links_open_new_tabs(client):
    from test_settings_simplification import Document
    page = Document(client.get("/simple-settings").text)
    for path in ("/guides/platforms", "/guides/platforms/youtube", "/guides/platforms/instagram"):
        link = page.find("a", href=path)[0]
        assert link.attrs["target"] == "_blank" and "noopener" in link.attrs["rel"]
    extra = Document(client.get("/publishing/platforms").text)
    assert extra.find("a", href="/guides/platforms/tiktok")[0].attrs["target"] == "_blank"


def test_browser_guides_preserve_settings_and_support_mobile_print(app, browser, tmp_path):
    output = Path(os.environ.get("NEWSFLOW_GUIDE_EVIDENCE", str(tmp_path / "screens")))
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        remote, posts, errors = [], [], []

        def route_request(route):
            if not route.request.url.startswith(origin + "/"):
                remote.append(route.request.url)
                route.abort()
            else:
                if route.request.method != "GET":
                    posts.append(route.request.url)
                route.continue_()

        context.route("**/*", route_request)
        context.on("page", lambda tab: tab.on("pageerror", lambda error: errors.append(str(error))))
        page = context.new_page()
        try:
            page.goto(origin + "/simple-settings#accounts")
            page.get_by_text("YouTube·Instagram 계정 관리", exact=True).click()
            page.locator("#instagram summary").click()
            field = page.locator('#instagram input[name="app_id"]')
            field.fill("1234567890")
            with page.expect_popup() as opened:
                page.locator('a[href="/guides/platforms/instagram"]').click()
            guide = opened.value
            guide.wait_for_load_state()
            expect(guide.get_by_role("heading", name="Instagram 시작 가이드", exact=True)).to_be_visible()
            expect(field).to_have_value("1234567890")
            for platform in ("youtube", "instagram", "tiktok"):
                guide.goto(origin + "/guides/platforms/" + platform)
                for width, height in ((1366, 768), (1920, 1080), (390, 844)):
                    guide.set_viewport_size({"width": width, "height": height})
                    assert guide.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    guide.screenshot(path=str(output / f"{platform}-{width}.png"))
                guide.locator('a[href="#connect"]').click()
                summary = guide.locator(".guide-body summary").first
                summary.focus()
                summary.press("Enter")
                expect(guide.locator(".guide-body details").first).to_have_attribute("open", "")
                summary.press("Enter")
                guide.evaluate("window.dispatchEvent(new Event('beforeprint'))")
                assert guide.locator(".guide-body details:not([open])").count() == 0
                guide.emulate_media(media="print")
                assert guide.locator(".creator-sidebar").is_hidden()
                guide.pdf(path=str(output / f"{platform}.pdf"), format="A4")
                guide.evaluate("window.dispatchEvent(new Event('afterprint'))")
                guide.emulate_media(media="screen")
                assert guide.locator(".guide-body details[open]").count() == 0
            guide.goto(origin + "/guides/platforms")
            expect(guide.get_by_role("link", name="TikTok 가이드 읽기 →")).to_be_visible()
            assert not remote and not posts and not errors
        finally:
            context.close()
