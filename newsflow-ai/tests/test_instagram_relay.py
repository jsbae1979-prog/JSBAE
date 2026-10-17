"""Synthetic HTTPS relay clients/transports; no Meta request or user data."""

import hashlib
import threading
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from newsflow.oauth.instagram import FACEBOOK_SCOPES
from newsflow.oauth.relay_server import (
    MetaRelayTransport,
    RelayConfig,
    RelayError,
    create_relay_app,
)

ORIGIN = "https://auth.newsflow.example"
VERIFIER = "v" * 64
TOKEN = "nf-synthetic-access-relay"
CODE = "nf-synthetic-code-relay"
SECRET = "nf-synthetic-server-secret"


class FakeMeta:
    def __init__(self, clock):
        self.calls = []
        self.clock = clock
        self.fail = False
        self.debug = {"app_id": "100001", "user_id": "200001", "is_valid": True, "type": "USER",
                      "scopes": list(FACEBOOK_SCOPES), "expires_at": int(clock()) + 3600,
                      "data_access_expires_at": int(clock()) + 7200}
        self.permission_rows = [{"permission": scope, "status": "granted"} for scope in FACEBOOK_SCOPES]
        self.page_rows = [{"id": "300001", "name": "Synthetic Page", "tasks": ["PROFILE_PLUS_CREATE_CONTENT"],
                           "instagram_business_account": {"id": "400001"}}]
        self.entered = None
        self.resume = None

    def exchange(self, code):
        assert isinstance(code, SecretStr)
        self.calls.append("exchange")
        if self.entered:
            self.entered.set()
            self.resume.wait(5)
        if self.fail:
            raise TimeoutError(TOKEN + SECRET)
        return {"access_token": TOKEN, "token_type": "bearer", "expires_in": 3600}

    def inspect(self, token):
        assert token.get_secret_value() == TOKEN
        self.calls.append("inspect")
        return {"data": self.debug}

    def permissions(self, token):
        self.calls.append("permissions")
        return {"data": self.permission_rows}

    def pages(self, token):
        self.calls.append("pages")
        return {"data": self.page_rows}


@pytest.fixture
def relay():
    now = [2100000000.0]
    clock = lambda: now[0]
    config = RelayConfig(ORIGIN, "100001", "500001", SecretStr(SECRET))
    transport = FakeMeta(clock)
    app = create_relay_app(config, transport=transport, clock=clock)
    with TestClient(app, base_url=ORIGIN) as client:
        yield SimpleNamespace(client=client, app=app, transport=transport, now=now, config=config)


def start(relay, verifier=VERIFIER):
    response = relay.client.post("/v1/sessions", json={"challenge": hashlib.sha256(verifier.encode()).hexdigest()})
    assert response.status_code == 200
    result = response.json()
    result["state"] = parse_qs(urlsplit(result["authorize_url"]).query)["state"][0]
    return result


def owned(relay, session, action="", *, verifier=VERIFIER, method="get", **kwargs):
    return getattr(relay.client, method)(f"/v1/sessions/{session['session_id']}{action}",
                                        headers={"Authorization": "Bearer " + verifier}, **kwargs)


def callback(relay, session, code=CODE, **kwargs):
    return relay.client.get("/oauth/callback", params={"state": session["state"], "code": code, **kwargs})


