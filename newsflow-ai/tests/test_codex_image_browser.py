"""Real Chrome, temporary loopback server/data and Fake image adapter only."""
import os
from pathlib import Path

from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_codex_images import FakeNative
from test_image_posts import article
from test_model_picker_browser import browser as browser_fixture

browser = browser_fixture


def test_codex_copy_review_to_whole_image_save_in_offline_chrome(browser, app, monkeypatch, tmp_path):
    monkeypatch.setattr("newsflow.gui.image_post_routes.cli_path", lambda: Path("fixture-codex.exe"))
    monkeypatch.setattr("newsflow.easy_setup.voice_catalog", list)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("No external HTTP")))
    service = app.state.image_generation
    service.codex_adapter = FakeNative()
    news = article(app)
    with local_server(app) as origin:
        exercise(browser, service, news, origin, tmp_path)


def exercise(browser, service, news, origin, tmp_path):
    context = browser.new_context(viewport={"width": 1280, "height": 960}, locale="ko-KR")
    requests = []
    def handle(route):
        request = route.request
        assert request.url.startswith(origin + "/"), "Unexpected external browser request"
        requests.append((request.method, request.url))
        route.continue_()
    context.route("**/*", handle)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("requestfailed", lambda request: errors.append(request.failure)
            if request.failure != "net::ERR_ABORTED" else None)
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(f"{origin}/image-posts?article_id={news}")
    panel = page.locator("#codex-image")
    panel.locator("summary").click()
    expect(panel).to_contain_text("로그인·이미지 생성 권한 미검증")
    assert not service.codex_adapter.calls
    page.locator("#image-title").fill("합성 도서관 소식")
    page.locator("#image-body").fill("독서 모임을 소개하는 합성 자료입니다.")
    panel.locator('[name="reviewed"]').check()
    panel.locator('[name="consent"]').check()
    output = Path(os.environ.get("NEWSFLOW_VALIDATION_OUTPUT", str(tmp_path / "evidence")))
    output.mkdir(parents=True, exist_ok=True)
    panel.screenshot(path=str(output / "codex-image-choice.png"))
    for p in panel.locator("p").all():
        assert p.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    panel.get_by_role("button", name="Codex 전체 이미지 1장 요청").click()
    try:
        expect(page.get_by_text("Codex 생성 결과 · 최종 검토 필요", exact=True)).to_be_visible()
    except AssertionError:
        raise AssertionError({"errors": errors, "requests": requests, "url": page.url,
                              "status": page.locator("[data-generation-status]").all_text_contents()}) from None
    assert "합성 도서관 소식" in service.codex_adapter.calls[0]
    expect(page.locator("#image-title")).to_have_value("합성 도서관 소식")
    assert page.locator("#image-title").get_attribute("readonly") is not None
    page.reload()
    assert len(service.codex_adapter.calls) == 1
    form = page.locator("[data-image-form]")
    for name in ("reviewed", "sources_confirmed", "rights"):
        form.locator(f'[name="{name}"]').check()
    form.get_by_role("button", name="검토한 전체 이미지 저장").click()
    expect(page.get_by_text("이미지 준비 완료 · 1080×1350 JPEG", exact=True)).to_be_visible()
    expect(page.locator("#image-caption")).to_contain_text("https://example.com/image-news")
    assert len(service.codex_adapter.calls) == 1
    page.locator("#image-result").screenshot(path=str(output / "codex-image-saved.png"))
    assert len([r for r in requests if r[0] == "POST" and "generate-codex-image" in r[1]]) == 1
    assert not errors
    context.close()


def test_existing_openai_image_form_still_uses_its_own_handler(browser, app, monkeypatch):
    from test_image_generation import prepared

    service, news = prepared.__wrapped__(app)
    monkeypatch.setattr("newsflow.easy_setup.voice_catalog", list)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("No external HTTP")))
    with local_server(app) as origin:
        context = browser.new_context()
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith(origin + "/") else route.abort())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{origin}/image-posts?article_id={news}")
        form = page.locator('form[action="/image-posts/generate-background"]')
        form.locator("xpath=ancestor::details[1]/summary").click()
        form.locator('[name="consent"]').check()
        form.get_by_role("button", name="배경 1장 생성").click()
        expect(page.get_by_text("이 배경을 카드에 사용합니다.", exact=True)).to_be_visible()
        assert len(service.adapter.calls) == 1 and not errors
        context.close()
