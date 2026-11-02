"""Synthetic accounts, media and providers only. No credentials or network access."""

import json
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from newsflow.db.models import AppSetting, Base, utcnow
from newsflow.db.session import make_engine, session_factory
from newsflow.meta.contracts import SCOPES, Grant, MetaError, parse_grant
from newsflow.meta.graph import MetaGraph
from newsflow.meta.media import MetaDelivery
from newsflow.meta.media_server import create_media_app
from newsflow.meta.models import MetaAccount
from newsflow.meta.publishing import MetaPublishing
from newsflow.meta.relay import (
    MetaBusinessSessions,
    MetaServerConfig,
    create_meta_relay_app,
)
from newsflow.meta.service import DEFAULTS, MetaConnections

pytestmark = pytest.mark.usefixtures("synthetic_app_isolation")


class Vault:
    def __init__(self):
        self.values = {}

    def put(self, key, identity, bundle):
        ref = uuid4().hex
        self.values[(key, identity, ref)] = bundle
        return ref

    def get(self, key, identity, ref):
        return self.values[(key, identity, ref)]

    def delete(self, key, identity, ref):
        self.values.pop((key, identity, ref), None)


def grant(page="101", ig="201", **changes):
    return replace(
        Grant(
            DEFAULTS["appId"],
            page,
            "Synthetic " + page,
            ig,
            "synthetic_" + page if ig else None,
            SCOPES,
            ("CREATE_CONTENT",),
            utcnow() + timedelta(days=60),
            None,
            utcnow() + timedelta(days=90),
            SecretStr("synthetic-user-" + page),
            SecretStr("synthetic-page-" + page),
        ),
        **changes,
    )


