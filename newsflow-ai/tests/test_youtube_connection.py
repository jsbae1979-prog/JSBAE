"""Desktop OAuth service contracts with synthetic transports; no Google calls."""

import json
import socket
import sys
import threading
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from newsflow.db.models import (
    AuditLog,
    Base,
    OAuthConnection,
    OAuthLifecycleOperation,
    PlatformAccount,
    utcnow,
)
from newsflow.db.session import make_engine, session_factory
from newsflow.intelligence.credentials import FakeCipher
from newsflow.oauth.activation import require_production_activation, youtube_operation
from newsflow.oauth.callback import CallbackError, CallbackResult, _result_seal
from newsflow.oauth.contracts import OAuthBlocked
from newsflow.oauth.identity import IDENTITY_LINK_SCOPES, IdentityHTTPResponse
from newsflow.oauth.production import ProtocolError, TokenHTTPResponse
from newsflow.oauth.production_dpapi import ProductionWindowsCredentialVault
from newsflow.oauth.session import pkce_s256
from newsflow.oauth.youtube import (
    YouTubeClientStore,
    YouTubeConnectionError,
    YouTubeConnectionService,
    _tokens,
)

CLIENT = json.dumps({"installed": {
    "client_id": "nf-test-client.apps.googleusercontent.com", "client_secret": "test-desktop-secret",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": ["http://localhost"],
}})
CHANNEL = "UC" + "a" * 22


def token_response(**changes):
    payload = {
        "access_token": "nf-synthetic-access-first", "refresh_token": "nf-synthetic-refresh-first",
        "expires_in": 3600, "token_type": "Bearer", "scope": " ".join(IDENTITY_LINK_SCOPES),
    }
    payload.update(changes)
    return TokenHTTPResponse(200, json.dumps(payload).encode())


class FakeTokens:
    def __init__(self):
        self.calls = []
        self.response = token_response()
        self.fail = False

    def post(self, operation, values):
        self.calls.append((operation, values["grant_type"]))
        if self.fail:
            raise TimeoutError("DO_NOT_EXPOSE_TOKEN")
        return self.response


class FakeIdentity:
    def __init__(self):
        self.calls = 0
        self.channel = CHANNEL

    def get_channels(self, access_token):
        self.calls += 1
        return IdentityHTTPResponse(200, json.dumps({
            "kind": "youtube#channelListResponse", "items": [{"id": self.channel}],
        }).encode())


class FakeVault:
    def __init__(self):
        self.data = {}
        self.fail = False

    def write_reserved(self, key, identity, reference, bundle, *, operation_id):
        if self.fail:
            raise OSError("DO_NOT_EXPOSE_TOKEN")
        self.data[reference] = (key, identity, bundle)

    def load(self, key, identity, reference, *, allow_expired=False):
        stored_key, stored_identity, bundle = self.data[reference]
        assert (key, identity) == (stored_key, stored_identity)
        return bundle


class FakeListener:
    hold = False

    def __init__(self):
        self.cancelled = threading.Event()
        self.code = SecretStr("nf-synthetic-code-test")
        self.verifier = SecretStr("v" * 64)
        self.redirect_uri = "http://127.0.0.1:9321/oauth/callback"

    def start(self, key, *, scopes):
        self.key, self.scopes = key, scopes
        return SimpleNamespace(redirect_uri=self.redirect_uri, request=SimpleNamespace(
            state=SecretStr("s" * 43), code_challenge=pkce_s256(self.verifier.get_secret_value()),
        ))

    def assert_valid(self, account_key, *, production):
        assert production and account_key == self.key

    def wait(self):
        if self.hold:
            self.cancelled.wait(5)
        if self.cancelled.is_set():
            raise YouTubeConnectionError("cancelled")
        return self

    def cancel(self):
        self.cancelled.set()

    def close(self):
        pass


class FakeBrowser:
    def __init__(self):
        self.calls = []

    def open(self, url):
        self.calls.append(url)


