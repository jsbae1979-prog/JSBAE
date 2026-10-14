"""A full synthetic loopback OAuth flow, separate from blocked production entry.

This module never opens a browser, contacts Google, or enables a production
backend. The explicit HTTP fixture client accepts NF credentials and sealed
callbacks only. It connects the callback, token, identity and durable lifecycle
boundaries without treating synthetic results as a real account connection.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from threading import Lock
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import SecretStr

from newsflow.publishing.auth import TokenBundle

from .activation import require_production_activation
from .callback import CallbackLaunch, CallbackResult
from .contracts import OAuthBlocked, account_key_valid
from .identity import (
    IDENTITY_LINK_SCOPES,
    IdentityError,
    SyntheticYouTubeIdentityAdapter,
    VerifiedIdentity,
    grant_fingerprint,
)
from .lifecycle import SyntheticOAuthCredentialLifecycle
from .production import ProtocolError, _json_object
from .session import checked_time

_ACCESS = re.compile(r"nf-synthetic-access-[A-Za-z0-9_-]{1,200}\Z")
_REFRESH = re.compile(r"nf-synthetic-refresh-[A-Za-z0-9_-]{1,200}\Z")
_CODE = re.compile(r"nf-synthetic-code-[A-Za-z0-9_-]{1,200}\Z")
_CLIENT = re.compile(r"nf-synthetic-[A-Za-z0-9_-]{1,150}\.apps\.googleusercontent\.com\Z")
_CLIENT_SECRET = re.compile(r"nf-synthetic-client-[A-Za-z0-9_-]{1,200}\Z")
_BODY_LIMIT = 65_536


def _account(value: str) -> None:
    if not account_key_valid(value) or not value.startswith("youtube:"):
        raise ProtocolError("account_mismatch")


def _origin(value: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.port is None or not 1024 <= parsed.port <= 65535 or parsed.port == 8765
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or value.rstrip("/") != f"http://127.0.0.1:{parsed.port}"
        ):
            raise ValueError
        return f"http://127.0.0.1:{parsed.port}", parsed.port
    except Exception:  # noqa: BLE001 - reject untrusted targets without reflecting addresses
        raise ProtocolError("transport_invalid") from None


def _callback_uri(value: str) -> int:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.port is None or not 1024 <= parsed.port <= 65535 or parsed.port == 8765
            or parsed.username is not None or parsed.password is not None
            or parsed.path != "/oauth/callback" or parsed.query or parsed.fragment
            or value != f"http://127.0.0.1:{parsed.port}/oauth/callback"
        ):
            raise ValueError
        return parsed.port
    except Exception:  # noqa: BLE001 - no untrusted callback URL is reflected
        raise ProtocolError("redirect_mismatch") from None


def _scopes(value: tuple[str, ...]) -> None:
    if (
        not isinstance(value, tuple) or len(value) != len(IDENTITY_LINK_SCOPES)
        or any(not isinstance(scope, str) for scope in value)
        or frozenset(value) != frozenset(IDENTITY_LINK_SCOPES)
    ):
        raise ProtocolError("scope_mismatch")


class ProductionOAuthFlow:
    """The production factory and all side effects remain inaccessible."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory

    @staticmethod
    def _deny() -> None:
        require_production_activation()
        # Replacing the shared gate alone still cannot construct a real pipeline.
        raise OAuthBlocked()

    def prepare(self, *args: Any, **kwargs: Any) -> None:
        self._deny()

    def complete(self, *args: Any, **kwargs: Any) -> None:
        self._deny()

    def refresh(self, *args: Any, **kwargs: Any) -> None:
        self._deny()

    def revoke(self, *args: Any, **kwargs: Any) -> None:
        self._deny()


