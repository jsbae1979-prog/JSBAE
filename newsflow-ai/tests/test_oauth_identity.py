"""Actual loopback HTTP requests with synthetic channel identities and NF grants."""

from __future__ import annotations

import json
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread

import pytest
from pydantic import SecretStr

from newsflow.oauth.contracts import YOUTUBE_UPLOAD_SCOPE, OAuthBlocked
from newsflow.oauth.identity import (
    IDENTITY_LINK_SCOPES,
    YOUTUBE_CHANNELS_ENDPOINT,
    YOUTUBE_IDENTITY_SCOPE,
    IdentityError,
    SyntheticLoopbackIdentityTransport,
    SyntheticYouTubeIdentityAdapter,
    VerifiedIdentity,
    YouTubeHTTPSIdentityTransport,
    YouTubeIdentityAdapter,
)
from newsflow.publishing.auth import TokenBundle

CHANNEL_ONE = "UC" + "a" * 22
CHANNEL_TWO = "UC" + "b" * 22
CLIENT = "nf-synthetic-desktop.apps.googleusercontent.com"


def synthetic_identity_payload(channel: str = CHANNEL_ONE) -> dict[str, object]:
    return {
        "kind": "youtube#channelListResponse", "pageInfo": {"totalResults": 1, "resultsPerPage": 1},
        "items": [{"kind": "youtube#channel", "id": channel}],
    }


def synthetic_identity_bundle(suffix: str = "one", *, now: datetime | None = None) -> TokenBundle:
    return TokenBundle(
        access_token=SecretStr(f"nf-synthetic-access-{suffix}"),
        refresh_token=SecretStr(f"nf-synthetic-refresh-{suffix}"),
        expires_at=(now or datetime.now(UTC)) + timedelta(hours=1), scopes=IDENTITY_LINK_SCOPES,
    )


@dataclass(frozen=True)
class IdentityResponse:
    status: int = 200
    payload: dict[str, object] | None = field(default=None, repr=False)
    body: bytes | None = field(default=None, repr=False)
    delay: float = 0
    location: str | None = None


class SyntheticIdentityHTTPServer:
    """Synthetic GET fixture, bound to 127.0.0.1, with no request logging."""

    def __init__(self) -> None:
        self.responses: deque[IdentityResponse] = deque()
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.lock = Lock()
        self.received = Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                with owner.lock:
                    owner.requests.append((self.path, {key.lower(): value for key, value in self.headers.items()}))
                    response = owner.responses.popleft() if owner.responses else IdentityResponse()
                    owner.received.set()
                if response.delay:
                    time.sleep(response.delay)
                body = response.body if response.body is not None else json.dumps(
                    response.payload if response.payload is not None else synthetic_identity_payload(),
                ).encode()
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if response.location:
                    self.send_header("Location", response.location)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.thread = Thread(target=lambda: self.http.serve_forever(poll_interval=0.02), daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.http.server_port}"

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)

    def queue(self, *responses: IdentityResponse) -> None:
        with self.lock:
            self.responses.extend(responses)


@pytest.fixture
def identity_server():
    server = SyntheticIdentityHTTPServer()
    server.start()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def identity_adapter(identity_server):
    return SyntheticYouTubeIdentityAdapter(
        SyntheticLoopbackIdentityTransport(identity_server.base_url), client_id=CLIENT,
    )


def verify(adapter, bundle=None, *, key="youtube:1", channel=CHANNEL_ONE, now=None):
    grant = bundle or synthetic_identity_bundle(now=now)
    adapter.register_synthetic_grant(key, grant, now=now)
    return adapter.lookup(key, grant, expected_channel=channel, now=now), grant


def test_synthetic_http_lookup_uses_mine_and_minimized_part(identity_adapter, identity_server):
    receipt, bundle = verify(identity_adapter)
    assert receipt.account_key == "youtube:1" and receipt.channel_id == CHANNEL_ONE
    assert receipt.client_id == CLIENT and receipt.scopes == IDENTITY_LINK_SCOPES
    receipt.validate_bundle("youtube:1", bundle)
    assert len(receipt.digest("youtube:1")) == 64
    assert identity_adapter.readiness("youtube:1") == "SYNTHETIC_VERIFIED"
    assert identity_server.requests[0][0] == "/youtube/v3/channels?part=id&mine=true"
    assert identity_server.requests[0][1]["authorization"] == "Bearer nf-synthetic-access-one"
    assert "nf-synthetic-access-one" not in repr(receipt)
    assert "nf-synthetic-refresh-one" not in repr(receipt)
    assert identity_adapter.evidence() == {
        "mode": "SYNTHETIC_IDENTITY", "synthetic_identity_requests": 1,
        "real_identity_requests": 0, "real_oauth_requests": 0, "real_sns_upload_requests": 0,
        "production_readiness": "BLOCKED",
    }


