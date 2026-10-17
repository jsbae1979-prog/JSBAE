"""Desktop relay contract with in-memory HTTPS responses and isolated settings."""

import hashlib
import json
import time
from datetime import timedelta
from threading import Event, Thread
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from sqlalchemy import select

from newsflow.db.models import AppSetting, Base, OAuthConnection, OAuthLifecycleOperation, utcnow
from newsflow.db.session import make_engine, session_factory
from newsflow.oauth.instagram import FACEBOOK_SCOPES, InstagramConnectionError, InstagramConnectionService
from newsflow.oauth.instagram_relay import (
    InstagramRelayAuthorization,
    PublicRelayTransport,
    RelayConfig,
    RelayResponse,
)

ORIGIN, APP, PAGE, INSTAGRAM = "https://relay.example.com", "100001", "200001", "300001"
SESSION = "f" * 48
PAGES = [{"id": PAGE, "name": "Synthetic Page", "instagram_id": INSTAGRAM}]


def started(**changes):
    url = "https://www.facebook.com/v25.0/dialog/oauth?" + urlencode({
        "client_id": APP, "config_id": "400001", "response_type": "code", "override_default_response_type": "true",
        "state": "s" * 48, "redirect_uri": ORIGIN + "/oauth/callback",
    })
    return {"app_id": APP, "session_id": SESSION, "expires_in": 600, "authorize_url": url, **changes}


def grant(**changes):
    return {"app_id": APP, "page_id": PAGE, "access_token": "nf-synthetic-access-instagram-user",
            "expires_at": (utcnow() + timedelta(hours=1)).isoformat(),
            "data_access_expires_at": (utcnow() + timedelta(days=30)).isoformat(),
            "scopes": list(FACEBOOK_SCOPES), **changes}


class Transport:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def request(self, method, path, body=None, verifier=None):
        self.calls.append((method, path, body, verifier))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return RelayResponse(200, outcome)


def backend(outcomes):
    transport, browsers = Transport(outcomes), []
    auth = InstagramRelayAuthorization(RelayConfig.parse(ORIGIN, APP), transport=transport,
                                      browser_open=lambda url: browsers.append(url) or True, poll_interval=0.01)
    return auth, transport, browsers


def run_auth(auth):
    results = []

    def run():
        try:
            results.append(auth.authorize(scopes=FACEBOOK_SCOPES))
        except Exception as error:  # noqa: BLE001 - only synthetic diagnostic assertions
            results.append(error)
    thread = Thread(target=run, daemon=True)
    thread.start()
    return thread, results


def wait_until(condition):
    deadline = time.monotonic() + 3
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert condition()


@pytest.mark.parametrize("url", ["http://relay.example.com", "https://localhost", "https://127.0.0.1",
                                 "https://10.0.0.1", "https://relay.example.com/path",
                                 "https://relay.example.com?token=x", "https://user@relay.example.com",
                                 "https://relay.example.com:444", "https://relay.example.com/#fragment"])
def test_configuration_rejects_nonpublic_origins_or_secrets(url):
    with pytest.raises(InstagramConnectionError) as error:
        RelayConfig.parse(url, APP)
    assert error.value.code == "relay_config_invalid" and url not in str(error.value)


def test_authorization_browser_page_selection_and_one_time_redemption():
    auth, transport, browsers = backend([started(), {"status": "ready", "pages": PAGES}, grant()])
    assert auth.snapshot()["relay_state"] == "idle" and transport.calls == []
    thread, result = run_auth(auth)
    wait_until(lambda: auth.snapshot()["awaiting_page"])
    assert len(transport.calls) == 2 and len(browsers) == 1
    assert auth.snapshot()["pages"] == PAGES  # Even one Page requires the user's selection.
    for _ in range(3):
        auth.snapshot()
    assert len(transport.calls) == 2
    auth.select_page(PAGE)
    thread.join(3)
    assert not thread.is_alive() and len(result) == 1
    assert result[0].app_id == APP and result[0].page_id == PAGE
    create, poll, redeem = transport.calls
    assert create[0:2] == ("POST", "/v1/sessions") and create[3] is None
    assert create[2] == {"challenge": hashlib.sha256(poll[3].encode()).hexdigest()}
    assert redeem == ("POST", f"/v1/sessions/{SESSION}/redeem", {"page_id": PAGE}, poll[3])
    assert auth._verifier is None
    assert "nf-synthetic-access" not in repr(result[0]) + str(auth.snapshot())


