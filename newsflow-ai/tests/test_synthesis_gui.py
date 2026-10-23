"""Cloud browser source review; Fake API, no real supplier account or media generation."""

import os
from pathlib import Path

from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_multi_article_synthesis import (
    TITLES,
    settled,
    start,
)
from test_multi_article_synthesis import (
    api_pipeline as pipeline_fixture,
)
from test_multi_article_synthesis import (
    grouped as grouped_fixture,
)
from test_youtube_gui import forbid_external_calls  # noqa: F401

browser = browser_fixture
api_pipeline = pipeline_fixture
grouped = grouped_fixture


def test_browser_review_group_sources_and_reopen(app, browser, grouped, monkeypatch, tmp_path):
    pipeline, _ = grouped
    coordinator, _, provider, _, mode, _ = pipeline
    job = settled(pipeline, start(pipeline, acquisition_policy="rss"))
    monkeypatch.setattr(app.state, "autopilot", coordinator)
    output = Path(os.environ.get("NEWSFLOW_SYNTHESIS_EVIDENCE", str(tmp_path / "screens")))
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width":1366, "height":768})
        external = []
        def intercept(route):
            if route.request.url.startswith(origin + "/"):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()
        context.route("**/*", intercept)
        page = context.new_page()
        try:
            url = origin + "/autopilot/jobs/" + job["id"]
            page.goto(url)
            expect(page.locator("[data-synthesis-count]")).to_contain_text("관련 기사 2개")
            details = page.locator("[data-synthesis-sources]")
            details.locator("summary").click()
            for title in TITLES[:2]:
                expect(details.get_by_role("heading", name=title, exact=True)).to_be_visible()
            assert TITLES[2] not in details.inner_text()
            assert details.locator("a").count() == 2
            for width,height in ((1366,768),(390,844)):
                page.set_viewport_size({"width":width,"height":height})
                details.scroll_into_view_if_needed()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(output / f"synthesis-{mode}-{width}.png"))
            page.goto(origin + "/")
            page.goto(url)
            expect(page.locator("[data-synthesis-count]")).to_contain_text("관련 기사 2개")
            assert provider.calls == ["analysis", "script"] and not external
        finally:
            context.close()


def test_single_article_is_not_presented_as_synthesis(client, app, api_pipeline, monkeypatch):
    pipeline = api_pipeline
    job = settled(pipeline, start(pipeline))
    monkeypatch.setattr(app.state, "autopilot", pipeline[0])
    response = client.get("/autopilot/jobs/" + job["id"])
    assert response.status_code == 200
    assert "기사 1개로 작성했습니다" in response.text
    assert "종합에 사용한 기사·출처 확인" not in response.text

