"""TikTok Desktop OAuth with synthetic credentials and real loopback HTTP only."""
import hashlib
import http.client
import json
import socket
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from newsflow.db.models import Base, OAuthConnection, OAuthLifecycleOperation, PlatformAccount
from newsflow.db.session import make_engine, session_factory
from newsflow.intelligence.credentials import FakeCipher
from newsflow.oauth.production_dpapi import FakeProductionCipherProtector
from newsflow.oauth.tiktok import TikTokConnectionService
from newsflow.oauth.tiktok_callback import TikTokCallback
from newsflow.oauth.tiktok_credentials import TikTokClientStore, TikTokVault
from newsflow.oauth.tiktok_protocol import (
    SCOPES,
    DesktopConfig,
    TikTokBrowser,
    TikTokError,
    TikTokHTTP,
    challenge,
    token_result,
)

RAW = json.dumps({"client_key": "nf-synthetic-client", "client_secret": "nf-synthetic-secret-private", "port": 0})
CONFIG = DesktopConfig("nf-synthetic-client", SecretStr("nf-synthetic-secret-private"))


def grant(**changes):
    return {"access_token": "nf-synthetic-access-private", "refresh_token": "nf-synthetic-refresh-private",
            "expires_in": 86400, "refresh_expires_in": 31536000, "token_type": "Bearer",
            "open_id": "nf-synthetic-user-1", "scope": ",".join(SCOPES), **changes}


class Wire:
    def __init__(self):
        self.calls, self.version, self.fail, self.change, self.identity = [], 0, None, {}, None
        self.status, self.raw = 200, None

    def factory(self, host, *, timeout, context):
        assert host == "open.tiktokapis.com" and timeout == 20
        assert context.check_hostname
        parent = self

        class Connection:
            def request(self, method, path, body=None, headers=None):
                self.path = path
                parent.calls.append((method, path, parse_qs((body or b"").decode()), headers))
                if parent.fail and parent.fail in path:
                    raise TimeoutError("nf-synthetic-do-not-log")

            def getresponse(self):
                if "token/" in self.path:
                    parent.version += 1
                    value = grant(access_token=f"nf-synthetic-access-{parent.version}",
                                  refresh_token=f"nf-synthetic-refresh-{parent.version}", **parent.change)
                elif "user/info" in self.path:
                    value = {"data": {"user": {"open_id": parent.identity or "nf-synthetic-user-1", "display_name": "테스트 계정"}},
                             "error": {"code": "ok"}}
                else:
                    value = {}
                raw = parent.raw if parent.raw is not None else json.dumps(value).encode()
                return SimpleNamespace(status=parent.status, read=lambda count: raw[:count])

            def close(self):
                pass
        return Connection()


