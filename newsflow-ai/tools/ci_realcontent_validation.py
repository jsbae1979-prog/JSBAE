"""Phase 5C real-content validation: registered RSS → gated script → Korean voice → MP4 → review → queue.

Deterministic part: the application's public factory with the fixture RSS adapter, so the
real-content mode (registered source, connection test, collection, mandatory script and
final reviews, 30/45/60 second MP4s) is exercised end to end without external services.
Optional part: one live public RSS connection test through the real server, recorded as
PASS or NOT VERIFIED; it never fails the run on its own. No external AI call is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
import wave
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from ci_autopilot_validation import notice, open_job, submit, wait_job
from ci_validation import BASE, HTTP, ROOT, STARTUP_ERROR, child_env, start, stop

FIXTURE_URL = "https://example.com/rss"


def fixture_server(data: Path, env: dict) -> subprocess.Popen:
    return start([sys.executable, str(ROOT / "tools/ci_fixture_server.py"), "--data-dir", str(data)], env, 60)


def database_evidence(root: Path) -> dict:
    with closing(sqlite3.connect(root / "newsflow.db")) as db:
        jobs = db.execute("SELECT content_mode, ai_mode, status FROM autopilot_jobs ORDER BY created_at").fetchall()
        usage = db.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0]
        providers = [row[0] for row in db.execute("SELECT DISTINCT provider FROM intelligence_runs")]
        checks = db.execute("SELECT status, article_count FROM news_source_checks").fetchall()
        drafts = db.execute("SELECT review_status, review_notes FROM content_drafts").fetchall()
        approvals = db.execute("SELECT content_reviewed, copyright_confirmed, sources_confirmed, account_id, state FROM publish_drafts").fetchall()
        assert approvals and all(row[:4] == (0, 0, 0, None) for row in approvals)
        assert all(row[4] not in {"ready", "approved", "success"} for row in approvals)
        assert all(row[0] == "review_required" for row in drafts)
        assert db.execute("SELECT COUNT(*) FROM publish_jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM platform_accounts WHERE credential_ref IS NOT NULL OR api_ready = 1").fetchone()[0] == 0
        settings = {row[0]: row[1] for row in db.execute("SELECT key, value FROM app_settings WHERE key LIKE 'ai_%'")}
        assert not any("sk-" in value for value in settings.values()), "key material must never reach app_settings"
        # Phase 5C.1 settings (user-entered prices) are plain numbers; their persistence across a
        # restart is part of the evidence. Keys and the dated approval are never listed here.
        prices = {key: value for key, value in settings.items() if key.startswith("ai_price_")}
        return {
            "ai_price_settings": prices,
            "autopilot_jobs": [{"content_mode": a, "ai_mode": b, "status": c} for a, b, c in jobs],
            "external_ai_calls_recorded": usage, "intelligence_providers": providers,
            "source_checks": [{"status": s, "articles": n} for s, n in checks],
            "drafts_with_review_notes": sum(1 for _, notes in drafts if notes and json.loads(notes)),
            "human_approval_preserved": True, "publish_jobs": 0,
        }


def media(page, job: dict, output: Path, name: str, duration: int) -> dict:
    from newsflow.publishing.media import FFprobeMediaInspector

    page.locator("video").wait_for()
    decodable = page.evaluate("() => document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E, mp4a.40.2\"')")
    if decodable:
        page.wait_for_function("() => {const v=document.querySelector('video');return v && (v.error || v.readyState>=1);}", timeout=30000)
        assert page.locator("video").evaluate("v => ({w:v.videoWidth,h:v.videoHeight,e:v.error?1:0})") == {"w": 1080, "h": 1920, "e": 0}
        page.locator("video").evaluate("async v => {v.muted=true;v.currentTime=0;await v.play();}")
        page.wait_for_function("() => {const v=document.querySelector('video');return v.error || (v.currentTime>=1 && !v.paused);}", timeout=30000)
        page.locator("video").evaluate("v => v.pause()")
        playback = "PASS (playback time advanced)"
    else:
        # Open-source Chromium without H.264: the page and file are checked, browser decoding is not.
        assert page.locator("video").is_visible()
        playback = "NOT VERIFIED (this Chromium has no H.264 decoder; Windows Chrome run verifies playback)"
    content = HTTP().get(f"/video/jobs/{job['render_job_id']}/file?download=true")
    path = output / name
    path.write_bytes(content)
    meta = FFprobeMediaInspector().inspect(path)
    assert meta["video_codec"] == "h264" and meta["audio_codec"] == "aac" and (meta["width"], meta["height"]) == (1080, 1920)
    assert abs(meta["duration"] - duration) < 0.25
    audio = job["stage_results"]["validate"].get("audio", "silent")
    return {"file": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "duration": meta["duration"],
            "audio": audio, "browser_playback": playback, "human_watch_quality": "NOT VERIFIED",
            "korean_pronunciation": "NOT VERIFIED" if audio == "voice" else "n/a (silent review video)"}


def real_job(page, duration: int, mode: str = "easy") -> str:
    page.goto(BASE + "/autopilot/start")
    form = page.locator('form[action="/autopilot/start"]')
    form.locator('input[name="source"][value="feeds"]').check()
    form.locator(f'input[name="mode"][value="{mode}"]').check()
    form.locator(f'input[name="duration"][value="{duration}"]').check()
    form.locator('select[name="ai"]').select_option("offline")
    submit(page, form, "/autopilot/start")
    page.wait_for_url(re.compile(re.escape(BASE) + r"/autopilot/jobs/[0-9a-f]{32}$"))
    return page.url.rsplit("/", 1)[1]


def resume(page, job_id: str) -> None:
    open_job(page, job_id)
    path = f"/autopilot/jobs/{job_id}/resume"
    submit(page, page.locator(f'form[action="{path}"]'), path)


def fixture_flow(mode: str, data: Path, env: dict, output: Path, executable: str | None, result: dict) -> None:
    from playwright.sync_api import sync_playwright

    process = fixture_server(data, env)
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
        page.on("request", lambda r: external.add(f"{urlsplit(r.url).scheme}://{urlsplit(r.url).netloc}") if urlsplit(r.url).scheme in {"http", "https"} and f"{urlsplit(r.url).scheme}://{urlsplit(r.url).netloc}" != BASE else None)
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        try:
            # 1. Sources page: register, test, enable, collect.
            page.goto(BASE + "/sources")
            form = page.locator('form[action="/sources"]')
            form.locator('input[name="name"]').fill("CI 픽스처 RSS")
            form.locator('input[name="url"]').fill(FIXTURE_URL)
            form.locator('input[name="permission"]').check()
            submit(page, form, "/sources")
            card = page.locator(".source-card", has_text=FIXTURE_URL)
            test_path = card.locator('form[action$="/test"]').get_attribute("action")
            submit(page, card.locator(f'form[action="{test_path}"]'), test_path)
            card = page.locator(".source-card", has_text=FIXTURE_URL)
            card.locator(".check-message.pass").wait_for()
            assert "기사 3개" in card.locator(".check-message.pass").inner_text()
            page.screenshot(path=str(output / "sources-tested.png"), full_page=True)
            toggle_path = test_path.replace("/test", "/toggle")
            toggle = page.locator(f'form[action="{toggle_path}"]')
            toggle.locator('input[name="permission"]').check()
            submit(page, toggle, toggle_path)
            submit(page, page.locator('form[action="/sources/collect"]'), "/sources/collect")
            HTTP().done()
            page.goto(BASE + "/sources")
            assert "실제 RSS" in page.content()
            page.screenshot(path=str(output / "sources-collected.png"), full_page=True)
            result["rss_register_test_collect"] = "PASS (fixture bytes through the registered adapter path)"

            # 2. AI settings: save settings and a synthetic key; the gate stays closed without network.
            page.goto(BASE + "/ai-settings")
            page.screenshot(path=str(output / "ai-settings.png"), full_page=True)
            assert page.locator("#ai-ready").inner_text().startswith("외부 AI 사용 불가")
            HTTP().blocked_post("/ai-settings", 422, {"provider": "openai", "model": "gpt-4o-mini", "approved": "true", "monthly_token_limit": "0", "timeout": "20"})
            result["ai_approval_requires_limit"] = "PASS (422 without monthly limit)"
            result["external_ai"] = "NOT VERIFIED (no API key in CI; gate closed, 0 calls)"

            # 3. Voices page.
            page.goto(BASE + "/voices")
            page.screenshot(path=str(output / "voices.png"), full_page=True)
            state = page.locator("#voice-status").inner_text()
            if "SAPI 미노출" in state:
                result["korean_voice_page"] = "PASS (OneCore-only Korean voice reported; SAPI guidance shown; not selectable)"
            elif "설치됨" in state:
                result["korean_voice_page"] = "PASS (installed voices listed)"
            else:
                result["korean_voice_page"] = "PASS (install guidance shown; no Korean SAPI voice)"

            # 4. Real-content easy job pauses on script and final video; 30/45/60.
            videos = []
            first_draft = None
            for index, duration in enumerate((30, 45, 60)):
                job_id = real_job(page, duration)
                waiting = wait_job(job_id, "waiting_review", "script", timeout=600)
                assert waiting["content_mode"] == "real" and waiting["ai_mode"] == "offline"
                assert waiting["review_pauses"] == ["script", "validate"]
                open_job(page, job_id)
                assert page.locator("#review-notes").is_visible() and page.locator("#source-compare").is_visible()
                if index == 0:
                    page.screenshot(path=str(output / "real-script-review.png"), full_page=True)
                    first_draft = waiting["content_draft_id"]
                    page.get_by_role("link", name="대본 수정", exact=False).click()
                    edit_path = f"/ai/drafts/{first_draft}"
                    edit = page.locator(f'form[action="{edit_path}"]')
                    edit.locator('input[name="closing"]').fill("자세한 내용은 원문 기사를 확인해 주세요.")
                    submit(page, edit, edit_path)
                    with closing(sqlite3.connect(data / "newsflow.db")) as db:
                        row = db.execute("SELECT revision, content FROM content_drafts WHERE id=?", (first_draft,)).fetchone()
                    assert row[0] == 2 and json.loads(row[1])["closing"].startswith("자세한 내용은")
                    result["script_edit_with_closing"] = "PASS (revision 2)"
                resume(page, job_id)
                final = wait_job(job_id, "waiting_review", "validate", timeout=900)
                assert not final.get("publish_draft_id")
                open_job(page, job_id)
                assert page.locator(".final-checklist").is_visible()
                if index == 0:
                    page.screenshot(path=str(output / "real-final-review.png"), full_page=True)
                videos.append(media(page, final, output, f"real-{duration}s.mp4", duration))
                resume(page, job_id)
                done = wait_job(job_id, "completed", timeout=300)
                assert done["publish_draft_id"]
            result["real_videos"] = videos
            result["real_content_easy_flow"] = "PASS (script review → final review → local queue, 30/45/60)"
            page.goto(BASE + "/queue")
            page.screenshot(path=str(output / "queue.png"), full_page=True)

            # 5. Restart persistence.
            before = database_evidence(data)
            stop(process)
            process = fixture_server(data, env)
            assert database_evidence(data) == before
            result["restart_persistence"] = "PASS"
            result["database"] = before
            assert not errors and not external
            result["browser_external_request_origins"] = []
            result["browser_javascript_errors"] = 0
            result["screenshots"] = sorted(p.name for p in output.glob("*.png"))
        except BaseException:
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            raise
        finally:
            browser.close()
            stop(process)


def live_rss(mode: str, url: str, env: dict, output: Path, result: dict) -> None:
    """Best-effort public feed connection test through the real server; never fails the run."""
    with TemporaryDirectory(prefix="newsflow-live-") as directory:
        data = Path(directory) / "live"
        env = dict(env)
        env["NEWSFLOW_DATA_DIR"] = str(data)
        command = ["cmd.exe", "/d", "/c", str(ROOT / "run.bat")] if mode == "windows" else [sys.executable, "-m", "newsflow.main"]
        if mode == "windows":
            env.pop("NEWSFLOW_DATA_DIR")
            env["LOCALAPPDATA"] = str(data)
        process = start(command, env, 240 if mode == "windows" else 30)
        try:
            http = HTTP()
            http.post("/sources", {"name": "공개 RSS 연결 테스트", "url": url, "permission": "true"})
            page_html = http.get("/sources").decode("utf-8")
            match = re.search(r'/sources/(\d+)/test', page_html)
            assert match
            client_timeout = None
            try:
                # A real feed can legitimately need DNS + robots + redirects + feed (~6 x request_timeout).
                http.post(f"/sources/{match.group(1)}/test", {}, timeout=75)
            except Exception as exc:  # noqa: BLE001 - the server-side row is still the evidence
                client_timeout = type(exc).__name__
            with closing(sqlite3.connect((data if mode != "windows" else data / "NewsFlowAI") / "newsflow.db")) as db:
                row = db.execute("SELECT status, kind, message, article_count FROM news_source_checks").fetchone()
            result["live_public_rss"] = {
                "url": url, "status": "PASS" if row and row[0] == "pass" else "NOT VERIFIED",
                "kind": row[1] if row else None, "message": row[2] if row else "no check row", "articles": row[3] if row else 0,
                "note": "network-dependent; articles were not stored by the connection test",
                "client_timeout": client_timeout,
            }
        except Exception as exc:  # noqa: BLE001 - network is outside this validation's control
            result["live_public_rss"] = {"url": url, "status": "NOT VERIFIED", "error_type": type(exc).__name__}
        finally:
            stop(process)


def korean_voice(mode: str, output: Path, result: dict) -> None:
    if mode != "windows":
        result["korean_tts"] = "NOT VERIFIED (Cloud Linux has no Windows SAPI)"
        return
    from newsflow.video.tts import SpeechSettings, WindowsTTS, wav_duration, wav_has_signal

    tts = WindowsTTS()
    voices = tts.korean_voices()
    result["korean_voice_count"] = len(voices)
    if not voices:
        result["korean_tts"] = "NOT VERIFIED (runner has no installed Korean SAPI voice)"
        return
    sample = output / "korean-preview.wav"
    tts.preview(sample, voices[0]["name"], SpeechSettings(0, 250))
    with wave.open(str(sample)) as wav:
        frames = wav.getnframes()
    result["korean_tts"] = f"PASS (non-silent WAV {wav_duration(sample):.2f}s, {frames} frames, signal={wav_has_signal(sample)}); pronunciation quality NOT VERIFIED"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("cloud", "windows"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable")
    parser.add_argument("--live-rss", help="optional public RSS URL for a best-effort connection test")
    args = parser.parse_args()
    if args.mode == "windows" and sys.platform != "win32":
        raise SystemExit("Windows validation requires a Windows runner")
    args.output.mkdir(parents=True, exist_ok=True)
    result: dict = {"mode": args.mode, "platform": sys.platform, "outcome": "FAIL",
                    "scenario": "registered RSS (fixture bytes) / offline AI / default voice / mandatory reviews / local queue",
                    "external_ai_calls": 0, "sns_calls": 0, "Windows11_user_PC": "NOT VERIFIED"}
    try:
        with TemporaryDirectory(prefix="newsflow-realcontent-") as directory:
            env = child_env()
            data = Path(directory) / "한글 사용자 공간" / "NewsFlowAI"
            env["NEWSFLOW_DATA_DIR"] = str(data)
            fixture_flow(args.mode, data, env, args.output, args.browser_executable, result)
        korean_voice(args.mode, args.output, result)
        if args.live_rss:
            live_rss(args.mode, args.live_rss, child_env(), args.output, result)
        else:
            result["live_public_rss"] = "NOT VERIFIED (no --live-rss URL given)"
        result["outcome"] = "PASS with explicit NOT VERIFIED items"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        if STARTUP_ERROR:
            result["startup_error"] = STARTUP_ERROR
        raise
    finally:
        (args.output / "realcontent-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        core = {k: v for k, v in result.items() if k not in {"real_videos", "database", "live_public_rss"}}
        notice("RealContent", core)
        for key in ("real_videos", "database", "live_public_rss"):
            if key in result:
                notice(f"RealContent {key}", result[key] if isinstance(result[key], dict) else {"value": result[key]})
        time.sleep(0)


if __name__ == "__main__":
    main()