@pytest.mark.parametrize("change", [{"app_id": "999001"}, {"authorize_url": "https://attacker.example"},
                                   {"authorize_url": started()["authorize_url"].replace(APP, "999001")},
                                   {"authorize_url": started()["authorize_url"] + "&access_token=secret"},
                                   {"expires_in": 900}, {"session_id": "../escape"}])
def test_untrusted_initial_response_never_opens_browser_or_retries(change):
    auth, transport, browsers = backend([started(**change)])
    with pytest.raises(InstagramConnectionError):
        auth.authorize(scopes=FACEBOOK_SCOPES)
    assert len(transport.calls) == 1 and browsers == []


@pytest.mark.parametrize("change", [{"app_id": "999001"}, {"page_id": "999001"},
                                   {"scopes": ["instagram_business_basic"]}, {"access_token": "token\nheader"},
                                   {"expires_at": "2026-10-17T01:00:00"}])
def test_grant_identity_permissions_expiry_format_are_verified(change):
    auth, _, _ = backend([])
    with pytest.raises(InstagramConnectionError) as error:
        auth._grant(grant(**change), PAGE)
    assert error.value.code == "response_invalid"


def test_lost_redemption_response_is_not_retried():
    auth, transport, _ = backend([started(), {"status": "ready", "pages": PAGES}, TimeoutError("TOKEN-SECRET")])
    thread, result = run_auth(auth)
    wait_until(lambda: auth.snapshot()["awaiting_page"])
    auth.select_page(PAGE)
    thread.join(3)
    assert isinstance(result[0], InstagramConnectionError) and result[0].code == "outcome_unknown"
    assert len(transport.calls) == 3 and "TOKEN-SECRET" not in str(result[0])
    assert auth._verifier is None


def test_cancel_stops_polling_and_sends_at_most_one_explicit_delete():
    auth, transport, _ = backend([started(), {"status": "ready", "pages": PAGES}, {"status": "cancelled"}])
    thread, result = run_auth(auth)
    wait_until(lambda: auth.snapshot()["awaiting_page"])
    auth.cancel()
    auth.cancel()
    thread.join(3)
    assert isinstance(result[0], InstagramConnectionError) and result[0].code == "cancelled"
    assert [call[0] for call in transport.calls] == ["POST", "GET", "DELETE"]


def test_close_style_local_cancel_does_not_contact_relay():
    auth, transport, _ = backend([started(), {"status": "ready", "pages": PAGES}])
    thread, result = run_auth(auth)
    wait_until(lambda: auth.snapshot()["awaiting_page"])
    auth.cancel(remote=False)
    thread.join(3)
    assert result[0].code == "cancelled" and len(transport.calls) == 2


def test_cancel_before_worker_enters_authorization_stays_cancelled_without_network():
    auth, transport, _ = backend([])
    auth.prepare()
    auth.cancel(remote=False)
    with pytest.raises(InstagramConnectionError) as error:
        auth.authorize(scopes=FACEBOOK_SCOPES)
    assert error.value.code == "cancelled" and transport.calls == []


def test_timeout_is_terminal_without_new_session_or_exchange():
    auth, transport, _ = backend([started()])
    ticks = iter([0, 601])
    auth.monotonic = lambda: next(ticks)
    with pytest.raises(InstagramConnectionError) as error:
        auth.authorize(scopes=FACEBOOK_SCOPES)
    assert error.value.code == "expired" and len(transport.calls) == 1


def test_unknown_page_selection_cannot_redeem():
    auth, transport, _ = backend([started(), {"status": "ready", "pages": PAGES}])
    thread, _ = run_auth(auth)
    wait_until(lambda: auth.snapshot()["awaiting_page"])
    with pytest.raises(InstagramConnectionError):
        auth.select_page("999001")
    assert len(transport.calls) == 2
    auth.cancel(remote=False)
    thread.join(3)


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(tmp_path / "relay-test.db")
    Base.metadata.create_all(engine)
    yield session_factory(engine)
    engine.dispose()


