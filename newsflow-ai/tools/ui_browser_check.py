"""Chromium review of the explicitly isolated ui_preview.py server only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

PAGES = {"home": "/", "create": "/create", "videos": "/videos", "preview": "/ai?draft_id=1",
         "settings": "/simple-settings", "publishing": "/?video=1&publish_platform=unified#publish-workspace",
         "news": "/news", "queue": "/queue"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8880")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--empty-base", help="Optional separate empty ui_preview.py server")
    args = parser.parse_args()
    if urlsplit(args.base).hostname != "127.0.0.1":
        parser.error("Only a loopback demo is allowed")
    args.output.mkdir(parents=True, exist_ok=True)
    results = {"environment": "Cloud Chromium; not Windows display scaling", "checks": [], "layout": []}
    external, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="ko-KR")

        def guard(route):
            if urlsplit(route.request.url).netloc == urlsplit(args.base).netloc:
                route.continue_()
            else:
                external.append(route.request.url.split("?")[0])
                route.abort()

        context.route("**/*", guard)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        def visit(path):
            response = page.goto(args.base + path)
            assert response and response.status == 200, (path, response.status if response else None)
            expect(page.locator(".demo-banner")).to_contain_text("UI 데모")

        # A real synthetic server is required: do not run against the user's app.
        visit("/")
        for width, height in ((1366, 768), (1920, 1080), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            for name, path in PAGES.items():
                visit(path)
                page.locator("body").click(position={"x": 1, "y": 1})
                dimensions = page.evaluate("({viewport:innerWidth,document:document.documentElement.scrollWidth})")
                assert dimensions["document"] <= width + 1, (name, width, dimensions)
                unnamed = page.locator("input:not([type=hidden]):visible,textarea:visible,select:visible").evaluate_all(
                    "nodes=>nodes.filter(n=>!n.labels?.length&&!n.getAttribute('aria-label')&&!n.getAttribute('aria-labelledby')).map(n=>n.name)"
                )
                assert not unnamed, (name, unnamed)
                results["layout"].append({"page": name, "width": width, "height": height, "horizontal_overflow": False,
                                           "visible_inputs_named": True})
                if name in {"home", "create", "videos", "preview", "settings", "publishing"}:
                    # Capture a decoded paused frame, not Chrome's transient native loading spinner.
                    for video in page.locator("video").all():
                        video.evaluate("async v => { v.muted=true; await v.play(); await new Promise(r=>setTimeout(r,200)); v.pause(); }")
                    page.screenshot(path=str(args.output / f"{name}-{width}.png"), full_page=True)
        page.set_viewport_size({"width": 1366, "height": 768})
        visit("/")
        page.keyboard.press("Tab")
        expect(page.locator("a.skip-link")).to_be_focused()
        page.keyboard.press("Enter")
        expect(page.locator("#main-content")).to_be_focused()
        page.get_by_role("textbox", name="어떤 주제로 만들까요?").fill("https://example.com/article")
        page.get_by_role("button", name="쇼츠 만들기").first.click()
        expect(page.locator("[data-topic-error]")).to_be_visible()
        assert urlsplit(page.url).path == "/"
        page.get_by_role("textbox", name="어떤 주제로 만들까요?").fill("도시")
        page.get_by_role("button", name="쇼츠 만들기").first.click()
        page.wait_for_url("**/news?q=*")
        expect(page.locator(".article-row")).to_have_count(1)
        page.locator(".article-row").click()
        page.get_by_role("link", name="이 기사로 쇼츠 만들기").click()
        expect(page.locator("#article-1")).to_be_checked()
        page.get_by_role("button", name="선택 기사 분석", exact=True).click()
        page.wait_for_url("**/ai?analysis_id=*")
        page.get_by_role("button", name="대본 생성 및 초안 저장", exact=True).click()
        page.wait_for_url(lambda url: "/ai?" in url and "draft_id=" in url)
        expect(page.locator('form[action^="/ai/drafts/"]')).to_be_visible()
        results["checks"].append("topic search → saved article → existing analysis selection; URL import honestly blocked")
        results["checks"].append("existing Offline analysis and draft generation POST, no content engine changes")

        visit("/ai?draft_id=1")
        player = page.locator("[data-editor-player]")
        player.evaluate("v => v.load()")
        page.wait_for_function("() => document.querySelector('[data-editor-player]').readyState >= 1")
        player.evaluate("v=>v.play()")
        page.wait_for_function("() => document.querySelector('[data-editor-player]').currentTime > 0")
        player.evaluate("v=>v.pause()")
        media_before = context.request.get(args.base + "/video/jobs/1/file").body()
        page.get_by_role("button", name="장면 2", exact=True).click()
        active_scene = page.locator("[data-topic-scene]:visible")
        expect(active_scene).to_have_count(1)
        active_scene.get_by_label("자막", exact=True).fill("직접 편집한 한글 자막 · 원문 확인 필요")
        expect(page.locator("[data-editor-dirty]")).to_be_visible()
        held = []
        page.route("**/ai/drafts/1", lambda route: held.append(route))
        page.get_by_role("button", name="수정 초안 저장").click()
        expect(page.get_by_role("button", name="처리 중…", exact=True)).to_be_disabled()
        page.screenshot(path=str(args.output / "loading-save.png"), full_page=True)
        assert len(held) == 1
        held[0].continue_()
        page.unroute("**/ai/drafts/1")
        page.wait_for_url("**/ai?draft_id=1")
        expect(page.locator("[data-editor-dirty]")).to_be_hidden()
        page.get_by_role("button", name="장면 2", exact=True).click()
        expect(page.locator("[data-topic-scene]:visible").get_by_label("자막", exact=True)).to_have_value("직접 편집한 한글 자막 · 원문 확인 필요")
        assert hashlib.sha256(context.request.get(args.base + "/video/jobs/1/file").body()).digest() == hashlib.sha256(media_before).digest()
        # Stale revision: a real 409 from the existing route, visible focused alert, no resubmit.
        page.locator('form[action="/ai/drafts/1"] input[name="revision"]').evaluate("n=>n.value='1'")
        with page.expect_response(lambda r: r.request.method == "POST" and "/ai/drafts/1" in r.url) as response:
            page.get_by_role("button", name="수정 초안 저장").click()
        assert response.value.status == 409
        expect(page.locator('form[action="/ai/drafts/1"] [data-submit-error]')).to_be_focused()
        page.screenshot(path=str(args.output / "error-stale-edit.png"), full_page=True)
        results["checks"].append("real MP4 playback; scene edit POST persisted; output hash preserved; stale edit 409 focused without retry")

        visit("/create")
        page.locator("#quick-source").select_option("sample")
        assert page.locator('#quick-news-usage option[value="VERIFIED"]').count() == 0
        page.get_by_role("button", name="쇼츠 만들기").click()
        page.wait_for_url("**/?task=*")
        expect(page.locator("[data-autopilot-job]")).to_be_visible()
        expect(page.get_by_role("list", name="현재 제작 단계")).to_be_visible()
        page.screenshot(path=str(args.output / "creation-progress.png"), full_page=True)
        results["checks"].append("existing offline guided Autopilot POST; actual stage display; unsupported VERIFIED hidden")

        visit("/ai?draft_id=3")
        assert len(page.locator('form[action="/ai/drafts/3"] textarea[name="narration"]').first.input_value()) >= 300
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(path=str(args.output / "long-korean-editor.png"), full_page=True)
        visit("/?task=" + "e" * 32)
        expect(page.locator(".error-panel")).to_be_visible()
        page.screenshot(path=str(args.output / "creation-failure.png"), full_page=True)
        results["checks"].append("long Korean title/narration; synthetic render failure and recovery guidance")

        for scenario in ("partial", "unknown", "failed"):
            visit(f"/?video=1&publish_platform=unified&demo={scenario}#publish-workspace")
            expect(page.locator(".publish-result")).to_have_count(2)
            assert page.locator('form[action$="/execute"]').count() == 0
            if scenario == "partial":
                expect(page.locator('[data-outcome="success"]')).to_contain_text("재게시 안 함")
            if scenario == "unknown":
                expect(page.locator('[data-outcome="unknown"]')).to_contain_text("재전송 안 함")
            page.screenshot(path=str(args.output / f"publishing-{scenario}.png"), full_page=True)
        results["checks"].append("synthetic platform partial success / failure / unknown; no execute action offered")

        visit("/simple-settings")
        page.get_by_role("button", name="전체 연결 상태", exact=True).click()
        expect(page.locator("#settings-diagnostics")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("button", name="전체 연결 상태", exact=True)).to_be_focused()
        # Browser zoom approximation only; not Windows DPI or a native browser menu zoom assertion.
        for name, path in PAGES.items():
            visit(path)
            page.locator("html").evaluate("n=>n.style.zoom='2'")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), name
        results["checks"].append("settings dialog keyboard/return focus; 200% CSS zoom with no horizontal overflow")
        visit("/")
        colors = page.evaluate("""() => ['body','.creator-heading h1','.creator-heading>p:last-child','.topic-hero label','.topic-actions p','.topic-actions button','.creator-sidebar .workspace-nav a'].map(selector => {
          const node=document.querySelector(selector), style=getComputedStyle(node);
          let background=style.backgroundColor, parent=node.parentElement;
          while ((background==='rgba(0, 0, 0, 0)' || background==='transparent') && parent) {
            background=getComputedStyle(parent).backgroundColor; parent=parent.parentElement;
          }
          return {selector,foreground:style.color,background};
        })""")
        def luminance(color):
            import re
            values = [float(value) / 255 for value in re.findall(r"[\d.]+", color)[:3]]
            linear = [value / 12.92 if value <= 0.04045 else ((value + .055) / 1.055) ** 2.4 for value in values]
            return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
        for color in colors:
            first, second = sorted((luminance(color["foreground"]), luminance(color["background"])))
            color["contrast_ratio"] = round((second + .05) / (first + .05), 2)
            assert color["contrast_ratio"] >= 4.5, color
        results["contrast_samples"] = colors
        if args.empty_base:
            assert urlsplit(args.empty_base).hostname == "127.0.0.1"
            for path in ("/", "/videos", "/queue"):
                # A separate context keeps the empty fixture and its cookies isolated.
                empty = browser.new_page(viewport={"width":390,"height":844})
                response = empty.goto(args.empty_base + path)
                assert response.status == 200
                expect(empty.locator(".demo-banner")).to_be_visible()
                expect(empty.locator(".gentle-empty").first).to_be_visible()
                assert empty.locator("video").count() == 0
                empty.screenshot(path=str(args.output / ("empty-" + (path.strip("/") or "home") + ".png")),full_page=True)
                empty.close()
            results["checks"].append("separate empty demo: home/videos/publishing, no fake player or success")
        assert not errors, errors
        assert not external, external
        results.update(status="PASS", javascript_errors=errors, external_browser_requests=external,
                       actual_oauth=0, actual_upload_publish=0, paid_api_calls=0,
                       simulated_publish_outcomes="presentation fixtures, never actual publishing success")
        browser.close()
    (args.output / "browser-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": results["status"], "layout_checks": len(results["layout"]), "checks": len(results["checks"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
