"""Explicit, non-inference OpenAI and Claude API connection checks.

Only the official model metadata GET is sent. A successful response proves key
authentication and access to that model, not billing, inference or web search.
No key, request headers, supplier error body or arbitrary response is persisted.
"""

from __future__ import annotations

import hmac
import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import utcnow

from .api_providers import API_MODELS
from .api_settings import _provider, _read, _time
from .credentials import CredentialError
from .provider import OpenAIProvider, ProviderResponseError
from .settings import _set, _value

PROVIDER = "claude_api"
ENDPOINT = "https://api.anthropic.com/v1/models/"
ENDPOINTS = {PROVIDER: ENDPOINT, "openai": "https://api.openai.com/v1/models/"}
TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 64 * 1024
BUSY_TTL = timedelta(seconds=60)
CHECK_MESSAGES = {
    "not_checked": "실제 API 연결 미확인",
    "checking": "Claude API 연결을 확인하고 있습니다.",
    "success": "API 인증·모델 접근 확인 완료 · 생성·웹 검색·결제 상태는 별도 확인이 필요합니다.",
    "consent_required": "저장된 API Key를 Claude에 보내 연결을 확인하는 데 동의해 주세요.",
    "key_missing": "API Key를 먼저 등록하세요.",
    "key_error": "저장된 API Key를 읽지 못했습니다. 보호 저장소 상태를 확인하세요.",
    "unsupported_model": "저장된 모델의 연결 확인은 지원하지 않습니다. 고급 설정에서 모델을 확인하세요.",
    "auth_error": "API 인증에 실패했습니다. Claude API Key 상태를 확인하세요.",
    "permission": "이 API Key에 모델 조회 권한이 없습니다. Claude 계정 권한을 확인하세요.",
    "model_unavailable": "저장된 모델을 찾을 수 없습니다. 모델 이름과 계정 접근 권한을 확인하세요.",
    "rate_limit": "Claude API 요청 또는 계정 한도에 도달했습니다. 자동 재시도하지 않습니다.",
    "timeout": "연결 확인 시간이 초과됐습니다. 자동 재시도하지 않습니다.",
    "network": "Claude API에 연결하지 못했습니다. 네트워크 상태를 확인하세요.",
    "unavailable": "Claude API가 연결 확인 요청을 처리하지 못했습니다. 자동 재시도하지 않습니다.",
    "invalid_response": "Claude 모델 응답을 확인하지 못했습니다. 자동 재시도하지 않습니다.",
    "stale": "확인 중 API Key 또는 모델 설정이 변경됐습니다. 현재 설정으로 다시 확인하세요.",
    "busy": "이미 연결 확인 중입니다. 완료 후 결과를 확인하세요.",
}
_PROOF_KEYS = ("authentication_verified_at", "search_verified_at", "request_succeeded_at", "verified_model")


@dataclass(frozen=True)
class ConnectionCheckResult:
    ok: bool
    code: str
    message: str
    checked_at: str | None = None


def _result(code: str, checked_at: str | None = None, provider: str = PROVIDER) -> ConnectionCheckResult:
    message = CHECK_MESSAGES[code]
    if provider == "openai":
        message = message.replace("Claude", "OpenAI")
    return ConnectionCheckResult(code == "success", code, message, checked_at)


def invalidate_connection_check(session: Session, provider: str) -> None:
    """Call within the same transaction that invalidates key/model verification."""
    for name in ("connection_check_id", "connection_check_code", "connection_checked_at",
                 "connection_check_started_at"):
        _set(session, f"api_{provider}_{name}", "")


def read_connection_check(sessions: sessionmaker[Session], provider: str = PROVIDER) -> ConnectionCheckResult:
    _provider(provider)
    with sessions() as session:
        code = _value(session, f"api_{provider}_connection_check_code")
        checked_at = _value(session, f"api_{provider}_connection_checked_at")
    return _result(code if code in CHECK_MESSAGES else "not_checked",
                   checked_at if _time(checked_at) else None, provider)


def _clear_proof(session: Session, provider: str = PROVIDER) -> None:
    for name in _PROOF_KEYS:
        _set(session, f"api_{provider}_{name}", "")


def _record(session: Session, code: str, checked_at: str, provider: str = PROVIDER) -> ConnectionCheckResult:
    _set(session, f"api_{provider}_connection_check_id", "")
    _set(session, f"api_{provider}_connection_check_code", code)
    _set(session, f"api_{provider}_connection_checked_at", checked_at)
    return _result(code, checked_at, provider)