@pytest.mark.parametrize("operation", ["adapter", "transport"])
def test_production_identity_is_hard_blocked_before_network(monkeypatch, operation):
    calls = []
    monkeypatch.setattr("newsflow.oauth.identity.build_opener", lambda *args: calls.append(args))
    monkeypatch.setenv("NEWSFLOW_OAUTH_PRODUCTION_ENABLED", "true")
    monkeypatch.setenv("NEWSFLOW_OAUTH_USER_APPROVED", "true")
    if operation == "adapter":
        adapter = YouTubeIdentityAdapter(CLIENT)
        with pytest.raises(OAuthBlocked):
            adapter.lookup("youtube:1", synthetic_identity_bundle(), expected_channel=CHANNEL_ONE)
    else:
        with pytest.raises(OAuthBlocked):
            YouTubeHTTPSIdentityTransport().get_channels(SecretStr("non-synthetic-token-test-format"))
    assert calls == []
    assert YOUTUBE_CHANNELS_ENDPOINT == "https://youtube.googleapis.com/youtube/v3/channels"


@pytest.mark.parametrize("scope", [
    (YOUTUBE_UPLOAD_SCOPE,), (YOUTUBE_IDENTITY_SCOPE,), (),
    (*IDENTITY_LINK_SCOPES, "openid"), (*IDENTITY_LINK_SCOPES, YOUTUBE_IDENTITY_SCOPE),
])
def test_identity_requires_explicit_exact_combined_scope_set(identity_adapter, identity_server, scope):
    grant = synthetic_identity_bundle().model_copy(update={"scopes": scope})
    with pytest.raises(IdentityError) as error:
        identity_adapter.register_synthetic_grant("youtube:1", grant)
    assert error.value.code == "scope_mismatch"
    assert identity_server.requests == []
    assert identity_adapter.readiness("youtube:1") == "BLOCKED"


def test_scope_order_is_semantic_but_no_scopes_are_added(identity_adapter):
    grant = synthetic_identity_bundle().model_copy(update={"scopes": tuple(reversed(IDENTITY_LINK_SCOPES))})
    receipt, _ = verify(identity_adapter, grant)
    receipt.validate_bundle("youtube:1", grant)
    assert receipt.scopes == IDENTITY_LINK_SCOPES
    assert grant.scopes == tuple(reversed(IDENTITY_LINK_SCOPES))


@pytest.mark.parametrize("mutation", ["account", "client", "channel", "scope", "fingerprint", "expiry", "mode"])
def test_receipt_field_substitution_is_rejected(identity_adapter, mutation):
    receipt, bundle = verify(identity_adapter)
    changes = {
        "account": {"account_key": "youtube:2"},
        "client": {"client_id": "nf-synthetic-other.apps.googleusercontent.com"},
        "channel": {"channel_id": CHANNEL_TWO},
        "scope": {"scopes": (YOUTUBE_UPLOAD_SCOPE,)},
        "fingerprint": {"grant_fingerprint": "a" * 64},
        "expiry": {"expires_at": receipt.expires_at + timedelta(days=1)},
        "mode": {"synthetic": False},
    }[mutation]
    forged = replace(receipt, **changes)
    with pytest.raises(IdentityError):
        forged.digest("youtube:2" if mutation == "account" else "youtube:1")
    receipt.validate_bundle("youtube:1", bundle)


def test_manually_constructed_receipt_has_no_verification_authority():
    receipt = VerifiedIdentity(
        "youtube:1", CLIENT, CHANNEL_ONE, IDENTITY_LINK_SCOPES, "a" * 64,
        datetime.now(UTC) + timedelta(hours=1), datetime.now(UTC), True,
    )
    with pytest.raises(IdentityError) as error:
        receipt.digest("youtube:1")
    assert error.value.code == "identity_unverified"