@pytest.fixture
def env(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    sessions = session_factory(engine)
    a = MetaConnections(sessions, tmp_path / "a", owner="a" * 64, vault=Vault())
    b = MetaConnections(sessions, tmp_path / "b", owner="b" * 64, vault=Vault())
    ids = [
        a.accept(grant(), app_id=DEFAULTS["appId"]),
        a.accept(grant("102", "202"), app_id=DEFAULTS["appId"]),
    ]
    b_id = b.accept(grant("103", "203"), app_id=DEFAULTS["appId"])
    yield SimpleNamespace(a=a, b=b, ids=ids, b_id=b_id, sessions=sessions, root=tmp_path)
    engine.dispose()


def test_two_users_two_accounts_metadata_and_secret_separation(env):
    assert len(env.a.accounts()) == 2 and len(env.b.accounts()) == 1
    assert env.a.credential(env.ids[0], "facebook")[1] == "101"
    assert env.a.credential(env.ids[1], "instagram")[1] == "202"
    with pytest.raises(MetaError):
        env.a.credential(env.b_id, "facebook")
    view = json.dumps(env.a.status())
    assert "synthetic-user-" not in view and "synthetic-page-" not in view and "reference" not in view
    with env.sessions() as db:
        for row in db.scalars(select(MetaAccount)):
            assert "synthetic-user-" not in str(row.__dict__) and "synthetic-page-" not in str(row.__dict__)


@pytest.mark.parametrize("operation", ["disconnect", "rename", "credential"])
def test_foreign_connection_rejected(env, operation):
    args = {"disconnect": (), "rename": ("renamed",), "credential": ("instagram",)}[operation]
    with pytest.raises(MetaError, match="이 사용자"):
        getattr(env.a, operation)(env.b_id, *args)
    assert env.b.accounts()[0]["state"] == "connected"


def test_reconnect_rotates_only_owned_ciphertext_and_disconnect_revokes(env):
    before = set(env.a.vault.values)
    key = env.ids[0]
    env.a.accept(grant(user_token=SecretStr("synthetic-new-user")), app_id=DEFAULTS["appId"], reconnect=key)
    assert len(env.a.vault.values) == 4 and len(before & set(env.a.vault.values)) == 2
    assert next(r for r in env.a.accounts() if r["id"] == key)["revision"] == 2
    env.a.disconnect(key)
    env.a.disconnect(key)
    assert len(env.a.vault.values) == 2
    with pytest.raises(MetaError):
        env.a.credential(key, "instagram")
    assert len(env.b.vault.values) == 2


def test_expiries_are_distinct_and_user_expiry_does_not_fake_page_expiry(env):
    with env.sessions.begin() as db:
        row = db.get(MetaAccount, env.ids[0])
        row.user_expires_at = utcnow() - timedelta(days=1)
    assert env.a.credential(env.ids[0], "facebook")[1] == "101"
    with env.sessions.begin() as db:
        db.get(MetaAccount, env.ids[0]).data_expires_at = utcnow() - timedelta(seconds=1)
    with pytest.raises(MetaError, match="만료"):
        env.a.credential(env.ids[0], "facebook")
    assert env.a.accounts()[0]["pageExpiresAt"] is None


def test_permissions_and_config_are_owner_scoped(env):
    env.a.configure({**DEFAULTS, "relayOrigin": "https://auth.example.com"})
    assert env.b.config()["relayOrigin"] == ""
    with env.sessions.begin() as db:
        db.get(MetaAccount, env.ids[0]).scopes = ["pages_show_list"]
    with pytest.raises(MetaError, match="권한"):
        env.a.credential(env.ids[0], "instagram")
    with pytest.raises(MetaError):
        env.a.accept(grant("104", "204"), app_id=DEFAULTS["appId"], reconnect=env.ids[1])


class Graph:
    def __init__(self):
        self.calls = []
        self.fail = None
        self.status = "FINISHED"

    def call(self, method, path, token, values):
        self.calls.append((method, path, token.get_secret_value(), values))
        if self.fail:
            raise self.fail
        if method == "POST":
            return {"id": "9001", "post_id": "101_9001"}
        if values.get("fields") == "status_code":
            return {"status_code": self.status}
        return {"id": path, "is_published": True, "published": True, "status": {"video_status": "ready"}}


class Delivery:
    def __init__(self):
        self.calls = []

    def ready(self):
        return True

    def upload(self, *args):
        self.calls.append(args)
        return "https://media.example.com/media/" + "a" * 64 + ".jpg"


def publisher(env, kind="image", owner=None):
    media = {"path": env.root / "synthetic.jpg", "sha256": "a" * 64, "kind": kind}
    p = MetaPublishing(owner or env.a, Graph(), lambda key: media, Delivery())
    return p, media


def prepare(p, account, platform="instagram"):
    return p.prepare(
        "post:1", [{"connectionId": account, "platform": platform}], "Synthetic caption", reviewed=True
    )[0]["id"]


@pytest.mark.parametrize(
    "kind,platform",
    [("image", "instagram"), ("video", "instagram"), ("image", "facebook"), ("video", "facebook")],
)
def test_media_flow_target_token_and_final_confirmation(env, kind, platform):
    p, _ = publisher(env, kind)
    identifier = prepare(p, env.ids[1], platform)
    assert p.graph.calls == [] and p.delivery.calls == []
    result = p.send(identifier, consent=True)
    assert p.graph.calls[0][2] == "synthetic-page-102"
    assert p.graph.calls[0][1].startswith("202/" if platform == "instagram" else "102/")
    if platform == "instagram":
        assert result["state"] == "processing"
        assert p.check(identifier)["state"] == "ready"
        assert p.publish(identifier, consent=True)["state"] == "published_unverified"
    assert p.check(identifier)["state"] == "published"
    assert p.list_one(identifier)["publishedAt"]
    with pytest.raises(MetaError):
        p.send(identifier, consent=True)
    with pytest.raises(MetaError):
        p.publish(identifier, consent=True)


def test_unknown_outcome_retained_no_retry_and_other_target_independent(env):
    p, _ = publisher(env)
    first = prepare(p, env.ids[0])
    second = prepare(p, env.ids[1])
    p.graph.fail = TimeoutError("synthetic-private-token")
    assert p.send(first, consent=True)["state"] == "unknown"
    with pytest.raises(MetaError):
        p.send(first, consent=True)
    assert len(p.graph.calls) == 1
    assert prepare(p, env.ids[0]) == first
    p.graph.fail = None
    assert p.send(second, consent=True)["state"] == "processing"
    assert "synthetic-private-token" not in json.dumps(p.list())


@pytest.mark.parametrize("state", ["sending", "publishing"])
def test_interrupted_submission_becomes_unknown_only_for_owner(env, state):
    p, _ = publisher(env)
    q, _ = publisher(env, owner=env.b)
    mine = prepare(p, env.ids[0])
    other = prepare(q, env.b_id)
    p._set(mine, state)
    q._set(other, state)
    assert p.recover() == 1
    assert p.list_one(mine)["state"] == "unknown" and q.list_one(other)["state"] == state
    assert not p.graph.calls


@pytest.mark.parametrize("operation", ["send", "check", "publish", "list_one"])
def test_foreign_publication_is_not_read_or_sent(env, operation):
    p, _ = publisher(env)
    q, _ = publisher(env, owner=env.b)
    other = prepare(q, env.b_id)
    with pytest.raises(MetaError):
        getattr(p, operation)(other, **({"consent": True} if operation in {"send", "publish"} else {}))
    assert p.graph.calls == [] and p.delivery.calls == []


def test_consent_changed_media_and_reconnected_identity_block_send(env):
    p, media = publisher(env)
    identifier = prepare(p, env.ids[0])
    with pytest.raises(MetaError):
        p.send(identifier)
    media["sha256"] = "b" * 64
    with pytest.raises(MetaError):
        p.send(identifier, consent=True)
    media["sha256"] = "a" * 64
    env.a.accept(grant(), app_id=DEFAULTS["appId"], reconnect=env.ids[0])
    assert p.send(identifier, consent=True)["errorCode"] == "identity"
    assert not p.graph.calls and not p.delivery.calls


def test_auth_revocation_invalidates_only_one_connection(env):
    p, _ = publisher(env)
    identifier = prepare(p, env.ids[0])
    p.graph.fail = MetaError("expired")
    assert p.send(identifier, consent=True)["state"] == "failed"
    states = {r["id"]: r["state"] for r in env.a.accounts()}
    assert states[env.ids[0]] == "expired" and states[env.ids[1]] == "connected"


@pytest.mark.parametrize(
    "status,body,code",
    [
        (401, {"error": {"code": 190, "message": "private-token"}}, "expired"),
        (403, {}, "permission"),
        (429, {}, "unknown"),
        (500, {}, "unknown"),
        (400, {}, "rejected"),
    ],
)
def test_graph_errors_safe_and_single_attempt(status, body, code):
    calls = []

    def http(*args):
        calls.append(args)
        return status, json.dumps(body).encode()

    graph = MetaGraph(transport=http)
    with pytest.raises(MetaError) as error:
        graph.call("POST", "101/photos", SecretStr("synthetic-page"), {"message": "hello"})
    assert error.value.code == code and "private-token" not in str(error.value) and len(calls) == 1
    assert calls[0][1] == "https://graph.facebook.com/v26.0/101/photos"
    assert "synthetic-page" not in calls[0][1] and b"synthetic-page" not in calls[0][3]


def test_graph_rejects_arbitrary_paths():
    graph = MetaGraph(transport=lambda *a: pytest.fail("network"))
    for path in ("https://evil.example", "../me", "101/permissions"):
        with pytest.raises(MetaError):
            graph.call("POST", path, SecretStr("synthetic"))


def jpeg():
    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (1080, 1350), "navy").save(out, format="JPEG")
    return out.getvalue()


