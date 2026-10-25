"""A reversible description edit; never erase internal evidence or imply approval."""

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
    youtube_media,  # noqa: F401
    youtube_ui,  # noqa: F401
)
from test_youtube_gui import forbid_external_calls  # noqa: F401

from newsflow.db.models import PublishDraft, RenderJob, VideoProject
from newsflow.publishing.metadata import suggest_metadata

browser = browser_fixture


def test_source_block_only_contains_valid_included_links():
    result = suggest_metadata("합성 영상", {"summary": "요약 안의 출처: 문구는 그대로 보존"}, {
        "articles": [{"sources": [{"url": "https://example.com/a"}, {"url": "javascript:bad"}]}]})
    assert result["source_block"] == "출처:\nhttps://example.com/a"
    assert result["source_block"] in result["description"]
    assert suggest_metadata("영상", {}, {})["source_block"] == ""


@pytest.mark.parametrize("platform", ["unified", "youtube", "instagram"])
def test_toggle_save_reopen_and_restore_does_not_change_sources_or_publish(app, browser, request, platform):
    request.getfixturevalue("unified")
    media = request.getfixturevalue("youtube_media")
    yt, ig = request.getfixturevalue("youtube_ui"), request.getfixturevalue("instagram_ui")
    with app.state.sessions() as session:
        project_id = session.get(RenderJob, media).project_id
        original_sources = session.get(VideoProject, project_id).sources
    external = []
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 1366, "height": 768})
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
            url = origin + f"/?video={media}&publish_platform={platform}"
            page.goto(url)
            toggle = page.get_by_label("게시 설명에 자동 출처 링크 포함", exact=True)
            description = page.locator('textarea[name="description"]')
            expect(toggle).to_be_checked()
            initial = description.input_value()
            toggle.uncheck()
            assert "https://example.com/synthetic-news" not in description.input_value()
            assert "검토용" in description.input_value()
            for name in ("content_reviewed", "copyright_confirmed", "sources_confirmed"):
                expect(page.locator(f'[name="{name}"]')).not_to_be_checked()
            toggle.check()
            assert description.input_value() == initial
            toggle.uncheck()
            # Store exactly what the user sees. No request/flag modifies it after approval.
            without_sources = description.input_value()
            if platform != "instagram":
                page.locator('[name="youtube_category_id"]').select_option("28")
            for name in ("content_reviewed", "copyright_confirmed", "sources_confirmed"):
                page.locator(f'[name="{name}"]').check()
            page.locator('[name="ai_disclosure"]').select_option("disclose")
            page.evaluate("document.documentElement.dataset.sourceBefore = 'yes'")
            page.get_by_role("button", name="검토 기록·파일 확인" if platform == "unified" else "검토 저장·파일 확인", exact=True).click()
            expect(page.locator("html")).not_to_have_attribute("data-source-before", "yes")
            page.goto(origin + "/simple-settings")
            page.goto(url)
            expect(toggle).not_to_be_checked()
            expect(description).to_have_value(without_sources)
            for width, height in ((1366, 768), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                toggle.scroll_into_view_if_needed()
                expect(toggle).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                evidence = os.environ.get("NEWSFLOW_SOURCE_CHOICE_EVIDENCE")
                if evidence and platform == "unified":
                    Path(evidence).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(evidence) / f"source-choice-{width}.png"))
            toggle.focus()
            page.keyboard.press("Space")
            expect(toggle).to_be_checked()
            assert description.input_value().count("https://example.com/synthetic-news") == 1
            with app.state.sessions() as session:
                drafts = list(session.scalars(select(PublishDraft).where(PublishDraft.render_job_id == media)))
                assert drafts and all(d.sources == original_sources and d.description == without_sources for d in drafts)
                assert session.get(VideoProject, project_id).sources == original_sources
            assert not external
            assert not yt[0].calls and not ig[0].calls and not yt[1].calls and not ig[1].calls
        finally:
            context.close()
