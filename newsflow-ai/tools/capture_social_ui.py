"""Capture an already running isolated preview; deny all other browser requests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:47965")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    args = parser.parse_args()
    if urlsplit(args.origin).hostname != "127.0.0.1":
        raise SystemExit("Use the isolated loopback preview only.")
    args.out.mkdir(parents=True, exist_ok=False)
    results, external, errors = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.browser, headless=True)
        context = browser.new_context(locale="ko-KR", reduced_motion="reduce")

        def guard(route):
            if route.request.url.startswith(args.origin + "/"):
                route.continue_()
            else:
                external.append(urlsplit(route.request.url).hostname)
                route.abort()

        context.route("**/*", guard)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        for width, height in [(1920, 1080), (1366, 768), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            for name, path in [
                ("news", "/news"),
                ("script", "/ai?draft_id=1"),
                ("video", "/video?draft_id=1"),
                ("publish", "/queue"),
                ("analytics", "/analytics"),
                ("settings", "/simple-settings"),
                ("accounts", "/simple-settings#accounts"),
            ]:
                response = page.goto(args.origin + path)
                if response is None:
                    response = page.reload()
                page.wait_for_load_state("networkidle")
                assert page.locator(".demo-banner").count() > 0, "Not a demo; do not capture production data."
                playback = page.locator("video").evaluate_all(
                    """async videos => {const results=[]; for(const video of videos){ video.muted=true;try{await video.play();video.pause(); results.push({ready:video.readyState,width:video.videoWidth,height:video.videoHeight,duration:video.duration});}catch(e){results.push({error:String(e)});}} return results;}"""
                )
                metrics = page.evaluate("""()=>({overflow:document.documentElement.scrollWidth>innerWidth,
                    outside:[...document.querySelectorAll('input,select,button,a.button')].filter(e=>e.getClientRects().length && e.getBoundingClientRect().right>innerWidth+1).map(e=>e.textContent.trim().slice(0,50))})""")
                page.screenshot(path=str(args.out / f"{name}-{width}.png"))
                results.append(
                    {
                        "page": name,
                        "viewport": f"{width}x{height}",
                        "http": response.status,
                        "synthetic": True,
                        "playback": playback,
                        **metrics,
                    }
                )
        (args.out / "browser-audit.json").write_text(
            json.dumps(
                {
                    "environment": "Cloud Linux Chromium, not Windows display scaling",
                    "pages": results,
                    "external_requests": external,
                    "javascript_errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        browser.close()
    assert not external and not errors
    assert all(r["http"] == 200 and not r["overflow"] and not r["outside"] for r in results)
    print(f"{len(results)} page/viewport checks passed; no outbound browser requests.")


if __name__ == "__main__":
    main()