class Vault:
    def __init__(self):
        self.values = {}

    def write_reserved(self, key, identity, reference, bundle, *, operation_id):
        self.values[reference] = bundle

    def load(self, key, identity, reference, *, allow_expired=False):
        return self.values[reference]


class Identity:
    def __init__(self):
        self.calls = []

    def get(self, path, token, fields=""):
        self.calls.append(path)
        if path == "me/permissions":
            return {"data": [{"permission": scope, "status": "granted"} for scope in FACEBOOK_SCOPES]}
        if path == "me/accounts":
            return {"data": [{"id": PAGE, "name": "Synthetic", "tasks": ["CREATE_CONTENT"],
                              "access_token": "nf-synthetic-page-token", "instagram_business_account": {"id": INSTAGRAM}}]}
        return {"id": INSTAGRAM, "username": "synthetic_news"}


def test_configured_production_factory_background_connection_and_settings_survive_restart(sessions, tmp_path):
    auth, transport, _ = backend([started(), {"status": "ready", "pages": PAGES}, grant()])
    identity, vault = Identity(), Vault()
    service = InstagramConnectionService(sessions, tmp_path, relay_factory=lambda config: auth,
                                         identity_transport=identity, vault=vault)
    service.save_relay(ORIGIN, APP)
    assert service.status()["relay_code_available"] and service.status()["relay_configured"]
    assert transport.calls == []
    account_id = service.begin(consent=True)
    wait_until(lambda: service.status().get("awaiting_page"))
    assert service.status()["pending_account_id"] == account_id
    assert identity.calls == []
    with pytest.raises(InstagramConnectionError, match="동의"):
        service.select_page(account_id, PAGE)
    service.select_page(account_id, PAGE, consent=True)
    wait_until(lambda: service.accounts()[0]["ready"])
    assert service.access_for_upload(account_id, consent=True).instagram_id == INSTAGRAM
    assert identity.calls == ["me/permissions", "me/accounts", INSTAGRAM]
    service.close()
    resumed = InstagramConnectionService(sessions, tmp_path, identity_transport=identity, vault=vault)
    assert isinstance(resumed.authorization, InstagramRelayAuthorization)
    assert resumed.status()["relay_url"] == ORIGIN and resumed.accounts()[0]["ready"]
    assert len(transport.calls) == 3 and len(identity.calls) == 3
    with sessions() as session:
        values = " ".join(row.value for row in session.scalars(select(AppSetting)))
    assert "nf-synthetic" not in values and "access_token" not in values
    resumed.save_relay(ORIGIN, "999001")
    assert not resumed.accounts()[0]["ready"]
    with pytest.raises(InstagramConnectionError, match="일치"):
        resumed.access_for_upload(account_id, consent=True)


def test_service_cancel_preserves_cancelled_journal_and_does_not_verify_identity(sessions, tmp_path):
    auth, transport, _ = backend([started(), {"status": "ready", "pages": PAGES}, {"status": "cancelled"}])
    identity = Identity()
    service = InstagramConnectionService(sessions, tmp_path, authorization_backend=auth, identity_transport=identity,
                                         vault=Vault())
    account_id = service.begin(consent=True)
    wait_until(lambda: service.status().get("awaiting_page"))
    service.cancel(account_id)
    wait_until(lambda: service.status()["pending_account_id"] is None)
    assert service.accounts()[0]["status"] == "cancelled" and identity.calls == []
    with sessions() as session:
        assert session.scalar(select(OAuthLifecycleOperation.status)) == "instagram_cancelled"
    assert len(transport.calls) == 3
    service.close()


