"""In-memory, account-bound, one-use state and S256 sessions. No callback HTTP route."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import uuid4

from pydantic import SecretStr

from .contracts import FIXED_REDIRECT, OAuthError, account_key_valid


def pkce_s256(verifier: str) -> str:
    if not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        raise OAuthError("invalid_input")
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()


def checked_time(value: datetime | None = None) -> datetime:
    result = value or datetime.now(UTC)
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise OAuthError("invalid_input")
    return result.astimezone(UTC)


@dataclass(frozen=True)
class OAuthSession:
    session_id: str
    account_key: str
    redirect_uri: str
    scopes: tuple[str, ...]
    expires_at: datetime
    state_digest: bytes = field(repr=False)
    verifier: SecretStr = field(repr=False)
    mode: str = "fake"


@dataclass(frozen=True)
class OAuthRequest:
    session_id: str
    state: SecretStr = field(repr=False)
    code_challenge: str
    code_challenge_method: str = "S256"
    redirect_uri: str = FIXED_REDIRECT


class OAuthSessionStore:
    def __init__(self, ttl_seconds: int = 300) -> None:
        if not 1 <= ttl_seconds <= 300:
            raise OAuthError("invalid_input")
        self.ttl = ttl_seconds
        self._sessions: dict[str, OAuthSession] = {}
        self._lock = Lock()

    def create(
        self, account_key: str, *, redirect_uri: str = FIXED_REDIRECT,
        scopes: tuple[str, ...] = (), now: datetime | None = None,
    ) -> OAuthRequest:
        if not account_key_valid(account_key) or redirect_uri != FIXED_REDIRECT:
            raise OAuthError("invalid_input")
        if len(scopes) > 20 or any(not isinstance(s, str) or len(s) > 512 for s in scopes):
            raise OAuthError("invalid_input")
        instant = checked_time(now)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        identifier = uuid4().hex
        session = OAuthSession(
            identifier, account_key, redirect_uri, tuple(scopes), instant + timedelta(seconds=self.ttl),
            hashlib.sha256(state.encode("ascii")).digest(), SecretStr(verifier),
        )
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items() if v.expires_at > instant}
            if len(self._sessions) >= 128:
                raise OAuthError("invalid_input")
            self._sessions[identifier] = session
        return OAuthRequest(identifier, SecretStr(state), pkce_s256(verifier))

    def pop(self, identifier: str) -> OAuthSession:
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise OAuthError("reused")
        with self._lock:
            session = self._sessions.pop(identifier, None)
        if session is None:
            raise OAuthError("reused")
        return session

    def invalidate(self, account_key: str) -> None:
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items() if v.account_key != account_key}


class OAuthCallbackValidator:
    def __init__(self, store: OAuthSessionStore) -> None:
        self.store = store

    def consume(
        self, session_id: str, account_key: str, callback_uri: str,
        params: Sequence[tuple[str, str]], *, now: datetime | None = None,
    ) -> tuple[OAuthSession, SecretStr]:
        # Reserve and consume before validation/exchange, including cancelled/bad responses.
        session = self.store.pop(session_id)
        if session.account_key != account_key:
            raise OAuthError("account_mismatch")
        if callback_uri != session.redirect_uri or callback_uri != FIXED_REDIRECT:
            raise OAuthError("redirect_mismatch")
        if session.expires_at <= checked_time(now):
            raise OAuthError("expired")
        try:
            pairs = list(params)
            values: dict[str, str] = {}
            if not 1 <= len(pairs) <= 4:
                raise ValueError
            for key, value in pairs:
                if key not in {"state", "code", "error", "error_description"} or key in values:
                    raise ValueError
                if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
                    raise ValueError
                values[key] = value
            state = values.get("state", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", state):
                raise OAuthError("state_mismatch")
            if not hmac.compare_digest(hashlib.sha256(state.encode()).digest(), session.state_digest):
                raise OAuthError("state_mismatch")
            if ("code" in values) == ("error" in values):
                raise ValueError
            if "error" in values:
                raise OAuthError("cancelled" if values["error"] == "access_denied" else "provider_error")
            if "error_description" in values or not values["code"]:
                raise ValueError
            return session, SecretStr(values["code"])
        except OAuthError:
            raise
        except Exception:  # noqa: BLE001 - fail closed without reflecting secrets or provider errors
            raise OAuthError("callback_invalid") from None