@pytest.mark.parametrize("mutation", ["refresh", "access", "expiry", "scope"])
def test_receipt_validates_whole_grant(identity_adapter, mutation):
    receipt, bundle = verify(identity_adapter)
    forged = bundle.model_copy(deep=True)
    if mutation == "refresh":
        forged.refresh_token = SecretStr("nf-synthetic-refresh-other-account")
    elif mutation == "access":
        forged.access_token = SecretStr("nf-synthetic-access-other-account")
    elif mutation == "expiry":
        forged.expires_at += timedelta(days=1)
    else:
        forged.scopes = (YOUTUBE_UPLOAD_SCOPE,)
    with pytest.raises(IdentityError):
        receipt.validate_bundle("youtube:1", forged)
    receipt.validate_bundle("youtube:1", bundle)


def test_account_cross_binding_is_blocked_before_second_http(identity_adapter, identity_server):
    receipt, bundle = verify(identity_adapter)
    with pytest.raises(IdentityError):
        identity_adapter.lookup("youtube:2", bundle, expected_channel=CHANNEL_ONE)
    with pytest.raises(IdentityError):
        identity_adapter.register_synthetic_grant("youtube:2", bundle)
    with pytest.raises(IdentityError):
        receipt.digest("youtube:2")
    assert len(identity_server.requests) == 1


def test_same_access_with_foreign_refresh_cannot_register(identity_adapter, identity_server):
    receipt, bundle = verify(identity_adapter)
    forged = bundle.model_copy(update={"refresh_token": SecretStr("nf-synthetic-refresh-foreign")})
    with pytest.raises(IdentityError) as error:
        identity_adapter.register_synthetic_grant("youtube:1", forged)
    assert error.value.code == "account_mismatch"
    receipt.validate_bundle("youtube:1", bundle)
    assert len(identity_server.requests) == 1


def test_a_channel_cannot_bind_to_two_local_accounts(identity_adapter, identity_server):
    verify(identity_adapter)
    second = synthetic_identity_bundle("two")
    identity_adapter.register_synthetic_grant("youtube:2", second)
    with pytest.raises(IdentityError) as error:
        identity_adapter.lookup("youtube:2", second, expected_channel=CHANNEL_ONE)
    assert error.value.code == "account_mismatch"
    assert identity_adapter.readiness("youtube:2") == "BLOCKED"
    assert len(identity_server.requests) == 2


def test_channel_change_invalidates_original_identity(identity_adapter, identity_server):
    receipt, bundle = verify(identity_adapter)
    identity_server.queue(IdentityResponse(payload=synthetic_identity_payload(CHANNEL_TWO)))
    with pytest.raises(IdentityError) as error:
        identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_TWO)
    assert error.value.code == "identity_mismatch"
    with pytest.raises(IdentityError):
        receipt.digest("youtube:1")
    assert identity_adapter.readiness("youtube:1") == "BLOCKED"


def test_new_refresh_grant_needs_new_identity_receipt(identity_adapter, identity_server):
    old_receipt, old = verify(identity_adapter)
    prior_digest = old_receipt.digest("youtube:1")
    rotated = synthetic_identity_bundle("rotated")
    with pytest.raises(IdentityError):
        old_receipt.validate_bundle("youtube:1", rotated)
    identity_adapter.register_synthetic_grant("youtube:1", rotated)
    new_receipt = identity_adapter.lookup("youtube:1", rotated, expected_channel=CHANNEL_ONE)
    new_receipt.validate_bundle("youtube:1", rotated)
    assert new_receipt.digest("youtube:1") == prior_digest
    with pytest.raises(IdentityError):
        old_receipt.validate_bundle("youtube:1", old)
    assert len(identity_server.requests) == 2


def test_expired_registered_grant_can_be_invalidated_without_a_request(identity_adapter, identity_server):
    prior_time = datetime.now(UTC) - timedelta(hours=2)
    receipt, bundle = verify(identity_adapter, now=prior_time)
    assert bundle.expires_at < datetime.now(UTC)
    assert identity_adapter.readiness("youtube:1", now=prior_time) == "SYNTHETIC_VERIFIED"
    identity_adapter.invalidate_grant("youtube:1", bundle)
    assert identity_adapter.readiness("youtube:1", now=prior_time) == "BLOCKED"
    with pytest.raises(IdentityError):
        receipt.digest("youtube:1", now=prior_time)
    with pytest.raises(IdentityError) as error:
        identity_adapter.register_synthetic_grant("youtube:1", bundle, now=prior_time)
    assert error.value.code == "reused"
    assert len(identity_server.requests) == 1


