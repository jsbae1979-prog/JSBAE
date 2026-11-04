"""Synthetic JPEG, loopback HTTP and Fake tunnel/Meta only. Never runs cloudflared."""

import json
import socket
import threading
from hashlib import sha256
from http.client import HTTPConnection
from http.server import HTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import test_meta_accounts
from sqlalchemy import select
from test_meta_accounts import jpeg, prepare

from newsflow.db.models import AppSetting
from newsflow.meta.contracts import MetaError
from newsflow.meta.graph import MetaGraph
from newsflow.meta.local_delivery import LocalImageDelivery
from newsflow.meta.local_image_tunnel import QuickTunnel
from newsflow.meta.local_images import MAX_IMAGE, LocalImageSession
from newsflow.meta.media import MetaDelivery
from newsflow.meta.publishing import MetaPublishing

pytestmark = pytest.mark.usefixtures("synthetic_app_isolation")


@pytest.fixture
def env(tmp_path):
    yield from test_meta_accounts.env.__wrapped__(tmp_path)


class Bridge:
    def __init__(self):
        self.started = self.closed = False
        self.origin = "https://synthetic-local-images.trycloudflare.com"

    def available(self):
        return True

    def start(self, handler, port):
        self.started, self.handler, self.port = True, handler, port
        return self.origin

    def alive(self):
        return self.started and not self.closed

    def close(self):
        self.closed = True


@pytest.fixture
def local():
    bridge = Bridge()
    now = [1000.0]
    fetched = []
    session = None

    def verify(method, url):
        fetched.append((method, url))
        return session.read(urlsplit(url).path)

    session = LocalImageSession(lambda: bridge, 18769, verify=verify, clock=lambda: now[0])
    yield session, bridge, now, fetched
    session.close()


def test_one_snapshot_only_repeat_fetch_and_expiry(local):
    s, bridge, now, fetched = local
    assert not bridge.started
    url = s.offer(jpeg(), sha256(jpeg()).hexdigest())
    path = urlsplit(url).path
    assert len(path.split("/")[-1].split(".")[0]) == 64
    assert s.read(path) == jpeg() and s.read(path) == jpeg()
    assert s.read("/studio/settings") is None
    assert s.read("/api/meta/status") is None
    assert s.read("/image/../../newsflow.db") is None
    assert s.read(path + "?anything=1") is None
    assert fetched == [("GET", url)]
    now[0] += 3600
    assert s.read(path) is None
    s.close()
    assert bridge.closed and not s.images


def test_http_image_only_head_no_upload_no_file_listing_no_secret_logs(local, capsys):
    s, _bridge, _now, _fetched = local
    url = s.offer(jpeg(), sha256(jpeg()).hexdigest())
    path = urlsplit(url).path
    server = HTTPServer(("127.0.0.1", 0), s.handler())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def request(method, target):
        conn = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            conn.request(method, target)
            result = conn.getresponse()
            return result.status, dict(result.getheaders()), result.read()
        finally:
            conn.close()

    try:
        status, headers, body = request("GET", path)
        assert status == 200 and body == jpeg()
        assert headers["Content-Type"] == "image/jpeg" and headers["Cache-Control"] == "no-store"
        assert request("HEAD", path)[2] == b""
        for target in ("/", "/docs", "/api/meta/status", "/image/" + "0" * 64 + ".jpg"):
            assert request("GET", target)[0] == 404
        assert request("POST", path)[0] == 501
        s.close()
        assert request("GET", path)[0] == 404
        assert path not in capsys.readouterr().err
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


@pytest.mark.parametrize("port", [0, 80, 8765, 18768, 65536, True])
def test_invalid_or_operating_port_never_starts(port):
    with pytest.raises(MetaError):
        LocalImageSession(lambda: pytest.fail("no bridge"), port)


