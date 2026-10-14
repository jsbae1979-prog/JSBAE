"""Pinned YouTube channel identity lookup and a separate synthetic test boundary.

``channels.list(mine=true)`` cannot use the upload-only grant. The proposed
identity grant explicitly includes ``youtube.readonly``; no adapter adds scopes
to a caller's grant or treats a token exchange as verified channel identity.
All production lookup entry points remain blocked before network access.
The returned channel ID does not identify a Google email address or OIDC subject.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import secrets
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from pydantic import SecretStr

from newsflow.publishing.auth import TokenBundle

from .activation import require_production_activation
from .contracts import YOUTUBE_UPLOAD_SCOPE, OAuthBlocked, account_key_valid
from .session import checked_time

YOUTUBE_IDENTITY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
IDENTITY_LINK_SCOPES = (YOUTUBE_UPLOAD_SCOPE, YOUTUBE_IDENTITY_SCOPE)
YOUTUBE_CHANNELS_ENDPOINT = "https://youtube.googleapis.com/youtube/v3/channels"
_CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
_CLIENT = re.compile(r"[A-Za-z0-9_-]{5,200}\.apps\.googleusercontent\.com\Z")
_SYNTHETIC_ACCESS = re.compile(r"nf-synthetic-access-[A-Za-z0-9_-]{1,200}\Z")
_SYNTHETIC_REFRESH = re.compile(r"nf-synthetic-refresh-[A-Za-z0-9_-]{1,200}\Z")
_MAX_BODY = 65_536
_RECEIPT_KEY = secrets.token_bytes(32)
_RECEIPT_SEAL = object()
_RECEIPT_LOCK = Lock()
_REVOKED_RECEIPTS: set[str] = set()
_ERRORS = {
    "blocked": "실제 계정 조회는 production activation 승인 전까지 차단됩니다.",
    "account_mismatch": "조회 대상 계정과 인증정보의 계정 바인딩이 일치하지 않습니다.",
    "identity_mismatch": "확인한 채널과 선택한 채널이 일치하지 않습니다.",
    "identity_unverified": "채널 identity를 확인하지 못했습니다. 연결 준비 상태는 차단됩니다.",
    "ambiguous_identity": "한 개의 채널 identity를 안전하게 확정하지 못했습니다.",
    "scope_mismatch": "채널 확인에 필요한 최소 권한이 승인한 범위와 일치하지 않습니다.",
    "permission_denied": "채널 조회 권한이 거부되었습니다. 계정 연결 준비는 차단됩니다.",
    "revoked": "인증정보가 회수되었거나 유효하지 않습니다. 새 인증 준비가 필요합니다.",
    "expired": "인증정보 또는 identity 검증 결과가 만료되었습니다.",
    "response_invalid": "채널 조회 응답을 안전하게 검증하지 못했습니다.",
    "outcome_unknown": "채널 조회 결과를 확인할 수 없습니다. 자동 연결이나 재시도는 차단됩니다.",
    "transport_invalid": "허용된 채널 조회 전송 경계를 확인하지 못했습니다.",
    "reused": "이 인증정보의 조회 결과를 다시 사용할 수 없습니다.",
}


class IdentityError(Exception):
    """Fixed messages only: no server body, URL, token or subject is reflected."""

    def __init__(self, code: str, *, outcome_unknown: bool = False) -> None:
        self.code = code if code in _ERRORS else "identity_unverified"
        self.outcome_unknown = outcome_unknown or self.code == "outcome_unknown"
        super().__init__(_ERRORS[self.code])


def _account(value: str) -> str:
    if not account_key_valid(value) or not value.startswith("youtube:"):
        raise IdentityError("account_mismatch")
    return value


def _client(value: str, *, synthetic: bool) -> str:
    if not isinstance(value, str) or not _CLIENT.fullmatch(value):
        raise IdentityError("account_mismatch")
    if synthetic and not value.startswith("nf-synthetic-"):
        raise OAuthBlocked()
    return value


def _scope_set(scopes: tuple[str, ...]) -> None:
    if (
        not isinstance(scopes, tuple) or len(scopes) != len(IDENTITY_LINK_SCOPES)
        or any(not isinstance(scope, str) for scope in scopes)
        or frozenset(scopes) != frozenset(IDENTITY_LINK_SCOPES)
    ):
        raise IdentityError("scope_mismatch")


def grant_fingerprint(bundle: TokenBundle) -> str:
    """Hash the whole grant, including its refresh token, expiry and scopes."""
    try:
        if type(bundle) is not TokenBundle:
            raise TypeError
        values = [bundle.access_token.get_secret_value(),
                  bundle.refresh_token.get_secret_value() if bundle.refresh_token else None,
                  checked_time(bundle.expires_at).isoformat(), list(bundle.scopes)]
        return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    except Exception:  # noqa: BLE001 - do not relay malformed token details
        raise IdentityError("response_invalid") from None


def _bundle(bundle: TokenBundle, *, synthetic: bool, now: datetime | None = None) -> str:
    fingerprint = grant_fingerprint(bundle)
    _scope_set(bundle.scopes)
    if checked_time(bundle.expires_at) <= checked_time(now):
        raise IdentityError("expired")
    if synthetic and (
        not _SYNTHETIC_ACCESS.fullmatch(bundle.access_token.get_secret_value())
        or bundle.refresh_token is None
        or not _SYNTHETIC_REFRESH.fullmatch(bundle.refresh_token.get_secret_value())
    ):
        raise OAuthBlocked()
    return fingerprint


def _receipt_payload(receipt: VerifiedIdentity) -> bytes:
    return json.dumps([
        receipt.account_key, receipt.client_id, receipt.channel_id,
        list(receipt.scopes), receipt.grant_fingerprint,
        checked_time(receipt.expires_at).isoformat(), checked_time(receipt.verified_at).isoformat(),
        receipt.synthetic, receipt._nonce,
    ], separators=(",", ":")).encode()


@dataclass(frozen=True)
class VerifiedIdentity:
    """Process-local synthetic receipt, never a production authorization.

    The HMAC detects field substitution through ``dataclasses.replace``. Restart
    requires a new identity lookup; only the stable account/client/channel digest
    belongs in durable metadata. The receipt never contains an access token.
    """

    account_key: str
    client_id: str
    channel_id: str
    scopes: tuple[str, ...]
    grant_fingerprint: str = field(repr=False)
    expires_at: datetime
    verified_at: datetime
    synthetic: bool
    _nonce: str = field(default="", repr=False)
    _signature: bytes = field(default=b"", repr=False)
    _seal: object = field(default=None, repr=False, compare=False)

    def _validate(self, account_key: str, *, now: datetime | None = None) -> None:
        try:
            _account(account_key)
            _scope_set(self.scopes)
            _client(self.client_id, synthetic=True)
            if (
                self._seal is not _RECEIPT_SEAL or self.synthetic is not True
                or self.account_key != account_key or not _CHANNEL.fullmatch(self.channel_id)
                or not re.fullmatch(r"[a-f0-9]{64}", self.grant_fingerprint)
                or not re.fullmatch(r"[a-f0-9]{32}", self._nonce)
                or not isinstance(self._signature, bytes)
                or not hmac.compare_digest(
                    self._signature, hmac.digest(_RECEIPT_KEY, _receipt_payload(self), "sha256"),
                )
            ):
                raise IdentityError("identity_unverified")
            with _RECEIPT_LOCK:
                if self._nonce in _REVOKED_RECEIPTS:
                    raise IdentityError("identity_unverified")
            instant = checked_time(now)
            if checked_time(self.expires_at) <= instant or checked_time(self.verified_at) > instant:
                raise IdentityError("expired")
        except IdentityError:
            raise
        except Exception:  # noqa: BLE001 - malformed receipts fail without field disclosure
            raise IdentityError("identity_unverified") from None

    def digest(self, account_key: str, *, now: datetime | None = None) -> str:
        self._validate(account_key, now=now)
        value = ["youtube", self.account_key, self.client_id, self.channel_id, list(IDENTITY_LINK_SCOPES)]
        return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()

    def validate_bundle(
        self, account_key: str, bundle: TokenBundle, *, now: datetime | None = None,
    ) -> None:
        self._validate(account_key, now=now)
        fingerprint = _bundle(bundle, synthetic=True, now=now)
        if not hmac.compare_digest(self.grant_fingerprint, fingerprint):
            raise IdentityError("account_mismatch")


def _issue_receipt(
    account_key: str, client_id: str, channel_id: str, bundle: TokenBundle, *, now: datetime | None,
) -> VerifiedIdentity:
    values = {
        "account_key": account_key, "client_id": client_id, "channel_id": channel_id,
        "scopes": IDENTITY_LINK_SCOPES, "grant_fingerprint": grant_fingerprint(bundle),
        "expires_at": checked_time(bundle.expires_at), "verified_at": checked_time(now),
        "synthetic": True, "_nonce": secrets.token_hex(16), "_seal": _RECEIPT_SEAL,
    }
    unsigned = VerifiedIdentity(**values)
    return VerifiedIdentity(**values, _signature=hmac.digest(_RECEIPT_KEY, _receipt_payload(unsigned), "sha256"))


@dataclass(frozen=True)
class IdentityHTTPResponse:
    status: int
    body: bytes = field(repr=False)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.05 <= value <= 30:
        raise IdentityError("transport_invalid")
    return float(value)


class YouTubeHTTPSIdentityTransport:
    """Official fixed endpoint, strict TLS, no redirects and hard activation gate."""

    mode = "production"

    def __init__(self, *, timeout_seconds: float = 10) -> None:
        self.timeout_seconds = _timeout(timeout_seconds)

    def get_channels(self, access_token: SecretStr) -> IdentityHTTPResponse:
        require_production_activation()
        if not isinstance(access_token, SecretStr):
            raise IdentityError("transport_invalid")
        endpoint = YOUTUBE_CHANNELS_ENDPOINT + "?" + urlencode({"part": "id", "mine": "true"})
        request = Request(endpoint, method="GET", headers={
            "Accept": "application/json", "Authorization": "Bearer " + access_token.get_secret_value(),
        })
        opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                body, status = response.read(_MAX_BODY + 1), response.status
            if len(body) > _MAX_BODY:
                raise IdentityError("response_invalid")
            return IdentityHTTPResponse(status, body)
        except HTTPError as exc:
            try:
                body, status = exc.read(_MAX_BODY + 1), exc.code
            finally:
                exc.close()
            if len(body) > _MAX_BODY:
                raise IdentityError("response_invalid") from None
            return IdentityHTTPResponse(status, body)
        except (URLError, OSError, TimeoutError, http.client.HTTPException):
            raise IdentityError("outcome_unknown", outcome_unknown=True) from None


class SyntheticLoopbackIdentityTransport:
    """NF-only bearer tokens sent solely to a numeric loopback HTTP fixture."""

    mode = "synthetic"

    def __init__(self, base_url: str, *, timeout_seconds: float = 2) -> None:
        try:
            parsed = urlsplit(base_url)
            if (
                parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.port is None or not 1024 <= parsed.port <= 65535 or parsed.port == 8765
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or base_url.rstrip("/") != f"http://127.0.0.1:{parsed.port}"
            ):
                raise ValueError
            self.port, self.timeout_seconds = parsed.port, _timeout(timeout_seconds)
        except Exception:  # noqa: BLE001 - an untrusted address must never leave this boundary
            raise IdentityError("transport_invalid") from None

    def get_channels(self, access_token: SecretStr) -> IdentityHTTPResponse:
        if not isinstance(access_token, SecretStr) or not _SYNTHETIC_ACCESS.fullmatch(
            access_token.get_secret_value(),
        ):
            raise OAuthBlocked()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout_seconds)
        try:
            connection.request("GET", "/youtube/v3/channels?part=id&mine=true", headers={
                "Accept": "application/json", "Authorization": "Bearer " + access_token.get_secret_value(),
            })
            response = connection.getresponse()
            body, status = response.read(_MAX_BODY + 1), response.status
            if len(body) > _MAX_BODY:
                raise IdentityError("response_invalid")
            return IdentityHTTPResponse(status, body)
        except (OSError, TimeoutError, http.client.HTTPException):
            raise IdentityError("outcome_unknown", outcome_unknown=True) from None
        finally:
            connection.close()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise IdentityError("response_invalid")
        result[key] = value
    return result


def _channel_response(response: IdentityHTTPResponse) -> str:
    if type(response) is not IdentityHTTPResponse or not isinstance(response.body, bytes):
        raise IdentityError("response_invalid")
    if response.status == 401:
        raise IdentityError("revoked")
    if response.status == 403:
        raise IdentityError("permission_denied")
    if response.status >= 500 or response.status == 429:
        raise IdentityError("outcome_unknown", outcome_unknown=True)
    if response.status != 200:
        raise IdentityError("identity_unverified")
    try:
        if len(response.body) > _MAX_BODY:
            raise ValueError
        data = json.loads(response.body, object_pairs_hook=_unique)
        if (
            not isinstance(data, dict) or "error" in data or "nextPageToken" in data
            or data.get("kind") != "youtube#channelListResponse"
        ):
            raise ValueError
        items = data.get("items")
        if not isinstance(items, list) or len(items) != 1:
            raise IdentityError("ambiguous_identity")
        page = data.get("pageInfo")
        if page is not None and (
            not isinstance(page, dict) or type(page.get("totalResults")) is not int
            or page["totalResults"] != 1
        ):
            raise IdentityError("ambiguous_identity")
        item = items[0]
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not _CHANNEL.fullmatch(item["id"]):
            raise ValueError
        if item.get("kind") not in {None, "youtube#channel"}:
            raise ValueError
        return item["id"]
    except IdentityError:
        raise
    except Exception:  # noqa: BLE001 - provider response and JSON diagnostics may contain sensitive data
        raise IdentityError("response_invalid") from None


class YouTubeIdentityAdapter:
    """Production identity facade. Neither flags nor injected fixtures activate it."""

    mode = "OFFLINE/BLOCKED"

    def __init__(self, client_id: str, *, timeout_seconds: float = 10) -> None:
        self.client_id = _client(client_id, synthetic=False)
        self.transport = YouTubeHTTPSIdentityTransport(timeout_seconds=timeout_seconds)

    def lookup(
        self, account_key: str, bundle: TokenBundle, *, expected_channel: str,
        now: datetime | None = None,
    ) -> VerifiedIdentity:
        require_production_activation()
        _account(account_key)
        _bundle(bundle, synthetic=False, now=now)
        channel = _channel_response(self.transport.get_channels(bundle.access_token))
        if channel != expected_channel:
            raise IdentityError("identity_mismatch")
        # Production receipts require a future reviewed durable trust boundary.
        # Merely replacing the activation function cannot issue a synthetic receipt.
        raise OAuthBlocked()


class SyntheticYouTubeIdentityAdapter:
    """Explicit local fixture grant registration and channel verification.

    A successful recheck invalidates the previous receipt before the GET. Any
    failed, expired, ambiguous or uncertain lookup leaves readiness blocked.
    Automatic retries are never attempted; an uncertain grant is quarantined.
    """

    mode = "SYNTHETIC_IDENTITY"

    def __init__(self, transport: SyntheticLoopbackIdentityTransport, *, client_id: str) -> None:
        if type(transport) is not SyntheticLoopbackIdentityTransport:
            raise OAuthBlocked()
        self.transport, self.client_id = transport, _client(client_id, synthetic=True)
        self._grants: dict[str, str] = {}
        self._access: dict[str, tuple[str, str]] = {}
        self._channels: dict[str, str] = {}
        self._owners: dict[str, str] = {}
        self._receipts: dict[str, VerifiedIdentity] = {}
        self._unknown: set[str] = set()
        self._invalid: set[str] = set()
        self._pending: set[str] = set()
        self._requests = 0
        self._lock = Lock()

    def register_synthetic_grant(
        self, account_key: str, bundle: TokenBundle, *, now: datetime | None = None,
    ) -> None:
        _account(account_key)
        fingerprint = _bundle(bundle, synthetic=True, now=now)
        access_digest = hashlib.sha256(bundle.access_token.get_secret_value().encode()).hexdigest()
        with self._lock:
            prior = self._access.get(access_digest)
            if prior is not None and prior != (account_key, fingerprint):
                raise IdentityError("account_mismatch")
            if fingerprint in self._unknown or fingerprint in self._invalid:
                raise IdentityError("reused")
            self._access[access_digest] = (account_key, fingerprint)
            self._grants[fingerprint] = account_key

    def _invalidate(self, account_key: str) -> None:
        prior = self._receipts.pop(account_key, None)
        if prior is not None:
            with _RECEIPT_LOCK:
                _REVOKED_RECEIPTS.add(prior._nonce)

    def invalidate_grant(self, account_key: str, bundle: TokenBundle) -> None:
        """Quarantine a known NF grant before an explicit refresh attempt.

        Access expiry does not prevent invalidation. A historical grant unknown
        to this process has no receipt to revoke; it cannot clear an unrelated
        current receipt. Account and whole-grant checks still apply before any
        mutation, and no identity request or provider operation occurs here.
        """
        _account(account_key)
        fingerprint = grant_fingerprint(bundle)
        _scope_set(bundle.scopes)
        if (
            not _SYNTHETIC_ACCESS.fullmatch(bundle.access_token.get_secret_value())
            or bundle.refresh_token is None
            or not _SYNTHETIC_REFRESH.fullmatch(bundle.refresh_token.get_secret_value())
        ):
            raise OAuthBlocked()
        access_digest = hashlib.sha256(bundle.access_token.get_secret_value().encode()).hexdigest()
        with self._lock:
            owner = self._grants.get(fingerprint)
            access_owner = self._access.get(access_digest)
            if (
                owner is not None and owner != account_key
                or access_owner is not None and access_owner != (account_key, fingerprint)
            ):
                raise IdentityError("account_mismatch")
            if owner is None:
                return
            self._invalid.add(fingerprint)
            prior = self._receipts.get(account_key)
            if prior is not None and prior.grant_fingerprint == fingerprint:
                self._invalidate(account_key)

    def lookup(
        self, account_key: str, bundle: TokenBundle, *, expected_channel: str,
        now: datetime | None = None,
    ) -> VerifiedIdentity:
        _account(account_key)
        if type(self.transport) is not SyntheticLoopbackIdentityTransport:
            raise OAuthBlocked()
        try:
            fingerprint = _bundle(bundle, synthetic=True, now=now)
        except (IdentityError, OAuthBlocked):
            # Uncorrelated foreign or malformed input cannot clear another
            # account's healthy receipt. A known access grant whose permissions
            # or expiry changed does invalidate that account's readiness.
            try:
                access_digest = hashlib.sha256(bundle.access_token.get_secret_value().encode()).hexdigest()
            except Exception:  # noqa: BLE001 - invalid input must not reveal token/parser details
                access_digest = ""
            with self._lock:
                owner = self._access.get(access_digest)
                if owner is not None and owner[0] == account_key:
                    self._invalidate(account_key)
            raise
        if not isinstance(expected_channel, str) or not _CHANNEL.fullmatch(expected_channel):
            raise IdentityError("identity_mismatch")
        with self._lock:
            if fingerprint in self._unknown:
                raise IdentityError("outcome_unknown", outcome_unknown=True)
            if fingerprint in self._invalid:
                raise IdentityError("reused")
            if self._grants.get(fingerprint) != account_key:
                raise IdentityError("account_mismatch")
            if account_key in self._pending:
                raise IdentityError("reused")
            self._invalidate(account_key)
            self._pending.add(account_key)
            self._requests += 1
        try:
            channel = _channel_response(self.transport.get_channels(bundle.access_token))
            if channel != expected_channel:
                raise IdentityError("identity_mismatch")
            with self._lock:
                if fingerprint in self._unknown or fingerprint in self._invalid:
                    raise IdentityError("reused")
                prior_channel = self._channels.get(account_key)
                if prior_channel is not None and prior_channel != channel:
                    raise IdentityError("identity_mismatch")
                if self._owners.get(channel, account_key) != account_key:
                    raise IdentityError("account_mismatch")
                receipt = _issue_receipt(account_key, self.client_id, channel, bundle, now=now)
                self._channels[account_key] = channel
                self._owners[channel] = account_key
                self._receipts[account_key] = receipt
                return receipt
        except IdentityError as exc:
            with self._lock:
                (self._unknown if exc.outcome_unknown else self._invalid).add(fingerprint)
            raise
        finally:
            with self._lock:
                self._pending.discard(account_key)

    def readiness(self, account_key: str, *, now: datetime | None = None) -> str:
        _account(account_key)
        with self._lock:
            receipt = self._receipts.get(account_key)
        if receipt is not None:
            try:
                receipt._validate(account_key, now=now)
                return "SYNTHETIC_VERIFIED"
            except IdentityError:
                pass
        return "BLOCKED"

    def evidence(self) -> dict[str, object]:
        with self._lock:
            return {
                "mode": self.mode, "synthetic_identity_requests": self._requests,
                "real_identity_requests": 0, "real_oauth_requests": 0, "real_sns_upload_requests": 0,
                "production_readiness": "BLOCKED",
            }