def test_foreign_or_modified_known_grant_cannot_invalidate_another_receipt(identity_adapter, identity_server):
    first_receipt, first = verify(identity_adapter)
    identity_server.queue(IdentityResponse(payload=synthetic_identity_payload(CHANNEL_TWO)))
    second_receipt, second = verify(identity_adapter, synthetic_identity_bundle("second"),
                                    key="youtube:2", channel=CHANNEL_TWO)
    altered = first.model_copy(update={"refresh_token": SecretStr("nf-synthetic-refresh-forged")})
    for key, value in (("youtube:2", first), ("youtube:1", altered)):
        with pytest.raises(IdentityError) as error:
            identity_adapter.invalidate_grant(key, value)
        assert error.value.code == "account_mismatch"
        first_receipt.validate_bundle("youtube:1", first)
        second_receipt.validate_bundle("youtube:2", second)
    assert identity_adapter.readiness("youtube:1") == "SYNTHETIC_VERIFIED"
    assert identity_adapter.readiness("youtube:2") == "SYNTHETIC_VERIFIED"
    assert len(identity_server.requests) == 2


def test_historical_invalidation_preserves_unrelated_current_receipt(identity_adapter, identity_server):
    _old_receipt, known_old = verify(identity_adapter)
    current_receipt, current = verify(identity_adapter, synthetic_identity_bundle("current"))
    unknown_historical = synthetic_identity_bundle("unknown-historical", now=datetime.now(UTC) - timedelta(hours=2))
    identity_adapter.invalidate_grant("youtube:1", unknown_historical)
    current_receipt.validate_bundle("youtube:1", current)
    identity_adapter.invalidate_grant("youtube:1", known_old)
    current_receipt.validate_bundle("youtube:1", current)
    assert identity_adapter.readiness("youtube:1") == "SYNTHETIC_VERIFIED"
    with pytest.raises(IdentityError) as error:
        identity_adapter.register_synthetic_grant("youtube:1", known_old)
    assert error.value.code == "reused"
    assert len(identity_server.requests) == 2


def test_invalidation_during_http_lookup_cannot_reissue_old_identity(identity_adapter, identity_server):
    receipt, bundle = verify(identity_adapter)
    identity_server.received.clear()
    identity_server.queue(IdentityResponse(delay=0.15))
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(identity_adapter.lookup, "youtube:1", bundle, expected_channel=CHANNEL_ONE)
        assert identity_server.received.wait(timeout=2)
        identity_adapter.invalidate_grant("youtube:1", bundle)
        with pytest.raises(IdentityError) as error:
            pending.result(timeout=2)
        assert error.value.code == "reused"
    with pytest.raises(IdentityError):
        receipt.digest("youtube:1")
    assert identity_adapter.readiness("youtube:1") == "BLOCKED"
    with pytest.raises(IdentityError):
        identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_ONE)
    assert len(identity_server.requests) == 2


@pytest.mark.parametrize("mutation", ["non-synthetic", "missing-refresh", "reduced-scope"])
def test_invalid_invalidation_input_cannot_clear_healthy_identity(identity_adapter, identity_server, mutation):
    receipt, bundle = verify(identity_adapter)
    if mutation == "non-synthetic":
        forged = bundle.model_copy(update={"access_token": SecretStr("synthetic-real-format-test-value")})
    elif mutation == "missing-refresh":
        forged = bundle.model_copy(update={"refresh_token": None})
    else:
        forged = bundle.model_copy(update={"scopes": (YOUTUBE_UPLOAD_SCOPE,)})
    with pytest.raises((IdentityError, OAuthBlocked)):
        identity_adapter.invalidate_grant("youtube:1", forged)
    receipt.validate_bundle("youtube:1", bundle)
    assert identity_adapter.readiness("youtube:1") == "SYNTHETIC_VERIFIED"
    assert len(identity_server.requests) == 1


@pytest.mark.parametrize("status,expected", [(401, "revoked"), (403, "permission_denied")])
def test_revoked_or_reduced_permissions_block_previous_receipt(
    identity_adapter, identity_server, status, expected,
):
    receipt, bundle = verify(identity_adapter)
    identity_server.queue(IdentityResponse(status=status, payload={"error": {"message": "secret-provider-detail"}}))
    with pytest.raises(IdentityError) as error:
        identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_ONE)
    assert error.value.code == expected and "secret-provider-detail" not in str(error.value)
    with pytest.raises(IdentityError):
        receipt.digest("youtube:1")
    assert identity_adapter.readiness("youtube:1") == "BLOCKED"
    with pytest.raises(IdentityError):
        identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_ONE)
    assert len(identity_server.requests) == 2