def test_media_server_auth_expiry_range_and_revocation(tmp_path):
    now = [1000]
    secret = "s" * 64
    owners = {sha256(secret.encode()).hexdigest(): "a" * 32}
    app = create_media_app(tmp_path, "https://media.example.com", owners, clock=lambda: now[0])
    with TestClient(app, base_url="https://media.example.com") as client:
        assert (
            client.post("/v1/media", content=jpeg(), headers={"Content-Type": "image/jpeg"}).status_code
            == 403
        )
        response = client.post(
            "/v1/media",
            content=jpeg(),
            headers={"Content-Type": "image/jpeg", "Authorization": "Bearer " + secret},
        )
        assert response.status_code == 200
        path = urlsplit(response.json()["url"]).path
        assert client.get(path).content == jpeg()
        assert client.get(path, headers={"Range": "bytes=0-9"}).status_code == 206
        assert secret not in response.text
        now[0] += 3601
        assert client.get(path).status_code == 404
        now[0] = 1000
        owners.clear()
        assert client.get(path).status_code == 404


def test_delivery_per_owner_key_and_hash_checked_before_network(env):
    calls = []
    path = env.root / "test.jpg"
    path.write_bytes(jpeg())
    digest = sha256(jpeg()).hexdigest()

    def upload(origin, raw, kind, secret):
        calls.append((kind, secret))
        return {"url": origin + "/media/" + "a" * 64 + ".jpg", "sha256": digest}

    delivery = MetaDelivery(env.a, transport=upload)
    other = MetaDelivery(env.b)
    assert not delivery.ready()
    delivery.configure("https://media.example.com", "s" * 64)
    assert delivery.ready() and not other.ready()
    assert delivery.upload(path, digest, "image").endswith(".jpg")
    assert calls == [("image", "s" * 64)]
    with pytest.raises(MetaError):
        delivery.upload(path, "b" * 64, "image")
    assert len(calls) == 1
    with env.sessions() as db:
        assert "s" * 64 not in str([(s.key, s.value) for s in db.scalars(select(AppSetting))])