@pytest.mark.parametrize(
    "failure", ["hash", "invalid-jpeg", "oversize", "wrong-public-content", "wrong-origin"]
)
def test_preflight_failure_does_not_return_public_url(local, failure):
    s, bridge, _now, _fetched = local
    raw = jpeg()
    digest = sha256(raw).hexdigest()
    if failure == "hash":
        digest = "0" * 64
    if failure == "invalid-jpeg":
        raw = b"not-an-image"
        digest = sha256(raw).hexdigest()
    if failure == "oversize":
        raw = b"a" * (MAX_IMAGE + 1)
        digest = sha256(raw).hexdigest()
    if failure == "wrong-public-content":
        s.verify = lambda *_: b"other"
    if failure == "wrong-origin":
        bridge.origin = "https://evil.test/secret"
    with pytest.raises((MetaError, OSError)):
        s.offer(raw, digest)
    assert not s.images
    if failure in {"hash", "invalid-jpeg", "oversize"}:
        assert not bridge.started
    else:
        assert bridge.closed


def test_user_scope_configuration_does_not_open_listener_or_read_secrets(env):
    bridge = Bridge()
    local = LocalImageDelivery(env.a, lambda: bridge)
    other = LocalImageDelivery(env.b, lambda: Bridge())
    local.configure(True, 18769)
    assert local.ready() and not other.ready() and not bridge.started
    assert local.status() == {"enabled": True, "port": 18769, "available": True, "active": False}
    with pytest.raises(MetaError):
        LocalImageDelivery(env.a).configure(True, 18769)


def test_local_file_outside_owner_root_is_not_exposed(env):
    local = LocalImageDelivery(env.a, lambda: Bridge())
    local.configure(True, 18769)
    path = env.root / "other.jpg"
    path.write_bytes(jpeg())
    with pytest.raises(MetaError):
        local.upload(path, sha256(jpeg()).hexdigest(), "image")
    assert local.session is None


def test_local_send_through_existing_pipeline_no_storage_put_and_no_publish(env):
    raw = jpeg()
    env.a.root.mkdir()
    path = env.a.root / "selected.jpg"
    path.write_bytes(raw)
    bridge = Bridge()
    delivery = MetaDelivery(env.a, local_bridge_factory=lambda: bridge)
    delivery.local.configure(True, 18769)
    fetched = []

    def fetch(method, url):
        fetched.append(method)
        return delivery.local.session.read(urlsplit(url).path)

    delivery.local.verify = fetch
    calls = []

    def meta(method, url, headers, body):
        calls.append((method, url, body))
        return 200, b'{"id":"901","status_code":"FINISHED"}'

    p = MetaPublishing(
        env.a,
        MetaGraph(transport=meta),
        lambda _: {"path": path, "sha256": sha256(raw).hexdigest(), "kind": "image"},
        delivery,
    )
    key = prepare(p, env.ids[0])
    try:
        assert p.transfer_modes()[key] == "local" and p.storage_states()[key]
        with pytest.raises(MetaError):
            p.send(key, consent=False)
        assert not bridge.started and not calls
        assert p.send(key, consent=True)["state"] == "processing"
        assert fetched == ["GET"] and len(calls) == 1
        payload = parse_qs(calls[0][2].decode())
        assert payload["image_url"][0].startswith(bridge.origin + "/image/")
        assert "video_url" not in payload
        assert p.check(key)["state"] == "ready"
        assert not any("media_publish" in call[1] for call in calls)
        with pytest.raises(MetaError):
            p.send(key, consent=True)
        assert len(calls) == 2
        with pytest.raises(MetaError):
            delivery.local.configure(False, 18769)
        with env.sessions() as db:
            settings = " ".join(row.value for row in db.scalars(select(AppSetting)))
        assert "/image/" not in settings and bridge.origin not in settings
        assert path.read_bytes() == raw
    finally:
        delivery.local.close()


def test_broken_local_bridge_does_not_fall_back_to_existing_storage(env):
    delivery = MetaDelivery(env.a, local_bridge_factory=lambda: Bridge())
    delivery.local.configure(True, 18769)
    delivery.local.upload = lambda *_: (_ for _ in ()).throw(MetaError("media"))
    delivery.automatic.provision = lambda *_: pytest.fail("no fallback")
    with pytest.raises(MetaError):
        delivery.upload(Path("not-opened.jpg"), "a" * 64, "image")