@pytest.mark.parametrize("case", ["empty", "multiple", "paginated", "count-mismatch", "bad-id", "bad-kind", "error"])
def test_ambiguous_or_invalid_identity_never_connects(identity_adapter, identity_server, case):
    payload = synthetic_identity_payload()
    if case == "empty":
        payload["items"] = []
    elif case == "multiple":
        payload["items"] = [{"id": CHANNEL_ONE}, {"id": CHANNEL_TWO}]
    elif case == "paginated":
        payload["nextPageToken"] = "nonsecret-page-token"
    elif case == "count-mismatch":
        payload["pageInfo"] = {"totalResults": 2}
    elif case == "bad-id":
        payload["items"] = [{"id": "private-email@example.invalid"}]
    elif case == "bad-kind":
        payload["kind"] = "youtube#videoListResponse"
    else:
        payload["error"] = {"message": "provider-private-detail"}
    identity_server.queue(IdentityResponse(payload=payload))
    bundle = synthetic_identity_bundle()
    identity_adapter.register_synthetic_grant("youtube:1", bundle)
    with pytest.raises(IdentityError) as error:
        identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_ONE)
    assert "private-email" not in str(error.value) and "provider-private-detail" not in str(error.value)
    assert identity_adapter.readiness("youtube:1") == "BLOCKED"


@pytest.mark.parametrize("case", ["timeout", "server-error", "rate-limit"])
def test_unknown_lookup_is_quarantined_without_retry(identity_adapter, identity_server, case):
    receipt, bundle = verify(identity_adapter)
    if case == "timeout":
        identity_adapter.transport.timeout_seconds = 0.05
        identity_server.queue(IdentityResponse(delay=0.2))
    else:
        identity_server.queue(IdentityResponse(status=503 if case == "server-error" else 429))
    with pytest.raises(IdentityError) as error:
        identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_ONE)
    assert error.value.code == "outcome_unknown" and error.value.outcome_unknown
    assert identity_adapter.readiness("youtube:1") == "BLOCKED"
    with pytest.raises(IdentityError):
        receipt.digest("youtube:1")
    with pytest.raises(IdentityError) as retry:
        identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_ONE)
    assert retry.value.outcome_unknown
    assert len(identity_server.requests) == 2


def test_redirect_is_not_followed(identity_adapter, identity_server):
    identity_server.queue(IdentityResponse(status=302, location="https://accounts.google.com/o/oauth2/auth"))
    bundle = synthetic_identity_bundle()
    identity_adapter.register_synthetic_grant("youtube:1", bundle)
    with pytest.raises(IdentityError):
        identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_ONE)
    assert len(identity_server.requests) == 1


@pytest.mark.parametrize("case", ["invalid-json", "duplicate-key", "oversized"], ids=["json", "duplicate", "size"])
def test_unsafe_json_rejected_without_reflecting_data(identity_adapter, identity_server, case):
    if case == "invalid-json":
        body = b"sensitive-error-unparseable"
    elif case == "duplicate-key":
        body = b'{"kind":"youtube#channelListResponse","kind":"sensitive-error"}'
    else:
        body = b"x" * 65537
    identity_server.queue(IdentityResponse(body=body))
    bundle = synthetic_identity_bundle()
    identity_adapter.register_synthetic_grant("youtube:1", bundle)
    with pytest.raises(IdentityError) as error:
        identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_ONE)
    assert "sensitive-error" not in str(error.value)
    assert identity_adapter.readiness("youtube:1") == "BLOCKED"


def test_expired_receipt_and_token_block_readiness(identity_adapter, identity_server):
    now = datetime.now(UTC)
    receipt, bundle = verify(identity_adapter, now=now)
    future = bundle.expires_at + timedelta(seconds=1)
    assert identity_adapter.readiness("youtube:1", now=future) == "BLOCKED"
    with pytest.raises(IdentityError) as error:
        receipt.digest("youtube:1", now=future)
    assert error.value.code == "expired"
    with pytest.raises(IdentityError):
        identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_ONE, now=future)
    assert len(identity_server.requests) == 1


@pytest.mark.parametrize("url", [
    "http://localhost:12345", "https://127.0.0.1:12345", "http://127.0.0.1:8765",
    "http://192.168.1.1:12345", "http://127.0.0.1:12345/secret", "http://127.0.0.1:12345?x=1",
    "http://u:p@127.0.0.1:12345", "http://127.0.0.1:12345#fragment", "http://[::1]:12345",
])
def test_synthetic_transport_rejects_unpinned_targets(url):
    with pytest.raises(IdentityError):
        SyntheticLoopbackIdentityTransport(url)


