"""Direct-token and signed-storage contracts: Fake providers/credentials/media only."""

import json
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
import test_meta_accounts
from pydantic import SecretStr
from test_meta_accounts import jpeg, prepare, publisher

from newsflow.db.models import AppSetting, utcnow
from newsflow.meta.contracts import SCOPES, MetaError
from newsflow.meta.direct import discover
from newsflow.meta.graph import MetaGraph
from newsflow.meta.media import MetaDelivery
from newsflow.meta.service import DEFAULTS
from newsflow.meta.storage import StorageLinks, storage_url, transfer

pytestmark = pytest.mark.usefixtures("synthetic_app_isolation")


@pytest.fixture
def env(tmp_path):
    yield from test_meta_accounts.env.__wrapped__(tmp_path)


class DiscoveryGraph:
    def __init__(self):
        self.calls = []
        self.invalid = None

    def call(self, method, path, token, values):
        self.calls.append((method, path, values))
        assert method == "GET"
        expiry = int((utcnow() + timedelta(days=60)).timestamp())
        if path == "debug_token":
            page = values["input_token"].startswith("synthetic-page-")
            result = {
                "is_valid": True,
                "type": "PAGE" if page else "USER",
                "app_id": DEFAULTS["appId"],
                "user_id": "301",
                "expires_at": 0 if page else expiry,
                "data_access_expires_at": expiry,
                "profile_id": values["input_token"].removeprefix("synthetic-page-") if page else None,
                "scopes": list(SCOPES),
            }
            if self.invalid:
                result.update(self.invalid)
            return {"data": result}
        if path == "me/permissions":
            return {"data": [{"permission": s, "status": "granted"} for s in SCOPES]}
        if path == "me/accounts":
            return {
                "data": [
                    {
                        "id": p,
                        "name": "Synthetic " + p,
                        "access_token": "synthetic-page-" + p,
                        "tasks": ["CREATE_CONTENT"],
                        "instagram_business_account": {"id": i},
                    }
                    for p, i in [("101", "201"), ("102", "202")]
                ]
            }
        return {"id": path, "username": "synthetic_" + path}


def test_discovery_validates_tokens_and_returns_two_private_grants():
    graph = DiscoveryGraph()
    grants, pages = discover(SecretStr("synthetic-user"), DEFAULTS, graph=graph)
    assert set(grants) == {"101", "102"} and len(pages) == 2
    assert "synthetic-user" not in repr(grants)
    assert "synthetic-page" not in json.dumps(pages)
    assert grants["102"].page_token.get_secret_value() == "synthetic-page-102"
    assert all(method == "GET" for method, _, _ in graph.calls)


@pytest.mark.parametrize(
    "invalid",
    [
        {"is_valid": False},
        {"type": "APP"},
        {"app_id": "999"},
        {"expires_at": 1},
        {"scopes": []},
        {"data_access_expires_at": 0},
    ],
)
def test_unverified_expired_wrong_app_and_missing_scopes_never_import(invalid):
    graph = DiscoveryGraph()
    graph.invalid = invalid
    with pytest.raises(MetaError):
        discover(SecretStr("synthetic-user"), DEFAULTS, graph=graph)
    assert len(graph.calls) <= 2


def factory(graph):
    return lambda token, cfg: discover(token, cfg, graph=graph)


def test_import_no_relay_page_selection_secret_cleanup_owner_separation(env):
    graph = DiscoveryGraph()
    env.a.direct_factory = factory(graph)
    before = len(env.a.vault.values)
    env.a.import_token("synthetic-user", consent=True)
    assert len(env.a.vault.values) == before  # Discovery never persists a token.
    view = env.a.status()
    assert view["directPending"] and len(view["pages"]) == 2 and not view["configured"]
    assert "synthetic-user" not in json.dumps(view) and "synthetic-page" not in json.dumps(view)
    with pytest.raises(MetaError):
        env.a.select_page("999")
    env.a.select_page("101")
    assert not env.a.status()["pending"] and env.a.direct_pending is None
    assert len(env.a.vault.values) == before and len(env.b.accounts()) == 1
    assert env.a.credential(env.ids[0], "instagram")[1] == "201"


def test_consent_foreign_reconnect_timeout_cancel_and_duplicate(env):
    graph = DiscoveryGraph()
    env.a.direct_factory = factory(graph)
    for kwargs in [{}, {"consent": True, "reconnect": env.b_id}]:
        with pytest.raises(MetaError):
            env.a.import_token("synthetic-user", **kwargs)
    assert graph.calls == []
    env.a.import_token("synthetic-user", consent=True)
    count = len(graph.calls)
    with pytest.raises(MetaError):
        env.a.import_token("synthetic-user", consent=True)
    assert len(graph.calls) == count
    env.a.direct_pending["until"] = 0
    assert not env.a.status()["pending"]
    with pytest.raises(MetaError):
        env.a.select_page("101")
    env.a.import_token("synthetic-user", consent=True)
    env.a.cancel()
    assert env.a.direct_pending is None and not env.a.status()["pages"]


