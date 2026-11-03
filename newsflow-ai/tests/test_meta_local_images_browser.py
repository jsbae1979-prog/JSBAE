"""Isolated browser and Fake bridge. No public listener, upload or Meta call."""

import pytest
import test_meta_browser
import test_model_picker_browser
from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_meta_browser import context
from test_meta_local_images import Bridge

from newsflow.meta.media import MetaDelivery

connected = test_meta_browser.connected
browser = test_model_picker_browser.browser

pytestmark = pytest.mark.usefixtures("synthetic_app_isolation")


@pytest.mark.parametrize("installed", [False, True])
def test_local_image_settings_truthful_and_no_network(app, browser, connected, tmp_path, installed):
    accounts, publisher, _ids = connected
    bridge = Bridge()
    publisher.delivery = MetaDelivery(accounts, local_bridge_factory=(lambda: bridge) if installed else None)
    with local_server(app) as origin:
        ctx = context(browser, origin)
        page = ctx.new_page()
        page.goto(origin + "/studio/settings?tab=accounts")
        summary = page.get_by_text("이 PC에서 이미지 전달 · 시험 연결", exact=True)
        summary.click()
        button = page.get_by_role("button", name="이 PC 전달 사용", exact=True)
        if installed:
            expect(button).to_be_enabled()
            page.get_by_label("이미지 전달 포트", exact=True).fill("18770")
            button.click()
            expect(page.get_by_role("button", name="이 PC 전달 끄기", exact=True)).to_be_visible()
            assert publisher.delivery.local.enabled()
            assert publisher.delivery.local.config()["port"] == 18770
        else:
            expect(button).to_be_disabled()
            expect(
                page.get_by_text("전달 도구 준비 필요 · 아직 사용할 수 없습니다.", exact=True)
            ).to_be_visible()
        assert not bridge.started and publisher.graph.calls == []
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "local-image-settings.png"))
        ctx.close()
