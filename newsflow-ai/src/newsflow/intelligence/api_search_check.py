"""Explicit first-search check; normal production search still requires proof.

One saved authentication generation permits one paid search attempt. The existing
reservation journal survives restarts. No article import, analysis or continuation
is performed here; only validated tool evidence can create search proof.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import APIRequestReservation, utcnow

from .api_connection import _key
from .api_providers import AnthropicProvider, OpenAISearchProvider
from .api_search import SearchRequest, SearchResponseError, validate_search_result
from .api_settings import (
    FIRST_SEARCH_OUTPUT_TOKENS,
    APIBudgetService,
    APISettingsError,
    _read,
    _recent,
)
from .credentials import CredentialError
from .provider import Options, ProviderError
from .settings import _set, _value

MESSAGES = {
    "success": "검색 도구·출처·JSON·사용량 확인 완료. 기사 발행일·사실·대본·결제 금액은 별도 검토가 필요합니다.",
    "consent_required": "검색 조건을 외부 API에 보내는 것과 검색·토큰 비용 발생에 동의해 주세요.",
    "stale": "인증·키·모델이 변경됐거나 인증 확인 중입니다. 현재 설정을 다시 확인하세요.",
    "key_error": "API Key를 읽지 못했습니다. 키 등록과 인증 상태를 확인하세요.",
    "ai_auth_failed": "검색 요청의 인증·권한 확인에 실패했습니다. 자동 재시도하지 않습니다.",
    "ai_rate_limited": "API 사용 한도에 도달했습니다. 자동 재시도하지 않습니다.",
    "ai_bad_response": "완료된 검색·출처·JSON 근거를 확인하지 못했습니다. 자동 재시도하지 않습니다.",
    "unknown": "검색 결과 또는 사용량이 불명확합니다. 예약을 유지하고 새 호출을 차단합니다.",
}


@dataclass(frozen=True)
class SearchCheckResult:
    ok: bool
    code: str
    message: str


def _result(code: str, failure: SearchResponseError | None = None) -> SearchCheckResult:
    message = MESSAGES[code]
    if code in {"ai_bad_response", "unknown"} and failure is not None:
        message += " " + str(failure)
    return SearchCheckResult(code == "success", code, message)


def _same_auth(session: Session, provider: str, model: str, authentication_at: str) -> bool:
    settings = _read(session, provider)
    return (settings.model == settings.verified_model == model
            and settings.authentication_verified_at == authentication_at
            and _recent(authentication_at, utcnow())
            and not _value(session, f"api_{provider}_connection_check_id"))


def read_search_check(sessions: sessionmaker[Session], provider: str) -> dict:
    with sessions() as session:
        raw = _value(session, f"api_{provider}_search_check_summary")
        try:
            result = json.loads(raw or "{}")
            if isinstance(result, dict) and _same_auth(
                session, provider, result.get("model", ""), result.get("authentication_at", ""),
            ):
                return result
        except (ValueError, TypeError):
            pass
    return {}


def check_api_search(
    sessions: sessionmaker[Session], key_store, *, provider: str, model: str,
    authentication_at: str, max_cost_usd: str | None = None, consent: bool, transport=None,
) -> SearchCheckResult:
    if consent is not True:
        return _result("consent_required")
    if provider not in {"openai", "claude_api"}:
        return SearchCheckResult(False, "blocked", "API 제공자를 다시 선택하세요.")
    with sessions() as session:
        if not _same_auth(session, provider, model, authentication_at):
            return _result("stale")
    try:
        key = _key(key_store)
        if not key:
            return _result("key_error")
    except (CredentialError, OSError):
        return _result("key_error")

    budget = APIBudgetService(sessions)
    try:
        reservation = budget.reserve_first_search(
            provider=provider, model=model, authentication_at=authentication_at,
            key_store=key_store, consent=consent, max_cost_usd=max_cost_usd,
        )
    except APISettingsError as exc:
        return SearchCheckResult(False, "blocked", str(exc))

    adapter = (OpenAISearchProvider if provider == "openai" else AnthropicProvider)(lambda: key)
    if transport is not None:
        adapter._open = transport  # Tests replace HTTP only; production validation is unchanged.
    code, status, evidence = "unknown", "unknown", {}
    failure = None
    prefix = f"api_{provider}_"
    try:
        with sessions.begin() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            if not _same_auth(session, provider, model, authentication_at) or not hmac.compare_digest(_key(key_store), key):
                code, status = "stale", "failed"
            else:
                _set(session, prefix + "search_verified_at", "")
                _set(session, prefix + "search_check_summary", "")
        if code != "stale":
            result = validate_search_result(adapter.search(
                SearchRequest(category="it", period="24h", count=1),
                Options(model=model, max_tokens=FIRST_SEARCH_OUTPUT_TOKENS, timeout=60),
            ))
            if (result.provider != provider or result.model != model or len(result.articles) != 1
                    or result.tool_evidence.provenance != "provider_response"):
                raise SearchResponseError("result_contract")
            if (adapter.last_usage or {}).get("web_search_requests") != 1:
                # Tool evidence alone cannot stand in for an incomplete usage report.
                code, status = "unknown", "unknown"
            else:
                code, status = "success", "success"
                evidence = {"tool": result.tool_evidence.tool_name,
                            "tool_ids": result.tool_evidence.completed_tool_ids,
                            "sources": [{"title": article.title, "url": article.url} for article in result.articles],
                            "source_review": "NOT VERIFIED"}
    except SearchResponseError as exc:
        # Revalidate the finite diagnostic vocabulary; never persist str(exc)
        # from an arbitrary provider error or attach the original response.
        failure = exc.safe_copy()
        code, status = "ai_bad_response", "failed"
    except ProviderError as exc:
        code = exc.code if exc.code in MESSAGES else "unknown"
        status = "unknown" if code == "unknown" else "failed"
    except Exception:  # noqa: BLE001 - arbitrary I/O errors must not leak credentials or allow replay
        code, status = "unknown", "unknown"

    budget.finish(reservation.id, status=status, usage=adapter.last_usage)
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        row = session.get(APIRequestReservation, reservation.id)
        try:
            current = (_same_auth(session, provider, model, authentication_at)
                       and hmac.compare_digest(_key(key_store), key))
        except (CredentialError, OSError):
            current = False
        if not current:
            return _result("stale")  # Never overwrite a newer key/model/check result.
        if row.status == "unknown":
            code = "unknown"
        checked_at = utcnow().isoformat()
        if code == "success" and row.status == "success":
            _set(session, prefix + "search_verified_at", checked_at)
            _set(session, prefix + "request_succeeded_at", checked_at)
        else:
            evidence = {}
            _set(session, prefix + "search_verified_at", "")
        outcome = _result(code, failure)
        summary = {"code": code, "message": outcome.message, "checked_at": checked_at,
                   "model": model, "authentication_at": authentication_at,
                   "reservation_id": reservation.id, **evidence}
        if failure is not None:
            # Cost outcome and response failure are independent. In particular,
            # an over-bound usage report must not erase the safe parser diagnostic.
            summary.update(failure.diagnostics())
        _set(session, prefix + "search_check_summary", json.dumps(summary, ensure_ascii=False))
    return outcome