class SyntheticTokenExchangeClient:
    """Pinned local HTTP fixture client with one-use codes and bound NF grants."""

    mode = "SYNTHETIC_PROTOCOL"

    def __init__(
        self, base_url: str, *, client_id: str, client_secret: SecretStr, timeout_seconds: float = 2,
    ) -> None:
        self.base_url, self.port = _origin(base_url)
        if (
            not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id)
            or not isinstance(client_secret, SecretStr)
            or not _CLIENT_SECRET.fullmatch(client_secret.get_secret_value())
        ):
            raise OAuthBlocked()
        if (
            isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not 0.05 <= timeout_seconds <= 30
        ):
            raise ProtocolError("transport_invalid")
        self.client_id, self.client_secret = client_id, client_secret
        self.timeout_seconds = float(timeout_seconds)
        self._used_codes: set[str] = set()
        self._used_sessions: set[str] = set()
        self._issued: dict[str, str] = {}
        self._access_owners: dict[str, str] = {}
        self._refresh_attempted: set[str] = set()
        self._unusable: set[str] = set()
        self._counts = {"authorization": 0, "callback": 0, "token": 0, "refresh": 0, "revoke": 0}
        self._lock = Lock()

    def authorization_url(self, launch: CallbackLaunch) -> SecretStr:
        if type(launch) is not CallbackLaunch or launch.request.mode != "SYNTHETIC_CALLBACK":
            raise OAuthBlocked()
        request = launch.request
        _account(request.account_key)
        _scopes(request.scopes)
        _callback_uri(launch.redirect_uri)
        if (
            request.redirect_uri != launch.redirect_uri or request.code_challenge_method != "S256"
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", request.code_challenge)
            or not isinstance(request.state, SecretStr)
            or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", request.state.get_secret_value())
            or checked_time(request.expires_at) <= checked_time()
        ):
            raise ProtocolError("callback_invalid")
        return SecretStr(self.base_url + "/authorize?" + urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": launch.redirect_uri,
            "scope": " ".join(request.scopes), "state": request.state.get_secret_value(),
            "code_challenge": request.code_challenge, "code_challenge_method": "S256", "access_type": "offline",
        }))

    def _request(
        self, method: str, path: str, *, form: Mapping[str, str] | None = None,
    ) -> tuple[int, bytes, str | None]:
        # Host is a literal numeric loopback. No proxy, DNS, redirects or browser.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout_seconds)
        body = urlencode(form).encode("ascii") if form is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            data, location = response.read(_BODY_LIMIT + 1), response.getheader("Location")
            if len(data) > _BODY_LIMIT:
                raise ProtocolError("response_invalid", outcome_unknown=method == "POST")
            return response.status, data, location
        except (OSError, TimeoutError, http.client.HTTPException):
            raise ProtocolError("outcome_unknown", outcome_unknown=True) from None
        finally:
            connection.close()

    def dispatch_authorization(self, launch: CallbackLaunch) -> int:
        """Exercise a local fake redirect without opening a system browser."""
        target = urlsplit(self.authorization_url(launch).get_secret_value())
        with self._lock:
            self._counts["authorization"] += 1
        status, _body, location = self._request("GET", target.path + "?" + target.query)
        if status != 302 or not isinstance(location, str) or len(location) > 4096:
            raise ProtocolError("provider_error")
        try:
            redirect = urlsplit(location)
            canonical = f"{redirect.scheme}://{redirect.netloc}{redirect.path}"
            if canonical != launch.redirect_uri or redirect.fragment:
                raise ValueError
            port = _callback_uri(canonical)
            values = parse_qsl(redirect.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
            if len(dict(values)) != len(values) or set(dict(values)) not in ({"state", "code"}, {"state", "error"}):
                raise ValueError
            parameters = dict(values)
            if parameters["state"] != launch.request.state.get_secret_value():
                raise ValueError
            if "code" in parameters and not _CODE.fullmatch(parameters["code"]):
                raise ValueError
            if "error" in parameters and parameters["error"] != "access_denied":
                raise ValueError
        except Exception:  # noqa: BLE001 - no arbitrary redirect or response details leave this boundary
            raise ProtocolError("redirect_mismatch") from None
        callback = http.client.HTTPConnection("127.0.0.1", port, timeout=self.timeout_seconds)
        try:
            with self._lock:
                self._counts["callback"] += 1
            callback.request("GET", redirect.path + "?" + redirect.query)
            response = callback.getresponse()
            response.read(_BODY_LIMIT + 1)
            return response.status
        except (OSError, TimeoutError, http.client.HTTPException):
            raise ProtocolError("outcome_unknown", outcome_unknown=True) from None
        finally:
            callback.close()

    @staticmethod
    def _response(
        status: int, body: bytes, *, previous: TokenBundle | None = None,
    ) -> TokenBundle:
        if status >= 500 or status == 429:
            raise ProtocolError("outcome_unknown", outcome_unknown=True)
        if status != 200:
            raise ProtocolError("provider_error")
        data = _json_object(body)
        if set(data) - {"access_token", "refresh_token", "scope", "expires_in", "token_type"}:
            raise ProtocolError("response_invalid", outcome_unknown=True)
        access, refresh = data.get("access_token"), data.get("refresh_token")
        if refresh is None and previous is not None and previous.refresh_token is not None:
            refresh = previous.refresh_token.get_secret_value()
        lifetime, scope = data.get("expires_in"), data.get("scope")
        if (
            not isinstance(access, str) or not _ACCESS.fullmatch(access)
            or not isinstance(refresh, str) or not _REFRESH.fullmatch(refresh)
            or data.get("token_type") != "Bearer"
            or type(lifetime) is not int or not 1 <= lifetime <= 86_400
        ):
            raise ProtocolError("response_invalid", outcome_unknown=True)
        granted = previous.scopes if scope is None and previous is not None else tuple(scope.split()) if isinstance(scope, str) else ()
        try:
            _scopes(granted)
        except ProtocolError:
            raise ProtocolError("scope_mismatch", outcome_unknown=True) from None
        return TokenBundle(access_token=SecretStr(access), refresh_token=SecretStr(refresh),
                           expires_at=checked_time() + timedelta(seconds=lifetime), scopes=IDENTITY_LINK_SCOPES)

    def _register(self, account_key: str, bundle: TokenBundle) -> None:
        fingerprint = grant_fingerprint(bundle)
        access_digest = hashlib.sha256(bundle.access_token.get_secret_value().encode()).hexdigest()
        with self._lock:
            prior = self._access_owners.get(access_digest)
            if prior is not None and prior != account_key:
                raise ProtocolError("account_mismatch")
            self._access_owners[access_digest] = account_key
            self._issued[fingerprint] = account_key

    def exchange(self, account_key: str, result: CallbackResult) -> TokenBundle:
        _account(account_key)
        if type(result) is not CallbackResult:
            raise ProtocolError("callback_invalid")
        result.assert_valid(account_key)
        _callback_uri(result.redirect_uri)
        _scopes(result.scopes)
        code = result.code.get_secret_value()
        if not _CODE.fullmatch(code):
            raise OAuthBlocked()
        digest = hashlib.sha256(code.encode()).hexdigest()
        with self._lock:
            if digest in self._used_codes or result.session_id in self._used_sessions:
                raise ProtocolError("reused")
            self._used_codes.add(digest)
            self._used_sessions.add(result.session_id)
            self._counts["token"] += 1
        status, body, _location = self._request("POST", "/token", form={
            "client_id": self.client_id, "client_secret": self.client_secret.get_secret_value(),
            "grant_type": "authorization_code", "code": code, "code_verifier": result.verifier.get_secret_value(),
            "redirect_uri": result.redirect_uri,
        })
        bundle = self._response(status, body)
        self._register(account_key, bundle)
        return bundle

    def _bound(self, account_key: str, bundle: TokenBundle) -> str:
        _account(account_key)
        try:
            if (
                type(bundle) is not TokenBundle or not _ACCESS.fullmatch(bundle.access_token.get_secret_value())
                or bundle.refresh_token is None or not _REFRESH.fullmatch(bundle.refresh_token.get_secret_value())
            ):
                raise OAuthBlocked()
            _scopes(bundle.scopes)
            fingerprint = grant_fingerprint(bundle)
        except (ProtocolError, OAuthBlocked):
            raise
        except Exception:  # noqa: BLE001 - malformed grants do not expose fields
            raise ProtocolError("response_invalid") from None
        with self._lock:
            if self._issued.get(fingerprint) != account_key:
                raise ProtocolError("account_mismatch")
            if fingerprint in self._unusable:
                raise ProtocolError("outcome_unknown", outcome_unknown=True)
        return fingerprint

    def refresh(self, account_key: str, bundle: TokenBundle) -> TokenBundle:
        fingerprint = self._bound(account_key, bundle)
        with self._lock:
            if fingerprint in self._refresh_attempted:
                raise ProtocolError("reused")
            self._refresh_attempted.add(fingerprint)
            self._unusable.add(fingerprint)
            self._counts["refresh"] += 1
        status, body, _location = self._request("POST", "/token", form={
            "client_id": self.client_id, "client_secret": self.client_secret.get_secret_value(),
            "grant_type": "refresh_token", "refresh_token": bundle.refresh_token.get_secret_value(),
        })
        replacement = self._response(status, body, previous=bundle)
        self._register(account_key, replacement)
        return replacement

    def revoke(self, account_key: str, bundle: TokenBundle) -> None:
        fingerprint = self._bound(account_key, bundle)
        with self._lock:
            self._unusable.add(fingerprint)
            self._counts["revoke"] += 1
        status, _body, _location = self._request("POST", "/revoke", form={
            "token": bundle.refresh_token.get_secret_value(),
        })
        if status >= 500 or status == 429:
            raise ProtocolError("outcome_unknown", outcome_unknown=True)
        if status != 200:
            raise ProtocolError("provider_error")

    def evidence(self) -> dict[str, object]:
        with self._lock:
            return {
                "mode": self.mode, **{f"synthetic_{key}_requests": value for key, value in self._counts.items()},
                "real_oauth_requests": 0, "real_sns_upload_requests": 0,
            }


@dataclass(frozen=True)
class SyntheticConnectionResult:
    reference: str = field(repr=False)
    bundle: TokenBundle = field(repr=False)
    identity: VerifiedIdentity = field(repr=False)
    mode: str = "SYNTHETIC_ONLY"


class SyntheticOAuthFlow:
    """Explicit orchestration with no production adapter, browser or fallback."""

    def __init__(
        self, client: SyntheticTokenExchangeClient, identity: SyntheticYouTubeIdentityAdapter,
        lifecycle: SyntheticOAuthCredentialLifecycle,
    ) -> None:
        if (
            type(client) is not SyntheticTokenExchangeClient or type(identity) is not SyntheticYouTubeIdentityAdapter
            or type(lifecycle) is not SyntheticOAuthCredentialLifecycle or client.client_id != identity.client_id
        ):
            raise OAuthBlocked()
        self.client, self.identity, self.lifecycle = client, identity, lifecycle

    @staticmethod
    def _key(account_id: int) -> str:
        if type(account_id) is not int or not 1 <= account_id < 2**63:
            raise ProtocolError("account_mismatch")
        return f"youtube:{account_id}"

    def connect(
        self, account_id: int, callback: CallbackResult, *, expected_channel: str, expected_revision: int,
    ) -> SyntheticConnectionResult:
        key = self._key(account_id)
        bundle = self.client.exchange(key, callback)
        self.identity.register_synthetic_grant(key, bundle)
        receipt = self.identity.lookup(key, bundle, expected_channel=expected_channel)
        reference = self.lifecycle.store(account_id, receipt, bundle, expected_revision=expected_revision)
        return SyntheticConnectionResult(reference, bundle, receipt)

    def refresh(
        self, account_id: int, bundle: TokenBundle, identity: VerifiedIdentity, *,
        expected_channel: str, expected_revision: int,
    ) -> SyntheticConnectionResult:
        key = self._key(account_id)
        identity.validate_bundle(key, bundle)
        stored = self.lifecycle.load(account_id, identity)
        if not hmac.compare_digest(grant_fingerprint(stored), grant_fingerprint(bundle)):
            raise ProtocolError("account_mismatch")
        reservation = self.lifecycle.reserve(account_id, identity, operation="replace", expected_revision=expected_revision)
        try:
            self.identity.invalidate_grant(key, bundle)
            replacement = self.client.refresh(key, bundle)
            self.identity.register_synthetic_grant(key, replacement)
            receipt = self.identity.lookup(key, replacement, expected_channel=expected_channel)
            reference = self.lifecycle.complete(reservation, replacement, identity=receipt)
            return SyntheticConnectionResult(reference, replacement, receipt)
        except (ProtocolError, IdentityError) as error:
            if error.outcome_unknown:
                self.lifecycle.mark_unknown(reservation)
            else:
                self.lifecycle.mark_error(reservation)
            raise

    def refresh_for_revalidation(
        self, account_id: int, *, expected_channel: str, expected_revision: int,
    ) -> SyntheticConnectionResult:
        """Explicit expiry/restart refresh; historical trust never implies readiness.

        The durable candidate is bound to the configured client and expected
        channel before a provider request. A journal reservation consumes the
        current revision before HTTP, and only fresh identity can commit it.
        """
        key = self._key(account_id)
        historical = self.lifecycle.load_for_revalidation(account_id, expected_revision=expected_revision)
        historical.validate(account_id, expected_revision=expected_revision)
        if (
            not isinstance(expected_channel, str) or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", expected_channel)
            or not hmac.compare_digest(
                historical.channel_binding_digest,
                hashlib.sha256(("NewsFlowAI:channel-binding:" + self.client.client_id + ":" + expected_channel).encode()).hexdigest(),
            )
        ):
            raise ProtocolError("account_mismatch")
        reservation = self.lifecycle.reserve_for_revalidation(historical)
        try:
            self.identity.invalidate_grant(key, historical.bundle)
            # Only an authenticated, CAS-reserved durable grant can restore this
            # explicit synthetic client's process-local ownership registry.
            self.client._register(key, historical.bundle)
            replacement = self.client.refresh(key, historical.bundle)
            self.identity.register_synthetic_grant(key, replacement)
            receipt = self.identity.lookup(key, replacement, expected_channel=expected_channel)
            reference = self.lifecycle.complete(reservation, replacement, identity=receipt)
            return SyntheticConnectionResult(reference, replacement, receipt)
        except (ProtocolError, IdentityError) as error:
            if error.outcome_unknown:
                self.lifecycle.mark_unknown(reservation)
            else:
                self.lifecycle.mark_error(reservation)
            raise

    def revoke(
        self, account_id: int, bundle: TokenBundle, identity: VerifiedIdentity, *, expected_revision: int,
    ) -> None:
        key = self._key(account_id)
        identity.validate_bundle(key, bundle)
        stored = self.lifecycle.load(account_id, identity)
        if not hmac.compare_digest(grant_fingerprint(stored), grant_fingerprint(bundle)):
            raise ProtocolError("account_mismatch")
        reservation = self.lifecycle.reserve(account_id, identity, operation="revoke", expected_revision=expected_revision)
        try:
            self.client.revoke(key, bundle)
            self.lifecycle.complete(reservation, identity=identity)
            self.identity.invalidate_grant(key, bundle)
        except ProtocolError as error:
            if error.outcome_unknown:
                self.lifecycle.mark_unknown(reservation)
            else:
                self.lifecycle.mark_error(reservation)
            raise
