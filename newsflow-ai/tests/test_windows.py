"""Portable contract tests. Simulations do not constitute a Windows BAT execution."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from newsflow.config import Settings
from newsflow.db.models import AppSetting, ArticleMention, ArticleScore, NewsArticle, NewsSource
from newsflow.main import create_app
from newsflow.migrate_data import migrate_data
from newsflow.paths import default_data_dir, prepare_data_dir
from newsflow.runtime import PortInUseError, reserve_socket, runtime_logger

ROOT = Path(__file__).resolve().parents[1]


def launcher():
    spec = importlib.util.spec_from_file_location("windows_bootstrap", ROOT / "tools/windows_launcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_default_contract_and_explicit_override(tmp_path):
    root = tmp_path / "사용자 계정" / "App Data"
    assert default_data_dir("win32", {"LOCALAPPDATA": str(root)}) == root / "NewsFlowAI"
    override = tmp_path / "별도 데이터"
    assert default_data_dir("win32", {"NEWSFLOW_DATA_DIR": str(override)}) == override
    with pytest.raises(ValueError):
        default_data_dir("win32", {})
    with pytest.raises(ValueError):
        default_data_dir("win32", {"LOCALAPPDATA": "relative/path"})


def test_layout_unicode_spaces_percent_and_db_config_separation(tmp_path):
    root = tmp_path / "사용자 자료 100% #" / "NewsFlow AI"
    prepare_data_dir(root)
    assert all((root / name).is_dir() for name in ("logs", "content", "videos"))
    app = create_app(Settings(data_dir=root))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/settings").status_code == 200
        with app.state.sessions.begin() as session:
            session.get(AppSetting, "request_timeout").value = "8"
    app = create_app(Settings(data_dir=root))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert 'value="8"' in client.get("/settings").text
        assert (root / "newsflow.db").is_file()
        assert (root / "session.key").is_file()


def test_bat_static_version_quotes_no_secrets():
    raw = (ROOT / "run.bat").read_bytes()
    script = raw.decode("ascii")
    assert b"\r\n" in raw
    assert 'cd /d "%~dp0"' in script
    assert "py -3.12" in script and "sys.version_info[:2] == (3,12)" in script
    assert '"tools\\windows_launcher.py"' in script
    assert "if errorlevel 1" in script
    assert "exit /b %NF_EXIT%" in script
    assert 'set "NF_EXIT=%ERRORLEVEL%"' in script
    assert "API_KEY" not in script and "PASSWORD" not in script
    assert "set\r\n" not in script


def test_install_failure_stops_marker_and_redacts(tmp_path, monkeypatch, capsys):
    module = launcher()
    root = tmp_path / "프로젝트 공간"
    python = root / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    (root / "pyproject.toml").write_text("test")
    (root / "requirements-dev.lock").write_text("test")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert isinstance(command, list)
        return subprocess.CompletedProcess(command, 1 if "install" in command else 0)

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(module.LaunchError, match="의존성 설치"):
        module.ensure_environment(root)
    assert not (root / ".venv/.newsflow-installed").exists()
    assert all("newsflow.main" not in cmd for cmd in calls)
    assert "secret" not in capsys.readouterr().out


def test_install_marker_refresh_on_dependency_change(tmp_path, monkeypatch):
    module = launcher()
    root = tmp_path
    python = root / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    (root / "pyproject.toml").write_text("a")
    (root / "requirements-dev.lock").write_text("b")
    calls = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or subprocess.CompletedProcess(command, 0),
    )
    module.ensure_environment(root)
    assert sum("install" in c for c in calls) == 1
    module.ensure_environment(root)
    assert sum("install" in c for c in calls) == 1
    (root / "requirements-dev.lock").write_text("changed")
    module.ensure_environment(root)
    assert sum("install" in c for c in calls) == 2


def test_server_socket_conflict_and_release():
    with reserve_socket("127.0.0.1", 0) as listener:
        port = listener.getsockname()[1]
        with pytest.raises(PortInUseError):
            reserve_socket("127.0.0.1", port)
    with reserve_socket("127.0.0.1", port):
        pass


def test_runtime_logging_is_separate(tmp_path):
    root = tmp_path / "앱 데이터"
    prepare_data_dir(root)
    logger = runtime_logger(root)
    logger.info("server_start port=8765")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    assert "server_start" in (root / "logs/execution.log").read_text(encoding="utf-8")
    assert not (ROOT / "execution.log").exists()


def test_migrate_existing_database_settings_and_key(tmp_path, rss):
    original = tmp_path / "기존 데이터"
    target = tmp_path / "새 사용자 공간"
    from newsflow.news.rss_adapter import FakeRSSAdapter

    app = create_app(Settings(data_dir=original), FakeRSSAdapter({"https://example.com/rss": rss}))
    with TestClient(app, base_url="http://127.0.0.1"):
        with app.state.sessions.begin() as session:
            session.add(NewsSource(name="이전 테스트", url="https://example.com/rss"))
            session.get(AppSetting, "request_timeout").value = "6"
        app.state.coordinator.start()
        app.state.coordinator.future.result(timeout=10)
    original_key = (original / "session.key").read_bytes()
    migrate_data(original, target)
    assert (original / "newsflow.db").is_file()
    assert (target / "session.key").read_bytes() == original_key
    app = create_app(Settings(data_dir=target))
    with TestClient(app, base_url="http://127.0.0.1"), app.state.sessions() as session:
        assert session.get(AppSetting, "request_timeout").value == "6"
        assert session.scalar(select(NewsSource).where(NewsSource.name == "이전 테스트"))
        for model in (NewsArticle, ArticleMention, ArticleScore):
            assert session.scalar(select(func.count()).select_from(model)) == 3
    with pytest.raises(ValueError, match="덮어쓰지"):
        migrate_data(original, target)
    assert (target / "session.key").read_bytes() == original_key


def test_migration_bad_or_overlapping_source(tmp_path):
    with pytest.raises(ValueError):
        migrate_data(tmp_path, tmp_path)
    with pytest.raises(ValueError):
        migrate_data(tmp_path / "missing", tmp_path / "new")


def test_actual_server_lifecycle_and_port_collision(tmp_path):
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    env = os.environ.copy()
    env.update(
        NEWSFLOW_DATA_DIR=str(tmp_path / "운영 데이터"), NEWSFLOW_PORT=str(port), NEWSFLOW_HOST="127.0.0.1"
    )
    from urllib.request import urlopen

    process = subprocess.Popen(
        [sys.executable, "-m", "newsflow.main"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        for _ in range(80):
            assert process.poll() is None
            try:
                with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                    assert json.load(response)["status"] == "ok"
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("server readiness timeout")
        import http.cookiejar
        from urllib.parse import urlencode
        from urllib.request import HTTPCookieProcessor, Request, build_opener

        base = f"http://127.0.0.1:{port}"
        jar = http.cookiejar.CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))
        with opener.open(base + "/settings", timeout=3) as response:
            assert response.status == 200

        def post(path, fields):
            token = next(cookie.value for cookie in jar if cookie.name == "newsflow_csrf")
            request = Request(
                base + path,
                data=urlencode({**fields, "csrf_token": token}).encode(),
                headers={"Origin": base},
            )
            with opener.open(request, timeout=5) as response:
                assert response.status == 200

        post("/settings/collection", {"timeout": 7})
        post(
            "/settings/sources",
            {"name": "오프라인 출처", "url": "https://example.com/rss", "permission": "true"},
        )
        post("/settings/sources/2/toggle", {})
        post("/settings/sources/2/toggle", {"permission": "true"})
        post("/settings/sources/2/toggle", {})
        post("/collection", {})
        for _ in range(30):
            with opener.open(base + "/api/collection", timeout=3) as response:
                status = json.load(response)["status"]
            if status != "running":
                break
            time.sleep(0.1)
        assert status == "empty"  # Offline: registered source was deliberately disabled.
        duplicate = subprocess.run(
            [sys.executable, "-m", "newsflow.main"],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert duplicate.returncode != 0
        assert "지정 포트" in duplicate.stdout or "이미 실행" in duplicate.stdout
    finally:
        process.terminate()
        process.wait(timeout=15)
    with socket.socket() as check:
        assert check.connect_ex(("127.0.0.1", port)) != 0
    assert (tmp_path / "운영 데이터/logs/execution.log").exists()


def test_invalid_secret_not_printed(tmp_path):
    env = os.environ.copy()
    sentinel = "SECRET-SENTINEL"
    env.update(NEWSFLOW_SECRET_KEY=sentinel, NEWSFLOW_DATA_DIR=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-m", "newsflow.main"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert sentinel not in result.stdout + result.stderr


def test_migration_closes_sqlite_handles(tmp_path, monkeypatch):
    import sqlite3

    import newsflow.migrate_data as module

    source = tmp_path / "source"
    source.mkdir()
    with sqlite3.connect(source / "newsflow.db") as connection:
        connection.execute("CREATE TABLE alembic_version(version_num TEXT)")
        connection.execute("INSERT INTO alembic_version VALUES ('0001')")
    connection.close()
    real_connect = sqlite3.connect
    handles = []

    def connect(*args, **kwargs):
        actual = real_connect(*args, **kwargs)
        handles.append(actual)
        return actual

    monkeypatch.setattr(module.sqlite3, "connect", connect)
    module.migrate_data(source, tmp_path / "target")
    assert len(handles) == 2
    for handle in handles:
        with pytest.raises(sqlite3.ProgrammingError):
            handle.execute("SELECT 1")
