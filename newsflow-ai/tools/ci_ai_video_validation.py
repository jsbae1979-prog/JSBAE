"""Phase 5D AI high-quality mode through the real GUI with the offline Fake provider.

The fixture server (public app factory) runs with ``--fake-video-provider``: nothing leaves the
machine and no Higgsfield request is possible. The browser walks the whole user path: default
off, settings refusals, approval and limits, model entry, storyboard, prompt policy refusal,
budget refusal, paid confirmation, async generation, duplicate refusal, restart recovery
without resubmission, relation review, compose approval and the final MP4 (real FFmpeg) with
the burned-in AI label. Vendor behaviour, prices and quality stay NOT VERIFIED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from ci_autopilot_validation import notice, submit
from ci_validation import BASE, HTTP, ROOT, STARTUP_ERROR, child_env, start, stop

MODEL = "vendor/model/text-to-video"
PROMPT = "도시 경제를 상징하는 푸른 추상 파동"
LABEL_POINTS = ((150, 540), (930, 540))


def server(data: Path, env: dict) -> subprocess.Popen:
    command = [sys.executable, str(ROOT / "tools/ci_fixture_server.py"), "--data-dir", str(data), "--fake-video-provider"]
    return start(command, env, 90)


def seed(data: Path) -> int:
    """One real-looking (non-sample) article and its offline draft, written before the server starts."""
    from newsflow.config import Settings
    from newsflow.db.models import NewsArticle
    from newsflow.intelligence.service import IntelligenceService
    from newsflow.main import create_app
    from newsflow.news.rss_adapter import FakeRSSAdapter

    app = create_app(Settings(data_dir=data), FakeRSSAdapter({}))
    try:
        with app.state.sessions.begin() as session:
            article = NewsArticle(
                title="CI AI 영상 검증용 합성 뉴스", summary="기관 발표를 전했다는 합성 요약입니다.",
                url="https://example.com/ci-ai-video", canonical_url="https://example.com/ci-ai-video",
                source_id=1, publisher="합성 출처",
            )
            session.add(article)
            session.flush()
            article_id = article.id
        ai = IntelligenceService(app.state.sessions)
        return ai.generate(ai.analyze([article_id]), 30)
    finally:
        app.state.video_ai.close()
        app.state.video.close()
        app.state.engine.dispose()


def db_rows(data: Path, query: str, args: tuple = ()) -> list[tuple]:
    with closing(sqlite3.connect(data / "newsflow.db")) as db:
        return db.execute(query, args).fetchall()


def plan_state(plan_id: int) -> dict:
    return json.loads(HTTP().get(f"/api/video/ai/plans/{plan_id}"))


def wait_scene(plan_id: int, position: int, statuses: set[str], timeout: float = 180) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = plan_state(plan_id)
        scene = state["scenes"][position]
        if scene["status"] in statuses:
            return state
        assert scene["status"] not in {"failed", "nsfw", "canceled", "unknown"} - statuses, scene
        time.sleep(0.5)
    raise AssertionError(f"scene deadline: {statuses}")


def wait_render(job_id: int, timeout: float = 420) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = json.loads(HTTP().get(f"/api/video/jobs/{job_id}"))
        if job["status"] in {"success", "failed", "interrupted", "simulated"}:
            assert job["status"] == "success", job.get("message")
            return job
        time.sleep(0.5)
    raise AssertionError("render deadline")


def refused(page, form, path: str, status: int, text: str) -> None:
    """A refusal keeps the page and shows the server's fixed sentence (JSON detail) next to the form."""
    with page.expect_response(lambda r: r.request.method == "POST" and urlsplit(r.url).path == path) as response:
        form.locator('button[type="submit"]').click()
    assert response.value.status == status, (path, response.value.status)
    form.locator("[data-submit-error]").filter(has_text=text).wait_for()


def post_status(path: str, fields: dict, origin: str = BASE) -> int:
    client = HTTP()
    client.get("/settings")
    token = next(cookie.value for cookie in client.cookies if cookie.name == "newsflow_csrf")
    request = Request(BASE + path, data=urlencode({**fields, "csrf_token": token}).encode(), headers={"Origin": origin})
    try:
        with client.opener.open(request, timeout=5) as response:
            return response.status
    except HTTPError as error:
        try:
            return error.code
        finally:
            error.close()


