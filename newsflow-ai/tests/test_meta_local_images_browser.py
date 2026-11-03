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
        card = page.get_by_role("region", name="PC 이미지 전달", exact=True)
        expect(card).to_be_visible()
        expect(page.get_by_label("이미지 전달 포트", exact=True)).not_to_be_visible()
        button = page.get_by_role("button", name="PC 이미지 전달 사용하기", exact=True)
        if installed:
            expect(button).to_be_enabled()
            card.get_by_text("연결 설정 · 안내", exact=True).click()
            page.get_by_label("이미지 전달 포트", exact=True).fill("18770")
            card.get_by_role("button", name="포트 저장", exact=True).click()
            expect(card.get_by_role("button", name="포트 저장", exact=True)).to_be_disabled()
            assert not publisher.delivery.local.enabled()
            card.get_by_text("연결 설정 · 안내", exact=True).click()
            button.click()
            expect(page.get_by_role("button", name="PC 이미지 전달 끄기", exact=True)).to_be_visible()
            assert publisher.delivery.local.enabled()
            assert publisher.delivery.local.config()["port"] == 18770
        else:
            expect(button).to_be_disabled()
            expect(
                page.get_by_text("전달 도구를 먼저 준비해 주세요.", exact=True)
            ).to_be_visible()
        assert not bridge.started and publisher.graph.calls == []
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        card.screenshot(path=str(tmp_path / "local-image-settings.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        expect(card).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        card.screenshot(path=str(tmp_path / "local-image-settings-mobile.png"))
        ctx.close()