@pytest.fixture
def service(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    result = YouTubeConnectionService(
        session_factory(engine), tmp_path, client_store=YouTubeClientStore(tmp_path, FakeCipher()),
        vault=FakeVault(), token_transport=FakeTokens(), identity_transport=FakeIdentity(),
        browser=FakeBrowser(), listener_factory=FakeListener,
    )
    yield result
    result.close()
    engine.dispose()


def connect(service):
    service.save_client(CLIENT)
    account_id = service.begin(consent=True)
    service._workers[account_id].join(5)
    assert not service._workers[account_id].is_alive()
    return account_id


def test_status_does_not_decrypt_or_contact_google(service, monkeypatch):
    monkeypatch.setattr(service.client_store, "key", lambda: pytest.fail("status decrypted config"))
    assert service.status()["client_configured"] is False
    assert service.status()["accounts"] == []
    assert service.tokens.calls == []
    assert service.identity.calls == 0


def test_client_separate_encrypted_storage_and_no_environment_override(service, monkeypatch):
    service.save_client(CLIENT)
    raw = service.client_store.path.read_bytes()
    assert b"test-desktop-secret" not in raw
    assert b"client_id" not in raw
    assert service.status()["client_configured"]
    monkeypatch.setenv(service.client_store.ENV, CLIENT)
    service.client_store.path.unlink()
    assert not service.status()["client_configured"]
    with pytest.raises(YouTubeConnectionError):
        service.begin(consent=True)
    assert service.tokens.calls == []


def test_consent_required_before_config_tokens_or_browser(service):
    with pytest.raises(YouTubeConnectionError, match="동의"):
        service.begin()
    with pytest.raises(YouTubeConnectionError, match="동의"):
        service.access_for_upload(1)
    assert service.browser.calls == []
    assert service.tokens.calls == []


def test_success_stores_metadata_and_returns_bound_token_without_extra_http(service):
    account_id = connect(service)
    state = service.accounts()[0]
    assert state["ready"] and state["channel_id"] == CHANNEL
    bundle, channel = service.access_for_upload(account_id, consent=True)
    assert channel == CHANNEL and bundle.scopes == IDENTITY_LINK_SCOPES
    assert service.tokens.calls == [("token", "authorization_code")]
    assert service.identity.calls == 1
    with service.sessions() as session:
        connection = session.get(OAuthConnection, account_id)
        assert connection.status == "connected"
        assert session.scalar(select(OAuthLifecycleOperation.status)) == "youtube_completed"
    assert "test-desktop-secret" not in str(service.status())
    assert "nf-synthetic-access" not in str(service.status())


def test_failed_exchange_never_retries_and_sanitizes(service):
    service.tokens.fail = True
    account_id = connect(service)
    state = service.accounts()[0]
    assert state["status"] == "unknown"
    assert state["error_code"] == "outcome_unknown"
    with pytest.raises(YouTubeConnectionError):
        service.access_for_upload(account_id, consent=True)
    assert service.tokens.calls == [("token", "authorization_code")]
    assert service.identity.calls == 0
    assert "DO_NOT_EXPOSE" not in str(service.status())


@pytest.mark.parametrize("code,reason,stored_code,status", [
    ("callback_invalid", "unknown_field", "callback_unknown_field", "error"),
    ("callback_invalid", "duplicate_field", "callback_duplicate_field", "error"),
    ("callback_invalid", "empty_field", "callback_empty_field", "error"),
    ("provider_error", "provider_error", "callback_provider_error", "error"),
    ("cancelled", "provider_denied", "cancelled", "cancelled"),
])
def test_callback_failure_reason_persists_without_exchange_retry_or_secret_disclosure(
    service, code, reason, stored_code, status, capfd,
):
    failure = CallbackError(code, reason=reason)
    failure.args = ("DO_NOT_EXPOSE_google_code_state_client_secret",)

    class Rejected(FakeListener):
        def wait(self):
            raise failure

    service.listener_factory = Rejected
    service.save_client(CLIENT)
    saved_client = service.client_store.path.read_bytes()
    with service.sessions.begin() as session:
        session.add(AuditLog(level="info", event="prior_record", message="preserved"))
    account_id = service.begin(consent=True)
    service._workers[account_id].join(5)
    assert not service._workers[account_id].is_alive()
    result = service.accounts()[0]
    assert (result["status"], result["error_code"], result["ready"]) == (status, stored_code, False)
    assert result["channel_id"] is None
    assert service.recover() == 0
    assert service.client_store.path.read_bytes() == saved_client
    assert service.tokens.calls == [] and service.identity.calls == 0 and service.vault.data == {}
    with service.sessions() as session:
        assert session.scalar(select(AuditLog.message).where(AuditLog.event == "prior_record")) == "preserved"
        audit = session.scalar(select(AuditLog.message).where(AuditLog.event == "youtube_callback_rejected"))
        operation = session.scalar(select(OAuthLifecycleOperation))
        assert json.loads(audit) == {
            "account_id": account_id, "stage": "callback", "outcome": stored_code,
            "operation_id": operation.id, "revision": operation.expected_revision,
            "reason": reason, "last_rejected_request": None,
            "observation": {},
        }
        assert session.scalar(select(OAuthLifecycleOperation.status)) == f"youtube_{status}"
    assert "DO_NOT_EXPOSE" not in str(service.status()) + audit
    assert capfd.readouterr() == ("", "")


@pytest.mark.parametrize("observed", ["origin", "DO_NOT_EXPOSE_state_token"])
def test_callback_expiry_records_observation_separately_and_only_if_allowlisted(service, observed):
    class Expired(FakeListener):
        def wait(self):
            failure = CallbackError("expired")
            failure.last_rejection = observed
            raise failure

    service.listener_factory = Expired
    account_id = connect(service)
    assert service.accounts()[0]["error_code"] == "callback_expired"
    assert "로컬 인증 응답" in service.accounts()[0]["message"]
    assert "Google 인증이 만료" not in service.accounts()[0]["message"]
    with service.sessions() as session:
        audit = session.scalar(select(AuditLog.message).where(AuditLog.event == "youtube_callback_rejected"))
        operation = session.scalar(select(OAuthLifecycleOperation))
    assert json.loads(audit) == {
        "account_id": account_id, "stage": "callback", "outcome": "callback_expired", "reason": None,
        "operation_id": operation.id, "revision": operation.expected_revision, "observation": {},
        "last_rejected_request": "origin" if observed == "origin" else None,
    }
    assert "DO_NOT_EXPOSE" not in audit + str(service.status())
    assert service.tokens.calls == [] and service.identity.calls == 0


def test_callback_wait_observations_persist_with_no_exchange_retry_or_data_changes(service, capfd):
    from newsflow.oauth.callback import SyntheticLoopbackCallback

    class NoResponse(FakeListener):
        def wait(self):
            with SyntheticLoopbackCallback() as listener:
                listener.start(self.key, ttl_seconds=0.02)
                return listener.wait(1)

    service.listener_factory = NoResponse
    service.save_client(CLIENT)
    saved_client = service.client_store.path.read_bytes()
    account_id = service.begin(consent=True)
    service._workers[account_id].join(5)
    assert not service._workers[account_id].is_alive()
    with service.sessions() as session:
        audit = json.loads(session.scalar(select(AuditLog.message).where(
            AuditLog.event == "youtube_callback_rejected")))
    assert audit["outcome"] == "callback_expired"
    assert audit["revision"] == 1 and audit["operation_id"]
    assert audit["observation"]["tcp_connections"] == 0
    assert audit["observation"]["http_requests"] == 0
    assert audit["observation"]["accepted_callbacks"] == 0
    assert audit["observation"]["rejected_requests"] == 0
    assert audit["observation"]["listener_running"] is True
    assert 0 <= audit["observation"]["elapsed_ms"] < 5000
    assert service.recover() == 0
    for _ in range(2):
        assert service.status()["accounts"][0]["error_code"] == "callback_expired"
    assert len(service.browser.calls) == 1
    assert service.tokens.calls == [] and service.identity.calls == 0 and service.vault.data == {}
    assert service.client_store.path.read_bytes() == saved_client
    assert capfd.readouterr() == ("", "")


def test_callback_observation_persistence_drops_injected_sensitive_values(service, capfd):
    class Poisoned(FakeListener):
        def wait(self):
            failure = CallbackError("expired")
            failure.args = ("DO_NOT_EXPOSE_secret",)
            failure.observation = {
                "tcp_connections": 1, "http_requests": "DO_NOT_EXPOSE_secret",
                "read_failures": True, "accepted_callbacks": -1, "rejected_requests": 10**20,
                "elapsed_ms": 300000, "listener_running": "DO_NOT_EXPOSE_secret",
                "deadline_reached": True, "url": "DO_NOT_EXPOSE_secret",
                "headers": {"code": "DO_NOT_EXPOSE_secret"},
            }
            raise failure

    service.listener_factory = Poisoned
    connect(service)
    with service.sessions() as session:
        raw = session.scalar(select(AuditLog.message).where(AuditLog.event == "youtube_callback_rejected"))
    assert json.loads(raw)["observation"] == {
        "tcp_connections": 1, "elapsed_ms": 300000, "deadline_reached": True,
    }
    assert "DO_NOT_EXPOSE" not in raw + str(service.status())
    assert service.tokens.calls == [] and service.identity.calls == 0
    assert capfd.readouterr() == ("", "")


def test_cancel_before_callback_and_duplicate_begin(service):
    class Waiting(FakeListener):
        hold = True

    service.listener_factory = Waiting
    service.save_client(CLIENT)
    account_id = service.begin(consent=True)
    with pytest.raises(YouTubeConnectionError, match="진행"):
        service.begin(consent=True)
    service.cancel(account_id)
    service._workers[account_id].join(5)
    assert service.accounts()[0]["status"] == "cancelled"
    assert service.tokens.calls == []


def test_refresh_once_only_when_user_approved_upload_and_preserves_old_ciphertext(service):
    service.tokens.response = token_response(expires_in=10)
    account_id = connect(service)
    old_reference = next(iter(service.vault.data))
    service.tokens.response = token_response(access_token="nf-synthetic-access-second")
    bundle, channel = service.access_for_upload(account_id, consent=True)
    assert bundle.access_token.get_secret_value() == "nf-synthetic-access-second"
    assert channel == CHANNEL and old_reference in service.vault.data
    assert len(service.vault.data) == 2
    assert service.tokens.calls == [("token", "authorization_code"), ("token", "refresh_token")]
    service.access_for_upload(account_id, consent=True)
    assert len(service.tokens.calls) == 2


def test_refresh_failure_blocks_next_attempt(service):
    service.tokens.response = token_response(expires_in=10)
    account_id = connect(service)
    service.tokens.response = TokenHTTPResponse(400, b'{"error":"invalid_grant"}')
    with pytest.raises(YouTubeConnectionError, match="만료"):
        service.access_for_upload(account_id, consent=True)
    with pytest.raises(YouTubeConnectionError):
        service.access_for_upload(account_id, consent=True)
    assert len(service.tokens.calls) == 2
    assert service.accounts()[0]["error_code"] == "expired"


def test_refresh_cannot_switch_channel(service):
    service.tokens.response = token_response(expires_in=10)
    account_id = connect(service)
    service.identity.channel = "UC" + "b" * 22
    with pytest.raises(YouTubeConnectionError, match="채널"):
        service.access_for_upload(account_id, consent=True)
    assert service.accounts()[0]["channel_id"] == CHANNEL
    assert not service.accounts()[0]["ready"]


def test_restart_pending_is_unknown_without_network_or_ciphertext_deletion(service):
    account_id = connect(service)
    old_files = dict(service.vault.data)
    with service.sessions.begin() as session:
        session.get(OAuthConnection, account_id).status = "refreshing"
    assert service.recover() == 1
    assert service.accounts()[0]["status"] == "unknown"
    assert service.vault.data == old_files
    assert len(service.tokens.calls) == 1
    with pytest.raises(YouTubeConnectionError):
        service.access_for_upload(account_id, consent=True)


def test_failed_ciphertext_commit_preserves_unknown_journal(service):
    service.vault.fail = True
    connect(service)
    with service.sessions() as session:
        operation = session.scalar(select(OAuthLifecycleOperation))
        assert operation.status == "youtube_unknown"
        assert operation.new_reference
        assert session.scalar(select(PlatformAccount.credential_ref)) is None
    assert service.accounts()[0]["status"] == "unknown"


def test_client_change_preserves_tokens_and_requires_explicit_reconnection(service):
    account_id = connect(service)
    old_files = dict(service.vault.data)
    replacement = json.loads(CLIENT)
    replacement["installed"]["client_id"] = "nf-new-client.apps.googleusercontent.com"
    service.save_client(json.dumps(replacement))
    assert not service.accounts()[0]["ready"]
    assert service.accounts()[0]["error_code"] == "client_changed"
    assert service.vault.data == old_files
    with pytest.raises(YouTubeConnectionError):
        service.access_for_upload(account_id, consent=True)
    assert len(service.tokens.calls) == 1
    assert service.begin(consent=True, account_id=account_id) == account_id
    service._workers[account_id].join(5)
    assert service.accounts()[0]["ready"]
    assert set(old_files).issubset(service.vault.data)


@pytest.mark.parametrize("change", [
    {"scope": IDENTITY_LINK_SCOPES[0]}, {"scope": " ".join(IDENTITY_LINK_SCOPES) + " extra"},
    {"expires_in": True}, {"access_token": "secret\ninvalid"}, {"refresh_token": None},
])
def test_malformed_grants_rejected(change):
    with pytest.raises((ProtocolError, YouTubeConnectionError)):
        _tokens(token_response(**change))


def test_activation_context_is_temporary_and_does_not_leak_to_threads():
    with pytest.raises(OAuthBlocked):
        require_production_activation()
    errors = []

    def check_other_thread():
        try:
            require_production_activation()
        except OAuthBlocked:
            errors.append(True)

    with youtube_operation(consent=True):
        require_production_activation()
        worker = threading.Thread(target=check_other_thread)
        worker.start()
        worker.join()
    assert errors == [True]
    with pytest.raises(OAuthBlocked):
        require_production_activation()


def test_real_callback_requires_seal_context_and_separate_mode():
    verifier = "v" * 64
    result = CallbackResult(
        "s", "youtube:1", IDENTITY_LINK_SCOPES, "http://127.0.0.1:9321/oauth/callback",
        SecretStr(verifier), SecretStr("4/real-format-code"), pkce_s256(verifier),
        utcnow() + timedelta(minutes=1), mode="YOUTUBE_CALLBACK",
    )
    object.__setattr__(result, "_seal", _result_seal(result))
    with pytest.raises(CallbackError):
        result.assert_valid("youtube:1")
    with youtube_operation(consent=True):
        result.assert_valid("youtube:1", production=True)
        with pytest.raises(CallbackError):
            replace(result, code=SecretStr("changed")).assert_valid("youtube:1", production=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows current-user DPAPI requires Windows")
def test_native_youtube_client_and_token_vault_roundtrip_without_network(tmp_path, monkeypatch):
    """Exercise the production DPAPI path using only dummy credentials in tmp_path."""
    def reject_network(*args, **kwargs):
        pytest.fail("Native credential storage must not contact a provider")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    client_path = tmp_path / "client"
    token_path = tmp_path / "tokens"
    client_store = YouTubeClientStore(client_path)
    vault = ProductionWindowsCredentialVault(token_path)
    bundle, _ = _tokens(token_response())
    with youtube_operation(consent=True):
        client_store.save(CLIENT)
        assert YouTubeClientStore(client_path).key() == CLIENT
        reference = vault.store("youtube:1", "a" * 64, bundle)
        restored = ProductionWindowsCredentialVault(token_path).load("youtube:1", "a" * 64, reference)
        assert restored == bundle
    for file in [client_store.path, token_path / (reference + ".pcred")]:
        ciphertext = file.read_bytes()
        assert b"test-desktop-secret" not in ciphertext
        assert b"nf-synthetic-access-first" not in ciphertext
        assert b"nf-synthetic-refresh-first" not in ciphertext
    with pytest.raises(OAuthBlocked):
        vault.load("youtube:1", "a" * 64, reference)
