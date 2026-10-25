"""Actual local Chromium navigation with synthetic records and no outbound requests."""

import re
from datetime import timedelta

import pytest
from conftest import csrf
from playwright.sync_api import expect
from test_blue_studio_browser import guarded_page
from test_blue_studio_browser import studio_ui as studio_ui_fixture
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import stored_values
from test_unified_publishing_gui import (
    instagram_ui,  # noqa: F401
    unified,  # noqa: F401
    values,
    youtube_media,  # noqa: F401
    youtube_ui,  # noqa: F401
)

from newsflow.db.models import utcnow
from newsflow.publishing.calendar import KST, PublishingCalendar

browser = browser_fixture
studio_ui = studio_ui_fixture


@pytest.mark.parametrize(
    "url",
    ["/analytics", "/analytics?platform=facebook&account=", "/publishing/platforms", "/queue?month=2026-12"],
)
def test_social_pages_have_csp_and_get_is_read_only(client, app, url):
    before = stored_values(app)
    response = client.get(url)
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert 'http-equiv="refresh"' not in response.text
    assert stored_values(app) == before
    assert not app.state.publishing_calendar.rows()


@pytest.mark.parametrize(
    "url", ["/analytics?platform=unknown", "/analytics?account=oops", "/queue?month=not-a-month"]
)
def test_invalid_filter_does_not_return_server_error(client, url):
    assert client.get(url).status_code == 422


def test_calendar_post_save_reentry_edit_and_cancel(request, client, app):
    service = request.getfixturevalue("unified")
    media = request.getfixturevalue("youtube_media")
    yt, ig = request.getfixturevalue("youtube_ui"), request.getfixturevalue("instagram_ui")
    app.state.publishing_calendar = PublishingCalendar(app.state.sessions, service)
    result = client.post("/publishing/unified/review", data=values(client, media, yt, ig))
    assert result.status_code == 200
    cohort = service.for_video(media)
    due = (utcnow().astimezone(KST) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    assert (
        client.post("/publishing/calendar", data={"cohort_id": cohort["id"], "due": due}).status_code == 403
    )
    response = client.post(
        "/publishing/calendar", data={"csrf_token": csrf(client), "cohort_id": cohort["id"], "due": due}
    )
    assert response.status_code == 200 and "일정 보관" in response.text
    row = app.state.publishing_calendar.rows()[0]
    assert not row.approval and row.status == "paused"
    detail = client.get(f"/publishing/calendar/{row.id}")
    assert detail.status_code == 200 and due in detail.text
    later = (utcnow().astimezone(KST) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    response = client.post(
        "/publishing/calendar",
        data={"csrf_token": csrf(client), "cohort_id": cohort["id"], "due": later, "revision": row.revision},
    )
    assert response.status_code == 200
    response = client.post(
        f"/publishing/calendar/{row.id}/cancel", data={"csrf_token": csrf(client), "revision": row.revision}
    )
    assert response.status_code == 422  # Stale form cannot cancel a revised schedule.
    updated = app.state.publishing_calendar.rows()[0]
    response = client.post(
        f"/publishing/calendar/{row.id}/cancel",
        data={"csrf_token": csrf(client), "revision": updated.revision},
    )
    assert response.status_code == 200
    assert app.state.publishing_calendar.rows()[0].status == "cancelled"
    assert not yt[1].calls and not ig[1].calls


def test_social_browser_layout_navigation_and_empty_metrics(studio_ui, browser):
    app = studio_ui
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366, 768))
        posts = []
        page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
        for width, height in [(1366, 768), (1920, 1080), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            for path, heading in [
                ("/queue", "게시 허브"),
                ("/analytics", "성과 분석"),
                ("/publishing/platforms", "게시 계정 준비"),
                ("/simple-settings#accounts", "설정 · 자동화"),
            ]:
                assert page.goto(origin + path).status == 200
                expect(page.get_by_role("heading", name=heading, exact=True, level=1)).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, path)
            expect(page.locator("[id=accounts]")).to_be_visible()
            page.get_by_role("link", name=re.compile("TikTok")).click()
            page.wait_for_url("**/publishing/platforms#tiktok")
            expect(page.get_by_role("heading", name="TikTok", exact=True)).to_be_visible()
            page.goto(origin + "/queue")
            calendar = page.locator('#publishing-calendar')
            if calendar.get_attribute('open') is None:
                calendar.locator('>summary').click()
            page.get_by_role("link", name="다음 달", exact=True).click()
            page.wait_for_url("**/queue?month=*#publishing-calendar")
            assert page.locator(".social-calendar .weekday").count() == 7
            page.get_by_text('게시 전 확인 항목', exact=True).click()
            page.locator('a[href="/analytics"]:visible').first.click()
            page.wait_for_url("**/analytics")
            expect(page.locator(".analytics-empty")).to_contain_text("아직 저장된 성과가 없습니다.")
            expect(page.locator(".social-kpis")).to_have_count(0)
            expect(page.locator(".analytics-empty")).not_to_contain_text("2.4M")
            page.get_by_label("플랫폼", exact=True).select_option("tiktok")
            page.get_by_role("button", name="저장 기록 보기", exact=True).focus()
            page.keyboard.press("Enter")
            page.wait_for_url("**/analytics?*")
            expect(page.get_by_label("플랫폼", exact=True)).to_have_value("tiktok")
            expect(page.locator(".social-kpis")).to_have_count(0)
            expect(page.locator(".analytics-empty")).to_contain_text("0으로 채우지 않습니다")
        assert not external and not errors and not posts
        context.close()