class RelayFake:
    def __init__(self):
        self.calls = []
        self.expire = False

    def exchange(self, code):
        self.calls.append("exchange")
        return {"access_token": "synthetic-user"}

    def inspect(self, token):
        page = token.get_secret_value().removeprefix("synthetic-page-")
        base = {
            "is_valid": True,
            "app_id": DEFAULTS["appId"],
            "scopes": list(SCOPES),
            "data_access_expires_at": 2100010000,
        }
        return {
            "data": {
                **base,
                **(
                    {"type": "USER", "user_id": "99", "expires_at": 2099990000 if self.expire else 2100009000}
                    if token.get_secret_value() == "synthetic-user"
                    else {"type": "PAGE", "profile_id": page, "expires_at": 0}
                ),
            }
        }

    def permissions(self, token):
        return {"data": [{"permission": s, "status": "granted"} for s in SCOPES]}

    def pages(self, token):
        return {
            "data": [
                {
                    "id": p,
                    "name": "Synthetic " + p,
                    "tasks": ["CREATE_CONTENT"],
                    "access_token": "synthetic-page-" + p,
                    **({"instagram_business_account": {"id": "201"}} if p == "101" else {}),
                }
                for p in ("101", "102")
            ]
        }

    def profile(self, identifier, token):
        return {"id": identifier, "username": "synthetic101"}


