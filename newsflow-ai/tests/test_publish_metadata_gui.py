"""Actual form reentry with Fake accounts; all external service traffic forbidden."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect
from sqlalchemy import select
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_settings_simplification import Document
from test_unified_publishing_gui import (
    instagram_ui,  # noqa: F401
    unified,  # noqa: F401
    values,
    youtube_media,  # noqa: F401
    youtube_ui,  # noqa: F401
)
from test_youtube_gui import forbid_external_calls  # noqa: F401

from newsflow.db.models import ContentDraft, PublishDraft, RenderJob, VideoProject

browser = browser_fixture


@pytest.mark.parametrize("platform", ["unified", "youtube", "instagram"])
def test_defaults_use_rendered_snapshot_and_never_approve_or_save(app, client, request, platform):
    request.getfixturevalue("unified")
    media = request.getfixturevalue("youtube_media")
    with app.state.sessions.begin() as session:
        project = session.get(VideoProject, session.get(RenderJob, media).project_id)
        draft = session.get(ContentDraft, project.draft_id)
        draft.content = {**draft.content, "summary": "영상 완성 후 수정한 대본은 사용하면 안 됨"}
    response = client.get(f"/?video={media}&publish_platform={platform}")
    dom = Document(response.text)
    assert response.status_code == 200
    description = dom.find("textarea", name="description")[0]
    assert "검토용" in "".join(description.text)
    assert "https://example.com/synthetic-news" in "".join(description.text)
    assert "영상 완성 후 수정한" not in "".join(description.text)
    for name in ("content_reviewed", "copyright_confirmed", "sources_confirmed"):
        assert all("checked" not in node.attrs for node in dom.find("input", name=name))
    with app.state.sessions() as session:
        assert list(session.scalars(select(PublishDraft))) == []


def test_saved_user_text_including_empty_fields_overrides_suggestions(app, client, request):
    request.getfixturevalue("unified")
    media = request.getfixturevalue("youtube_media")
    yt, ig = request.getfixturevalue("youtube_ui"), request.getfixturevalue("instagram_ui")
    response = client.post("/publishing/unified/review", data=values(client, media, yt, ig,
                           title="사용자가 직접 쓴 제목", description="", hashtags=""))
    assert response.status_code == 200
    dom = Document(client.get(f"/?video={media}&publish_platform=unified").text)
    assert dom.find("input", name="title")[0].attrs["value"] == "사용자가 직접 쓴 제목"
    assert "".join(dom.find("textarea", name="description")[0].text) == ""
    assert dom.find("input", name="hashtags")[0].attrs["value"] == ""
    assert not yt[0].calls and not ig[0].calls and not yt[1].calls and not ig[1].calls


def test_browser_edit_suggestion_save_reenter_and_mobile(app, browser, request, tmp_path):
    request.getfixturevalue("unified")
    media = request.getfixturevalue("youtube_media")
    yt, ig = request.getfixturevalue("youtube_ui"), request.getfixturevalue("instagram_ui")
    output = Path(os.environ.get("NEWSFLOW_METADATA_EVIDENCE", str(tmp_path / "screens")))
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        external = []
        def intercept(route):
            if route.request.url.startswith(origin + "/"):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()
        context.route("**/*", intercept)
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        try:
            url = origin + f"/?video={media}&publish_platform=unified#publish-workspace"
            page.goto(url)
            form = page.locator('[data-publish-review]')
            description = form.locator('[name="description"]')
            assert "검토용" in description.input_value()
            assert "https://example.com/synthetic-news" in description.input_value()
            expect(form.locator('[name="hashtags"]')).to_have_value("#합성 #영상")
            for name in ("content_reviewed", "copyright_confirmed", "sources_confirmed"):
                expect(form.locator(f'[name="{name}"]')).not_to_be_checked()
            for target in ("youtube", "instagram", "tiktok", "both"):
                form.locator('[name="target"]').select_option(target)
                assert "검토용" in description.input_value()
            for width, height in ((1366, 768), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                description.scroll_into_view_if_needed()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(output / f"metadata-{width}.png"))
            description.fill("사용자가 검토하고 수정한 게시 설명")
            form.locator('[name="youtube_category_id"]').select_option("28")
            for name in ("content_reviewed", "copyright_confirmed", "sources_confirmed"):
                form.locator(f'[name="{name}"]').check()
            form.locator('[name="ai_disclosure"]').select_option("disclose")
            page.evaluate("document.documentElement.dataset.metadataBefore = 'yes'")
            form.get_by_role("button", name="검토 기록·파일 확인").click()
            expect(page.locator("html")).not_to_have_attribute("data-metadata-before", "yes")
            page.goto(origin + "/simple-settings")
            page.goto(url)
            expect(description).to_have_value("사용자가 검토하고 수정한 게시 설명")
            expect(page.locator('form[action$="/execute"] [name="consent"]')).not_to_be_checked()
            assert not external
            assert not yt[0].calls and not ig[0].calls and not yt[1].calls and not ig[1].calls
        finally:
            context.close()
