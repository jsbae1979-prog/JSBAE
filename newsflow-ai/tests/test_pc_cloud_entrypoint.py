"""Actual Windows run() in a subprocess with a new synthetic profile and bounded local server."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CHILD = r"""
import faulthandler,json,os,sys,threading,time
faulthandler.dump_traceback_later(20)
from pathlib import Path
from pc_cloud_guard import audit,attempts
sys.addaudithook(audit)
from newsflow import main
from newsflow.news.rss_adapter import FakeRSSAdapter
from newsflow.scheduler.service import Scheduler
from newsflow.publishing.calendar import PublishingCalendar
from newsflow.video.ai.service import AIVideoCoordinator
Scheduler.start=lambda self:None
PublishingCalendar.start=lambda self:None
AIVideoCoordinator.start=lambda self:None
create=main.create_app
main.create_app=lambda settings,**kwargs:create(settings,FakeRSSAdapter({}),**kwargs)
import uvicorn
server=uvicorn.Server
class BoundedServer(server):
    def __init__(self,config):
        config.timeout_graceful_shutdown=3
        super().__init__(config)
    async def startup(self,sockets=None):
        await super().startup(sockets)
        def wait_stop():
            deadline=time.monotonic()+60
            while not Path(os.environ['NF_STOP_FILE']).exists() and time.monotonic()<deadline:
                time.sleep(.05)
            self.should_exit=True
        threading.Thread(target=wait_stop,daemon=True).start()
uvicorn.Server=BoundedServer
main.run()
faulthandler.cancel_dump_traceback_later()
Path(os.environ['NF_GUARD_RESULT']).write_text(json.dumps({'attempts':attempts,'shutdown':'normal'}))
"""


def test_windows_entrypoint_and_synthetic_profile_survive_normal_reopen(tmp_path):
    import sqlite3

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    assert port != 8765
    profile = tmp_path / "fresh-profile"
    env = dict(os.environ, NEWSFLOW_DATA_DIR=str(profile), NEWSFLOW_PORT=str(port))
    project = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project / "tools") + os.pathsep + str(project / "src")
    env["LOCALAPPDATA"], env["APPDATA"] = str(tmp_path / "local"), str(tmp_path / "roaming")
    for name in list(env):
        if name.upper().endswith(("_KEY", "_TOKEN", "_SECRET")):
            del env[name]
    # No settings/keys/media from a real profile are copied or loaded.
    output = Path(os.environ.get("NEWSFLOW_VALIDATION_OUTPUT", str(tmp_path)))
    expected_rows = None
    for attempt in (1, 2):
        stop = tmp_path / f"stop-{attempt}"
        guard = tmp_path / f"guard-{attempt}.json"
        env.update(NF_STOP_FILE=str(stop), NF_GUARD_RESULT=str(guard))
        with (tmp_path / f"entry-{attempt}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "-B", "-c", CHILD], env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while True:
                    assert process.poll() is None
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                            assert response.status == 200
                            response.read()
                        break
                    except (OSError, TimeoutError):
                        assert time.monotonic() < deadline
                        time.sleep(.05)
                for path in ("/news", "/ai", "/video", "/queue", "/analytics", "/simple-settings"):
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
                        assert response.status == 200
                        response.read()
            finally:
                stop.touch()
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)
                    raise
            assert process.returncode == 0, (tmp_path / f"entry-{attempt}.log").read_text(encoding="utf-8")
        assert json.loads(guard.read_text()) == {"attempts": [], "shutdown": "normal"}
        with sqlite3.connect(profile / "newsflow.db") as connection:
            assert connection.execute("pragma integrity_check").fetchone() == ("ok",)
            assert connection.execute("pragma foreign_key_check").fetchall() == []
            assert connection.execute("select version_num from alembic_version").fetchall() == [("0018",)]
            rows = {table: connection.execute(f"select count(*) from {table}").fetchone()[0]
                    for table in ("news_articles", "content_drafts", "publish_jobs", "api_request_reservations")}
        if expected_rows is not None:
            assert rows == expected_rows
        expected_rows = rows
    (output / "entrypoint-result.json").write_text(json.dumps({
        "status": "PASS", "launches": 2, "shutdown": "normal", "revision": "0018",
        "integrity": "ok", "foreign_key_errors": 0, "stored_counts_preserved": expected_rows,
        "external_requests": 0, "operating_profile_used": False,
    }), encoding="utf-8")
