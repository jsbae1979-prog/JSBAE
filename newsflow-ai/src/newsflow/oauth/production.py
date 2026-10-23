"""Dormant Google desktop OAuth protocol and strictly synthetic loopback transport.

The production network/browser entry points require the source-controlled activation
boundary. Synthetic protocol tests use an explicitly local server and recognizable
fixture credentials; neither environment variables nor GUI input select production.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import ssl
import webbrowser
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from pydantic import SecretStr

from newsflow.publishing.auth import TokenBundle

from .activation import require_production_activation
from .contracts import FIXED_REDIRECT, YOUTUBE_UPLOAD_SCOPE, OAuthBlocked, OAuthError, account_key_valid
from .session import OAuthCallbackValidator, OAuthRequest, OAuthSessionStore, checked_time

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
_LEGACY_GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/auth"
_MAX_RESPONSE_BYTES = 65_536
_SCOPES = (YOUTUBE_UPLOAD_SCOPE,)
_ERRORS = {
    "config_invalid": "데스크톱 OAuth 클라이언트 설정을 안전하게 검증하지 못했습니다.",
    "response_invalid": "OAuth 응답 형식 또는 인증정보를 안전하게 검증하지 못했습니다.",
    "outcome_unknown": "OAuth 요청의 처리 결과를 확인할 수 없습니다. 자동 재시도하지 않습니다.",
    "rate_limited": "인증 요청 준비 횟수를 초과했습니다. 잠시 후 다시 준비하세요.",
    "identity_unverified": "이 토큰의 실제 플랫폼 계정 identity는 확인되지 않았습니다.",
    "identity_mismatch": "검증 대상 계정과 플랫폼 계정 identity가 일치하지 않습니다.",
    "transport_invalid": "허용된 OAuth 전송 경계를 확인하지 못했습니다.",
}


class ProtocolError(OAuthError):
    """Fixed messages only: no provider errors, request bodies or credentials."""

    def __init__(self, code: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(code)
        if code in _ERRORS:
            self.code = code
            self.args = (_ERRORS[code],)
        self.outcome_unknown = outcome_unknown or code == "outcome_unknown"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("response_invalid", outcome_unknown=True)
        result[key] = value
    return result


def _json_object(raw: str | bytes, *, configuration: bool = False) -> dict[str, object]:
    try:
        if not isinstance(raw, (str, bytes)) or len(raw) > (16_384 if configuration else _MAX_RESPONSE_BYTES):
            raise ValueError
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            raise TypeError
        return value
    except Exception:  # noqa: BLE001 - do not expose JSON content or parser diagnostics
        raise ProtocolError("config_invalid" if configuration else "response_invalid",
                            outcome_unknown=not configuration) from None


def _safe_string(value: object, *, maximum: int = 2048) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= maximum
        and all(ord(character) >= 33 and ord(character) != 127 for character in value)
    )


def _synthetic(value: str, kind: str) -> bool:
    return bool(re.fullmatch(r"nf-synthetic-" + kind + r"-[A-Za-z0-9_-]{1,200}", value))


@dataclass(frozen=True)
class DesktopClientConfig:
    """Locally validated downloaded installed-client configuration, not a live grant.

    Desktop exports commonly list ``http://localhost``. That is an installed-client
    loopback hint, not the application's effective callback: the latter stays the
    exact fixed URI and is sent identically in authorization and token requests.
    Local JSON cannot prove the project's actual registration or consent eligibility.
    """

    client_id: str
    client_secret: SecretStr = field(repr=False)
    redirect_uri: str = FIXED_REDIRECT
    registered_redirects: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, value: str | bytes, *, redirect_uri: str = FIXED_REDIRECT) -> DesktopClientConfig:
        return cls.from_installed_json(_json_object(value, configuration=True), redirect_uri=redirect_uri)

    @classmethod
    def from_installed_json(
        cls, payload: Mapping[str, object], *, redirect_uri: str = FIXED_REDIRECT,
    ) -> DesktopClientConfig:
        try:
            if not isinstance(payload, Mapping) or set(payload) != {"installed"}:
                raise ValueError
            installed = payload["installed"]
            if not isinstance(installed, Mapping):
                raise TypeError
            allowed = {
                "client_id", "project_id", "auth_uri", "token_uri", "auth_provider_x509_cert_url",
                "client_secret", "redirect_uris",
            }
            if set(installed) - allowed:
                raise ValueError
            client_id, client_secret = installed.get("client_id"), installed.get("client_secret")
            if (
                not isinstance(client_id, str) or len(client_id) > 255
                or not re.fullmatch(r"[A-Za-z0-9_-]{5,200}\.apps\.googleusercontent\.com", client_id)
                or not _safe_string(client_secret)
                or redirect_uri != FIXED_REDIRECT
                or installed.get("auth_uri") not in {
                    GOOGLE_AUTHORIZATION_ENDPOINT, _LEGACY_GOOGLE_AUTHORIZATION_ENDPOINT,
                }
                or installed.get("token_uri") != GOOGLE_TOKEN_ENDPOINT
            ):
                raise ValueError
            redirects = installed.get("redirect_uris")
            if (
                not isinstance(redirects, list) or not 1 <= len(redirects) <= 8
                or len(set(redirects)) != len(redirects)
                or any(value not in {"http://localhost", "http://127.0.0.1", FIXED_REDIRECT}
                       for value in redirects)
            ):
                raise ValueError
            certificate_url = installed.get("auth_provider_x509_cert_url")
            if certificate_url is not None and certificate_url != "https://www.googleapis.com/oauth2/v1/certs":
                raise ValueError
            project = installed.get("project_id")
            if project is not None and not _safe_string(project, maximum=128):
                raise ValueError
            return cls(client_id, SecretStr(client_secret), redirect_uri, tuple(redirects))
        except Exception:  # noqa: BLE001 - reject untrusted client JSON without reflecting its contents
            raise ProtocolError("config_invalid") from None


@dataclass(frozen=True)
class TokenHTTPResponse:
    status: int
    body: bytes = field(repr=False)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        # Neither token nor revoke POST may follow an OAuth endpoint redirect.
        return None


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.05 <= value <= 30:
        raise ProtocolError("transport_invalid")
    return float(value)


class GoogleHTTPSOAuthTransport:
    """TLS-validating, no-redirect Google transport; every call is hard blocked."""

    mode = "production"
    authorization_endpoint = GOOGLE_AUTHORIZATION_ENDPOINT

    def __init__(self, *, timeout_seconds: float = 10) -> None:
        self.timeout_seconds = _timeout(timeout_seconds)

    def post(self, operation: str, values: Mapping[str, str]) -> TokenHTTPResponse:
        require_production_activation()
        endpoint = {"token": GOOGLE_TOKEN_ENDPOINT, "revoke": GOOGLE_REVOKE_ENDPOINT}.get(operation)
        if endpoint is None:
            raise ProtocolError("transport_invalid")
        data = urlencode(values).encode("ascii")
        request = Request(endpoint, data=data, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
        })
        # Uses the system proxy configuration and normal CA trust. No TLS/policy override.
        opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                status = response.status
            if len(body) > _MAX_RESPONSE_BYTES:
                raise ProtocolError("response_invalid", outcome_unknown=True)
            return TokenHTTPResponse(status, body)
        except HTTPError as exc:
            # HTTPError string can contain URLs; only the numerical status leaves this boundary.
            try:
                body = exc.read(_MAX_RESPONSE_BYTES + 1)
                status = exc.code
            finally:
                exc.close()
            if len(body) > _MAX_RESPONSE_BYTES:
                raise ProtocolError("response_invalid", outcome_unknown=True) from None
            return TokenHTTPResponse(status, body)
        except (URLError, OSError, TimeoutError, http.client.HTTPException):
            # A POST may have reached the provider even when its response was lost.
            raise ProtocolError("outcome_unknown", outcome_unknown=True) from None


class SyntheticLoopbackTransport:
    """Test-only HTTP server, pinned to numeric IPv4 loopback with synthetic inputs."""

    mode = "synthetic"

    def __init__(self, base_url: str, *, timeout_seconds: float = 2) -> None:
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
            if (
                not isinstance(base_url, str) or port is None or not 1024 <= port <= 65535 or port == 8765
                or parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or base_url.rstrip("/") != f"http://127.0.0.1:{port}"
            ):
                raise ValueError
            self.base_url = f"http://127.0.0.1:{port}"
            self.port = port
            self.timeout_seconds = _timeout(timeout_seconds)
            self.authorization_endpoint = self.base_url + "/authorize"
        except Exception:  # noqa: BLE001 - do not echo an untrusted URL
            raise ProtocolError("transport_invalid") from None

    def post(self, operation: str, values: Mapping[str, str]) -> TokenHTTPResponse:
        if operation not in {"token", "revoke"}:
            raise ProtocolError("transport_invalid")
        if not isinstance(values, Mapping) or len(values) > 8:
            raise ProtocolError("transport_invalid")
        allowed = {
            "client_id", "client_secret", "redirect_uri", "grant_type", "code", "code_verifier",
            "refresh_token", "token",
        }
        for key, value in values.items():
            if key not in allowed or not _safe_string(value):
                raise ProtocolError("transport_invalid")
            if key == "client_id" and not value.startswith("nf-synthetic-"):
                raise OAuthBlocked()
            if key == "client_secret" and not _synthetic(value, "client"):
                raise OAuthBlocked()
            if key in {"code", "refresh_token", "token"}:
                kinds = {"code": ("code",), "refresh_token": ("refresh",), "token": ("refresh", "access")}
                if not any(_synthetic(value, kind) for kind in kinds[key]):
                    raise OAuthBlocked()
            if key == "redirect_uri" and value != FIXED_REDIRECT:
                raise ProtocolError("transport_invalid")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout_seconds)
        try:
            connection.request("POST", "/" + operation, body=urlencode(values).encode("ascii"), headers={
                "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
            })
            response = connection.getresponse()
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            status = response.status
            if len(body) > _MAX_RESPONSE_BYTES:
                raise ProtocolError("response_invalid", outcome_unknown=True)
            # A redirect is returned to the engine; never followed to another host.
            return TokenHTTPResponse(status, body)
        except (OSError, TimeoutError, http.client.HTTPException):
            raise ProtocolError("outcome_unknown", outcome_unknown=True) from None
        finally:
            connection.close()


class BrowserLaunchError(ProtocolError):
    """The validated authorization URL could not be opened by the OS."""

    def __init__(self) -> None:
        super().__init__("provider_error")


class GoogleSystemBrowser:
    """Dormant system browser launcher, never called in synthetic tests."""

    def open(self, authorization_url: SecretStr) -> None:
        require_production_activation()
        if not isinstance(authorization_url, SecretStr):
            raise ProtocolError("transport_invalid")
        parsed = urlsplit(authorization_url.get_secret_value())
        if (
            parsed.scheme != "https" or parsed.netloc != "accounts.google.com"
            or parsed.path != "/o/oauth2/v2/auth" or parsed.fragment
        ):
            raise ProtocolError("transport_invalid")
        try:
            opened = webbrowser.open(authorization_url.get_secret_value(), new=1, autoraise=True)
        except Exception:  # noqa: BLE001 - operating-system browser errors may contain the state URL
            raise BrowserLaunchError() from None
        if not opened:
            raise BrowserLaunchError()


@dataclass(frozen=True)
class AuthorizationLaunch:
    request: OAuthRequest
    authorization_url: SecretStr = field(repr=False)
    mode: str


class GoogleOAuthProtocol:
    """Authorization Code + PKCE protocol, one-use callbacks, no automatic retries.

    ``synthetic=True`` is a local protocol test facility, not a production activation.
    It cannot use an arbitrary transport, real-format credentials or official hosts.
    Upload-only scope cannot verify a YouTube channel identity; initial token exchange
    does not authorize credential persistence or mark an account connected.
    """

    def __init__(
        self, config: DesktopClientConfig,
        transport: GoogleHTTPSOAuthTransport | SyntheticLoopbackTransport, *,
        synthetic: bool = False, sessions: OAuthSessionStore | None = None,
    ) -> None:
        if type(config) is not DesktopClientConfig or config.redirect_uri != FIXED_REDIRECT:
            raise ProtocolError("config_invalid")
        if synthetic:
            if (
                type(transport) is not SyntheticLoopbackTransport
                or not config.client_id.startswith("nf-synthetic-")
                or not _synthetic(config.client_secret.get_secret_value(), "client")
            ):
                raise OAuthBlocked()
        elif type(transport) is not GoogleHTTPSOAuthTransport:
            raise ProtocolError("transport_invalid")
        self.config, self.transport, self.synthetic = config, transport, synthetic
        self.sessions = sessions or OAuthSessionStore()
        self.validator = OAuthCallbackValidator(self.sessions)
        self._starts: dict[str, list[datetime]] = {}
        self._used_codes: set[str] = set()
        self._issued: dict[str, str] = {}
        self._fingerprints: dict[str, str] = {}
        self._refresh_deadlines: dict[str, datetime | None] = {}
        self._unknown: set[str] = set()
        self._refresh_attempted: set[str] = set()
        self._revoked: set[str] = set()
        self._identity: dict[str, str] = {}
        self._lock = Lock()
        self._requests = {"token": 0, "refresh": 0, "revoke": 0}

    def _gate(self) -> None:
        if not self.synthetic:
            require_production_activation()
        elif type(self.transport) is not SyntheticLoopbackTransport:
            raise OAuthBlocked()

    @staticmethod
    def _account(account_key: str) -> None:
        if not account_key_valid(account_key) or not account_key.startswith("youtube:"):
            raise ProtocolError("account_mismatch")

    @staticmethod
    def _digest(bundle: TokenBundle) -> str:
        if not isinstance(bundle, TokenBundle):
            raise ProtocolError("response_invalid")
        return hashlib.sha256(bundle.access_token.get_secret_value().encode("utf-8")).hexdigest()

    @staticmethod
    def _fingerprint(bundle: TokenBundle) -> str:
        # Bind the whole grant, not just its access token: a caller cannot splice
        # another account's refresh token or alter expiration/permissions.
        values = [bundle.access_token.get_secret_value(),
                  bundle.refresh_token.get_secret_value() if bundle.refresh_token else None,
                  checked_time(bundle.expires_at).isoformat(), list(bundle.scopes)]
        return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()

    def _bound(self, account_key: str, bundle: TokenBundle) -> str:
        self._account(account_key)
        digest = self._digest(bundle)
        with self._lock:
            if digest in self._unknown:
                raise ProtocolError("outcome_unknown", outcome_unknown=True)
            if digest in self._revoked:
                raise ProtocolError("reused")
            if self._issued.get(digest) != account_key:
                raise ProtocolError("account_mismatch")
            if not hmac.compare_digest(self._fingerprints.get(digest, ""), self._fingerprint(bundle)):
                raise ProtocolError("account_mismatch")
        if bundle.scopes != _SCOPES:
            raise ProtocolError("scope_mismatch")
        if self.synthetic and (
            not _synthetic(bundle.access_token.get_secret_value(), "access")
            or (bundle.refresh_token is not None
                and not _synthetic(bundle.refresh_token.get_secret_value(), "refresh"))
        ):
            raise OAuthBlocked()
        return digest

    def begin(
        self, account_key: str, *, open_browser: bool = False, now: datetime | None = None,
    ) -> AuthorizationLaunch:
        self._gate()
        self._account(account_key)
        if self.synthetic and open_browser:
            # Real system browsers are not a fixture HTTP-server transport.
            raise OAuthBlocked()
        instant = checked_time(now)
        with self._lock:
            recent = [value for value in self._starts.get(account_key, ())
                      if value > instant - timedelta(minutes=15)]
            if len(recent) >= 3:
                raise ProtocolError("rate_limited")
            self._starts[account_key] = [*recent, instant]
        self.sessions.invalidate(account_key)
        request = self.sessions.create(account_key, scopes=_SCOPES, now=instant)
        authorization_url = self.transport.authorization_endpoint + "?" + urlencode({
            "client_id": self.config.client_id, "redirect_uri": FIXED_REDIRECT,
            "response_type": "code", "scope": YOUTUBE_UPLOAD_SCOPE,
            "state": request.state.get_secret_value(), "code_challenge": request.code_challenge,
            "code_challenge_method": "S256", "access_type": "offline",
        })
        launch = AuthorizationLaunch(request, SecretStr(authorization_url),
                                     "synthetic" if self.synthetic else "production")
        if open_browser:
            GoogleSystemBrowser().open(launch.authorization_url)
        return launch

    def complete(
        self, session_id: str, account_key: str, callback_uri: str,
        params: Sequence[tuple[str, str]], *, now: datetime | None = None,
    ) -> TokenBundle:
        self._gate()
        self._account(account_key)
        session, code = self.validator.consume(session_id, account_key, callback_uri, params, now=now)
        value = code.get_secret_value()
        if not _safe_string(value):
            raise ProtocolError("callback_invalid")
        if self.synthetic and not _synthetic(value, "code"):
            raise OAuthBlocked()
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        with self._lock:
            if digest in self._used_codes:
                raise ProtocolError("reused")
            self._used_codes.add(digest)
            self._requests["token"] += 1
        response = self.transport.post("token", {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret.get_secret_value(),
            "code": value, "code_verifier": session.verifier.get_secret_value(),
            "grant_type": "authorization_code", "redirect_uri": FIXED_REDIRECT,
        })
        bundle, refresh_deadline = self._token_response(response, now=now)
        with self._lock:
            token_digest = self._digest(bundle)
            if token_digest in self._issued and self._issued[token_digest] != account_key:
                raise ProtocolError("identity_mismatch")
            self._issued[token_digest] = account_key
            self._fingerprints[token_digest] = self._fingerprint(bundle)
            self._refresh_deadlines[token_digest] = refresh_deadline
        return bundle

    def _token_response(
        self, response: TokenHTTPResponse, *, previous: TokenBundle | None = None,
        now: datetime | None = None,
    ) -> tuple[TokenBundle, datetime | None]:
        self._response_status(response)
        data = _json_object(response.body)
        if set(data) - {"access_token", "refresh_token", "expires_in", "scope", "token_type",
                         "refresh_token_expires_in"}:
            raise ProtocolError("response_invalid", outcome_unknown=True)
        if data.get("token_type") != "Bearer" or not _safe_string(data.get("access_token"), maximum=4096):
            raise ProtocolError("response_invalid", outcome_unknown=True)
        lifetime = data.get("expires_in")
        if isinstance(lifetime, bool) or not isinstance(lifetime, int) or not 1 <= lifetime <= 86400:
            raise ProtocolError("response_invalid", outcome_unknown=True)
        scope = data.get("scope")
        if scope is None and previous is not None:
            granted_scopes = previous.scopes
        elif isinstance(scope, str):
            granted_scopes = tuple(scope.split())
        else:
            raise ProtocolError("scope_mismatch", outcome_unknown=True)
        if granted_scopes != _SCOPES:
            raise ProtocolError("scope_mismatch", outcome_unknown=True)
        refresh = data.get("refresh_token")
        if previous is None and refresh is None:
            # Google's installed-app documentation guarantees an initial refresh
            # token. Missing credentials must not become an accepted desktop grant.
            raise ProtocolError("response_invalid", outcome_unknown=True)
        if refresh is None and previous is not None:
            refresh = previous.refresh_token.get_secret_value() if previous.refresh_token else None
        if refresh is not None and not _safe_string(refresh, maximum=4096):
            raise ProtocolError("response_invalid", outcome_unknown=True)
        refresh_lifetime = data.get("refresh_token_expires_in")
        if refresh_lifetime is not None and (
            isinstance(refresh_lifetime, bool) or not isinstance(refresh_lifetime, int)
            or not 1 <= refresh_lifetime <= 31_536_000
        ):
            raise ProtocolError("response_invalid", outcome_unknown=True)
        access = data["access_token"]
        if self.synthetic and (
            not _synthetic(access, "access") or (refresh is not None and not _synthetic(refresh, "refresh"))
        ):
            raise ProtocolError("response_invalid", outcome_unknown=True)
        bundle = TokenBundle(
            access_token=SecretStr(access), refresh_token=SecretStr(refresh) if refresh is not None else None,
            expires_at=checked_time(now) + timedelta(seconds=lifetime), scopes=granted_scopes,
        )
        deadline = checked_time(now) + timedelta(seconds=refresh_lifetime) if refresh_lifetime else None
        if previous is not None and deadline is None and bundle.refresh_token == previous.refresh_token:
            deadline = self._refresh_deadlines.get(self._digest(previous))
        return bundle, deadline

    @staticmethod
    def _response_status(response: TokenHTTPResponse) -> None:
        if type(response) is not TokenHTTPResponse or not isinstance(response.body, bytes):
            raise ProtocolError("response_invalid", outcome_unknown=True)
        if response.status >= 500:
            raise ProtocolError("outcome_unknown", outcome_unknown=True)
        if response.status == 429:
            raise ProtocolError("rate_limited")
        if response.status != 200:
            # Never echo error_description or retry_after and never retry automatically.
            raise ProtocolError("provider_error")

    def refresh(self, account_key: str, bundle: TokenBundle, *, now: datetime | None = None) -> TokenBundle:
        self._gate()
        digest = self._bound(account_key, bundle)
        if bundle.refresh_token is None:
            raise ProtocolError("response_invalid")
        with self._lock:
            deadline = self._refresh_deadlines.get(digest)
            if deadline is not None and deadline <= checked_time(now):
                raise ProtocolError("expired")
            if digest in self._refresh_attempted:
                raise ProtocolError("reused")
            self._refresh_attempted.add(digest)
            self._requests["refresh"] += 1
            self._unknown.add(digest)
            self._identity.pop(digest, None)
        response = self.transport.post("token", {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret.get_secret_value(),
            "refresh_token": bundle.refresh_token.get_secret_value(), "grant_type": "refresh_token",
        })
        replacement, refresh_deadline = self._token_response(response, previous=bundle, now=now)
        with self._lock:
            replacement_digest = self._digest(replacement)
            if replacement_digest in self._issued and self._issued[replacement_digest] != account_key:
                raise ProtocolError("identity_mismatch")
            self._issued.pop(digest, None)
            self._fingerprints.pop(digest, None)
            self._refresh_deadlines.pop(digest, None)
            self._issued[replacement_digest] = account_key
            self._fingerprints[replacement_digest] = self._fingerprint(replacement)
            self._refresh_deadlines[replacement_digest] = refresh_deadline
            self._unknown.discard(digest)
            self._unknown.discard(replacement_digest)
            # Identity evidence was for the old token; do not transfer it without revalidation.
            self._identity.pop(digest, None)
        return replacement

    def revoke(self, account_key: str, bundle: TokenBundle) -> None:
        self._gate()
        digest = self._bound(account_key, bundle)
        with self._lock:
            self._revoked.add(digest)
            self._issued.pop(digest, None)
            self._identity.pop(digest, None)
            self._requests["revoke"] += 1
        token = bundle.refresh_token or bundle.access_token
        response = self.transport.post("revoke", {"token": token.get_secret_value()})
        self._response_status(response)

    def cancel(self, account_key: str) -> None:
        self._gate()
        self._account(account_key)
        self.sessions.invalidate(account_key)

    def identity_status(self, account_key: str, bundle: TokenBundle) -> str:
        self._gate()
        digest = self._bound(account_key, bundle)
        with self._lock:
            return "SYNTHETIC_VERIFIED" if digest in self._identity else "UNVERIFIED"

    def bind_synthetic_identity(
        self, account_key: str, bundle: TokenBundle, expected_subject: str, provider_subject: str,
    ) -> None:
        self._gate()
        if not self.synthetic:
            raise ProtocolError("identity_unverified")
        digest = self._bound(account_key, bundle)
        if (
            not isinstance(expected_subject, str) or not isinstance(provider_subject, str)
            or not re.fullmatch(r"nf-synthetic-identity-[A-Za-z0-9_-]{1,100}", provider_subject)
            or provider_subject != expected_subject
        ):
            raise ProtocolError("identity_mismatch")
        with self._lock:
            if any(subject == provider_subject and self._issued.get(token) != account_key
                   for token, subject in self._identity.items()):
                raise ProtocolError("identity_mismatch")
            self._identity[digest] = provider_subject

    def evidence(self) -> dict[str, object]:
        # This records local synthetic protocol operations, not live provider success.
        with self._lock:
            return {
                "mode": "SYNTHETIC_PROTOCOL" if self.synthetic else "OFFLINE/BLOCKED",
                "synthetic_token_requests": self._requests["token"] if self.synthetic else 0,
                "synthetic_refresh_requests": self._requests["refresh"] if self.synthetic else 0,
                "synthetic_revoke_requests": self._requests["revoke"] if self.synthetic else 0,
                "real_oauth_requests": 0, "real_sns_upload_requests": 0,
            }