def test_failed_discovery_preserves_previous_tokens_and_sanitizes(env):
    before = dict(env.a.vault.values)

    def fail(*args):
        raise RuntimeError("synthetic-private-token-in-error")

    env.a.direct_factory = fail
    with pytest.raises(MetaError) as error:
        env.a.import_token("synthetic-user", consent=True)
    assert "synthetic-private" not in str(error.value)
    assert env.a.vault.values == before and not env.a.pending


def test_graph_token_inspection_is_fixed_host_and_no_error_leak():
    calls = []

    def http(method, url, headers, body):
        calls.append((method, url, headers))
        return 403, json.dumps({"error": {"code": 200, "message": "synthetic-private"}}).encode()

    graph = MetaGraph(transport=http)
    with pytest.raises(MetaError) as error:
        graph.call("GET", "debug_token", SecretStr("synthetic-user"), {"input_token": "synthetic-page"})
    assert len(calls) == 1 and calls[0][1].startswith("https://graph.facebook.com/v26.0/debug_token?")
    assert "synthetic-private" not in str(error.value)
    with pytest.raises(MetaError):
        graph.call("GET", "me/accounts", SecretStr("synthetic-user"), {"input_token": "x"})


def urls():
    return (
        "https://storage.example.com/asset.jpg?put=synthetic",
        "https://storage.example.com/asset.jpg?get=synthetic",
    )


def stored(env, transport):
    raw = jpeg()
    path = env.root / "synthetic-storage.jpg"
    path.write_bytes(raw)
    digest = sha256(raw).hexdigest()
    links = StorageLinks(env.a, transport)
    links.configure(digest, *urls(), (utcnow() + timedelta(hours=2)).isoformat())
    return links, path, digest, raw


def test_storage_config_no_network_encrypted_urls_and_verified_upload(env):
    calls = []

    def transport(method, url, raw=None, kind=None):
        calls.append((method, url))
        return jpeg() if method == "GET" else b""

    links, path, digest, raw = stored(env, transport)
    assert not calls and links.ready(digest)
    with env.sessions() as db:
        assert "https://" not in db.get(AppSetting, links.keys(digest)[0]).value
    assert not StorageLinks(env.b).ready(digest)
    assert links.upload(path, digest, "image") == urls()[1]
    assert [m for m, _ in calls] == ["PUT", "GET"] and path.read_bytes() == raw
    links.upload(path, digest, "image")
    assert [m for m, _ in calls] == ["PUT", "GET", "GET"]  # No duplicate upload across targets.


@pytest.mark.parametrize("failure", ["timeout", "mismatch"])
def test_storage_failure_no_retry_or_url_reset(env, failure):
    calls = []

    def transport(method, *args):
        calls.append(method)
        if failure == "timeout":
            raise TimeoutError("signed-private-url")
        return b"wrong-content"

    links, path, digest, _raw = stored(env, transport)
    with pytest.raises(MetaError):
        links.upload(path, digest, "image")
    count = len(calls)
    with pytest.raises(MetaError):
        links.upload(path, digest, "image")
    with pytest.raises(MetaError):
        links.configure(digest, *urls(), (utcnow() + timedelta(hours=2)).isoformat())
    assert len(calls) == count and links.config(digest)["state"] == "unknown"


@pytest.mark.parametrize(
    "url",
    [
        "http://storage.example.com/a",
        "https://u:p@storage.example.com/a",
        "https://storage.example.com:444/a",
        "https://storage.example.com/a#secret",
        "https://storage.example.com/a\n",
    ],
)
def test_storage_rejects_unsafe_url(url):
    with pytest.raises(MetaError):
        storage_url(url)


def test_storage_ssrf_and_redirect_rejected(monkeypatch):
    import newsflow.meta.storage as module

    def block(*args):
        raise ValueError("non-public address")

    monkeypatch.setattr(module, "public_addresses", block)
    with pytest.raises(ValueError):
        transfer("GET", "https://127.0.0.1/a")
    calls = []

    class Conn:
        def __init__(self, *args):
            pass

        def request(self, *args, **kwargs):
            calls.append(args)

        def getresponse(self):
            return SimpleNamespace(status=302)

        def close(self):
            pass

    monkeypatch.setattr(module, "public_addresses", lambda *a: ["192.0.2.1"])
    monkeypatch.setattr(module, "PinnedConnection", Conn)
    with pytest.raises(MetaError):
        transfer("GET", urls()[1])
    assert len(calls) == 1