def test_quick_tunnel_requires_pinned_binary_and_no_process_on_configuration(tmp_path):
    binary = tmp_path / "cloudflared.exe"
    binary.write_bytes(b"synthetic-binary-never-executed")
    launch = lambda *a, **kw: pytest.fail("no process")
    assert not QuickTunnel(binary, None, popen=launch).available()
    assert not QuickTunnel(binary, "0" * 64, popen=launch).available()
    good = QuickTunnel(binary, sha256(binary.read_bytes()).hexdigest(), popen=launch)
    assert good.available()
    binary.write_bytes(b"changed")
    with pytest.raises(MetaError):
        good.start(None, 18769)


def test_new_post_registered_in_both_catalogs_and_exact_local_boundary():
    from bat_distribution.meta_access import EXTERNAL, LOCAL

    root = Path(__file__).parents[1]
    for file in ("src/newsflow/studio/actions.json", "frontend/src/legacy-actions.json"):
        entries = json.loads((root / file).read_text(encoding="utf-8"))
        rows = [e for e in entries if e["path"] == "/api/meta/local-images"]
        assert len(rows) == 1 and rows[0]["risk"] == "local"
    assert LOCAL.fullmatch("/api/meta/local-images")
    assert not LOCAL.fullmatch("/api/meta/local-images/send")
    assert not EXTERNAL.fullmatch("/api/meta/local-images")


def test_route_requires_csrf_and_settings_do_not_launch_bridge(app, client, env):
    from test_meta_accounts import publisher

    bridge = Bridge()
    p, _ = publisher(env)
    p.delivery = MetaDelivery(env.a, local_bridge_factory=lambda: bridge)
    app.state.meta_connections, app.state.meta_publishing = env.a, p
    values = {"enabled": "true", "port": "18769"}
    assert client.post("/api/meta/local-images", data=values).status_code == 403
    client.get("/api/meta/status")
    values["csrf_token"] = client.cookies.get("newsflow_csrf")
    assert (
        client.post(
            "/api/meta/local-images", data=values, headers={"Origin": "https://foreign.example"}
        ).status_code
        == 403
    )
    assert client.post("/api/meta/local-images", data=values).status_code == 200
    status = client.get("/api/meta/status").json()["localImageDelivery"]
    assert status["enabled"] and status["available"] and not status["active"]
    assert not bridge.started and p.graph.calls == []


def test_quick_tunnel_fake_process_command_and_cleanup(tmp_path, monkeypatch):
    from newsflow.meta.local_image_tunnel import ImageHTTPServer

    binary = tmp_path / "cloudflared.exe"
    binary.write_bytes(b"fake tool")
    calls = []

    class Process:
        def __init__(self):
            self.stdout = StringIO("https://synthetic-image-test.trycloudflare.com |\n")
            self.stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

    def launch(args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    monkeypatch.setenv("NEWSFLOW_API_SECRET", "synthetic-secret")
    tunnel = QuickTunnel(binary, sha256(binary.read_bytes()).hexdigest(), popen=launch)
    # Port zero is used only for this synthetic listener, never exposed by LocalImageSession.
    session = LocalImageSession(lambda: Bridge(), 18769)
    origin = tunnel.start(session.handler(), 0)
    assert origin == "https://synthetic-image-test.trycloudflare.com" and tunnel.alive()
    assert calls[0][0][-1] == "http://127.0.0.1:0"
    assert "--no-autoupdate" in calls[0][0] and "--config" in calls[0][0]
    assert calls[0][1]["shell"] is False and "NEWSFLOW_API_SECRET" not in calls[0][1]["env"]
    assert tunnel.server.server_address[0] == "127.0.0.1"
    port = tunnel.server.server_port
    with pytest.raises(OSError):
        ImageHTTPServer(("127.0.0.1", port), session.handler())
    tunnel.close()
    assert not tunnel.alive()
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0


def test_bridge_failure_keeps_publication_failed_and_no_meta_submit(env):
    from test_meta_accounts import publisher

    p, _ = publisher(env)
    p.delivery.available = lambda _: True
    count = []

    def fail(*args):
        count.append(1)
        raise MetaError("media")

    p.delivery.upload = fail
    identifier = prepare(p, env.ids[0])
    assert p.send(identifier, consent=True)["state"] == "failed"
    with pytest.raises(MetaError):
        p.send(identifier, consent=True)
    assert count == [1] and p.graph.calls == []