def test_relay_two_pages_no_token_in_browser_and_one_use():
    fake = RelayFake()
    cfg = MetaServerConfig(
        "https://auth.example.com", DEFAULTS["appId"], DEFAULTS["configId"], SecretStr("synthetic-secret")
    )
    app = create_meta_relay_app(cfg, transport=fake, clock=lambda: 2100000000)
    verifier = "v" * 64
    headers = {"Authorization": "Bearer " + verifier}
    with TestClient(app, base_url=cfg.public_origin) as client:
        start = client.post("/v1/sessions", json={"challenge": sha256(verifier.encode()).hexdigest()}).json()
        assert "/v26.0/" in start["authorize_url"]
        state = parse_qs(urlsplit(start["authorize_url"]).query)["state"][0]
        callback = client.get("/oauth/callback", params={"state": state, "code": "synthetic-code"})
        assert "synthetic-user" not in callback.text and "synthetic-page" not in callback.text
        route = "/v1/sessions/" + start["session_id"]
        poll = client.get(route, headers=headers).json()
        assert len(poll["pages"]) == 2 and poll["pages"][1]["instagram_id"] is None
        assert "access_token" not in json.dumps(poll)
        assert client.get(route, headers={"Authorization": "Bearer " + "w" * 64}).status_code == 403
        result = client.post(route + "/redeem", headers=headers, json={"page_id": "101"})
        assert result.status_code == 200
        parsed = parse_grant(result.json(), cfg.app_id, "101")
        assert parsed.page_token.get_secret_value() == "synthetic-page-101" and parsed.page_expires_at is None
        assert "synthetic-page-102" not in result.text and "_selected_grants" not in result.text
        assert client.post(route + "/redeem", headers=headers, json={"page_id": "101"}).status_code == 409
        assert fake.calls == ["exchange"]


def test_relay_expiry_and_cancel_fail_closed():
    fake = RelayFake()
    fake.expire = True
    cfg = MetaServerConfig(
        "https://auth.example.com", DEFAULTS["appId"], DEFAULTS["configId"], SecretStr("synthetic-secret")
    )
    store = MetaBusinessSessions(cfg, fake, lambda: 2100000000)
    from newsflow.oauth.relay_server import RelayError

    with pytest.raises(RelayError):
        store._exchange(SecretStr("synthetic-code"), lambda: None)