def test_complete_official_code_flow_account_choice_and_one_use_redemption(relay):
    assert relay.transport.calls == []
    session = start(relay)
    url = urlsplit(session["authorize_url"])
    query = parse_qs(url.query)
    assert (url.scheme, url.netloc, url.path) == ("https", "www.facebook.com", "/v25.0/dialog/oauth")
    assert query["client_id"] == ["100001"] and query["config_id"] == ["500001"]
    assert query["response_type"] == ["code"] and query["redirect_uri"] == [ORIGIN + "/oauth/callback"]
    assert "scope" not in query and SECRET not in session["authorize_url"]
    assert owned(relay, session).json() == {"status": "pending"}
    response = callback(relay, session)
    assert response.status_code == 200
    assert not any(value in response.text for value in (TOKEN, SECRET, CODE, session["state"]))
    state = owned(relay, session).json()
    assert state == {"status": "ready", "pages": [{"id": "300001", "name": "Synthetic Page", "instagram_id": "400001"}]}
    result = owned(relay, session, "/redeem", method="post", json={"page_id": "300001"})
    assert result.status_code == 200 and result.json()["access_token"] == TOKEN
    assert result.json()["app_id"] == "100001" and result.json()["page_id"] == "300001"
    assert result.json()["scopes"] == list(FACEBOOK_SCOPES)
    assert datetime.fromisoformat(result.json()["expires_at"]).tzinfo is not None
    assert result.headers["cache-control"] == "no-store"
    assert owned(relay, session, "/redeem", method="post", json={"page_id": "300001"}).status_code == 409
    assert owned(relay, session).json() == {"status": "consumed"}
    assert relay.transport.calls == ["exchange", "inspect", "permissions", "pages"]
    assert TOKEN not in repr(relay.app.state.relay_sessions.sessions)


def test_verifier_and_selected_page_bound_to_session(relay):
    session = start(relay)
    assert owned(relay, session, verifier="x" * 64).status_code == 403
    assert relay.client.get(f"/v1/sessions/{session['session_id']}").status_code == 403
    callback(relay, session)
    assert owned(relay, session, "/redeem", method="post", json={"page_id": "999999"}).status_code == 403
    assert owned(relay, session).json()["status"] == "ready"
    assert owned(relay, session, "/redeem", method="post", json={"page_id": "300001"}).status_code == 200


def test_callback_state_and_code_are_single_use(relay):
    session = start(relay)
    assert callback(relay, {**session, "state": "z" * 43}).status_code == 400
    assert relay.transport.calls == []
    assert callback(relay, session).status_code == 200
    assert callback(relay, session).status_code == 400
    other = start(relay, "q" * 64)
    assert callback(relay, other).status_code == 400
    assert relay.transport.calls.count("exchange") == 1


def test_callback_rejects_duplicate_parameters_and_echoes_no_input(relay):
    session = start(relay)
    response = relay.client.get("/oauth/callback", params=[("state", session["state"]), ("code", CODE), ("code", SECRET)])
    assert response.status_code == 400 and SECRET not in response.text
    assert relay.transport.calls == []


def test_unknown_exchange_does_not_replay_on_callback_or_poll(relay):
    relay.transport.fail = True
    session = start(relay)
    assert callback(relay, session).status_code == 200
    for _ in range(3):
        assert owned(relay, session).json() == {"status": "unknown", "code": "outcome_unknown"}
    assert callback(relay, session).status_code == 400
    assert relay.transport.calls == ["exchange"]


@pytest.mark.parametrize("field,value,code", [
    ("app_id", "999999", "identity_mismatch"), ("type", "SYSTEM_USER", "identity_mismatch"),
    ("is_valid", False, "identity_mismatch"), ("user_id", "invalid", "identity_mismatch"),
    ("expires_at", 1, "expired"), ("data_access_expires_at", 1, "expired"),
    ("scopes", ["instagram_basic"], "permission_denied"),
])
def test_introspection_validates_app_user_scopes_and_expiry(relay, field, value, code):
    relay.transport.debug[field] = value
    session = start(relay)
    callback(relay, session)
    assert owned(relay, session).json() == {"status": "error", "code": code}
    assert relay.transport.calls == ["exchange", "inspect"]


def test_declined_permissions_block_before_page_discovery(relay):
    relay.transport.permission_rows[0]["status"] = "declined"
    session = start(relay)
    callback(relay, session)
    assert owned(relay, session).json()["code"] == "permission_denied"
    assert relay.transport.calls == ["exchange", "inspect", "permissions"]


