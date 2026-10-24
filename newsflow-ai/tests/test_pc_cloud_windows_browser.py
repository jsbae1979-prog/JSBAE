"""PC/Cloud candidate: real isolated loopback GUI, synthetic records, GET-only navigation."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_dashboard_cohesion import seed_archive
from test_single_workspace import stored_values
from test_studio_dashboard_polish import records
from test_usability_browser import (
    browser,
    instagram_ui,
    studio_ui,
    unified,
    visual,
    youtube_media,
    youtube_ui,
)
from test_youtube_gui import forbid_external_calls  # noqa: F401

__all__ = ["browser", "instagram_ui", "studio_ui", "unified", "visual", "youtube_media", "youtube_ui"]


@pytest.fixture(autouse=True)
def no_unattended_workers(monkeypatch):
    monkeypatch.setattr("newsflow.scheduler.service.Scheduler.start", lambda self: None)
    monkeypatch.setattr("newsflow.publishing.calendar.PublishingCalendar.start", lambda self: None)
    monkeypatch.setattr("newsflow.video.ai.service.AIVideoCoordinator.start", lambda self: None)


def test_isolated_windows_all_routes_assets_popup_and_preserved_records(visual, browser, tmp_path):
    app, (draft, render, failure) = visual
    seed_archive(app, draft)
    before = records(app), stored_values(app)
    output = Path(os.environ.get("NEWSFLOW_VALIDATION_OUTPUT", str(tmp_path))) / "windows-gui"
    output.mkdir(parents=True, exist_ok=True)
    external, writes, errors, asset_failures = [], [], [], []
    visited = []
    routes = [
        ("dashboard", "/"), ("news", "/news"), ("script", f"/ai?draft_id={draft}"),
        ("production", f"/video?draft_id={draft}"), ("videos", "/videos"),
        ("publish", "/queue"), ("analytics", "/analytics"), ("settings", "/simple-settings"),
        ("sources", "/sources"), ("voices", "/voices"), ("automation", "/schedules"),
        ("image-feed", "/image-posts"), ("ai-video", "/video/ai"),
        ("character", "/character"), ("failure", f"/video?job_id={failure}"),
    ]
    with local_server(app) as origin:
        assert urlsplit(origin).port != 8765
        context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR",
                                      reduced_motion="reduce")
        def guard(route):
            request = route.request
            if urlsplit(request.url).netloc != urlsplit(origin).netloc:
                external.append(urlsplit(request.url).path)
                route.abort()
            elif request.method != "GET":
                writes.append(request.method)
                route.abort()
            else:
                route.continue_()
        context.route("**/*", guard)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        def response_check(response):
            if "/static/" in response.url and response.status >= 400:
                asset_failures.append(urlsplit(response.url).path)
        page.on("response", response_check)
        for width in (1440, 980, 390):
            page.set_viewport_size({"width": width, "height": 900})
            for name, route in routes:
                response = page.goto(origin + route, wait_until="networkidle")
                assert response.status == 200, (name, width)
                expect(page.locator("h1").first).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), (name, width)
                assert page.locator("img").evaluate_all(
                    "(images)=>images.filter(i=>i.getAttribute('src') && i.offsetParent).every(i=>i.complete && i.naturalWidth>0)"
                ), (name, width)
                page.screenshot(path=str(output / f"{name}-{width}.png"), full_page=False, animations="disabled")
                visited.append({"page": name, "width": width, "status": response.status})
        page.goto(origin + "/")
        formats = page.get_by_role("navigation", name="만들 콘텐츠")
        for href in ("/create", "/image-posts", "/character"):
            formats.locator(f'a[href="{href}"]').click()
            expect(page).to_have_url(origin + href)
            page.goto(origin + "/")
        page.goto(origin + f"/video?job_id={render}")
        trigger = page.locator(".video-review-trigger")
        expect(trigger).to_have_count(1)
        trigger.click()
        dialog = page.locator(".video-review-dialog")
        expect(dialog).to_be_visible()
        expect(dialog.locator("h2")).to_have_text("영상 정보·출처")
        expect(dialog.get_by_role("button", name="닫기")).to_be_focused()
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(trigger).to_be_focused()
        expect(trigger).to_have_attribute("aria-expanded", "false")
        trigger.click()
        dialog.get_by_role("button", name="닫기").click()
        expect(dialog).not_to_be_visible()
        expect(trigger).to_have_attribute("aria-expanded", "false")
        expect(trigger).to_be_focused()
        assert not external and not writes and not errors and not asset_failures
        context.close()
    assert (records(app), stored_values(app)) == before
    (output / "gui-result.json").write_text(json.dumps({
        "status": "PASS", "visited": visited, "external_requests": external,
        "mutations": writes, "javascript_errors": errors, "static_asset_failures": asset_failures,
        "synthetic_records_unchanged": True, "operating_port_used": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
