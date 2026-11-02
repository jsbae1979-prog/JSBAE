"""No live Meta/storage requests. Synthetic media, identities and encrypted-vault double."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

import pytest
import test_meta_accounts
from sqlalchemy import select
from test_meta_accounts import jpeg, prepare

from newsflow.db.models import AppSetting, utcnow
from newsflow.meta.automatic_storage import AutomaticStorage, presign
from newsflow.meta.contracts import MetaError
from newsflow.meta.graph import MetaGraph
from newsflow.meta.media import MetaDelivery
from newsflow.meta.publishing import MetaPublishing

pytestmark = pytest.mark.usefixtures("synthetic_app_isolation")


@pytest.fixture
def env(tmp_path):
    yield from test_meta_accounts.env.__wrapped__(tmp_path)


def make(env, kind="image", platform="instagram", owner=None):
    raw = jpeg() if kind == "image" else b"\x00\x00\x00\x20ftypisom" + b"synthetic-video" * 5
    path = env.root / ("media.jpg" if kind == "image" else "media.mp4")
    path.write_bytes(raw)
    media = {"path": path, "sha256": sha256(raw).hexdigest(), "kind": kind}
    calls = []

    def http(method, url, headers, body):
        calls.append((method, url, headers, body))
        if "rupload.facebook.com" in url:
            return 200, b'{"success":true}'
        if method == "GET":
            return (
                200,
                b'{"id":"901","status_code":"FINISHED","is_published":true,"published":true,"status":{"video_status":"ready"}}',
            )
        return 200, b'{"id":"901"}'

    accounts = owner or env.a
    delivery = MetaDelivery(accounts)
    publisher = MetaPublishing(accounts, MetaGraph(transport=http), lambda _: media, delivery)
    identifier = prepare(publisher, env.b_id if owner else env.ids[0], platform)
    return publisher, identifier, media, calls, raw


def configure(automatic):
    automatic.configure(
        "https://s3.example.com",
        "us-east-1",
        "synthetic-bucket",
        "SYNTHETICACCESS",
        "synthetic-secret-key-only",
    )


@pytest.mark.parametrize(
    "kind,platform", [("image", "facebook"), ("video", "facebook"), ("video", "instagram")]
)
def test_direct_needs_no_storage_and_only_sends_selected_target(env, kind, platform):
    p, key, media, calls, raw = make(env, kind, platform)
    assert p.storage_states()[key] is True and not p.delivery.ready()
    assert p.transfer_modes()[key] == "direct" and calls == []
    with pytest.raises(MetaError):
        p.send(key, consent=False)
    assert not calls
    result = p.send(key, consent=True)
    assert result["state"] == ("processing" if platform == "instagram" else "published_unverified")
    assert not p.delivery.links.config(media["sha256"])
    if platform == "facebook":
        assert len(calls) == 1 and "/101/" in calls[0][1]
        assert raw in calls[0][3] and b'name="source"' in calls[0][3]
        assert b"file_url" not in calls[0][3] and b'name="url"' not in calls[0][3]
        assert calls[0][2]["Authorization"] == "Bearer synthetic-page-101"
    else:
        assert len(calls) == 2 and "/201/media" in calls[0][1]
        payload = parse_qs(calls[0][3].decode())
        assert payload["upload_type"] == ["resumable"] and "video_url" not in payload
        assert calls[1][1] == "https://rupload.facebook.com/ig-api-upload/v26.0/901"
        assert calls[1][3] == raw and calls[1][2]["file_size"] == str(len(raw))
        assert p.check(key)["state"] == "ready"
        assert not any("media_publish" in c[1] for c in calls)
    with pytest.raises(MetaError):
        p.send(key, consent=True)
    assert media["path"].read_bytes() == raw


def test_reel_upload_timeout_keeps_container_and_get_recovers_without_repost(env):
    p, key, _media, calls, _raw = make(env, "video")
    base = p.graph.transport

    def fail(method, url, headers, body):
        if "rupload.facebook.com" in url:
            calls.append((method, url, headers, body))
            raise TimeoutError("secret must never be displayed")
        return base(method, url, headers, body)

    p.graph.transport = fail
    result = p.send(key, consent=True)
    assert result["state"] == "upload_unknown" and result["canCheck"]
    assert "secret" not in json.dumps(result)
    with pytest.raises(MetaError):
        p.send(key, consent=True)
    assert p.check(key)["state"] == "ready"
    assert len([c for c in calls if c[0] == "POST"]) == 2


def test_direct_tampered_file_and_foreign_owner_never_upload(env):
    p, key, media, calls, _raw = make(env, platform="facebook")
    media["path"].write_bytes(jpeg() + b"changed")
    assert p.send(key, consent=True)["state"] == "failed"
    assert not calls
    q, _, _, other_calls, _ = make(env, owner=env.b)
    with pytest.raises(MetaError):
        q.send(key, consent=True)
    assert not other_calls


@pytest.mark.parametrize("status", [400, 403, 429, 500])
def test_direct_error_never_falls_back_to_storage_or_retries(env, status):
    p, key, _media, calls, _raw = make(env, platform="facebook")

    def reject(*args):
        calls.append(args)
        return status, b'{"error":{"code":1,"message":"do not expose"}}'

    p.graph.transport = reject
    configure(p.delivery.automatic)
    p.delivery.links.transport = lambda *args: pytest.fail("No fallback storage upload")
    assert p.send(key, consent=True)["state"] in {"failed", "unknown"}
    with pytest.raises(MetaError):
        p.send(key, consent=True)
    assert len(calls) == 1


def test_automatic_storage_one_time_configuration_uploads_and_checks_content(env):
    p, key, media, calls, raw = make(env)
    assert p.storage_states()[key] is False
    configure(p.delivery.automatic)
    assert p.storage_states()[key] is True and not calls
    assert not p.delivery.links.config(media["sha256"])
    transfers = []

    def store(method, url, body=None, kind=None):
        transfers.append((method, url, body))
        return raw if method == "GET" else b""

    p.delivery.links.transport = store
    assert p.send(key, consent=True)["state"] == "processing"
    assert [t[0] for t in transfers] == ["PUT", "GET"]
    assert transfers[0][2] == raw
    payload = parse_qs(calls[0][3].decode())
    assert payload["image_url"] == [transfers[1][1]]
    signed = parse_qs(urlsplit(transfers[1][1]).query)
    assert signed["X-Amz-Expires"] == ["86400"]
    second = prepare(p, env.ids[1])
    assert p.send(second, consent=True)["state"] == "processing"
    assert [t[0] for t in transfers] == ["PUT", "GET", "GET"]
    assert media["path"].read_bytes() == raw
    with env.sessions() as db:
        values = " ".join(r.value for r in db.scalars(select(AppSetting)))
    assert "synthetic-secret-key-only" not in values and "SYNTHETICACCESS" not in values
    assert "X-Amz-Signature" not in values
    assert not AutomaticStorage(env.b, p.delivery.links).ready()


@pytest.mark.parametrize("failure", ["timeout", "mismatch", "interrupted"])
def test_storage_failure_does_not_call_meta_or_repeat_put(env, failure):
    p, key, _media, calls, _raw = make(env)
    configure(p.delivery.automatic)
    transfers = []

    def store(method, *args):
        transfers.append(method)
        if method == "PUT" and failure == "timeout":
            raise TimeoutError("secret")
        if method == "PUT" and failure == "interrupted":
            raise KeyboardInterrupt()
        return b"wrong" if method == "GET" else b""

    p.delivery.links.transport = store
    if failure == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            p.send(key, consent=True)
        assert p.recover() == 1
    else:
        assert p.send(key, consent=True)["state"] == "unknown"
    assert not calls
    second = prepare(p, env.ids[1])
    assert not p.storage_states()[second]
    with pytest.raises(MetaError):
        p.send(second, consent=True)
    assert transfers.count("PUT") == 1


def test_expired_manual_urls_are_not_silently_reuploaded(env):
    p, key, media, calls, _raw = make(env)
    configure(p.delivery.automatic)
    p.delivery.automatic.provision(media["sha256"], "image")
    setting, _ = p.delivery.links.keys(media["sha256"])
    with env.sessions.begin() as db:
        row = db.get(AppSetting, setting)
        cfg = json.loads(row.value)
        cfg["expires"] = (utcnow() - timedelta(seconds=1)).isoformat()
        cfg.pop("automaticIdentity", None)
        cfg.pop("objectKey", None)
        row.value = json.dumps(cfg)
    assert not p.storage_states()[key]
    with pytest.raises(MetaError):
        p.send(key, consent=True)
    assert not calls


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://s3.example.com",
        "https://user:secret@s3.example.com",
        "https://s3.example.com/path",
        "https://s3.example.com?secret=1",
        "https://s3.example.com:8443",
        "https://s3.example.com/#fragment",
    ],
)
def test_invalid_storage_configuration_never_saves(env, endpoint):
    auto = MetaDelivery(env.a).automatic
    with pytest.raises(MetaError):
        auto.configure(endpoint, "auto", "synthetic-bucket", "SYNTHETICACCESS", "synthetic-secret-only")
    assert not auto.ready()


def test_sigv4_request_bound_to_method_object_owner_and_expiry():
    now = datetime(2026, 11, 2, 0, 0, 0, tzinfo=UTC)
    args = (
        "https://s3.example.com",
        "us-east-1",
        "synthetic-bucket",
        "newsflow/owner/filename.jpg",
        "SYNTHETICACCESS",
        "synthetic-secret-only",
        now,
    )
    put = presign("PUT", *args)
    get = presign("GET", *args)
    assert put != get and "synthetic-secret-only" not in put
    query = parse_qs(urlsplit(put).query)
    assert query["X-Amz-Credential"] == ["SYNTHETICACCESS/20261102/us-east-1/s3/aws4_request"]
    assert query["X-Amz-SignedHeaders"] == ["host"]
    assert len(query["X-Amz-Signature"][0]) == 64
    assert presign("PUT", *args) == put
    assert presign("PUT", *args, seconds=900) != put
    other = list(args)
    other[3] = "newsflow/other/filename.jpg"
    assert presign("PUT", *other) != put


def test_config_route_requires_csrf_and_status_never_exposes_keys(app, client, env):
    p, _, _, calls, _ = make(env)
    app.state.meta_connections = env.a
    app.state.meta_publishing = p
    values = {
        "endpoint": "https://s3.example.com",
        "region": "auto",
        "bucket": "synthetic-bucket",
        "access_key": "SYNTHETICACCESS",
        "secret_key": "synthetic-secret-only",
    }
    assert client.post("/api/meta/automatic-storage", data=values).status_code == 403
    client.get("/api/meta/status")
    values["csrf_token"] = client.cookies.get("newsflow_csrf")
    assert client.post("/api/meta/automatic-storage", data=values).status_code == 200
    response = client.get("/api/meta/status")
    assert response.json()["automaticStorageReady"] is True
    assert "SYNTHETICACCESS" not in response.text and "synthetic-secret-only" not in response.text
    assert not calls


def test_automatic_storage_bat_route_is_local_and_exact():
    from bat_distribution.meta_access import EXTERNAL, LOCAL

    assert LOCAL.fullmatch("/api/meta/automatic-storage")
    assert not EXTERNAL.fullmatch("/api/meta/automatic-storage")
    assert not LOCAL.fullmatch("/api/meta/automatic-storage/extra")


def test_storage_credentials_match_production_encrypted_bundle_contract(env):
    from newsflow.oauth.production_dpapi import _ProductionDPAPIFileKernel

    p, _, _, _, _ = make(env)
    configure(p.delivery.automatic)
    cfg = p.delivery.automatic.config()
    bundle = env.a.vault.get(p.delivery.automatic.identifier, cfg["identity"], cfg["reference"])
    _ProductionDPAPIFileKernel._bundle(bundle, check_expiry=True)
    assert "synthetic-secret-key-only" not in repr(bundle)


def test_multitarget_same_media_does_not_reupload_after_unknown(env):
    p, key, _media, _, _raw = make(env)
    configure(p.delivery.automatic)
    count = []

    def store(method, *args):
        count.append(method)
        raise TimeoutError()

    p.delivery.links.transport = store
    assert p.send(key, consent=True)["state"] == "unknown"
    configure(p.delivery.automatic)  # Rotating account credentials must not erase operation history.
    other = prepare(p, env.ids[1])
    with pytest.raises(MetaError):
        p.send(other, consent=True)
    assert count == ["PUT"]


def test_uncertain_final_publish_must_not_be_reenabled_by_finished_container(env):
    p, key, _, calls, _ = make(env, "video")
    p.send(key, consent=True)
    assert p.check(key)["state"] == "ready"
    base = p.graph.transport

    def fail_publish(method, url, headers, body):
        if "/media_publish" in url:
            calls.append((method, url, headers, body))
            raise TimeoutError()
        return base(method, url, headers, body)

    p.graph.transport = fail_publish
    result = p.publish(key, consent=True)
    assert result["state"] == "unknown" and not result["canCheck"]
    before = len(calls)
    with pytest.raises(MetaError):
        p.check(key)
    with pytest.raises(MetaError):
        p.publish(key, consent=True)
    assert len(calls) == before


def test_interrupted_reel_upload_recovery_only_queries_never_reuploads(env):
    p, key, _, calls, _ = make(env, "video")
    p._set(key, "uploading", container_id="901")
    assert p.recover() == 1
    assert p.list_one(key)["state"] == "upload_unknown"
    assert p.check(key)["state"] == "ready"
    assert [c[0] for c in calls] == ["GET"]


def test_sigv4_matches_aws_published_reference_vector():
    from newsflow.meta.automatic_storage import sign_string

    # Public example credentials from the AWS SigV4 documentation, NOT a real account.
    text = "AWS4-HMAC-SHA256\n20130524T000000Z\n20130524/us-east-1/s3/aws4_request\n3bfa292879f6447bbcda7001decf97f4a54dc650c8942174ae0a9121cf58ad04"
    result = sign_string(text, "20130524", "us-east-1", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    assert result == "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"


def test_expired_automatic_url_renews_without_uploading_again(env):
    p, key, media, _calls, raw = make(env)
    configure(p.delivery.automatic)
    transfers = []

    def store(method, url, body=None, kind=None):
        transfers.append(method)
        return raw if method == "GET" else b""

    p.delivery.links.transport = store
    assert p.send(key, consent=True)["state"] == "processing"
    setting, _ = p.delivery.links.keys(media["sha256"])
    with env.sessions.begin() as db:
        row = db.get(AppSetting, setting)
        cfg = json.loads(row.value)
        original_key = cfg["objectKey"]
        cfg["expires"] = (utcnow() - timedelta(seconds=1)).isoformat()
        row.value = json.dumps(cfg)
    other = prepare(p, env.ids[1])
    assert p.storage_states()[other]
    assert p.send(other, consent=True)["state"] == "processing"
    assert transfers == ["PUT", "GET", "GET"]
    assert p.delivery.links.config(media["sha256"])["objectKey"] == original_key