@pytest.mark.parametrize("change", ["no_link", "no_task", "no_pages"])
def test_only_publishable_page_linked_professional_accounts_returned(relay, change):
    if change == "no_link":
        relay.transport.page_rows[0].pop("instagram_business_account")
    elif change == "no_task":
        relay.transport.page_rows[0]["tasks"] = ["PROFILE_PLUS_ANALYZE"]
    else:
        relay.transport.page_rows = []
    session = start(relay)
    callback(relay, session)
    assert owned(relay, session).json()["code"] == "professional_required"


def test_cancel_pending_and_denied_callback_do_not_exchange(relay):
    session = start(relay)
    assert owned(relay, session, method="delete").json() == {"status": "cancelled"}
    assert callback(relay, session).status_code == 400
    other = start(relay, "q" * 64)
    response = relay.client.get("/oauth/callback", params={"state": other["state"], "error": "access_denied",
                                                          "error_description": SECRET})
    assert response.status_code == 200 and SECRET not in response.text
    assert owned(relay, other, verifier="q" * 64).json()["status"] == "cancelled"
    assert relay.transport.calls == []


def test_cancel_during_exchange_discards_result_without_retry(relay):
    session = start(relay)
    relay.transport.entered, relay.transport.resume = threading.Event(), threading.Event()
    store = relay.app.state.relay_sessions
    worker = threading.Thread(target=store.callback, args=(session["state"], SecretStr(CODE), False))
    worker.start()
    assert relay.transport.entered.wait(2)
    assert store.cancel(session["session_id"], VERIFIER)["status"] == "cancelled"
    relay.transport.resume.set()
    worker.join(5)
    assert not worker.is_alive()
    assert store.poll(session["session_id"], VERIFIER)["status"] == "cancelled"
    assert store.sessions[session["session_id"]].grant is None
    assert relay.transport.calls == ["exchange"]


def test_token_expiry_before_redeem_does_not_deliver_stale_token(relay):
    relay.transport.debug["expires_at"] = int(relay.now[0]) + 90
    session = start(relay)
    callback(relay, session)
    relay.now[0] += 61
    response = owned(relay, session, "/redeem", method="post", json={"page_id": "300001"})
    assert response.status_code == 410 and response.json()["code"] == "expired"
    assert TOKEN not in response.text