def forged_origin_post(path: str) -> int:
    return post_status(path, {}, "http://evil.example")


def headers(path: str) -> dict:
    client = HTTP()
    with client.opener.open(BASE + path, timeout=5) as response:
        return {key.lower(): value for key, value in response.headers.items()}


def frame(video: Path, seconds: float, target: Path):
    from PIL import Image

    subprocess.run(
        [shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-ss", f"{seconds:.3f}",
         "-i", str(video), "-frames:v", "1", str(target)],
        capture_output=True, timeout=60, check=True,
    )
    with Image.open(target) as image:
        return image.convert("RGB")


def yellow(pixel: tuple) -> bool:
    red, green, blue = pixel[:3]
    return red >= 235 and 170 <= green <= 220 and blue <= 50


def playback(page, selector: str) -> str:
    decodable = page.evaluate("() => document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E\"')")
    if not decodable:
        return "NOT VERIFIED (this Chromium has no H.264 decoder; the Windows Chrome run verifies playback)"
    video = page.locator(selector).first
    video.wait_for()
    page.wait_for_function(
        "s => {const v=document.querySelector(s);return v && (v.error || v.readyState>=1);}", arg=selector, timeout=30000)
    assert video.evaluate("v => v.error ? 1 : 0") == 0
    video.evaluate("async v => {v.muted=true;v.currentTime=0;await v.play();}")
    page.wait_for_function(
        "s => {const v=document.querySelector(s);return v.error || (v.currentTime>=1 && !v.paused);}", arg=selector, timeout=30000)
    video.evaluate("v => v.pause()")
    return "PASS (playback time advanced)"


