"""Real-process Cloud/Windows validation. Only synthetic data, no RSS requests."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
STARTUP_ERROR: dict = {}


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "NEWSFLOW_DATA_DIR",
        "NEWSFLOW_PORT",
        "NEWSFLOW_HOST",
        "NEWSFLOW_SECRET_KEY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
    ):
        env.pop(key, None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class HTTP:
    def __init__(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies))

    def get(self, path: str) -> bytes:
        with self.opener.open(BASE + path, timeout=3) as response:
            assert response.status == 200
            return response.read()

    def post(self, path: str, fields: dict) -> None:
        self.get("/settings")
        token = next(cookie.value for cookie in self.cookies if cookie.name == "newsflow_csrf")
        request = Request(
            BASE + path, data=urlencode({**fields, "csrf_token": token}).encode(), headers={"Origin": BASE}
        )
        with self.opener.open(request, timeout=5) as response:
            assert response.status == 200

    def done(self) -> dict:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = json.loads(self.get("/api/collection"))
            if result["status"] != "running":
                return result
            time.sleep(0.1)
        raise AssertionError("collection deadline")


def start(command: list[str], env: dict[str, str], deadline_seconds: int = 30) -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    try:
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.communicate(timeout=3)[0].decode("utf-8", errors="replace")
                stage = "unknown"
                for phrase, label in (
                    ("가상환경 생성 실패", "venv_creation"),
                    ("가상환경 Python 3.12 확인 실패", "venv_python"),
                    ("의존성 설치 실패", "dependency_install"),
                    ("의존성 검사 실패", "dependency_check"),
                    ("기존 data/newsflow.db", "legacy_data"),
                    ("포트가 사용 중", "port_conflict"),
                    ("지정 포트", "port_conflict"),
                    ("Python 3.12 is required", "python_discovery"),
                    ("Cannot open the project folder", "project_path"),
                    ("실행 설정 또는 데이터", "runtime_configuration"),
                ):
                    if phrase in output:
                        stage = label
                        break
                STARTUP_ERROR.update(stage=stage, exit_code=process.returncode)
                raise AssertionError("server exited before readiness")
            try:
                assert json.loads(HTTP().get("/health")) == {"status": "ok", "phase": 1}
                return process
            except (URLError, TimeoutError, ConnectionError):
                time.sleep(0.2)
        raise AssertionError("server readiness deadline")
    except BaseException:
        stop(process)
        raise


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        if sys.platform == "win32":
            # Explicit tree termination in CI. This is not a manual Ctrl+C claim.
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            assert result.returncode == 0, "CI process tree cleanup failed"
        else:
            process.terminate()
    process.wait(timeout=20)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8765)) != 0:
                return
        time.sleep(0.1)
    raise AssertionError("server socket was not released")


def counts(root: Path) -> dict:
    with closing(sqlite3.connect(root / "newsflow.db")) as connection:
        return {
            name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            for name in ("news_articles", "article_mentions", "article_scores", "news_sources")
        }


def seed(root: Path) -> None:
    from fastapi.testclient import TestClient

    from newsflow.config import Settings
    from newsflow.db.models import NewsSource
    from newsflow.main import create_app
    from newsflow.news.rss_adapter import FakeRSSAdapter

    fixture = (ROOT / "tests/fixtures/normal.xml").read_bytes()
    app = create_app(Settings(data_dir=root), FakeRSSAdapter({"https://example.com/rss": fixture}))
    with TestClient(app, base_url=BASE):
        with app.state.sessions.begin() as session:
            source = session.get(NewsSource, 2)
            assert source is not None
            source.enabled = True
        app.state.coordinator.start()
        app.state.coordinator.future.result(timeout=10)


def production(mode: str, root: Path, env: dict[str, str], trace: list[str]) -> dict:
    command = (
        ["cmd.exe", "/d", "/c", str(ROOT / "run.bat")]
        if mode == "windows"
        else [sys.executable, "-m", "newsflow.main"]
    )
    trace.append("first_start_requested")
    process = start(command, env, 180 if mode == "windows" else 30)
    trace.append("first_server_ready")
    try:
        client = HTTP()
        for path in ("/", "/news", "/settings"):
            client.get(path)
        client.post(
            "/settings/sources",
            {"name": "CI synthetic", "url": "https://example.com/rss", "permission": "true"},
        )
        client.post("/settings/sources/2/toggle", {})  # No external RSS when using production transport.
        client.post("/settings/collection", {"timeout": 7})
        client.post("/collection", {})
        assert client.done()["status"] == "empty"
        trace.append("production_HTTP_POST_completed")
        duplicate = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        assert duplicate.returncode != 0
        trace.append("duplicate_rejected")
        assert json.loads(client.get("/health"))["status"] == "ok"
        if mode == "windows":
            assert (ROOT / ".venv/Scripts/python.exe").is_file()
            assert (ROOT / ".venv/.newsflow-installed").is_file()
        assert (root / "newsflow.db").is_file()
    finally:
        stop(process)
    trace.append("first_server_stopped")
    seed(root)
    before = counts(root)
    assert before["news_articles"] == before["article_mentions"] == before["article_scores"] == 3
    key = (root / "session.key").read_bytes()
    trace.append("seed_stored_three_articles")
    process = start(command, env, 60)
    trace.append("restarted_server_ready")
    try:
        assert counts(root) == before
        assert (root / "session.key").read_bytes() == key
        assert "한국 우주 기술 발사 현장 공개" in HTTP().get("/news").decode()
        HTTP().post("/settings/sources/2/toggle", {})
    finally:
        stop(process)
    trace.append("restarted_server_stopped")
    with socket.socket() as occupied:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupied.bind(("127.0.0.1", 8765))
        occupied.listen(1)
        collision = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        assert collision.returncode != 0
        trace.append("port_collision_rejected")
    return {
        "server_lifecycle": "PASS",
        "http_POST": "PASS",
        "sqlite_store_restart_query": "PASS",
        "article_count": 3,
        "duplicate_and_port_collision": "PASS",
        "run_bat": "PASS" if mode == "windows" else "NOT VERIFIED",
        "stop_method": "taskkill process tree" if mode == "windows" else "SIGTERM",
        "Windows_manual_CtrlC": "NOT VERIFIED",
    }


def browser(
    mode: str, root: Path, env: dict[str, str], output: Path, executable: str | None, progress: dict
) -> dict:
    from playwright.sync_api import sync_playwright

    process = start([sys.executable, str(ROOT / "tools/ci_fixture_server.py"), "--data-dir", str(root)], env)
    progress["server_ready"] = True
    result: dict = {}
    try:
        with sync_playwright() as playwright:
            options: dict = {"headless": True}
            if executable:
                options["executable_path"] = executable
            if mode == "cloud":
                options["args"] = ["--no-sandbox"]
            instance = playwright.chromium.launch(**options)
            try:
                page = instance.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(BASE + "/settings")
                progress["context_origin"] = page.evaluate(
                    "({location:location.origin, window:window.origin})"
                )
                page.locator(".source-form input[name=name]").fill("CI synthetic")
                page.locator(".source-form input[name=url]").fill("https://example.com/rss")
                page.locator(".source-form input[name=permission]").check()
                with page.expect_response(
                    lambda r: r.request.method == "POST" and r.url.endswith("/settings/sources")
                ) as response:
                    page.locator(".source-form button").click()
                status = response.value.status
                progress.update(
                    registration_status=status,
                    registration_origin=response.value.request.all_headers().get("origin"),
                )
                assert status == 303, "GUI registration POST failed"
                assert progress["registration_origin"] == BASE, "Browser must generate the real Origin"
                progress["registration"] = "PASS"
                page.locator(".source-row").filter(has_text="CI synthetic").wait_for()
                page.wait_for_load_state("load")
                toggle = page.locator('form[action="/settings/sources/2/toggle"]')
                with page.expect_response(lambda r: r.request.method == "POST") as response:
                    toggle.locator("button").click()
                progress["disable_status"] = response.value.status
                assert response.value.status == 303
                page.locator('form[action="/settings/sources/2/toggle"] input[name=permission]').wait_for()
                page.wait_for_load_state("load")
                toggle = page.locator('form[action="/settings/sources/2/toggle"]')
                toggle.locator("input[name=permission]").check()
                with page.expect_response(lambda r: r.request.method == "POST") as response:
                    toggle.locator("button").click()
                progress["enable_status"] = response.value.status
                assert response.value.status == 303
                page.locator('form[action="/settings/sources/2/toggle"]').get_by_role(
                    "button", name="비활성화", exact=True
                ).wait_for()
                page.wait_for_load_state("load")
                page.goto(BASE)
                with (
                    page.expect_navigation(wait_until="domcontentloaded"),
                    page.expect_response(
                        lambda r: r.request.method == "POST" and r.url.endswith("/collection")
                    ) as response,
                ):
                    page.locator("#collect-button").click()
                progress["collection_status"] = response.value.status
                assert response.value.status == 303
                assert HTTP().done()["added"] == 3
                page.get_by_text("한국 우주 기술 발사 현장 공개", exact=True).first.wait_for()
                page.wait_for_load_state("load")
                result["GUI_browser_POST"] = "PASS (registration, disable/enable, collection)"
                assert counts(root)["news_articles"] == 3
                progress["sqlite_count"] = 3
                page.goto(BASE)
                page.screenshot(path=str(output / "dashboard.png"), full_page=True)
                page.goto(BASE + "/news")
                page.locator("input[name=q]").fill("우주")
                page.get_by_role("button", name="필터 적용").click()
                page.wait_for_url("**/news?**")
                progress["search_count"] = page.locator(".article-row").count()
                assert page.locator(".article-row").count() == 1
                page.locator(".article-row").click()
                page.get_by_role("heading", name="내부 추천 평가 근거").wait_for()
                page.set_viewport_size({"width": 390, "height": 844})
                for path in ("/", "/news", "/news/1", "/settings"):
                    page.goto(BASE + path)
                    overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    progress["mobile_last_path"] = path
                    progress["mobile_overflow"] = overflow
                    assert not overflow
                page.screenshot(path=str(output / "mobile.png"), full_page=True)
                assert not errors, "browser page error"
                result.update(
                    GUI_render_search_detail_mobile="PASS", GUI_synthetic_RSS_store="PASS", article_count=3
                )
            finally:
                instance.close()
    finally:
        stop(process)
    before = counts(root)
    process = start([sys.executable, str(ROOT / "tools/ci_fixture_server.py"), "--data-dir", str(root)], env)
    try:
        assert counts(root) == before
        assert "한국 우주 기술 발사 현장 공개" in HTTP().get("/news").decode()
        result["fixture_server_restart_persistence"] = "PASS"
    finally:
        stop(process)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("cloud", "windows"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    if args.mode == "windows" and sys.platform != "win32":
        raise SystemExit("Windows mode requires a real Windows runner")
    args.output.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "platform": sys.platform,
        "mode": args.mode,
        "real_RSS": "NOT VERIFIED (offline synthetic tests)",
    }
    try:
        with TemporaryDirectory(prefix="newsflow-ci-") as directory:
            env = child_env()
            if args.mode == "windows":
                from newsflow.paths import default_data_dir

                data = default_data_dir(environ=env)
                assert data == Path(env["LOCALAPPDATA"]) / "NewsFlowAI"
                assert not (data / "newsflow.db").exists(), "CI refuses to overwrite existing user database"
                result["LOCALAPPDATA_default"] = "PASS"
            else:
                data = Path(directory) / "개발 사용자 공간"
                env["NEWSFLOW_DATA_DIR"] = str(data)
                result["LOCALAPPDATA_default"] = "NOT VERIFIED (Linux)"
            result["production_trace"] = []
            result["production"] = production(args.mode, data, env, result["production_trace"])
            result["browser_progress"] = {}
            result["browser"] = browser(
                args.mode,
                Path(directory) / "합성 브라우저 데이터",
                env,
                args.output,
                args.browser_executable,
                result["browser_progress"],
            )
        result["outcome"] = "PASS with explicit unverified items" if args.mode == "cloud" else "PASS"
    except Exception as exc:
        result["outcome"] = "FAIL"
        result["error_type"] = type(exc).__name__
        if STARTUP_ERROR:
            result["startup_error"] = STARTUP_ERROR
        raise
    finally:
        (args.output / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        # Metadata is readable through GitHub's check API even if artifact/log hosts are blocked.
        notice = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        notice = notice.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::notice title=NewsFlow validation::{notice}")


if __name__ == "__main__":
    main()