@pytest.mark.parametrize("mutation", ["access", "refresh", "missing-refresh", "client"])
def test_real_format_credentials_cannot_enter_synthetic_transport(identity_server, mutation):
    adapter = SyntheticYouTubeIdentityAdapter(
        SyntheticLoopbackIdentityTransport(identity_server.base_url), client_id=CLIENT,
    )
    bundle = synthetic_identity_bundle()
    if mutation == "client":
        with pytest.raises(OAuthBlocked):
            SyntheticYouTubeIdentityAdapter(adapter.transport, client_id="realformat.apps.googleusercontent.com")
    else:
        if mutation == "access":
            bundle.access_token = SecretStr("non-synthetic-test-token")
        elif mutation == "refresh":
            bundle.refresh_token = SecretStr("non-synthetic-test-refresh")
        else:
            bundle.refresh_token = None
        with pytest.raises(OAuthBlocked):
            adapter.register_synthetic_grant("youtube:1", bundle)
    assert identity_server.requests == []


def test_unregistered_nf_grant_cannot_lookup(identity_adapter, identity_server):
    with pytest.raises(IdentityError) as error:
        identity_adapter.lookup("youtube:1", synthetic_identity_bundle(), expected_channel=CHANNEL_ONE)
    assert error.value.code == "account_mismatch"
    assert identity_server.requests == []


def test_foreign_account_grant_cannot_change_healthy_identity(identity_adapter, identity_server):
    first, first_bundle = verify(identity_adapter)
    second_bundle = synthetic_identity_bundle("two")
    identity_server.queue(IdentityResponse(payload=synthetic_identity_payload(CHANNEL_TWO)))
    second, _ = verify(identity_adapter, second_bundle, key="youtube:2", channel=CHANNEL_TWO)
    with pytest.raises(IdentityError):
        identity_adapter.lookup("youtube:1", second_bundle, expected_channel=CHANNEL_ONE)
    reduced_foreign = second_bundle.model_copy(update={"scopes": (YOUTUBE_UPLOAD_SCOPE,)})
    with pytest.raises(IdentityError):
        identity_adapter.lookup("youtube:1", reduced_foreign, expected_channel=CHANNEL_ONE)
    first.validate_bundle("youtube:1", first_bundle)
    second.validate_bundle("youtube:2", second_bundle)
    assert identity_adapter.readiness("youtube:1") == "SYNTHETIC_VERIFIED"
    assert identity_adapter.readiness("youtube:2") == "SYNTHETIC_VERIFIED"
    assert len(identity_server.requests) == 2


def test_concurrent_lookup_does_not_issue_duplicate_requests(identity_adapter, identity_server):
    bundle = synthetic_identity_bundle()
    identity_adapter.register_synthetic_grant("youtube:1", bundle)
    identity_server.queue(IdentityResponse(delay=0.2))
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(identity_adapter.lookup, "youtube:1", bundle, expected_channel=CHANNEL_ONE)
        assert identity_server.received.wait(timeout=1)
        assert identity_adapter.readiness("youtube:1") == "BLOCKED"
        with pytest.raises(IdentityError) as error:
            identity_adapter.lookup("youtube:1", bundle, expected_channel=CHANNEL_ONE)
        assert error.value.code == "reused"
        pending.result(timeout=2).validate_bundle("youtube:1", bundle)
    assert len(identity_server.requests) == 1


def test_synthetic_adapter_rejects_substituted_transport(identity_adapter, identity_server):
    identity_adapter.transport = YouTubeHTTPSIdentityTransport()
    with pytest.raises(OAuthBlocked):
        identity_adapter.lookup("youtube:1", synthetic_identity_bundle(), expected_channel=CHANNEL_ONE)
    assert identity_server.requests == []


def test_scope_reduction_during_recheck_invalidates_old_receipt(identity_adapter, identity_server):
    receipt, bundle = verify(identity_adapter)
    reduced = bundle.model_copy(update={"scopes": (YOUTUBE_UPLOAD_SCOPE,)})
    with pytest.raises(IdentityError) as error:
        identity_adapter.lookup("youtube:1", reduced, expected_channel=CHANNEL_ONE)
    assert error.value.code == "scope_mismatch"
    assert identity_adapter.readiness("youtube:1") == "BLOCKED"
    with pytest.raises(IdentityError):
        receipt.digest("youtube:1")
    assert len(identity_server.requests) == 1