def test_restart_quarantines_interrupted_login_without_relay_call(sessions, tmp_path):
    auth, transport, _ = backend([started(), {"status": "ready", "pages": PAGES}])
    service = InstagramConnectionService(sessions, tmp_path, authorization_backend=auth, vault=Vault())
    service.begin(consent=True)
    wait_until(lambda: service.status().get("awaiting_page"))
    restarted = InstagramConnectionService(sessions, tmp_path)
    assert restarted.recover() == 1
    assert restarted.accounts()[0]["status"] == "unknown" and len(transport.calls) == 2
    service.close()
    with sessions() as session:
        assert session.scalar(select(OAuthConnection.status)) == "unknown"


def test_cancel_during_identity_query_blocks_remaining_meta_reads_and_storage(sessions, tmp_path):
    auth, transport, _ = backend([started(), {"status": "ready", "pages": PAGES}, grant()])
    entered, resume = Event(), Event()

    class PausedIdentity(Identity):
        def get(self, path, token, fields=""):
            if path == "me/permissions":
                entered.set()
                assert resume.wait(3)
            return super().get(path, token, fields)

    identity, vault = PausedIdentity(), Vault()
    service = InstagramConnectionService(sessions, tmp_path, authorization_backend=auth,
                                         identity_transport=identity, vault=vault)
    try:
        account_id = service.begin(consent=True)
        wait_until(lambda: service.status().get("awaiting_page"))
        service.select_page(account_id, PAGE, consent=True)
        assert entered.wait(3)
        service.cancel(account_id)
        resume.set()
        wait_until(lambda: service.status()["pending_account_id"] is None)
        assert identity.calls == ["me/permissions"] and not vault.values
        assert service.accounts()[0]["status"] == "cancelled" and len(transport.calls) == 3
    finally:
        resume.set()
        service.close()


def test_public_transport_pins_dns_and_never_follows_redirect(monkeypatch):
    events = []

    class Response:
        status = 302

        def getheader(self, name, default=None):
            return default

    class Connection:
        sock = None

        def __init__(self, host, ip, port, timeout, tls):
            events.append((host, ip, port, tls))

        def request(self, method, path, body=None, headers=None):
            events.append((method, path))

        def getresponse(self):
            return Response()

        def close(self):
            events.append("closed")

    monkeypatch.setattr("newsflow.oauth.instagram_relay.public_addresses", lambda *args: ["8.8.8.8"])
    monkeypatch.setattr("newsflow.oauth.instagram_relay.PinnedConnection", Connection)
    with pytest.raises(InstagramConnectionError):
        PublicRelayTransport(RelayConfig.parse(ORIGIN, APP)).request("POST", "/v1/sessions", {"challenge": "f" * 64})
    assert events == [("relay.example.com", "8.8.8.8", 443, True), ("POST", "/v1/sessions"), "closed"]


def test_public_transport_rejects_arbitrary_url_and_private_dns_before_socket(monkeypatch):
    def rejected_dns(*args):
        raise ValueError("private DNS address")
    monkeypatch.setattr("newsflow.oauth.instagram_relay.public_addresses", rejected_dns)
    transport = PublicRelayTransport(RelayConfig.parse(ORIGIN, APP))
    with pytest.raises(InstagramConnectionError):
        transport.request("POST", "https://evil.example", {})
    with pytest.raises(InstagramConnectionError):
        transport.request("POST", "/v1/sessions", {"challenge": "f" * 64})


def test_transport_sensitive_response_is_not_in_repr():
    assert "SECRET" not in repr(RelayResponse(200, {"access_token": "SECRET"}))
    assert "SECRET" not in json.dumps(InstagramRelayAuthorization(RelayConfig.parse(ORIGIN, APP)).snapshot())