def flow(mode: str, data: Path, env: dict, output: Path, executable: str | None, result: dict) -> None:
    from playwright.sync_api import sync_playwright

    draft_id = seed(data)
    process = server(data, env)
    external: set[str] = set()
    errors: list[str] = []
    with sync_playwright() as playwright:
        options: dict = {"headless": True}
        if executable:
            options["executable_path"] = executable
        elif mode == "windows":
            options["channel"] = "chrome"
        if mode == "cloud":
            options["args"] = ["--no-sandbox"]
        browser = playwright.chromium.launch(**options)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(30000)

        def record(request) -> None:
            parts = urlsplit(request.url)
            origin = f"{parts.scheme}://{parts.netloc}"
            if parts.scheme in {"http", "https"} and origin != BASE:
                external.add(origin)

        page.on("request", record)
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        try:
            # 1. Default: AI mode off, basic FFmpeg mode untouched.
            page.goto(f"{BASE}/video/ai?draft_id={draft_id}")
            ready = page.locator("#video-ai-ready").inner_text()
            assert "AI 영상 사용 불가" in ready and "테스트 전용 Fake 공급자" in ready
            assert "기본 모드 · 로컬 FFmpeg" in page.content()
            page.screenshot(path=str(output / "ai-home-default-off.png"), full_page=True)
            page.goto(f"{BASE}/video?draft_id={draft_id}")
            assert page.locator("#video-ai-link").is_visible() and "외부 영상 API 없음" in page.content()
            nav = page.locator('nav[aria-label="주 메뉴"] a').count()
            assert nav == 6, nav
            result["default_off_and_basic_mode"] = "PASS (AI mode unavailable until approved; Video Studio unchanged; 6 menus)"

            # 2. Settings: refusal without limits, then approval, limits and a confirmed model.
            page.goto(BASE + "/video-ai-settings")
            form = page.locator("#video-ai-settings-form")
            form.locator("#video-ai-provider").select_option("higgsfield")
            form.locator('input[name="approved"]').check()
            refused(page, form, "/video-ai-settings", 422, "0보다 큰 작업별 한도와 월 한도")
            form.locator("#video-ai-job-limit").fill("0.5")
            form.locator("#video-ai-monthly-limit").fill("20")
            form.locator("#video-ai-poll").fill("5")
            submit(page, form, "/video-ai-settings")
            model = page.locator("#video-ai-model-new")
            model.locator("#new-model-path").fill(MODEL)
            model.locator("#new-model-label").fill("CI 시험 모델")
            model.locator("#new-model-price").fill("0.1")
            model.locator("#new-model-durations").fill("5,10")
            model.locator('input[name="confirmed"]').check()
            submit(page, model, "/video-ai-settings/models")
            assert "AI 영상 사용 가능" in page.locator("#video-ai-status").inner_text()
            page.screenshot(path=str(output / "ai-settings.png"), full_page=True)
            result["settings_gate"] = "PASS (approval refused without limits; approval, limits and confirmed model saved)"

            # 3. Plan and storyboard: the prompt policy refuses footage-like wording.
            page.goto(f"{BASE}/video/ai?draft_id={draft_id}")
            new = page.locator("#video-ai-new")
            new.locator('input[name="duration"][value="30"]').check()
            submit(page, new, "/video/ai/plans")
            page.wait_for_url(re.compile(re.escape(BASE) + r"/video/ai/plans/\d+"))
            plan_id = int(re.search(r"/video/ai/plans/(\d+)", page.url).group(1))
            board = page.locator("#storyboard-form")
            board.locator("#source-0").select_option("generated")
            board.locator("#model-0").select_option(MODEL)
            board.locator("#prompt-0").fill("사고 현장 실제 영상처럼 보이게")
            refused(page, board, f"/video/ai/plans/{plan_id}/scenes", 422, "실제 뉴스 현장")
            board.locator("#prompt-0").fill(PROMPT)
            submit(page, board, f"/video/ai/plans/{plan_id}/scenes")
            page.screenshot(path=str(output / "ai-plan-storyboard.png"), full_page=True)
            assert "예상 합계" in page.locator("#cost-summary").inner_text()
            result["storyboard_and_prompt_policy"] = "PASS (scene source/prompt/model saved; footage-like prompt refused before any call)"

            # 4. Paid confirmation: refused over the per-job limit, accepted after raising it.
            cost = page.locator("#cost-form")
            cost.locator('input[name="confirmed"]').check()
            refused(page, cost, f"/video/ai/plans/{plan_id}/confirm", 422, "작업별 한도")
            assert db_rows(data, "SELECT COUNT(*) FROM video_ai_usage")[0][0] == 0
            page.goto(BASE + "/video-ai-settings")
            form = page.locator("#video-ai-settings-form")
            form.locator("#video-ai-job-limit").fill("5")
            submit(page, form, "/video-ai-settings")
            page.goto(f"{BASE}/video/ai/plans/{plan_id}")
            revision_before = plan_state(plan_id)["revision"]
            page.screenshot(path=str(output / "ai-plan-cost.png"), full_page=True)
            cost = page.locator("#cost-form")
            cost.locator('input[name="confirmed"]').check()
            submit(page, cost, f"/video/ai/plans/{plan_id}/confirm")
            resend = post_status(
                f"/video/ai/plans/{plan_id}/confirm",
                {"revision": str(revision_before), "shown_total": "1", "confirmed": "true"},
            )
            assert resend in (409, 422), resend  # nothing left to generate, or a stale revision
            rows = db_rows(data, "SELECT status, attempt FROM video_ai_usage WHERE plan_id=?", (plan_id,))
            assert len(rows) == 1 and rows[0][1] == 1, rows
            result["budget_and_duplicate"] = (
                f"PASS (per-job limit refusal with 0 usage rows; confirm accepted once; resend refused {resend}; 1 reservation)")

            # 5. Async generation with the Fake provider, then the clip preview.
            wait_scene(plan_id, 0, {"ready"})
            page.goto(f"{BASE}/video/ai/plans/{plan_id}")
            preview = playback(page, "video.ai-clip-preview")
            page.screenshot(path=str(output / "ai-plan-ready.png"), full_page=True)
            scene = db_rows(data, "SELECT id, clip_name, clip_meta, request_id FROM ai_video_scenes WHERE plan_id=? AND position=0", (plan_id,))[0]
            clip_bytes = HTTP().get(f"/video/ai/scenes/{scene[0]}/clip", timeout=10)
            meta = json.loads(scene[2])
            assert hashlib.sha256(clip_bytes).hexdigest() == meta["sha256"] and meta["format"] == "mov"
            result["async_generation"] = f"PASS (waiting → queued → completed → downloaded and probed; clip preview {preview})"

            # 6. In-flight scene across a restart: never resubmitted.
            page.goto(f"{BASE}/video/ai?draft_id={draft_id}")
            new = page.locator("#video-ai-new")
            new.locator('input[name="duration"][value="30"]').check()
            submit(page, new, "/video/ai/plans")
            page.wait_for_url(re.compile(re.escape(BASE) + r"/video/ai/plans/\d+"))
            slow_id = int(re.search(r"/video/ai/plans/(\d+)", page.url).group(1))
            board = page.locator("#storyboard-form")
            board.locator("#source-0").select_option("generated")
            board.locator("#model-0").select_option(MODEL)
            board.locator("#prompt-0").fill(PROMPT + " [fake:slow]")
            submit(page, board, f"/video/ai/plans/{slow_id}/scenes")
            cost = page.locator("#cost-form")
            cost.locator('input[name="confirmed"]').check()
            submit(page, cost, f"/video/ai/plans/{slow_id}/confirm")
            wait_scene(slow_id, 0, {"queued", "in_progress"})
            before = db_rows(data, "SELECT id, attempt, status, request_id FROM video_ai_usage ORDER BY id")
            usage_before = len(before)
            page.goto("about:blank")
            stop(process)
            process = server(data, env)
            time.sleep(12)  # at least two worker passes at the 5 s poll interval
            after = db_rows(data, "SELECT id, attempt, status, request_id FROM video_ai_usage ORDER BY id")
            assert len(after) == usage_before and [r[3] for r in after] == [r[3] for r in before], (before, after)
            slow = plan_state(slow_id)["scenes"][0]
            assert slow["status"] in {"queued", "in_progress"}, slow
            assert plan_state(plan_id)["scenes"][0]["status"] == "ready"
            assert HTTP().get(f"/video/ai/scenes/{scene[0]}/clip", timeout=10) == clip_bytes
            result["restart_recovery"] = (
                "PASS (after a restart the in-flight scene keeps its request id and is only polled; no new submission; "
                "ready clip and usage rows persist)")

            # 7. Relation review and compose approval through the existing FFmpeg path.
            page.goto(f"{BASE}/video/ai/plans/{plan_id}")
            compose = page.locator("#compose-form")
            compose.locator('input[name="approved"]').check()
            refused(page, compose, f"/video/ai/plans/{plan_id}/approve", 422, "검토")
            page.goto(f"{BASE}/video/ai/plans/{plan_id}")
            review = page.locator("#relation-review")
            review.locator('input[name="reviewed_0"]').check()
            review.locator('input[name="statement"]').check()
            submit(page, review, f"/video/ai/plans/{plan_id}/review")
            page.screenshot(path=str(output / "ai-plan-reviewed.png"), full_page=True)
            compose = page.locator("#compose-form")
            compose.locator('input[name="approved"]').check()
            submit(page, compose, f"/video/ai/plans/{plan_id}/approve")
            page.wait_for_url(re.compile(re.escape(BASE) + r"/video\?job_id=\d+"))
            job_id = int(page.url.rsplit("=", 1)[1])
            wait_render(job_id)
            page.goto("about:blank")
            page.goto(f"{BASE}/video?job_id={job_id}")
            assert page.locator("#job-ai-notice").is_visible()
            final_playback = playback(page, "video")
            page.screenshot(path=str(output / "ai-job-page.png"), full_page=True)
            assert plan_state(plan_id)["status"] == "composed"

            # 8. The final MP4: real FFmpeg, labelled AI scene, card scenes unlabelled.
            from newsflow.publishing.media import FFprobeMediaInspector

            content = HTTP().get(f"/video/jobs/{job_id}/file?download=true", timeout=30)
            final = output / "ai-final.mp4"
            final.write_bytes(content)
            media = FFprobeMediaInspector().inspect(final)
            assert media["video_codec"] == "h264" and media["audio_codec"] == "aac"
            assert (media["width"], media["height"]) == (1080, 1920) and abs(media["duration"] - 30) < 0.25
            ai_frame = frame(final, 1.0, output / "ai-final-frame-ai-scene.png")
            card_frame = frame(final, 25.0, output / "ai-final-frame-card-scene.png")
            assert all(yellow(ai_frame.getpixel(point)) for point in LABEL_POINTS)
            assert not any(yellow(card_frame.getpixel(point)) for point in LABEL_POINTS)
            metadata = json.loads(db_rows(data, "SELECT metadata_json FROM render_jobs WHERE id=?", (job_id,))[0][0] or "{}")
            assert metadata.get("ai_generated_scenes") == [0] and metadata.get("ai_plan_id") == plan_id
            assert [clip["sha256"] for clip in metadata.get("ai_clips", [])] == [meta["sha256"]]
            result["final_mp4"] = {
                "status": "PASS", "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
                "duration": media["duration"], "browser_playback": final_playback,
                "ai_label_in_ai_scene": True, "ai_label_in_card_scene": False,
                "ai_generated_scenes": metadata["ai_generated_scenes"], "reviewed_clip_hash_recorded": True,
                "human_watch_quality": "NOT VERIFIED",
            }
            page.goto(BASE + "/videos")
            assert "AI 생성 장면 포함" in page.content()
            page.screenshot(path=str(output / "ai-library.png"), full_page=True)

            # 9. Security and separation evidence.
            assert forged_origin_post(f"/video/ai/plans/{plan_id}/approve") == 403
            csp = headers("/video/ai").get("content-security-policy", "")
            assert "default-src 'self'" in csp and "script-src 'self'" in csp
            settings = dict(db_rows(data, "SELECT key, value FROM app_settings WHERE key LIKE 'video_ai_%'"))
            assert not any("Key " in value or ":" in value and len(value) > 40 for key, value in settings.items() if key != "video_ai_approved_at")
            openai_usage = db_rows(data, "SELECT COUNT(*) FROM ai_usage")[0][0]
            usage_rows = db_rows(data, "SELECT provider, status, estimated_cost, currency FROM video_ai_usage ORDER BY id")
            assert all(row[0] == "fake" for row in usage_rows)
            assert not errors and not external, (errors, external)
            result["security"] = (
                "PASS (forged origin POST 403; CSP self-only; no key in app_settings; separate video_ai_usage; "
                "no browser request outside 127.0.0.1)")
            result["database"] = {
                "video_ai_usage": [{"provider": p, "status": s, "estimated_cost": c, "currency": u} for p, s, c, u in usage_rows],
                "openai_ai_usage_rows": openai_usage,
                "clip_files": len(list((data / "ai-clips").glob("clip-*"))),
            }
            result["screenshots"] = sorted(p.name for p in output.glob("*.png"))
        except BaseException:
            try:
                page.screenshot(path=str(output / "failure.png"), full_page=True)
            except Exception:  # noqa: BLE001, S110 - the original failure matters more
                pass
            raise
        finally:
            browser.close()
            stop(process)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("cloud", "windows"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "tool": "ci_ai_video_validation", "mode": args.mode, "provider": "FakeVideoProvider (offline, injected)",
        "higgsfield_api_calls": 0, "higgsfield_vendor_behaviour": "NOT VERIFIED", "generated_video_quality": "NOT VERIFIED",
    }
    outcome = "FAIL"
    try:
        with TemporaryDirectory(prefix="newsflow-ai-video-") as directory:
            flow(args.mode, Path(directory) / "data", child_env(), args.output, args.browser_executable, result)
        outcome = "PASS"
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {str(error)[:300]}"
        if STARTUP_ERROR:
            result["startup_error"] = dict(STARTUP_ERROR)
        raise
    finally:
        result["outcome"] = outcome
        (args.output / "ai-video-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = {key: value for key, value in result.items() if key not in {"database", "screenshots", "final_mp4"}}
        summary["final_mp4"] = (result.get("final_mp4") or {}).get("status", "n/a")
        notice("Phase 5D AI video", summary)


if __name__ == "__main__":
    main()