def test_storage_integrates_publish_only_after_consent_and_checks_owner(env):
    p, media = publisher(env)
    media["path"].write_bytes(jpeg())
    media["sha256"] = sha256(jpeg()).hexdigest()
    p.delivery = MetaDelivery(env.a)
    calls = []
    p.delivery.links.transport = lambda method, *args: (
        calls.append(method) or (jpeg() if method == "GET" else b"")
    )
    identifier = prepare(p, env.ids[0])
    p.configure_storage(identifier, *urls(), (utcnow() + timedelta(hours=2)).isoformat())
    assert not calls and p.storage_states()[identifier]
    with pytest.raises(MetaError):
        p.send(identifier)
    assert not calls and not p.graph.calls
    assert p.send(identifier, consent=True)["state"] == "processing"
    assert calls == ["PUT", "GET"] and len(p.graph.calls) == 1
    with pytest.raises(MetaError):
        p.configure_storage(identifier, *urls(), (utcnow() + timedelta(hours=2)).isoformat())
    other, _ = publisher(env, owner=env.b)
    other.delivery = MetaDelivery(env.b)
    with pytest.raises(MetaError):
        other.configure_storage(identifier, *urls(), (utcnow() + timedelta(hours=2)).isoformat())


def test_new_post_routes_require_csrf_and_do_not_echo_token(app, client, env):
    p, _ = publisher(env)
    app.state.meta_connections = env.a
    app.state.meta_publishing = p
    client.get("/api/meta/status")
    response = client.post(
        "/api/meta/import-token", data={"token": "synthetic-private-token", "consent": "true"}
    )
    assert response.status_code == 403 and "synthetic-private" not in response.text
    csrf = client.cookies.get("newsflow_csrf")
    response = client.post(
        "/api/meta/import-token", data={"token": "synthetic-private-token", "csrf_token": csrf}
    )
    assert response.status_code == 422 and "synthetic-private" not in response.text


def test_signed_urls_fit_real_vault_contract_and_expiry_blocks_before_send(env):
    from newsflow.oauth.production_dpapi import _ProductionDPAPIFileKernel

    links, path, digest, _raw = stored(env, lambda *args: pytest.fail("Unexpected network"))
    cfg = links.config(digest)
    bundle = env.a.vault.get(links.keys(digest)[1], cfg["identity"], cfg["reference"])
    _ProductionDPAPIFileKernel._bundle(bundle, check_expiry=True)
    with pytest.raises(MetaError):
        storage_url("https://storage.example.com/" + "a" * 4096)
    with env.sessions.begin() as db:
        cfg["expires"] = (utcnow() - timedelta(seconds=1)).isoformat()
        db.get(AppSetting, links.keys(digest)[0]).value = json.dumps(cfg)
    assert not links.ready(digest)
    with pytest.raises(MetaError):
        links.upload(path, digest, "image")


def test_interrupted_storage_is_not_replayed_after_new_instance(env):
    links, path, digest, _raw = stored(env, lambda *args: pytest.fail("Unexpected network"))
    with env.sessions.begin() as db:
        row = db.get(AppSetting, links.keys(digest)[0])
        cfg = json.loads(row.value)
        cfg["state"] = "sending"
        row.value = json.dumps(cfg)
    restarted = StorageLinks(env.a, lambda *args: pytest.fail("Unexpected network"))
    assert not restarted.ready(digest)
    with pytest.raises(MetaError):
        restarted.upload(path, digest, "image")
    with pytest.raises(MetaError):
        restarted.configure(digest, *urls(), (utcnow() + timedelta(hours=2)).isoformat())


def test_storage_configuration_cannot_replace_inflight_download(env):
    calls = []
    links, path, digest, _raw = stored(env, lambda *args: b"")

    def transport(method, *args):
        calls.append(method)
        with pytest.raises(MetaError):
            links.configure(digest, *urls(), (utcnow() + timedelta(hours=2)).isoformat())
        return jpeg() if method == "GET" else b""

    links.transport = transport
    links.upload(path, digest, "image")
    links.upload(path, digest, "image")
    assert calls == ["PUT", "GET", "GET"]


def test_new_bat_routes_remain_exact_external_or_local():
    from bat_distribution.meta_access import EXTERNAL, LOCAL

    assert EXTERNAL.fullmatch("/api/meta/import-token")
    assert not LOCAL.fullmatch("/api/meta/import-token")
    assert LOCAL.fullmatch("/api/meta/publications/" + "a" * 32 + "/storage")
    assert not LOCAL.fullmatch("/api/meta/publications/../storage")
    assert not EXTERNAL.fullmatch("/api/meta/import-token/anything")
