"""Official provider descriptions; real authorization/token transport deliberately absent."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Protocol
from uuid import uuid4

from pydantic import SecretStr

from newsflow.publishing.auth import TokenBundle

from .contracts import YOUTUBE_UPLOAD_SCOPE, OAuthBlocked, OAuthError, OAuthPolicy
from .session import OAuthRequest, OAuthSession, OAuthSessionStore


class OAuthProvider(Protocol):
    mode: str
    def begin(self, account_key: str, store: OAuthSessionStore) -> OAuthRequest: ...
    def exchange(self, code: SecretStr, session: OAuthSession) -> TokenBundle: ...
    def refresh(self, bundle: TokenBundle) -> TokenBundle: ...
    def revoke(self, bundle: TokenBundle) -> None: ...


class YouTubeOAuthAdapter:
    mode = "blocked"
    scopes = (YOUTUBE_UPLOAD_SCOPE,)
    authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    revoke_endpoint = "https://oauth2.googleapis.com/revoke"

    def __init__(self, *, feature_enabled: bool = False, user_approved: bool = False) -> None:
        self.policy = OAuthPolicy(feature_enabled, user_approved)

    def begin(self, *args: object, **kwargs: object) -> OAuthRequest:
        raise OAuthBlocked()

    def exchange(self, *args: object, **kwargs: object) -> TokenBundle:
        raise OAuthBlocked()

    def refresh(self, *args: object, **kwargs: object) -> TokenBundle:
        raise OAuthBlocked()

    def revoke(self, *args: object, **kwargs: object) -> None:
        raise OAuthBlocked()


class InstagramOAuthAdapter(YouTubeOAuthAdapter):
    # No inferred permissions or endpoints while login-specific documents are unavailable.
    scopes: tuple[str, ...] = ()
    authorization_endpoint = None
    token_endpoint = None
    revoke_endpoint = None


class FakeOAuthProvider:
    mode = "fake"

    def __init__(self, outcome: str = "success") -> None:
        if outcome not in {"success", "error", "cancelled", "expired"}:
            raise OAuthError("invalid_input")
        self.outcome = outcome
        self.calls = {"begin": 0, "exchange": 0, "refresh": 0, "revoke": 0}
        self._used_codes: set[str] = set()
        self._lock = Lock()

    def begin(self, account_key: str, store: OAuthSessionStore) -> OAuthRequest:
        self.calls["begin"] += 1
        scopes = (YOUTUBE_UPLOAD_SCOPE,) if account_key.startswith("youtube:") else ()
        return store.create(account_key, scopes=scopes)

    def _bundle(self, scopes: tuple[str, ...]) -> TokenBundle:
        if self.outcome in {"error", "cancelled"}:
            raise OAuthError("provider_error" if self.outcome == "error" else "cancelled")
        return TokenBundle(
            access_token=SecretStr("nf-synthetic-access-" + uuid4().hex),
            refresh_token=SecretStr("nf-synthetic-refresh-" + uuid4().hex),
            expires_at=datetime.now(UTC) + timedelta(seconds=-1 if self.outcome == "expired" else 3600),
            scopes=scopes,
        )

    def exchange(self, code: SecretStr, session: OAuthSession) -> TokenBundle:
        if session.mode != "fake" or not isinstance(code, SecretStr):
            raise OAuthBlocked()
        value = code.get_secret_value()
        if not re.fullmatch(r"nf-synthetic-code-[A-Za-z0-9_-]{1,200}", value):
            raise OAuthBlocked()
        digest = hashlib.sha256(value.encode()).hexdigest()
        with self._lock:
            if digest in self._used_codes:
                raise OAuthError("reused")
            self._used_codes.add(digest)
            self.calls["exchange"] += 1
        return self._bundle(session.scopes)

    def refresh(self, bundle: TokenBundle) -> TokenBundle:
        if (
            not bundle.refresh_token
            or not bundle.refresh_token.get_secret_value().startswith("nf-synthetic-")
            or not bundle.access_token.get_secret_value().startswith("nf-synthetic-")
        ):
            raise OAuthBlocked()
        self.calls["refresh"] += 1
        return self._bundle(bundle.scopes)

    def revoke(self, bundle: TokenBundle) -> None:
        if not bundle.access_token.get_secret_value().startswith("nf-synthetic-"):
            raise OAuthBlocked()
        self.calls["revoke"] += 1


def oauth_safety_status() -> dict:
    # Structural boundary, not a measurement of every network request in the application.
    return {
        "real_authorization_requests": 0, "real_token_exchange_calls": 0,
        "real_refresh_calls": 0, "real_revoke_calls": 0,
        "mode": "OFFLINE/BLOCKED", "feature_enabled": False,
        "user_approval": False, "phase_allows_real": False,
    }
