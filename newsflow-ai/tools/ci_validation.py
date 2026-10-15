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
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

if TYPE_CHECKING:
    from playwright.sync_api import Page

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
        "NEWSFLOW_AI_API_KEY",
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

    def blocked_post(
        self, path: str, expected_status: int, fields: dict[str, str] | None = None
    ) -> None:
        self.get("/settings")
        token = next(cookie.value for cookie in self.cookies if cookie.name == "newsflow_csrf")
        request = Request(
            BASE + path,
            data=urlencode({**(fields or {}), "csrf_token": token}).encode(),
            headers={"Origin": BASE},
        )
        try:
            with self.opener.open(request, timeout=5) as response:
                assert response.status == expected_status, "forged execution request must be blocked"
        except HTTPError as error:
            try:
                assert error.code == expected_status, "forged execution request must be blocked"
            finally:
                error.close()

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


def publishing_counts(root: Path) -> dict[str, int]:
    with closing(sqlite3.connect(root / "newsflow.db")) as connection:
        return {
            name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            for name in ("publish_drafts", "publish_validations", "publish_jobs", "publish_attempts")
        }


def oauth_database_state(root: Path, account_id: int) -> dict:
    with closing(sqlite3.connect(root / "newsflow.db")) as connection:
        row = connection.execute(
            "SELECT c.status, c.mode, c.revision, c.expires_at, c.error_code, a.status, "
            "a.credential_ref IS NOT NULL, a.api_ready, a.scopes "
            "FROM oauth_connections c JOIN platform_accounts a ON a.id = c.account_id "
            "WHERE c.account_id = ?",
            (account_id,),
        ).fetchone()
        assert row is not None, "local OAuth preparation record must be stored"
        return {
            "status": row[0], "mode": row[1], "revision": row[2], "expires_at": row[3],
            "error_code": row[4], "account_status": row[5], "credential_present": bool(row[6]),
            "api_ready": bool(row[7]), "scopes": json.loads(row[8]),
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


def oauth_browser(page: Page, root: Path, result: dict, progress: dict) -> None:
    """Real local GUI requests only; no login page or token exchange is opened."""
    metadata = page.locator('form[action="/publishing/accounts"]')
    metadata.locator("select[name=platform]").select_option("youtube")
    metadata.locator("input[name=label]").fill("CI 합성 YouTube 계정")
    metadata.locator("select[name=account_type]").select_option("youtube_channel")
    with (
        page.expect_navigation(wait_until="domcontentloaded"),
        page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/publishing/accounts")
        ) as response,
    ):
        metadata.locator("button[type=submit]").click()
    assert response.value.status == 303, "local account metadata POST failed"
    assert response.value.request.all_headers().get("origin") == BASE
    with closing(sqlite3.connect(root / "newsflow.db")) as connection:
        rows = connection.execute(
            "SELECT id FROM platform_accounts WHERE label = ? AND platform = ?",
            ("CI 합성 YouTube 계정", "youtube"),
        ).fetchall()
        assert len(rows) == 1, "synthetic account metadata must be stored once"
        account_id = rows[0][0]
    card = page.locator(f"#oauth-account-{account_id}")
    card.wait_for()
    assert card.get_attribute("data-connection-status") == "unprepared"
    assert card.get_attribute("data-mode") == "OFFLINE/BLOCKED"
    assert card.get_attribute("data-can-connect") == "false"
    assert card.locator(".oauth-start-disabled").is_disabled()
    assert page.locator('form[action$="/oauth/start"]').count() == 0
    for action, state in (("prepare", "prepared"), ("disconnect-prepare", "disconnect_prepared")):
        path = f"/publishing/accounts/{account_id}/oauth/{action}"
        with (
            page.expect_navigation(wait_until="domcontentloaded"),
            page.expect_response(
                lambda response, expected_path=path: response.request.method == "POST"
                and response.url.endswith(expected_path)
            ) as response,
        ):
            page.locator(f'form[action="{path}"] button[type=submit]').click()
        assert response.value.status == 303, "local OAuth preparation POST failed"
        assert response.value.request.all_headers().get("origin") == BASE
        card = page.locator(f"#oauth-account-{account_id}")
        card.wait_for()
        assert card.get_attribute("data-connection-status") == state
        assert card.get_attribute("data-mode") == "OFFLINE/BLOCKED"
        assert card.get_attribute("data-can-connect") == "false"
        assert card.locator(".oauth-start-disabled").is_disabled()
    HTTP().blocked_post(
        f"/publishing/accounts/{account_id}/oauth/start?allow_real=true&user_approval=true",
        423,
        {"mode": "real", "feature_enabled": "true", "user_approval": "true"},
    )
    progress["oauth_forged_start_status"] = 423
    page.reload(wait_until="domcontentloaded")
    card = page.locator(f"#oauth-account-{account_id}")
    assert card.get_attribute("data-connection-status") == "disconnect_prepared"
    assert card.locator(".oauth-start-disabled").is_disabled()
    safety = json.loads(HTTP().get("/api/oauth/safety"))
    assert safety == {
        "real_authorization_requests": 0,
        "real_token_exchange_calls": 0,
        "real_refresh_calls": 0,
        "real_revoke_calls": 0,
        "mode": "OFFLINE/BLOCKED",
        "feature_enabled": False,
        "user_approval": False,
        "phase_allows_real": False,
    }, "real OAuth operations must remain disabled regardless of forged flags"
    assert publishing_counts(root) == result["publishing_SQLite_counts"]
    stored = oauth_database_state(root, account_id)
    assert stored == {
        "status": "disconnect_prepared", "mode": "offline", "revision": 3,
        "expires_at": None, "error_code": None, "account_status": "not_connected",
        "credential_present": False, "api_ready": False, "scopes": [],
    }, "preparation must never create credentials, privileges or a connected account"
    result["OAuth_Studio_metadata_prepare_disconnect_blocked_start_POST"] = "PASS (local records only)"
    result["oauth_safety"] = safety
    result["oauth_account_id"] = account_id
    result["oauth_SQLite_state"] = stored
    readiness_panel = page.locator("#oauth-production-readiness")
    readiness_panel.wait_for()
    assert readiness_panel.get_attribute("data-phase") == "4B-2B"
    for attribute in (
        "data-production-activation", "data-browser-login-allowed", "data-token-exchange-allowed",
        "data-production-storage-allowed",
    ):
        assert readiness_panel.get_attribute(attribute) == "false", (
            "GUI must never claim production OAuth activation or credential access is allowed"
        )
    readiness = json.loads(HTTP().get("/api/oauth/production-readiness"))
    assert readiness == {
        "phase": "4B-2B", "production_activation": False, "environment_can_activate": False,
        "gui_can_activate": False, "browser_login_allowed": False, "token_exchange_allowed": False,
        "production_storage_allowed": False, "publishing_allowed": False,
        "providers": {
            "youtube": {
                "client_type": "desktop", "oauth_code_status": "implemented_inactive",
                "account_identity": "NOT VERIFIED", "production_vault": "inactive", "login": "blocked",
            },
            "instagram": {
                "oauth_code_status": "blocked", "official_requirements": "NOT VERIFIED",
                "production_vault": "inactive", "login": "blocked",
            },
        },
    }, "protocol preparation must never imply production readiness or verified real-account identity"
    result["oauth_production_readiness"] = readiness
    operational_panel = page.locator("#oauth-operations-readiness")
    operational_panel.wait_for()
    assert operational_panel.get_attribute("data-phase") == "4B-2B"
    for attribute in (
        "data-production-activation", "data-listener-started", "data-real-identity-lookup-allowed",
        "data-real-credentials-allowed",
    ):
        assert operational_panel.get_attribute(attribute) == "false"
    operations = json.loads(HTTP().get("/api/oauth/operations-readiness"))
    assert operations == {
        "phase": "4B-2B", "mode": "OFFLINE/BLOCKED", "production_activation": False,
        "callback": {
            "code_status": "implemented_inactive", "binding": "127.0.0.1",
            "registered_uri_match": "exact", "real_provider_connected": False,
            "listener_started_by_gui": False,
        },
        "youtube_identity": {
            "code_status": "implemented_inactive", "real_account": "NOT VERIFIED",
            "connection_on_error": "blocked",
        },
        "production_vault": {
            "code_status": "implemented_inactive", "boundary": "Windows current-user DPAPI",
            "validation_data": "synthetic_only", "real_credentials_allowed": False,
        },
        "instagram": {"login": "blocked", "official_requirements": "NOT VERIFIED"},
        "real_login_allowed": False, "real_token_exchange_allowed": False,
        "real_identity_lookup_allowed": False, "real_publishing_allowed": False,
    }, "operational OAuth code must remain inactive and must not imply verified real accounts"
    result["oauth_operations_readiness"] = operations
    result["OAuth_operations_readiness_browser"] = "PASS (inactive code; real operations blocked)"