def test_desktop_client_actual_relay_routes_fake_meta_and_explicit_page_choice(sessions, tmp_path):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from newsflow.oauth.relay_server import RelayConfig as ServerConfig
    from newsflow.oauth.relay_server import create_relay_app

    token = "nf-synthetic-access-instagram-user"

    class Meta:
        def __init__(self):
            self.calls = []

        def exchange(self, code):
            self.calls.append("exchange")
            assert code.get_secret_value() == "nf-synthetic-relay-callback-code"
            return {"access_token": token, "token_type": "bearer", "expires_in": 3600}

        def inspect(self, value):
            self.calls.append("inspect")
            assert value.get_secret_value() == token
            return {"data": {"app_id": APP, "user_id": "500001", "is_valid": True, "type": "USER",
                             "scopes": list(FACEBOOK_SCOPES), "expires_at": int(time.time()) + 3600,
                             "data_access_expires_at": int(time.time()) + 7200}}

        def permissions(self, value):
            self.calls.append("permissions")
            return {"data": [{"permission": scope, "status": "granted"} for scope in FACEBOOK_SCOPES]}

        def pages(self, value):
            self.calls.append("pages")
            return {"data": [{"id": PAGE, "name": "Synthetic Page", "tasks": ["CREATE_CONTENT"],
                              "instagram_business_account": {"id": INSTAGRAM}}]}

    meta = Meta()
    app = create_relay_app(ServerConfig(ORIGIN, APP, "400001", SecretStr("nf-synthetic-relay-server-secret")), transport=meta)
    with TestClient(app, base_url=ORIGIN) as client:
        class LocalTransport:
            def __init__(self):
                self.calls = []

            def request(self, method, path, body=None, verifier=None):
                self.calls.append((method, path))
                headers = {"Authorization": "Bearer " + verifier} if verifier else {}
                response = client.request(method, path, headers=headers, **({"json": body} if body is not None else {}))
                return RelayResponse(response.status_code, response.json())

        def browser(url):
            assert urlsplit(url).netloc == "www.facebook.com"
            state = parse_qs(urlsplit(url).query)["state"][0]
            response = client.get("/oauth/callback", params={"state": state, "code": "nf-synthetic-relay-callback-code"})
            assert response.status_code == 200 and token not in response.text
            return True

        transport = LocalTransport()
        auth = InstagramRelayAuthorization(RelayConfig.parse(ORIGIN, APP), transport=transport,
                                          browser_open=browser, poll_interval=0.01)
        identity, vault = Identity(), Vault()
        service = InstagramConnectionService(sessions, tmp_path, authorization_backend=auth,
                                             identity_transport=identity, vault=vault)
        try:
            account_id = service.begin(consent=True)
            wait_until(lambda: service.status().get("awaiting_page"))
            assert service.status()["pages"] == PAGES and identity.calls == []
            assert not service.accounts()[0]["ready"]
            service.select_page(account_id, PAGE, consent=True)
            wait_until(lambda: service.accounts()[0]["ready"])
            assert service.access_for_upload(account_id, consent=True).instagram_id == INSTAGRAM
            assert meta.calls == ["exchange", "inspect", "permissions", "pages"]
            assert [method for method, _ in transport.calls] == ["POST", "GET", "POST"]
            assert identity.calls == ["me/permissions", "me/accounts", INSTAGRAM]
            assert token not in json.dumps(service.status(), default=str)
        finally:
            service.close()


def test_reconnect_gui_route_passes_saved_account_only_with_consent():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from newsflow.gui.instagram_routes import router

    class Connections:
        def __init__(self):
            self.calls = []

        def status(self):
            return {"connection_supported": True}

        def begin(self, *, consent, account_id):
            self.calls.append((consent, account_id))
            return account_id

    app = FastAPI()
    app.state.instagram = Connections()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.post("/instagram/connect", data={"account_id": "42"}).status_code == 422
        assert app.state.instagram.calls == []
        response = client.post("/instagram/connect", data={"account_id": "42", "consent": "true"}, follow_redirects=False)
        assert response.status_code == 303 and app.state.instagram.calls == [(True, 42)]


def test_reconnect_template_uses_existing_account_and_unchecked_consent():
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader

    templates = Path(__file__).parents[1] / "src/newsflow/gui/templates"
    template = Environment(loader=FileSystemLoader(templates), autoescape=True).get_template("instagram_connection.html")
    body = template.render(csrf_field=lambda: "", instagram={
        "accounts": [{"id": 42, "label": "Synthetic Account", "instagram_id": INSTAGRAM,
                      "message": "연결 만료", "ready": False}],
        "connection_supported": True, "pending": False,
    })
    assert 'name="account_id" value="42"' in body and "이 계정 다시 연결" in body
    assert 'name="consent" value="true" required' in body and "checked" not in body
