"""Category selection, reentry and platform-specific visibility on a real Cloud browser."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect
from sqlalchemy import select
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_unified_publishing_gui import (
    instagram_ui,  # noqa: F401
    unified,  # noqa: F401
    values,
    youtube_media,  # noqa: F401
    youtube_ui,  # noqa: F401
)
from test_youtube_gui import forbid_external_calls  # noqa: F401

from newsflow.db.models import PublishDraft

browser = browser_fixture


@pytest.mark.parametrize("category", ["", "999", "bad"])
def test_missing_or_unknown_category_is_rejected_without_drafts(client, app, request, category):
    data = values(client, request.getfixturevalue("youtube_media"), request.getfixturevalue("youtube_ui"),
                  request.getfixturevalue("instagram_ui"), youtube_category_id=category)
    request.getfixturevalue("unified")
    response = client.post("/publishing/unified/review", data=data)
    assert response.status_code == 422
    with app.state.sessions() as session:
        assert list(session.scalars(select(PublishDraft))) == []


def test_browser_choose_save_reopen_change_and_hide_for_instagram(app, browser, request, tmp_path):
    request.getfixturevalue("unified")
    media = request.getfixturevalue("youtube_media")
    yt = request.getfixturevalue("youtube_ui")
    ig = request.getfixturevalue("instagram_ui")
    output = Path(os.environ.get("NEWSFLOW_CATEGORY_EVIDENCE", str(tmp_path / "screens")))
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width":1366,"height":768})
        external=[]
        def intercept(route):
            if route.request.url.startswith(origin + "/"):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()
        context.route("**/*",intercept)
        page=context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        try:
            url=origin+f"/?video={media}&publish_platform=unified#publish-workspace"
            page.goto(url)
            form=page.locator('[data-publish-review]')
            form.locator('[name="target"]').select_option("both")
            category=form.get_by_label("YouTube 영상 카테고리",exact=True)
            expect(category).to_have_value("")
            assert category.locator('option').count() == 15
            category.select_option("27")
            for name in ("content_reviewed","copyright_confirmed","sources_confirmed"):
                form.locator(f'[name="{name}"]').check()
            form.locator('[name="ai_disclosure"]').select_option("disclose")
            page.evaluate("document.documentElement.dataset.categoryBefore = 'yes'")
            form.get_by_role("button",name="검토 저장·파일 확인").click()
            expect(page.locator("html")).not_to_have_attribute("data-category-before", "yes")
            expect(page.locator('form[action$="/execute"]')).to_be_visible()
            page.goto(origin+"/simple-settings")
            page.goto(url)
            expect(category).to_have_value("27")
            category.select_option("28")
            page.evaluate("document.documentElement.dataset.categoryBefore = 'yes'")
            form.get_by_role("button",name="검토 저장·파일 확인").click()
            expect(page.locator("html")).not_to_have_attribute("data-category-before", "yes")
            expect(page.locator('form[action$="/execute"]')).to_be_visible()
            page.goto(url)
            expect(category).to_have_value("28")
            for width,height in ((1366,768),(390,844)):
                page.set_viewport_size({"width":width,"height":height})
                category.scroll_into_view_if_needed()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(output/f"category-{width}.png"))
            form.locator('[name="target"]').select_option("instagram")
            expect(category).not_to_be_visible()
            expect(category).to_be_disabled()
            form.locator('[name="target"]').select_option("youtube")
            expect(category).to_be_visible()
            expect(category).to_have_value("28")
            assert not yt[0].calls and not ig[0].calls and not yt[1].calls and not ig[1].calls
            assert not external
        finally:
            context.close()