def test_parallel_redeem_allows_one_delivery(relay):
    session = start(relay)
    callback(relay, session)
    store, results, errors = relay.app.state.relay_sessions, [], []

    def redeem():
        try:
            results.append(store.redeem(session["session_id"], VERIFIER, "300001"))
        except RelayError as error:
            errors.append(error.code)

    workers = [threading.Thread(target=redeem) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(2)
    assert len(results) == 1 and errors == ["consumed"]


def test_expiry_restart_and_duplicate_create_invalidate_sessions(relay):
    session = start(relay)
    response = relay.client.post("/v1/sessions", json={"challenge": hashlib.sha256(VERIFIER.encode()).hexdigest()})
    assert response.status_code == 409
    relay.now[0] += 601
    assert owned(relay, session).status_code == 410
    assert callback(relay, session).status_code == 400
    new_app = create_relay_app(relay.config, transport=relay.transport, clock=lambda: relay.now[0])
    with TestClient(new_app, base_url=ORIGIN) as client:
        assert client.get(f"/v1/sessions/{session['session_id']}",
                          headers={"Authorization": "Bearer " + VERIFIER}).status_code == 410
    assert relay.transport.calls == []


def test_https_exact_host_no_browser_origin_and_no_media_endpoint(relay):
    challenge = hashlib.sha256(VERIFIER.encode()).hexdigest()
    assert relay.client.post("http://auth.newsflow.example/v1/sessions", json={"challenge": challenge}).status_code == 403
    assert relay.client.post("/v1/sessions", headers={"Host": "attacker.example"},
                             json={"challenge": challenge}).status_code == 403
    assert relay.client.post("/v1/sessions", headers={"Origin": "https://attacker.example"},
                             json={"challenge": challenge}).status_code == 403
    assert relay.client.post("/upload", content=b"fake-mp4").status_code == 404
    assert relay.client.get("/docs").status_code == 404
    assert relay.transport.calls == []


def test_create_size_and_rate_limits(relay):
    assert relay.client.post("/v1/sessions", content=b"x" * 2049,
                             headers={"Content-Type": "application/json"}).status_code == 413
    for number in range(10):
        assert relay.client.post("/v1/sessions", json={"challenge": hashlib.sha256(str(number).encode()).hexdigest()}).status_code == 200
    assert relay.client.post("/v1/sessions", json={"challenge": "f" * 64}).status_code == 429


@pytest.mark.parametrize("origin", ["http://auth.example", "https://127.0.0.1", "https://localhost",
                                    "https://auth.example/path", "https://user:pass@auth.example",
                                    "https://auth.example?secret=value"])
def test_server_configuration_requires_public_https_origin(origin):
    with pytest.raises(RelayError) as error:
        RelayConfig(origin, "100001", "500001", SecretStr(SECRET))
    assert error.value.code == "configuration_invalid" and SECRET not in str(error.value)


def test_transport_uses_official_hosts_form_exchange_and_headers(monkeypatch):
    requests = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, count):
            assert count == 262145
            return b'{"data":{}}'

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            assert timeout == 25
            return Response()

    monkeypatch.setattr("newsflow.oauth.relay_server.build_opener", lambda *args: Opener())
    config = RelayConfig(ORIGIN, "100001", "500001", SecretStr(SECRET))
    transport = MetaRelayTransport(config)
    transport.exchange(SecretStr(CODE))
    transport.inspect(SecretStr(TOKEN))
    transport.permissions(SecretStr(TOKEN))
    transport.pages(SecretStr(TOKEN))
    assert requests[0].full_url == "https://graph.facebook.com/v25.0/oauth/access_token"
    assert parse_qs(requests[0].data.decode())["client_secret"] == [SECRET]
    assert SECRET not in requests[0].full_url and CODE not in requests[0].full_url
    assert requests[1].get_header("Authorization") == "Bearer 100001|" + SECRET
    assert parse_qs(urlsplit(requests[1].full_url).query)["input_token"] == [TOKEN]
    assert all(urlsplit(request.full_url).netloc == "graph.facebook.com" for request in requests)
    assert all(SECRET not in request.full_url for request in requests)
    assert all(TOKEN not in request.full_url for request in requests[2:])


def test_transport_failure_is_sanitized_and_not_retried(monkeypatch):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(True)
            raise OSError(TOKEN + SECRET)

    monkeypatch.setattr("newsflow.oauth.relay_server.build_opener", lambda *args: Opener())
    transport = MetaRelayTransport(RelayConfig(ORIGIN, "100001", "500001", SecretStr(SECRET)))
    with pytest.raises(RelayError) as error:
        transport.inspect(SecretStr(TOKEN))
    assert error.value.code == "outcome_unknown" and TOKEN not in str(error.value)
    assert len(calls) == 1


def test_server_secret_environment_only_and_startup_has_no_requests(monkeypatch):
    monkeypatch.setenv("NEWSFLOW_META_RELAY_ORIGIN", ORIGIN)
    monkeypatch.setenv("NEWSFLOW_META_APP_ID", "100001")
    monkeypatch.setenv("NEWSFLOW_META_CONFIG_ID", "500001")
    monkeypatch.setenv("NEWSFLOW_META_APP_SECRET", SECRET)
    monkeypatch.setattr("newsflow.oauth.relay_server.build_opener", lambda *args: pytest.fail("startup network"))
    app = create_relay_app()
    assert SECRET not in repr(app.state.relay_sessions.config)
    assert app.state.relay_sessions.sessions == {}
