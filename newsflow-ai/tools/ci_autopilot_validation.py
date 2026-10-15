"""Actual Easy UI/BAT/local-MP4 validation; synthetic news, no external services."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from ci_validation import BASE, HTTP, ROOT, STARTUP_ERROR, child_env, start, stop


def notice(name: str, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    assert len(payload.encode()) <= 4000, "CI evidence exceeds check annotation limit"
    payload = payload.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::notice title=NewsFlow {name}::{payload}")


def submit(page, form, path: str) -> None:
    with page.expect_response(lambda r: r.request.method == "POST" and urlsplit(r.url).path == path) as response:
        form.locator('button[type="submit"]').click()
    assert response.value.status == 303, f"POST failed: {path}"
    assert response.value.request.all_headers().get("origin") == BASE
    # Fetch-driven HTML forms navigate only after the redirected response loads.
    page.wait_for_timeout(250)
    page.wait_for_load_state("domcontentloaded")


def snapshot(job_id: str) -> dict:
    assert re.fullmatch(r"[0-9a-f]{32}", job_id)
    return json.loads(HTTP().get(f"/api/autopilot/jobs/{job_id}"))


def wait_job(job_id: str, status: str, stage: str | None = None, timeout: int = 420) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = snapshot(job_id)
        if state["status"] == status and (stage is None or state["current_stage"] == stage):
            return state
        assert state["status"] not in {"failed", "interrupted", "cancelled"}, (
            f"Job stopped: {state['current_stage']}/{state['error_code']}"
        )
        time.sleep(0.2)
    raise AssertionError(f"Job deadline: {status}/{stage}")


def open_job(page, job_id: str) -> None:
    from playwright.sync_api import Error as PlaywrightError

    for attempt in range(3):
        try:
            page.goto(f"{BASE}/autopilot/jobs/{job_id}")
            break
        except PlaywrightError as error:
            # The job page reloads itself when the stage changes; a goto that races that
            # reload is reported as interrupted. The page ends up at the same URL either way.
            if "interrupted by another navigation" not in str(error) or attempt == 2:
                raise
            page.wait_for_load_state("domcontentloaded")
    page.locator(f'[data-autopilot-job="{job_id}"]').wait_for()


def begin(page, mode: str = "easy", source: str = "sample") -> str:
    page.goto(BASE + "/autopilot/start")
    form = page.locator('form[action="/autopilot/start"]')
    form.locator(f'input[name="mode"][value="{mode}"]').check()
    form.locator('input[name="duration"][value="30"]').check()
    form.locator(f'input[name="source"][value="{source}"]').check()
    submit(page, form, "/autopilot/start")
    page.wait_for_url(re.compile(re.escape(BASE) + r"/autopilot/jobs/[0-9a-f]{32}$"))
    return page.url.rsplit("/", 1)[1]


def advance(page, job_id: str) -> None:
    open_job(page, job_id)
    path = f"/autopilot/jobs/{job_id}/resume"
    submit(page, page.locator(f'form[action="{path}"]'), path)


def database_evidence(root: Path) -> dict:
    with closing(sqlite3.connect(root / "newsflow.db")) as db:
        counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "autopilot_jobs", "autopilot_attempts", "autopilot_events", "autopilot_artifacts",
            "news_articles", "content_drafts", "video_projects", "render_jobs",
            "publish_drafts", "publish_validations", "publish_jobs", "publish_attempts",
        )}
        assert counts["publish_jobs"] == counts["publish_attempts"] == 0
        approvals = db.execute("SELECT content_reviewed,copyright_confirmed,sources_confirmed,account_id,state FROM publish_drafts").fetchall()
        assert approvals and all(row[:4] == (0, 0, 0, None) for row in approvals)
        assert all(row[4] not in {"ready", "approved", "success"} for row in approvals)
        assert db.execute("SELECT COUNT(*) FROM content_drafts WHERE review_status != 'review_required'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM video_projects WHERE preview_only != 1").fetchone()[0] == 0
        providers = [row[0] for row in db.execute("SELECT DISTINCT provider FROM intelligence_runs")]
        assert providers == ["offline"]
        assert db.execute("SELECT COUNT(*) FROM platform_accounts WHERE credential_ref IS NOT NULL OR api_ready = 1").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM news_sources WHERE enabled = 1").fetchone()[0] == 0
        return {"counts": counts, "AI_providers": providers, "human_approval_preserved": True,
                "review_only_video": True, "real_connected_accounts": 0, "enabled_RSS_sources": 0}


def media_evidence(page, job: dict, output: Path, filename: str) -> dict:
    from newsflow.publishing.media import FFprobeMediaInspector

    page.locator("video").wait_for()
    page.wait_for_function("() => {const v=document.querySelector('video');return v && (v.error || v.readyState>=1);}", timeout=30000)
    dimensions = page.locator("video").evaluate("v => ({width:v.videoWidth,height:v.videoHeight,error:v.error ? v.error.code : null})")
    assert dimensions == {"width": 1080, "height": 1920, "error": None}
    page.locator("video").evaluate("async v => {v.muted=true;v.currentTime=0;await v.play();}")
    page.wait_for_function("() => {const v=document.querySelector('video');return v.error || (v.currentTime>=1 && !v.paused && !v.seeking);}", timeout=30000)
    assert page.locator("video").evaluate("v => v.error === null")
    page.locator("video").evaluate("v => v.pause()")
    page.wait_for_timeout(250)
    content = HTTP().get(f"/video/jobs/{job['render_job_id']}/file?download=true")
    assert len(content) > 1000
    path = output / filename
    path.write_bytes(content)
    meta = FFprobeMediaInspector().inspect(path)
    assert meta["video_codec"] == "h264" and meta["audio_codec"] == "aac"
    assert (meta["width"], meta["height"]) == (1080, 1920)
    assert abs(meta["duration"] - 30) < 0.2
    return {"file": filename, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
            "metadata": meta, "browser_frame_decode": "PASS", "browser_playback": "PASS (playback time advanced)", "audio": "offline silence",
            "human_voice_and_editorial_quality": "NOT VERIFIED"}


def layout(page, output: Path, job_id: str) -> dict:
    checks = []
    for width, height, zoom, label in ((320, 800, "1", "mobile-320"), (1440, 1000, "2", "desktop-200percent")):
        page.set_viewport_size({"width": width, "height": height})
        for path, name in (("/", "home"), ("/autopilot/start", "start"), (f"/autopilot/jobs/{job_id}", "result"), ("/queue", "queue"), ("/simple-settings", "settings")):
            page.goto(BASE + path)
            # Real CSS zoom exercises reflow; deviceScaleFactor alone does not.
            page.locator("html").evaluate("(node, zoom) => {node.style.zoom=zoom}", zoom)
            page.wait_for_timeout(100)
            dims = page.evaluate("({content:document.documentElement.scrollWidth,viewport:document.documentElement.clientWidth})")
            assert dims["content"] <= dims["viewport"] + 2, f"Overflow: {label}/{name}"
            assert page.get_by_role("heading", level=1).is_visible()
            checks.append(f"{label}/{name}")
            if name == "home":
                page.screenshot(path=str(output / f"{label}.png"), full_page=True)
        page.goto(BASE + "/autopilot/start")
        page.locator("html").evaluate("(node, zoom) => {node.style.zoom=zoom}", zoom)
        button = page.locator('form[action="/autopilot/start"] button[type=submit]')
        button.scroll_into_view_if_needed()
        assert button.is_visible() and button.is_enabled()
    page.set_viewport_size({"width": 1440, "height": 1000})
    return {"status": "PASS", "checks": checks, "zoom_method": "CSS zoom 200%", "user_usability_study": "NOT VERIFIED"}


def validate(mode: str, root: Path, env: dict, output: Path, executable: str | None, result: dict) -> None:
    from playwright.sync_api import sync_playwright

    command = ["cmd.exe", "/d", "/c", str(ROOT / "run.bat")] if mode == "windows" else [sys.executable, "-m", "newsflow.main"]
    process = start(command, env, 180 if mode == "windows" else 30)
    result["actual_run_bat"] = "PASS" if mode == "windows" else "NOT VERIFIED (Cloud Linux)"
    external_origins: set[str] = set()
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

        def inspect_request(request) -> None:
            parsed = urlsplit(request.url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if parsed.scheme in {"http", "https"} and origin != BASE:
                external_origins.add(origin)

        page.on("request", inspect_request)
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        try:
            result["browser"] = "Google Chrome" if options.get("channel") == "chrome" else "Chromium"
            page.goto(BASE)
            assert page.get_by_role("button", name="자동 제작 시작", exact=False).is_visible()
            page.screenshot(path=str(output / "dashboard.png"), full_page=True)
            page.goto(BASE + "/autopilot/start")
            page.screenshot(path=str(output / "start.png"), full_page=True)
            page.goto(BASE)
            submit(page, page.locator('form[action="/autopilot/start"]'), "/autopilot/start")
            page.wait_for_url(re.compile(re.escape(BASE) + r"/autopilot/jobs/[0-9a-f]{32}$"))
            easy_id = page.url.rsplit("/", 1)[1]
            result["easy_job_id"] = easy_id
            running = wait_job(easy_id, "running", "render")
            assert 0 < running["progress"] < 100
            open_job(page, easy_id)
            page.screenshot(path=str(output / "progress.png"), full_page=True)
            result["progress_observed"] = {"stage": running["current_stage"], "progress": running["progress"]}
            HTTP().blocked_post("/autopilot/start", 409, {"mode": "easy", "source": "sample", "duration": "30", "platform": "youtube"})
            result["duplicate_start"] = "PASS (409)"
            easy = wait_job(easy_id, "completed")
            assert set(easy["stage_results"]) == {"collect", "select", "script", "render", "validate", "queue"}
            assert easy["progress"] == 100 and easy["publish_draft_id"]
            open_job(page, easy_id)
            result["easy_video"] = media_evidence(page, easy, output, "easy-30s.mp4")
            page.screenshot(path=str(output / "completed-video.png"), full_page=True)
            page.get_by_role("link", name="게시 대기함에서 확인", exact=False).click()
            page.locator(f"#draft-{easy['publish_draft_id']}").wait_for()
            assert page.get_by_text("검토 대기", exact=True).count() == 1
            page.screenshot(path=str(output / "queue.png"), full_page=True)
            result["one_click_easy_to_local_queue"] = "PASS"

            guided_id = begin(page, "guided")
            selected = wait_job(guided_id, "waiting_review", "select")
            assert selected["article_id"] != easy["article_id"], "Same news duplicated"
            advance(page, guided_id)
            script = wait_job(guided_id, "waiting_review", "script")
            open_job(page, guided_id)
            page.screenshot(path=str(output / "guided-script-review.png"), full_page=True)
            page.get_by_role("link", name="대본 수정", exact=False).click()
            edit_path = f"/ai/drafts/{script['content_draft_id']}"
            edit = page.locator(f'form[action="{edit_path}"]')
            edit.locator('input[name="title"]').fill("체험 뉴스의 새로운 이야기 · 검토용 수정 대본")
            submit(page, edit, edit_path)
            with closing(sqlite3.connect(root / "newsflow.db")) as db:
                draft = db.execute("SELECT revision,content FROM content_drafts WHERE id=?", (script["content_draft_id"],)).fetchone()
            assert draft[0] == 2 and json.loads(draft[1])["title"] == "체험 뉴스의 새로운 이야기 · 검토용 수정 대본"
            before = database_evidence(root)
            stop(process)
            process = start(command, env, 90)
            assert database_evidence(root) == before
            restored = snapshot(guided_id)
            assert restored["status"] == "waiting_review" and restored["content_draft_id"] == script["content_draft_id"]
            assert snapshot(easy_id)["status"] == "completed"
            assert hashlib.sha256(HTTP().get(f"/video/jobs/{easy['render_job_id']}/file")).hexdigest() == result["easy_video"]["sha256"]
            result["process_restart_persistence"] = "PASS (pause, edited script, MP4, queue)"
            advance(page, guided_id)
            guided = wait_job(guided_id, "waiting_review", "validate")
            assert not guided.get("publish_draft_id"), "Queue requires explicit guided confirmation"
            open_job(page, guided_id)
            result["guided_video"] = media_evidence(page, guided, output, "guided-30s.mp4")
            page.screenshot(path=str(output / "guided-video-review.png"), full_page=True)
            advance(page, guided_id)
            guided = wait_job(guided_id, "completed")
            assert guided["publish_draft_id"] != easy["publish_draft_id"]
            result["guided_news_script_edit_video_review_queue"] = "PASS"

            cancelled_id = begin(page, "guided")
            wait_job(cancelled_id, "waiting_review", "select")
            open_job(page, cancelled_id)
            cancel_path = f"/autopilot/jobs/{cancelled_id}/cancel"
            submit(page, page.locator(f'form[action="{cancel_path}"]'), cancel_path)
            cancelled = wait_job(cancelled_id, "cancelled")
            assert not cancelled.get("render_job_id") and not cancelled.get("publish_draft_id")
            result["guided_cancel"] = "PASS"
            # A genuine no-enabled-feed error; no test backend or security override.
            error_id = begin(page, source="feeds")
            failed = wait_job(error_id, "failed")
            assert failed["current_stage"] == "collect" and failed["progress"] < 100
            assert failed["error_code"] == "no_sources"
            open_job(page, error_id)
            assert page.locator("#error-title").is_visible()
            assert page.get_by_role("heading", name="이렇게 해 보세요", exact=True).is_visible()
            assert page.get_by_role("link", name="뉴스 출처 설정", exact=True).is_visible()
            page.screenshot(path=str(output / "error-guidance.png"), full_page=True)
            result["actionable_no_source_error"] = "PASS"

            page.goto(BASE + "/simple-settings")
            settings = page.locator('form[action="/simple-settings"]')
            settings.locator('select[name="duration"]').select_option("45")
            submit(page, settings, "/simple-settings")
            page.get_by_text("기본 설정을 저장했습니다.", exact=False).wait_for()
            page.screenshot(path=str(output / "simple-settings.png"), full_page=True)
            page.goto(BASE)
            assert "45초" in page.locator(".mode-note").inner_text()
            page.goto(BASE + "/settings")
            page.screenshot(path=str(output / "advanced-settings.png"), full_page=True)
            result["simple_defaults_and_advanced_access"] = "PASS"
            result["layout"] = layout(page, output, easy_id)
            result["database"] = database_evidence(root)
            safety = json.loads(HTTP().get("/api/oauth/safety"))
            assert safety["mode"] == "OFFLINE/BLOCKED"
            assert all(safety[name] == 0 for name in ("real_authorization_requests", "real_token_exchange_calls", "real_refresh_calls", "real_revoke_calls"))
            result["oauth_safety"] = safety
            assert not errors, "Browser JavaScript error"
            assert not external_origins, "Unexpected external browser request"
            result["browser_external_request_origins"] = []
            result["browser_javascript_errors"] = 0
            result["screenshots"] = sorted(path.name for path in output.glob("*.png"))
        except BaseException:
            page.screenshot(path=str(output / "failure.png"), full_page=True)
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
    if args.mode == "windows" and sys.platform != "win32":
        raise SystemExit("Windows validation requires a Windows runner")
    args.output.mkdir(parents=True, exist_ok=True)
    result: dict = {"mode": args.mode, "platform": sys.platform, "scenario": "synthetic RSS / offline AI / silent preview / local draft", "outcome": "FAIL"}
    try:
        with TemporaryDirectory(prefix="newsflow-autopilot-") as directory:
            env = child_env()
            data = Path(directory) / "한글 사용자 공간" / "NewsFlowAI"
            if args.mode == "windows":
                env["LOCALAPPDATA"] = str(data.parent)
                from newsflow.paths import default_data_dir

                assert default_data_dir(environ=env) == data
                result["LOCALAPPDATA_path"] = "PASS (isolated Windows current-user directory)"
            else:
                env["NEWSFLOW_DATA_DIR"] = str(data)
                result["LOCALAPPDATA_path"] = "NOT VERIFIED (Cloud Linux)"
            validate(args.mode, data, env, args.output, args.browser_executable, result)
        result["outcome"] = "PASS"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        if STARTUP_ERROR:
            result["startup_error"] = STARTUP_ERROR
        raise
    finally:
        (args.output / "autopilot-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        core = {key: value for key, value in result.items() if key not in {"easy_video", "guided_video", "database", "layout", "oauth_safety"}}
        notice("Autopilot GUI", core)
        for key in ("easy_video", "guided_video", "database", "layout", "oauth_safety"):
            if key in result:
                notice(f"Autopilot {key}", result[key])


if __name__ == "__main__":
    main()