def test_routes_keep_csrf_and_no_network_on_status(app, client, env):
    p, _ = publisher(env)
    app.state.meta_connections = env.a
    app.state.meta_publishing = p
    response = client.get("/api/meta/status")
    assert response.status_code == 200
    assert client.post("/api/meta/connect", data={"consent": "true"}).status_code == 403
    token = client.cookies.get("newsflow_csrf")
    assert (
        client.post(
            "/api/meta/connect",
            data={"consent": "true", "csrf_token": token},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert not p.graph.calls and not p.delivery.calls


def test_route_inventory_in_both_catalogs():
    from newsflow.meta.routes import router

    root = Path(__file__).parents[1]
    paths = {r.path for r in router.routes if "POST" in r.methods}
    a = json.loads((root / "src/newsflow/studio/actions.json").read_text(encoding="utf8"))
    b = json.loads((root / "frontend/src/legacy-actions.json").read_text(encoding="utf8"))
    assert paths <= {r["path"] for r in a} and paths <= {r["path"] for r in b}


def test_additive_migration_has_no_tokens(tmp_path):
    from sqlalchemy import inspect

    from newsflow.db.session import migrate

    engine = make_engine(tmp_path / "migration.db")
    try:
        migrate(engine)
        tables = inspect(engine).get_table_names()
        assert "meta_accounts" in tables and "meta_publications" in tables
        cols = {c["name"] for c in inspect(engine).get_columns("meta_accounts")}
        assert (
            "user_ref" in cols
            and "page_ref" in cols
            and not {"access_token", "page_token", "user_token"} & cols
        )
    finally:
        engine.dispose()


def test_poll_cannot_rewind_concurrent_publication(env):
    p, _ = publisher(env)
    identifier = prepare(p, env.ids[0])
    p.send(identifier, consent=True)
    p.check(identifier)

    class DelayedPoll:
        def call(self, *args):
            p._set(identifier, "published_unverified", remote_id="9901")
            return {"status_code": "FINISHED"}

    p.graph = DelayedPoll()
    assert p.check(identifier)["state"] == "published_unverified"
    with pytest.raises(MetaError):
        p.publish(identifier, consent=True)


def test_facebook_object_existence_is_not_publication_proof(env):
    p, _ = publisher(env, "video")
    identifier = prepare(p, env.ids[0], "facebook")
    p.send(identifier, consent=True)

    class PendingVideo:
        def call(self, *args):
            return {"id": "101_9001", "published": False, "status": {"video_status": "processing"}}

    p.graph = PendingVideo()
    assert p.check(identifier)["state"] == "published_unverified"
    assert p.list_one(identifier)["publishedAt"] is None


def test_invalid_media_credential_is_not_echoed(app, client, env):
    p, _ = publisher(env)
    p.delivery = MetaDelivery(env.a)
    app.state.meta_connections = env.a
    app.state.meta_publishing = p
    client.get("/api/meta/status")
    csrf = client.cookies.get("newsflow_csrf")
    secret = "synthetic-secret-too-long-" * 30
    response = client.post(
        "/api/meta/media-config",
        data={"origin": "https://media.example.com", "credential": secret, "csrf_token": csrf},
    )
    assert response.status_code == 422 and secret not in response.text


def test_missing_or_partial_permissions_do_not_yield_ig_grant():
    fake = RelayFake()
    fake.permissions = lambda token: {"data": [{"permission": s, "status": "granted"} for s in SCOPES[:3]]}
    cfg = MetaServerConfig(
        "https://auth.example.com", DEFAULTS["appId"], DEFAULTS["configId"], SecretStr("synthetic-secret")
    )
    store = MetaBusinessSessions(cfg, fake, lambda: 2100000000)
    result, pages = store._exchange(SecretStr("synthetic-code"), lambda: None)
    assert all(page["instagram_id"] is None for page in pages)
    assert "instagram_content_publish" not in result["scopes"]


def test_unknown_permission_loss_keeps_container_and_disables_resubmit(env):
    p, _ = publisher(env)
    identifier = prepare(p, env.ids[0])
    p.send(identifier, consent=True)
    p.graph.fail = MetaError("permission")
    assert p.check(identifier)["state"] == "processing"
    with env.sessions() as db:
        from newsflow.meta.models import MetaPublication

        assert db.get(MetaPublication, identifier).container_id == "9001"
    with pytest.raises(MetaError):
        p.send(identifier, consent=True)


def test_native_vault_rejects_other_windows_owner_before_decryption(tmp_path, monkeypatch):
    from newsflow.meta import vault

    monkeypatch.setattr(vault, "local_owner", lambda: "b" * 64)
    locked = vault.MetaVault(tmp_path / "protected", "a" * 64)
    with pytest.raises(MetaError):
        locked.backend()
    assert not (tmp_path / "protected").exists()


@pytest.mark.parametrize("enabled", [False, True])
def test_bat_meta_routes_preserve_auth_and_exact_scope(enabled):
    import asyncio
    from bat_distribution.meta_access import MetaRequests

    called = []

    async def normal(scope, receive, send):
        called.append("normal")

    async def authenticated(scope, receive, send):
        called.append("authenticated")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        called.append(message.get("status"))

    app = MetaRequests(normal, authenticated, enabled=enabled)

    def run(method, path):
        called.clear()
        asyncio.run(app({"type": "http", "method": method, "path": path}, receive, send))
        return called[:]

    assert run("GET", "/api/meta/status") == ["authenticated"]
    assert run("POST", "/api/meta/config") == ["authenticated"]
    assert run("POST", "/api/meta/connect") == (["authenticated"] if enabled else [403, None])
    assert run("POST", "/api/meta/publications/" + "a" * 32 + "/publish") == (
        ["authenticated"] if enabled else [403, None]
    )
    for method, path in [
        ("GET", "/api/meta/connect"),
        ("POST", "/api/meta/anything"),
        ("POST", "/api/meta/accounts/../disconnect"),
        ("POST", "/instagram/publish"),
    ]:
        assert run(method, path) == ["normal"]


def test_disconnect_cleanup_can_be_retried_without_reviving_account(env):
    identifier = env.ids[0]
    original = env.a.vault.delete

    def fail(*args):
        raise OSError("synthetic failure")

    env.a.vault.delete = fail
    with pytest.raises(OSError):
        env.a.disconnect(identifier)
    account = next(a for a in env.a.accounts() if a["id"] == identifier)
    assert account["state"] == "disconnected" and account["cleanupRequired"]
    with pytest.raises(MetaError):
        env.a.credential(identifier, "facebook")
    env.a.vault.delete = original
    env.a.disconnect(identifier)
    account = next(a for a in env.a.accounts() if a["id"] == identifier)
    assert not account["cleanupRequired"] and account["state"] == "disconnected"


def test_media_server_factory_uses_individual_hashed_credentials(tmp_path, monkeypatch):
    from newsflow.meta.media_server import from_environment

    config = tmp_path / "credential-map.json"
    config.write_text(json.dumps({"a" * 64: "b" * 32}))
    for key, value in {
        "NEWSFLOW_META_MEDIA_CREDENTIALS_FILE": str(config),
        "NEWSFLOW_META_MEDIA_ROOT": str(tmp_path / "media"),
        "NEWSFLOW_META_MEDIA_ORIGIN": "https://media.example.com",
    }.items():
        monkeypatch.setenv(key, value)
    with TestClient(from_environment()) as client:
        assert (
            client.post("/v1/media", content=b"not media", headers={"Content-Type": "image/jpeg"}).status_code
            == 403
        )


def test_png_posting_copy_is_jpeg_and_preserves_original(tmp_path):
    from PIL import Image
    from newsflow.meta.media import jpeg_derivative

    output = BytesIO()
    Image.new("RGBA", (800, 1000), (200, 80, 20, 180)).save(output, format="PNG")
    raw = output.getvalue()
    original = tmp_path / "original.png"
    original.write_bytes(raw)
    path, result = jpeg_derivative(tmp_path, raw)
    assert path.suffix == ".jpg" and original.read_bytes() == raw
    assert Image.open(BytesIO(result)).format == "JPEG"
    assert jpeg_derivative(tmp_path, raw) == (path, result)


def test_page_specific_scope_loss_excludes_ig_choice():
    fake = RelayFake()
    inspect = fake.inspect

    def partial(token):
        result = inspect(token)
        if result["data"].get("type") == "PAGE":
            result["data"]["scopes"] = list(SCOPES[:3])
        return result

    fake.inspect = partial
    cfg = MetaServerConfig(
        "https://auth.example.com", DEFAULTS["appId"], DEFAULTS["configId"], SecretStr("synthetic-secret")
    )
    result, pages = MetaBusinessSessions(cfg, fake, lambda: 2100000000)._exchange(
        SecretStr("synthetic-code"), lambda: None
    )
    assert all(p["instagram_id"] is None for p in pages)


@pytest.mark.parametrize("reason,expected", [("permission", "permission_denied"), ("expired", "expired")])
def test_login_failure_reason_is_safe_and_actionable(reason, expected):
    from newsflow.oauth.relay_server import RelayError

    fake = RelayFake()
    if reason == "permission":
        fake.permissions = lambda token: {"data": []}
    else:
        inspect = fake.inspect

        def expired(token):
            response = inspect(token)
            response["data"]["expires_at"] = 1
            return response

        fake.inspect = expired
    cfg = MetaServerConfig(
        "https://auth.example.com", DEFAULTS["appId"], DEFAULTS["configId"], SecretStr("synthetic-secret")
    )
    with pytest.raises(RelayError) as failure:
        MetaBusinessSessions(cfg, fake, lambda: 2100000000)._exchange(
            SecretStr("synthetic-code"), lambda: None
        )
    assert failure.value.code == expected and "synthetic" not in str(failure.value)