def callback_request(url, *, changes=None, headers=None, path=None):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    redirect = urlsplit(query["redirect_uri"][0])
    values = {"state": query["state"][0], "code": "nf-synthetic-code", "scopes": ",".join(SCOPES), **(changes or {})}
    connection = http.client.HTTPConnection(redirect.hostname, redirect.port, timeout=3)
    try:
        connection.request("GET", path or redirect.path + "?" + urlencode(values), headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read().decode()
    finally:
        connection.close()


class Browser:
    def __init__(self, auto=True):
        self.url, self.auto = None, auto

    def open(self, url):
        self.url = url.get_secret_value()
        if self.auto:
            assert callback_request(self.url)[0] == 200


def build(sessions, root, *, auto=True):
    client = TikTokClientStore(root, FakeCipher())
    wire, browser = Wire(), Browser(auto)
    vault = TikTokVault(root / "vault", synthetic=True, protector=FakeProductionCipherProtector())
    service = TikTokConnectionService(sessions, root, client_store=client,
                                     http=TikTokHTTP(synthetic_connection=wire.factory), browser=browser, vault=vault)
    service.save_client(RAW)
    return SimpleNamespace(service=service, wire=wire, browser=browser, root=root, sessions=sessions, vault=vault)


@pytest.fixture
def env(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real service connection forbidden")
    monkeypatch.setattr(http.client.HTTPSConnection, "request", forbidden)
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    env = build(session_factory(engine), tmp_path)
    yield env
    env.service.close()
    engine.dispose()


def connect(env, account_id=None):
    account = env.service.begin(consent=True, account_id=account_id)
    env.service._workers[account].join(5)
    assert not env.service._workers[account].is_alive()
    return account


def record(env, account):
    with env.sessions() as session:
        return session.get(OAuthConnection, account), session.get(PlatformAccount, account)


def test_connection_protocol_rotation_revoke_and_no_plaintext(env):
    account = connect(env)
    c, a = record(env, account)
    assert c.status == "connected" and a.api_ready and a.label == "합성 · 테스트 계정"
    first_ref = a.credential_ref
    query = parse_qs(urlsplit(env.browser.url).query)
    sent = env.wire.calls[0][2]
    assert query["code_challenge"] == [hashlib.sha256(sent["code_verifier"][0].encode()).hexdigest()]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == sent["redirect_uri"]
    assert sent["grant_type"] == ["authorization_code"]
    assert env.service.synthetic_binding(account)["identity"] == "nf-synthetic-user-1"
    env.service.refresh(account, consent=True)
    c, a = record(env, account)
    assert a.credential_ref != first_ref and c.status == "connected"
    assert env.wire.calls[2][2]["refresh_token"] == ["nf-synthetic-refresh-1"]
    env.service.revoke(account, consent=True)
    assert env.wire.calls[-1][2]["token"] == ["nf-synthetic-access-2"]
    c, a = record(env, account)
    assert c.status == "revoked" and not a.api_ready and a.credential_ref is None
    with pytest.raises(TikTokError):
        env.service.synthetic_binding(account)
    for file in env.root.rglob("*"):
        if file.is_file():
            raw = file.read_bytes()
            for secret in (b"nf-synthetic-access-1", b"nf-synthetic-refresh-1", b"nf-synthetic-secret-private"):
                assert secret not in raw


@pytest.mark.parametrize("change", [
    {"scope": "video.publish"}, {"scope": "user.info.basic,video.publish,video.publish"},
    {"scope": "user.info.basic,video.publish,other"}, {"expires_in": True}, {"expires_in": 86401},
    {"refresh_expires_in": 0}, {"token_type": "bearer"}, {"access_token": "bad\nsecret"}, {"unknown": "value"},
])
def test_malformed_grants_are_fail_closed(change):
    with pytest.raises(TikTokError):
        token_result(grant(**change))


def test_identity_mismatch_and_rebinding_rejected(env):
    env.wire.identity = "other"
    account = connect(env)
    c, a = record(env, account)
    assert c.error_code == "identity" and not a.api_ready and a.credential_ref is None
    env.wire.identity = None
    connect(env, account)
    before = record(env, account)[1].credential_ref
    env.wire.change = {"open_id": "another-account"}
    with pytest.raises(TikTokError, match="계정"):
        env.service.refresh(account, consent=True)
    assert record(env, account)[1].credential_ref == before
    assert not record(env, account)[1].api_ready


def test_duplicate_account_identity_cannot_bind_twice(env):
    first, second = connect(env), connect(env)
    assert record(env, first)[0].status == "connected"
    assert record(env, second)[0].error_code == "identity"
    assert record(env, second)[1].credential_ref is None


@pytest.mark.parametrize("operation,path", [("refresh", "token/"), ("revoke", "revoke/")])
def test_unknown_operation_retains_old_pointer_and_cannot_replay(env, operation, path):
    account = connect(env)
    before = record(env, account)[1].credential_ref
    env.wire.fail = path
    with pytest.raises(TikTokError):
        getattr(env.service, operation)(account, consent=True)
    c, a = record(env, account)
    assert c.status == "unknown" and not a.api_ready and a.credential_ref == before
    count = len(env.wire.calls)
    with pytest.raises(TikTokError):
        getattr(env.service, operation)(account, consent=True)
    assert len(env.wire.calls) == count


def test_write_failure_preserves_previous_credential_and_journal(env, monkeypatch):
    account = connect(env)
    before = record(env, account)[1].credential_ref
    def fail(*args, **kwargs):
        raise OSError("private-secret-detail")
    monkeypatch.setattr(env.vault, "write_reserved", fail)
    with pytest.raises(TikTokError):
        env.service.refresh(account, consent=True)
    c, a = record(env, account)
    assert a.credential_ref == before and not a.api_ready and c.status == "unknown"
    with env.sessions() as session:
        ops = list(session.scalars(select(OAuthLifecycleOperation)))
        assert any(o.old_reference == before and o.new_reference and o.status == "tt_unknown" for o in ops)
        assert all("private-secret-detail" not in str(o.__dict__) for o in ops)


def test_restart_and_cancel_never_exchange(env):
    env.browser.auto = False
    account = env.service.begin(consent=True)
    with pytest.raises(TikTokError, match="진행"):
        env.service.begin(consent=True)
    with pytest.raises(TikTokError):
        env.service.save_client(RAW)
    env.service.recover()
    callback_request(env.browser.url)
    env.service._workers[account].join(5)
    assert record(env, account)[0].status == "unknown" and env.wire.calls == []
    account2 = env.service.begin(consent=True)
    env.service.cancel(account2)
    env.service._workers[account2].join(5)
    assert record(env, account2)[0].status == "cancelled" and env.wire.calls == []


def test_revision_compare_swap_and_settings_invalidation(env):
    account = connect(env)
    config, _, _, _, snapshot = env.service._stored(account)
    env.service.refresh(account, consent=True)
    count = len(env.wire.calls)
    with pytest.raises(TikTokError):
        env.service._claim(account, "refresh", config=config, snapshot=snapshot)
    assert len(env.wire.calls) == count
    env.service.save_client(RAW)
    assert record(env, account)[0].status == "reconnect"
    with pytest.raises(TikTokError):
        env.service.synthetic_binding(account)


def test_missing_consent_and_production_gate_ignore_environment(env, monkeypatch):
    with pytest.raises(TikTokError, match="동의"):
        env.service.begin()
    assert env.wire.calls == [] and env.browser.url is None
    monkeypatch.setenv("NEWSFLOW_TIKTOK_ENABLED", "1")
    service = TikTokConnectionService(env.sessions, env.root)
    for call in (lambda: service.begin(consent=True), lambda: service.refresh(1, consent=True),
                 lambda: service.revoke(1, consent=True), lambda: TikTokHTTP().request("identity", {}),
                 lambda: TikTokBrowser().open(SecretStr("https://www.tiktok.com/v2/auth/authorize/?test")),
                 lambda: TikTokCallback().start(CONFIG), lambda: TikTokVault(env.root)._backend()):
        with pytest.raises(TikTokError, match="차단"):
            call()


@pytest.mark.parametrize("headers", [{"Host": "evil.example"}, {"Origin": "null"}, {"Origin": "https://www.tiktok.com"}])
def test_callback_host_origin_and_forged_state_do_not_consume(headers):
    listener = TikTokCallback(synthetic=True)
    url = listener.start(CONFIG).get_secret_value()
    try:
        assert callback_request(url, headers=headers)[0] == 400
        assert callback_request(url, changes={"state": "x" * 43})[0] == 400
        status, body = callback_request(url)
        assert status == 200 and "nf-synthetic-code" not in body
        assert listener.state.get_secret_value() not in body
        assert callback_request(url)[0] == 409
        assert listener.wait().get_secret_value() == "nf-synthetic-code"
        with pytest.raises(TikTokError):
            listener.wait()
    finally:
        listener.close()


@pytest.mark.parametrize("kind", ["expired", "cancelled", "denied", "wrong_scope", "duplicate", "bad_path"])
def test_callback_errors(kind):
    listener = TikTokCallback(synthetic=True)
    url = listener.start(CONFIG).get_secret_value()
    try:
        if kind == "expired":
            listener.deadline = 0
            assert callback_request(url)[0] == 410
        elif kind == "cancelled":
            listener.cancel()
        elif kind == "denied":
            p = parse_qs(urlsplit(url).query)
            path = "/oauth/tiktok/callback/?" + urlencode({"state": p["state"][0], "error": "access_denied"})
            assert callback_request(url, path=path)[0] == 400
        elif kind == "wrong_scope":
            assert callback_request(url, changes={"scopes": "video.publish"})[0] == 400
        elif kind == "duplicate":
            state = parse_qs(urlsplit(url).query)["state"][0]
            assert callback_request(url, path=f"/oauth/tiktok/callback/?state={state}&code=a&code=b")[0] == 400
        else:
            assert callback_request(url, path="//evil/callback?code=secret")[0] == 400
            listener.cancel()
        with pytest.raises(TikTokError):
            listener.wait()
    finally:
        listener.close()


def test_callback_port_conflict_and_hex_pkce():
    assert challenge("A" * 43) == hashlib.sha256(b"A" * 43).hexdigest()
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        config = DesktopConfig(CONFIG.client_key, CONFIG.client_secret, occupied.getsockname()[1])
        with pytest.raises(TikTokError, match="포트"):
            TikTokCallback(synthetic=True).start(config)
    with pytest.raises(TikTokError):
        DesktopConfig(CONFIG.client_key, CONFIG.client_secret, 8765)


@pytest.mark.parametrize("status,raw", [(408, b"{}"), (429, b"{}"), (500, b"{}"), (302, b"{}"),
                                       (200, b"x" * 65537), (200, b"not-json")])
def test_transport_unknown_responses_are_not_retried(status, raw):
    wire = Wire()
    wire.status, wire.raw = status, raw
    with pytest.raises(TikTokError):
        TikTokHTTP(synthetic_connection=wire.factory).request("identity", {"access_token": "nf-synthetic-access"})
    assert len(wire.calls) == 1


def test_vault_account_isolation_and_tamper(env):
    bundle = token_result(grant())[0]
    ref, identity = uuid4().hex, "a" * 64
    env.vault.write_reserved("tiktok:1", identity, ref, bundle, operation_id=uuid4().hex)
    assert env.vault.load("tiktok:1", identity, ref) == bundle
    for key, digest in (("tiktok:2", identity), ("youtube:1", identity), ("tiktok:1", "b" * 64)):
        with pytest.raises(TikTokError):
            env.vault.load(key, digest, ref)
    files = list((env.root / "vault").rglob("*.pcred"))
    assert files
    file = files[0]
    file.write_bytes(file.read_bytes()[:-1] + b"x")
    with pytest.raises(TikTokError):
        env.vault.load("tiktok:1", identity, ref)


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows current-user DPAPI required")
def test_windows_native_tiktok_vault_synthetic_only(tmp_path):
    vault = TikTokVault(tmp_path / "한국어 폴더", synthetic=True)
    bundle, ref, identity = token_result(grant())[0], uuid4().hex, "a" * 64
    vault.write_reserved("tiktok:1", identity, ref, bundle, operation_id=uuid4().hex)
    assert vault.load("tiktok:1", identity, ref) == bundle
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"nf-synthetic-access-private" not in path.read_bytes()


def test_expired_access_is_not_ready_but_explicit_refresh_remains_possible(env):
    from datetime import timedelta

    from newsflow.db.models import utcnow

    account = connect(env)
    with env.sessions.begin() as session:
        session.get(OAuthConnection, account).expires_at = utcnow() - timedelta(seconds=1)
    status = env.service.status()["accounts"][0]
    assert status["status"] == "expired" and not status["ready"]
    env.service.refresh(account, consent=True)
    assert env.service.status()["accounts"][0]["ready"]


def test_two_service_instances_cannot_start_duplicate_auth(env):
    from concurrent.futures import ThreadPoolExecutor

    env.browser.auto = False
    other = TikTokConnectionService(env.sessions, env.root, client_store=env.service.client,
        http=TikTokHTTP(synthetic_connection=env.wire.factory), browser=Browser(False), vault=env.vault)
    def begin(service):
        try:
            return service.begin(consent=True)
        except TikTokError as error:
            return error.code
    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(begin, [env.service, other]))
        assert sum(type(r) is int for r in results) == 1
        assert results.count("pending") == 1
        assert env.wire.calls == []
    finally:
        other.close()


def test_wrong_platform_and_real_secrets_cannot_use_synthetic_boundary(env):
    with env.sessions.begin() as session:
        account = PlatformAccount(platform="youtube", account_type="youtube_channel", label="합성")
        session.add(account)
        session.flush()
        identifier = account.id
    with pytest.raises(TikTokError):
        env.service.begin(consent=True, account_id=identifier)
    with pytest.raises(TikTokError):
        env.service.http.request("identity", {"access_token": "not-a-synthetic-token"})
    assert env.wire.calls == []
    with pytest.raises(TikTokError):
        env.vault.write_reserved("tiktok:1", "a" * 64, uuid4().hex,
                                 token_result(grant(access_token="not-a-synthetic-token"))[0], operation_id=uuid4().hex)