def _key(key_store) -> str:
    key = key_store.key() if key_store is not None else ""
    if not isinstance(key, str) or not key.strip():
        return ""
    # Reject newline/header injection even when a custom/environment store is used.
    if not re.fullmatch(r"[A-Za-z0-9_\-.:]{20,256}", key):
        raise CredentialError("Invalid key format")
    return key


def _check_model(model: str, key: str, transport, provider: str = PROVIDER) -> str:
    headers = {"Accept": "application/json"}
    if provider == "openai":
        headers["Authorization"] = "Bearer " + key
    else:
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    request = urllib.request.Request(ENDPOINTS[provider] + model, method="GET", headers=headers)
    try:
        # Reuse the existing verified-TLS, no-redirect transport directly: _send's
        # retry logic is deliberately never entered. Tests inject only this seam.
        send = transport or OpenAIProvider(allow_retry=False)._open
        raw = send(request, TIMEOUT_SECONDS, MAX_RESPONSE_BYTES)
        if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
            return "invalid_response"
        document = json.loads(raw)
        kind = "object" if provider == "openai" else "type"
        if not isinstance(document, dict) or document.get(kind) != "model" or document.get("id") != model:
            return "invalid_response"
        return "success"
    except urllib.error.HTTPError as error:
        # Never read, log or return the supplier error body/headers/URL.
        code = {401: "auth_error", 403: "permission", 404: "model_unavailable", 429: "rate_limit",
                408: "timeout", 504: "timeout"}.get(error.code, "unavailable")
        error.close()
        return code
    except TimeoutError:
        return "timeout"
    except urllib.error.URLError as error:
        return "timeout" if isinstance(error.reason, TimeoutError) else "network"
    except (ValueError, TypeError, ProviderResponseError):
        return "invalid_response"
    except OSError:
        return "network"
    except Exception:  # noqa: BLE001 - keep arbitrary transport failures secret-safe
        return "unavailable"


def check_api_connection(
    sessions: sessionmaker[Session], key_store, *, provider: str, consent: bool, transport=None,
) -> ConnectionCheckResult:
    """Perform one user-requested metadata check without spending inference budget.

    SQLite serializes check acquisition. An in-flight check blocks a second click
    for 60 seconds; expiry permits only a new explicit action, never a retry.
    A key/model change or new check invalidates a late result. Budget, approvals,
    provider choice and key files are never changed here.
    """
    _provider(provider)
    if consent is not True:
        return _result("consent_required", provider=provider)
    now = utcnow()
    prefix = f"api_{provider}_"
    generation = uuid.uuid4().hex
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        started = _time(_value(session, prefix + "connection_check_started_at"))
        if (_value(session, prefix + "connection_check_id") and started is not None
                and timedelta(0) <= now - started < BUSY_TTL):
            return _result("busy", provider=provider)
        settings = _read(session, provider)
        try:
            key = _key(key_store)
        except (CredentialError, OSError):
            _clear_proof(session, provider)
            return _record(session, "key_error", now.isoformat(), provider)
        if not key:
            _clear_proof(session, provider)
            return _record(session, "key_missing", now.isoformat(), provider)
        model = settings.model
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", model) or model not in API_MODELS[provider]:
            _clear_proof(session, provider)
            return _record(session, "unsupported_model", now.isoformat(), provider)
        _set(session, prefix + "connection_check_id", generation)
        _set(session, prefix + "connection_check_started_at", now.isoformat())
        _set(session, prefix + "connection_check_code", "checking")

    code = _check_model(model, key, transport, provider)
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        if _value(session, prefix + "connection_check_id") != generation:
            return _result("stale", provider=provider)  # Never replace newer settings or verification.
        current = _read(session, provider)
        try:
            same_key = hmac.compare_digest(_key(key_store), key)
        except (CredentialError, OSError):
            same_key = False
        checked_at = utcnow().isoformat()
        if current.model != model or not same_key:
            _clear_proof(session, provider)
            return _record(session, "stale", checked_at, provider)
        if code == "success":
            if current.verified_model != model:
                _clear_proof(session, provider)
            _set(session, prefix + "authentication_verified_at", checked_at)
            _set(session, prefix + "verified_model", model)
        else:
            _clear_proof(session, provider)
        return _record(session, code, checked_at, provider)


def check_claude_connection(
    sessions: sessionmaker[Session], key_store, *, consent: bool, transport=None,
) -> ConnectionCheckResult:
    """Compatibility entry point for the existing Claude connection screen."""
    return check_api_connection(sessions, key_store, provider=PROVIDER, consent=consent, transport=transport)