def browser(
    mode: str, root: Path, env: dict[str, str], output: Path, executable: str | None, progress: dict
) -> dict:
    from playwright.sync_api import Request as BrowserRequest
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
            elif not executable:
                # Windows MP4 preview needs a Chromium build with licensed H.264/AAC support.
                options["channel"] = "chrome"
            progress["browser_channel"] = options.get("channel", "chromium")
            instance = playwright.chromium.launch(**options)
            try:
                page = instance.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                external_request_origins: set[str] = set()

                def inspect_request(request: BrowserRequest) -> None:
                    # The synthetic workflow uses only the local GUI. Never disclose URL queries.
                    url = urlsplit(request.url)
                    origin = f"{url.scheme}://{url.netloc}"
                    if url.scheme in {"http", "https"} and origin != BASE:
                        external_request_origins.add(origin)

                page.on("request", inspect_request)
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
                page.goto(BASE + "/dashboard")
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
                page.goto(BASE + "/dashboard")
                page.screenshot(path=str(output / "dashboard.png"), full_page=True)
                page.goto(BASE + "/news")
                page.locator("input[name=q]").fill("우주")
                page.get_by_role("button", name="필터 적용").click()
                page.wait_for_url("**/news?**")
                progress["search_count"] = page.locator(".article-row").count()
                assert page.locator(".article-row").count() == 1
                page.locator(".article-row").click()
                page.get_by_role("heading", name="내부 추천 평가 근거").wait_for()
                page.goto(BASE + "/ai")
                page.locator('input[name=article_ids][value="1"]').check()
                with (
                    page.expect_navigation(wait_until="domcontentloaded"),
                    page.expect_response(
                        lambda r: r.request.method == "POST" and r.url.endswith("/ai/analyze")
                    ) as response,
                ):
                    page.get_by_role("button", name="선택 기사 분석", exact=True).click()
                assert response.value.status == 303
                assert response.value.request.all_headers().get("origin") == BASE
                page.locator("select[name=duration]").select_option("45")
                with (
                    page.expect_navigation(wait_until="domcontentloaded"),
                    page.expect_response(
                        lambda r: r.request.method == "POST" and r.url.endswith("/ai/generate")
                    ) as response,
                ):
                    page.get_by_role("button", name="대본 생성 및 초안 저장", exact=True).click()
                assert response.value.status == 303
                page.locator('form[action="/ai/drafts/1"] input[name=title]').fill("합성 검토용 수정 대본")
                with (
                    page.expect_navigation(wait_until="domcontentloaded"),
                    page.expect_response(
                        lambda r: r.request.method == "POST" and r.url.endswith("/ai/drafts/1")
                    ) as response,
                ):
                    page.get_by_role("button", name="수정 초안 저장", exact=True).click()
                assert response.value.status == 303
                page.get_by_role("heading", name="합성 검토용 수정 대본", exact=True).wait_for()
                page.screenshot(path=str(output / "ai-studio.png"), full_page=True)
                result["AI_Studio_analysis_script_edit_POST"] = (
                    "PASS (offline; unverified; sources preserved)"
                )
                page.goto(BASE + "/video?draft_id=1")
                page.locator("select[name=duration]").select_option("30")
                page.locator("input[name=reviewed]").check()
                with (
                    page.expect_navigation(wait_until="domcontentloaded"),
                    page.expect_response(
                        lambda r: r.request.method == "POST" and r.url.endswith("/video/render")
                    ) as response,
                ):
                    page.get_by_role("button", name="영상 제작 실행", exact=True).click()
                assert response.value.status == 303
                assert response.value.request.all_headers().get("origin") == BASE
                deadline = time.monotonic() + 300
                while True:
                    state = json.loads(HTTP().get("/api/video/jobs/1"))
                    progress["video_status"] = state["status"]
                    progress["video_progress"] = state["progress"]
                    if state["status"] != "running":
                        assert state["status"] == "success", "actual video render failed"
                        break
                    assert time.monotonic() < deadline, "video render deadline"
                    time.sleep(0.5)
                page.goto(BASE + "/video?job_id=1")
                page.locator("video").wait_for()
                media_deadline = time.monotonic() + 30
                while True:
                    media = page.locator("video").evaluate(
                        "v => ({ready:v.readyState,error:v.error ? v.error.code : null,width:v.videoWidth,height:v.videoHeight,support:v.canPlayType('video/mp4; codecs=\"avc1.640028,mp4a.40.2\"')})"
                    )
                    progress["video_metadata_state"] = media
                    assert not media["error"], "browser video metadata decoder error"
                    if media["ready"] >= 1:
                        break
                    assert time.monotonic() < media_deadline, "video metadata deadline"
                    page.wait_for_timeout(100)
                dimensions = page.locator("video").evaluate("v => [v.videoWidth,v.videoHeight]")
                progress["video_dimensions"] = dimensions
                assert dimensions == [1080, 1920], "browser video dimensions"
                page.locator("video").evaluate("v => { v.currentTime = 1; v.pause(); }")
                media_deadline = time.monotonic() + 30
                while True:
                    media = page.locator("video").evaluate(
                        "v => ({ready:v.readyState,error:v.error ? v.error.code : null})"
                    )
                    progress["video_media_state"] = media
                    assert not media["error"], "browser video decoder error"
                    if media["ready"] >= 2:
                        break
                    assert time.monotonic() < media_deadline, "video frame decode deadline"
                    page.wait_for_timeout(100)
                progress["video_frame_decode"] = "PASS"
                video_bytes = HTTP().get("/video/jobs/1/file?download=true")
                assert len(video_bytes) > 1000
                (output / "browser-30s.mp4").write_bytes(video_bytes)
                page.screenshot(path=str(output / "video-studio.png"), full_page=True)
                result["Video_Studio_POST_preview_download"] = (
                    "PASS (real 30s MP4; offline silent audio; human quality not verified)"
                )
                page.goto(BASE + "/publishing?render_job_id=1")
                create = page.locator("#publish-create")
                create.locator("select[name=platform]").select_option("youtube")
                create.locator("input[name=title]").fill("합성 게시 준비 초안")
                create.locator("textarea[name=description]").fill(
                    "합성 자료로 생성한 게시 준비 검증용 영상입니다. 실제 게시하지 않습니다."
                )
                create.locator("input[name=hashtags]").fill("#뉴스 #합성")
                for field in ("content_reviewed", "copyright_confirmed", "sources_confirmed"):
                    create.locator(f"input[name={field}]").check()
                create.locator("select[name=ai_disclosure]").select_option("disclose")
                with (
                    page.expect_navigation(wait_until="domcontentloaded"),
                    page.expect_response(
                        lambda r: r.request.method == "POST" and r.url.endswith("/publishing/drafts")
                    ) as response,
                ):
                    create.locator("button[type=submit]").click()
                assert response.value.status == 303, "publishing draft create POST failed"
                assert response.value.request.all_headers().get("origin") == BASE
                progress["publishing_create_status"] = response.value.status
                page.wait_for_url("**/publishing?draft_id=1")
                edit = page.locator("#publish-edit")
                edit.locator("input[name=title]").fill("합성 게시 준비 수정 초안")
                with (
                    page.expect_navigation(wait_until="domcontentloaded"),
                    page.expect_response(
                        lambda r: r.request.method == "POST" and r.url.endswith("/publishing/drafts/1")
                    ) as response,
                ):
                    edit.locator("button[type=submit]").click()
                assert response.value.status == 303, "publishing draft edit POST failed"
                assert response.value.request.all_headers().get("origin") == BASE
                progress["publishing_edit_status"] = response.value.status
                page.locator("#publish-edit input[name=title]").wait_for()
                assert page.locator("#publish-edit input[name=title]").input_value() == (
                    "합성 게시 준비 수정 초안"
                )
                with (
                    page.expect_navigation(wait_until="domcontentloaded"),
                    page.expect_response(
                        lambda r: r.request.method == "POST"
                        and r.url.endswith("/publishing/drafts/1/validate")
                    ) as response,
                ):
                    page.locator("#publish-validate button[type=submit]").click()
                assert response.value.status == 303, "publishing validation POST failed"
                assert response.value.request.all_headers().get("origin") == BASE
                progress["publishing_validate_status"] = response.value.status
                readiness = page.locator("#publish-readiness")
                readiness.wait_for()
                assert readiness.get_attribute("data-state") == "blocked", (
                    "unconnected account must block publishing readiness"
                )
                with (
                    page.expect_navigation(wait_until="domcontentloaded"),
                    page.expect_response(
                        lambda r: r.request.method == "POST"
                        and r.url.endswith("/publishing/drafts/1/validate")
                    ) as response,
                ):
                    page.locator("#publish-validate button[type=submit]").click()
                assert response.value.status == 303, "repeated publishing validation POST failed"
                assert response.value.request.all_headers().get("origin") == BASE
                page.locator('#publish-readiness[data-state="blocked"]').wait_for()
                stored = publishing_counts(root)
                assert stored["publish_drafts"] == 1
                assert stored["publish_validations"] == 2
                assert stored["publish_jobs"] == stored["publish_attempts"] == 0, (
                    "draft validation must not create publishing jobs or attempts"
                )
                result["publishing_SQLite_counts"] = stored
                safety = json.loads(HTTP().get("/api/publishing/safety"))
                assert safety == {
                    "real_publish_calls": 0,
                    "real_oauth_calls": 0,
                    "mode": "foundation",
                    "external_execution_enabled": False,
                }, "foundation must keep real SNS and OAuth execution disabled"
                result["Publishing_Studio_create_edit_validate_POST"] = (
                    "PASS (unconnected account blocked; approval pending; no real publishing)"
                )
                result["publishing_safety"] = safety
                oauth_browser(page, root, result, progress)
                page.screenshot(path=str(output / "oauth-studio.png"), full_page=True)
                page.goto(BASE + "/publishing?draft_id=1")
                page.screenshot(path=str(output / "publishing-studio.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                for path in (
                    "/", "/news", "/news/1", "/settings", "/ai?draft_id=1", "/video?job_id=1",
                    "/publishing?draft_id=1",
                ):
                    page.goto(BASE + path)
                    overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    progress["mobile_last_path"] = path
                    progress["mobile_overflow"] = overflow
                    assert not overflow
                page.screenshot(path=str(output / "mobile.png"), full_page=True)
                assert not errors, "browser page error"
                assert not external_request_origins, "synthetic GUI must never contact external origins"
                result["browser_external_request_origins"] = []
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
        assert "합성 검토용 수정 대본" in HTTP().get("/ai?draft_id=1").decode()
        assert json.loads(HTTP().get("/api/video/jobs/1"))["status"] == "success"
        assert len(HTTP().get("/video/jobs/1/file")) > 1000
        publishing = HTTP().get("/publishing?draft_id=1").decode()
        assert "합성 게시 준비 수정 초안" in publishing
        assert 'data-state="blocked"' in publishing
        assert publishing_counts(root) == result["publishing_SQLite_counts"]
        assert json.loads(HTTP().get("/api/publishing/safety")) == result["publishing_safety"]
        assert json.loads(HTTP().get("/api/oauth/safety")) == result["oauth_safety"]
        assert json.loads(HTTP().get("/api/oauth/production-readiness")) == result["oauth_production_readiness"]
        assert json.loads(HTTP().get("/api/oauth/operations-readiness")) == result["oauth_operations_readiness"]
        assert oauth_database_state(root, result["oauth_account_id"]) == result["oauth_SQLite_state"]
        assert 'data-connection-status="disconnect_prepared"' in publishing
        assert 'data-can-connect="false"' in publishing
        result["OAuth_preparation_restart_persistence"] = "PASS"
        result["Publishing_draft_validation_restart_persistence"] = "PASS"
        result["Video_job_file_restart_persistence"] = "PASS"
        result["AI_draft_restart_persistence"] = "PASS"
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
        # GitHub check notices truncate at 4096 UTF-8 bytes. Keep the additive
        # descriptor in a separate bounded notice rather than losing evidence.
        notice_result = dict(result)
        if "browser" in result:
            notice_result["browser"] = dict(result["browser"])
            operations = notice_result["browser"].pop("oauth_operations_readiness", None)
            if operations is not None:
                operations_notice = json.dumps(operations, ensure_ascii=False, separators=(",", ":"))
                operations_notice = operations_notice.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                print(f"::notice title=NewsFlow OAuth operations::{operations_notice}")
        notice = json.dumps(notice_result, ensure_ascii=False, separators=(",", ":"))
        notice = notice.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::notice title=NewsFlow validation::{notice}")


if __name__ == "__main__":
    main()
