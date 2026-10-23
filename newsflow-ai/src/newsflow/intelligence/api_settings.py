"""Explicit API approvals and atomic request/response usage accounting.

New requests do not reserve speculative dollar amounts. Reported token/tool usage
is priced after a response; this local estimate is never a vendor bill or hard cap.
Legacy reservations remain unchanged. Unknown outcomes and request replay block.
Only an injected Fake budget skips proof of a real authenticated API connection.
Neither settings saves nor readiness reads perform any network operation.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_UP, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import APIRequestReservation, utcnow

from .api_providers import API_MODELS
from .settings import SettingsError, _set, _value, month_start

PROVIDERS = {"openai": "OpenAI API", "claude_api": "Claude API"}
DEFAULT_MODELS = {"openai": "gpt-4.1-mini", "claude_api": "claude-sonnet-4-6"}
VERIFICATION_TTL = timedelta(hours=24)
FIRST_SEARCH_OUTPUT_TOKENS = 9000
# Supported search models retained for compatibility; these context sizes are NOT
# used to estimate or reserve a new request's dollar cost.
SEARCH_CONTEXT_BOUNDS = {"gpt-4.1-mini": 1_047_576, "claude-sonnet-4-6": 1_000_000,
                         "claude-haiku-4-5-20251001": 200_000, "claude-opus-4-6": 1_000_000}
# Official 2026-10-16 public list-price floors. User-entered higher account rates
# win; response usage estimates use at least the pinned model tariff.
PRICE_FLOORS = {"gpt-4.1-mini": ("0.40", "1.60"), "claude-sonnet-4-6": ("3", "15"),
                "claude-haiku-4-5-20251001": ("1", "5"), "claude-opus-4-6": ("5", "25")}
# Claude first-party standard rates checked 2026-10-17:
# https://platform.claude.com/docs/en/about-claude/pricing
# Missing rates use the pinned model's public tariff; explicit saved values,
# including zero/invalid values, are never silently repaired or overwritten.
DISCLAIMER = (
    "응답에 보고된 사용량의 사후 비용 추정은 공급사 실제 청구액이 아닙니다. 요청별 금액 한도와 "
    "추정 사전 예약을 적용하지 않으므로 한 요청의 최종 금액이나 월 예산 이내 완료를 보장하지 않습니다. "
    "다른 앱 사용·요금 변경은 실시간 반영되지 않습니다. 공급사 결제·한도를 함께 확인하세요."
)


class APISettingsError(SettingsError):
    """Safe fixed text; never include vendor errors or secret material."""


APIPolicyError = APISettingsError


def _provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise APISettingsError("API 제공자를 다시 선택하세요.")


def _amount(value, *, optional: bool = False) -> Decimal | None:
    if optional and (value is None or value == ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise APISettingsError("USD 금액과 단가는 0 이상의 숫자로 입력하세요.") from None
    if not result.is_finite() or not 0 <= result <= 1_000_000 or result.as_tuple().exponent < -8:
        raise APISettingsError("USD 금액과 단가 범위를 확인하세요.")
    return result


def _time(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value or "")
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def _recent(value: str | None, now: datetime) -> bool:
    parsed = _time(value)
    return parsed is not None and timedelta(0) <= now - parsed <= VERIFICATION_TTL


@dataclass(frozen=True)
class APISettings:
    provider: str
    model: str
    approved_at: str | None = None
    search_enabled: bool = False
    search_approved_at: str | None = None
    request_limit_usd: Decimal = Decimal(0)
    monthly_limit_usd: Decimal = Decimal(0)
    input_price_per_1m: Decimal | None = None
    output_price_per_1m: Decimal | None = None
    search_price_per_1k: Decimal | None = None
    billing_confirmed_at: str | None = None
    account_remaining_usd: Decimal | None = None
    authentication_verified_at: str | None = None
    search_verified_at: str | None = None
    request_succeeded_at: str | None = None
    verified_model: str | None = None

    @property
    def approved(self) -> bool:
        return bool(self.approved_at)

    @property
    def search_approved(self) -> bool:
        return bool(self.search_approved_at)


def _read(session: Session, provider: str) -> APISettings:
    _provider(provider)
    prefix = f"api_{provider}_"

    def raw(key):
        return _value(session, prefix + key) or None

    def money(key, default=None):
        try:
            return _amount(raw(key), optional=True) if raw(key) else default
        except APISettingsError:
            return default

    model = _value(session, "studio_model_" + provider)
    if not model and provider == "openai":
        model = _value(session, "ai_model")
    model = model or DEFAULT_MODELS[provider]

    def price(name, index):
        if raw(name) is None and provider == "claude_api" and model in PRICE_FLOORS:
            return Decimal(PRICE_FLOORS[model][index]) if index < 2 else Decimal(10)
        return money(name)

    return APISettings(
        provider=provider, model=model,
        approved_at=(_value(session, "ai_approved_at") or None) if provider == "openai" else raw("approved_at"),
        search_enabled=raw("search_enabled") == "1", search_approved_at=raw("search_approved_at"),
        request_limit_usd=money("request_limit_usd", Decimal(0)),
        monthly_limit_usd=money("monthly_limit_usd", Decimal(0)),
        input_price_per_1m=price("input_price_per_1m", 0), output_price_per_1m=price("output_price_per_1m", 1),
        search_price_per_1k=price("search_price_per_1k", 2), billing_confirmed_at=raw("billing_confirmed_at"),
        account_remaining_usd=money("account_remaining_usd"),
        authentication_verified_at=raw("authentication_verified_at"), search_verified_at=raw("search_verified_at"),
        request_succeeded_at=raw("request_succeeded_at"), verified_model=raw("verified_model"),
    )


def read_api_settings(sessions: sessionmaker[Session], provider: str) -> APISettings:
    with sessions() as session:
        return _read(session, provider)


def _invalidate(session: Session, provider: str) -> None:
    for key in ("authentication_verified_at", "search_verified_at", "request_succeeded_at", "verified_model",
                "billing_confirmed_at", "account_remaining_usd", "search_check_summary"):
        _set(session, f"api_{provider}_{key}", "")
    from .api_connection import invalidate_connection_check

    invalidate_connection_check(session, provider)


def invalidate_api_verification(sessions: sessionmaker[Session], provider: str) -> None:
    _provider(provider)
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        _invalidate(session, provider)


def save_api_settings(
    sessions: sessionmaker[Session], provider: str, *, model: str, approved: bool, search_enabled: bool,
    search_approved: bool, request_limit_usd: str | None = None, monthly_limit_usd: str, input_price_per_1m: str,
    output_price_per_1m: str, search_price_per_1k: str, billing_confirmed: bool = False,
    account_remaining_usd: str = "",
) -> APISettings:
    _provider(provider)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", model or ""):
        raise APISettingsError("모델 이름은 영문·숫자·점·하이픈 80자 이내여야 합니다.")
    if (provider == "claude_api") != model.startswith("claude-"):
        raise APISettingsError("선택한 API 제공자의 모델을 입력하세요.")
    for value in (approved, search_enabled, search_approved, billing_confirmed):
        if type(value) is not bool:
            raise APISettingsError("승인 설정을 다시 확인하세요.")
    values = {
        "monthly_limit_usd": _amount(monthly_limit_usd),
        "input_price_per_1m": _amount(input_price_per_1m, optional=True),
        "output_price_per_1m": _amount(output_price_per_1m, optional=True),
        "search_price_per_1k": _amount(search_price_per_1k, optional=True),
        "account_remaining_usd": _amount(account_remaining_usd, optional=True),
    }
    # Accept old clients without resetting saved legacy values when omitted.
    # The retained field no longer participates in any dispatch decision.
    if request_limit_usd is not None:
        values["request_limit_usd"] = _amount(request_limit_usd)
    if approved and values["monthly_limit_usd"] <= 0:
        raise APISettingsError("API 사용 승인에는 0보다 큰 월별 USD 한도가 필요합니다.")
    if billing_confirmed and (values["account_remaining_usd"] is None or values["account_remaining_usd"] <= 0):
        raise APISettingsError("공급사 대시보드에서 확인한 잔여 API 예산을 입력하세요.")
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        old = _read(session, provider)
        if old.model != model:
            _invalidate(session, provider)
        prefix = f"api_{provider}_"
        _set(session, "studio_model_" + provider, model)
        approved_key = "ai_approved_at" if provider == "openai" else prefix + "approved_at"
        _set(session, approved_key, (old.approved_at or utcnow().isoformat()) if approved else "")
        _set(session, prefix + "search_enabled", "1" if search_enabled else "0")
        _set(session, prefix + "search_approved_at",
             (old.search_approved_at or utcnow().isoformat()) if search_approved else "")
        for key, value in values.items():
            _set(session, prefix + key, str(value) if value is not None else "")
        # An unconfirmed save cannot silently renew or preserve old account evidence.
        _set(session, prefix + "billing_confirmed_at", utcnow().isoformat() if billing_confirmed else "")
    return read_api_settings(sessions, provider)


def _usage(rows: list[APIRequestReservation], now: datetime) -> dict:
    current = [row for row in rows if row.created_at >= month_start(now)]
    return {
        "calls": len(current), "held_usd": str(sum((Decimal(row.reserved_usd) for row in current), Decimal(0))),
        "estimated_usd": str(sum((Decimal(row.estimated_usd or "0") for row in current), Decimal(0))),
        "reported_usd": str(sum((Decimal(row.estimated_usd or "0") for row in current), Decimal(0))),
        "pending": sum(row.status == "reserved" for row in rows),
        "unknown": sum(row.status == "unknown" for row in rows),
        "test_calls": sum(row.test_only for row in current), "vendor_billing": "NOT VERIFIED",
    }


def _reasons(settings: APISettings, key: dict, capability: str, now: datetime, *, fake: bool = False,
             first_search: bool = False) -> list[str]:
    reasons = []
    if not key.get("configured"):
        reasons.append("API Key 미등록")
    if not settings.approved:
        reasons.append("API 사용 승인 필요")
    if settings.model not in API_MODELS[settings.provider] or settings.model not in PRICE_FLOORS:
        supported = " · ".join(API_MODELS[settings.provider])
        reasons.append(f"이 모델의 API 뉴스 자동화는 미검증입니다. 지원 모델: {supported}. 기존 모델 설정은 보존됩니다.")
    if capability == "search":
        if not settings.search_enabled:
            reasons.append("웹 검색 사용 설정이 꺼져 있습니다.")
        if not settings.search_approved:
            reasons.append("웹 검색 비용 별도 승인 필요")
        if settings.model not in SEARCH_CONTEXT_BOUNDS:
            reasons.append("이 모델의 웹 검색 계약은 미검증입니다.")
    if settings.monthly_limit_usd <= 0:
        reasons.append("월별 비용 한도 필요")
    prices = (settings.input_price_per_1m, settings.output_price_per_1m)
    if capability == "search":
        prices += (settings.search_price_per_1k,)
    if any(price is None or price <= 0 for price in prices):
        reasons.append("공식 요금표에서 확인한 단가 입력 필요")
    if not fake:
        if settings.verified_model != settings.model or not _recent(settings.authentication_verified_at, now):
            reasons.append("실제 API 연결 미확인 · 별도 승인 후 검증 필요")
        if capability == "search" and not first_search and (
            settings.verified_model != settings.model or not settings.search_verified_at
        ):
            reasons.append("실제 웹 검색 미검증 · BLOCKED")
    return reasons


def _readiness(sessions, provider, key_store, capability="search", *, fake=False) -> dict:
    from dataclasses import asdict

    from .api_connection import read_connection_check

    now = utcnow()
    with sessions() as session:
        settings = _read(session, provider)
        rows = list(session.scalars(select(APIRequestReservation).where(APIRequestReservation.provider == provider)))
    key = key_store.status() if key_store is not None else {"configured": False}
    usage = _usage(rows, now)
    reasons = _reasons(settings, key, capability, now, fake=fake)
    reasons.extend(_limit_reasons(settings, rows, now))
    auth = settings.verified_model == settings.model and _recent(settings.authentication_verified_at, now)
    return {"ready": not reasons, "state": "ready" if not reasons else "blocked", "reasons": reasons,
            "provider": provider, "model": settings.model, "capability": capability, "key": key,
            "configured": bool(key.get("configured")), "authentication_verified": auth,
            "request_succeeded": bool(auth and settings.request_succeeded_at), "settings": settings,
            "connection_check": asdict(read_connection_check(sessions, provider)),
            "usage": usage, "disclaimer": DISCLAIMER, "account_evidence": "USER CONFIRMED" if
            _recent(settings.billing_confirmed_at, now) else "NOT VERIFIED"}


def api_readiness(sessions: sessionmaker[Session], provider: str, key_store, capability: str = "search") -> dict:
    return _readiness(sessions, provider, key_store, capability)


def _first_search_id(provider: str, model: str, authentication_at: str) -> str:
    stamp = hashlib.sha256(f"{model}\n{authentication_at}".encode()).hexdigest()
    return f"first-search:{provider}:{stamp}"


def _prices(settings: APISettings) -> dict:
    floor_input, floor_output = PRICE_FLOORS[settings.model]
    return {"input": str(max(settings.input_price_per_1m, Decimal(floor_input))),
              "output": str(max(settings.output_price_per_1m, Decimal(floor_output))),
              "search": str(max(settings.search_price_per_1k or Decimal(0), Decimal(10)))}


def _limit_reasons(settings: APISettings, rows: list[APIRequestReservation], now: datetime) -> list[str]:
    reasons = []
    if any(row.status in ("reserved", "unknown") for row in rows):
        reasons.append("진행 중이거나 결과 불명인 API 요청이 있어 새 호출을 차단합니다.")
    monthly = sum((Decimal(row.estimated_usd or "0") for row in rows
                   if row.created_at >= month_start(now)), Decimal(0))
    # Only response-reported usage enters these totals. Missing usage remains an
    # unknown-outcome blocker, never an invented zero-cost success or refund.
    if settings.monthly_limit_usd > 0 and monthly >= settings.monthly_limit_usd:
        reasons.append("보고된 사용량 기준 월별 비용 한도에 도달했습니다.")
    return reasons


def first_search_readiness(sessions: sessionmaker[Session], provider: str, key_store) -> dict:
    """Local readiness for one explicit check; no speculative quote or request."""
    now = utcnow()
    with sessions() as session:
        settings = _read(session, provider)
        rows = list(session.scalars(select(APIRequestReservation).where(APIRequestReservation.provider == provider)))
        connection_busy = bool(_value(session, f"api_{provider}_connection_check_id"))
    key = key_store.status() if key_store is not None else {"configured": False}
    reasons = _reasons(settings, key, "search", now, first_search=True)
    if connection_busy:
        reasons.append("API 연결 확인 중입니다. 완료 후 검색 검증을 실행하세요.")
    stamp = settings.authentication_verified_at or ""
    request_id = _first_search_id(provider, settings.model, stamp)
    attempt = next((row for row in rows if row.request_id == request_id), None)
    if attempt is not None:
        reasons.append("이미 기록된 최초 검색 검증입니다. 실패·결과 불명 요청도 재전송하지 않습니다.")
    reasons.extend(_limit_reasons(settings, rows, now))
    return {"ready": not reasons, "reasons": reasons, "provider": provider, "model": settings.model,
            "reserved_usd": None, "accounting": "reported_usage", "request_id": request_id,
            "max_output_tokens": FIRST_SEARCH_OUTPUT_TOKENS,
            "authentication_at": stamp, "attempt_status": attempt.status if attempt else "",
            "reservation_id": attempt.id if attempt else "", "disclaimer": DISCLAIMER}


@dataclass(frozen=True)
class Reservation:
    id: str
    request_id: str
    reserved_usd: Decimal


class APIBudgetService:
    test_only = False

    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def readiness(self, provider: str, key_store, capability: str = "search") -> dict:
        result = _readiness(self.sessions, provider, key_store, capability, fake=self.test_only)
        result["test_only"] = self.test_only
        return result

    def reserve(self, *, provider: str, request_id: str, kind: str, model: str, max_input_tokens: int | None = None,
                max_output_tokens: int, key_store, max_search_calls: int = 0) -> Reservation:
        return self._reserve(provider=provider, request_id=request_id, kind=kind, model=model,
                             max_input_tokens=max_input_tokens, max_output_tokens=max_output_tokens,
                             key_store=key_store, max_search_calls=max_search_calls)

    def reserve_first_search(self, *, provider: str, model: str, authentication_at: str,
                             key_store, consent: bool, max_cost_usd: str | None = None) -> Reservation:
        """One explicitly approved bootstrap request per authentication.

        max_cost_usd is accepted only for compatibility with old clients.
        """
        _provider(provider)
        if consent is not True:
            raise APISettingsError("최초 웹 검색 검증에는 별도 실행 동의가 필요합니다.")
        if self.test_only:
            raise APISettingsError("실제 최초 검색 검증에는 Fake 예산의 인증 우회를 사용할 수 없습니다.")
        if model not in API_MODELS[provider] or model not in SEARCH_CONTEXT_BOUNDS:
            raise APISettingsError("이 모델의 웹 검색 계약은 미검증입니다.")
        if not isinstance(authentication_at, str) or not authentication_at:
            raise APISettingsError("인증 상태가 변경되었습니다. 화면을 새로 확인하세요.")
        return self._reserve(provider=provider, request_id=_first_search_id(provider, model, authentication_at),
                             kind="search", model=model,
                             max_output_tokens=FIRST_SEARCH_OUTPUT_TOKENS, key_store=key_store, max_search_calls=1,
                             first_search_authentication=authentication_at)

    def _reserve(self, *, provider: str, request_id: str, kind: str, model: str, max_input_tokens: int | None = None,
                 max_output_tokens: int, key_store, max_search_calls: int = 0,
                 first_search_authentication: str | None = None) -> Reservation:
        _provider(provider)
        if kind not in ("search", "analysis", "script") or not re.fullmatch(r"[A-Za-z0-9:._-]{1,128}", request_id):
            raise APISettingsError("API 요청 식별자와 작업 유형을 확인하세요.")
        for value, lower, upper in ((max_output_tokens, 1, 100_000),
                                    (max_search_calls, 0, 1)):
            if type(value) is not int or not lower <= value <= upper:
                raise APISettingsError("API 요청의 토큰·검색 상한이 불명확하여 차단합니다.")
        if (kind == "search") != (max_search_calls == 1):
            raise APISettingsError("검색 요청은 검색 도구 최대 1회를 명시해야 합니다.")
        now = utcnow()
        with self.sessions.begin() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            if session.scalar(select(APIRequestReservation.id).where(APIRequestReservation.request_id == request_id)):
                raise APISettingsError("이미 기록된 요청입니다. 성공 결과를 재사용하며 실패·결과 불명 요청은 재전송하지 않습니다.")
            settings = _read(session, provider)
            if settings.model != model:
                raise APISettingsError("저장된 API 모델과 실행 모델이 달라 다시 확인해야 합니다.")
            if (first_search_authentication is not None
                and settings.authentication_verified_at != first_search_authentication):
                raise APISettingsError("인증 상태가 변경되었습니다. 화면을 새로 확인하세요.")
            if first_search_authentication is not None and _value(session, f"api_{provider}_connection_check_id"):
                raise APISettingsError("API 연결 확인 중입니다. 완료 후 검색 검증을 실행하세요.")
            key = key_store.status() if key_store is not None else {"configured": False}
            reasons = _reasons(settings, key, kind, now, fake=self.test_only,
                               first_search=first_search_authentication is not None)
            if reasons:
                raise APISettingsError(" / ".join(reasons))
            # Token output limits remain transport/resource controls. They are not
            # a guessed dollar reservation or a claim about the final vendor bill.
            bounds = {"accounting": "reported_usage", "search_calls": max_search_calls}
            prices = _prices(settings)
            rows = list(session.scalars(select(APIRequestReservation).where(APIRequestReservation.provider == provider)))
            reasons = _limit_reasons(settings, rows, now)
            if reasons:
                raise APISettingsError(" / ".join(reasons))
            row = APIRequestReservation(id=uuid.uuid4().hex, request_id=request_id, provider=provider, kind=kind,
                                        model=model, status="reserved", reserved_usd="0", bounds=bounds,
                                        prices=prices, usage={}, test_only=self.test_only, created_at=now)
            session.add(row)
        return Reservation(row.id, request_id, Decimal(0))

    @staticmethod
    def _cost(usage: dict, prices: dict) -> Decimal:
        value = (Decimal(usage["prompt_tokens"]) * Decimal(prices["input"]) / 1_000_000
                 + Decimal(usage["completion_tokens"]) * Decimal(prices["output"]) / 1_000_000
                 + Decimal(usage["search_calls"]) * Decimal(prices["search"]) / 1000)
        return value.quantize(Decimal("0.000001"), rounding=ROUND_UP)

    def finish(self, reservation_id: str, *, status: str, usage: dict | None = None) -> None:
        if status not in ("success", "failed", "unknown", "cancelled"):
            raise APISettingsError("API 완료 상태를 확인하세요.")
        with self.sessions.begin() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            row = session.get(APIRequestReservation, reservation_id)
            if row is None or row.status != "reserved":
                raise APISettingsError("API 예약이 없거나 이미 종료되었습니다. 재전송하지 않습니다.")
            safe = {}
            for name in ("prompt_tokens", "completion_tokens", "search_calls"):
                value = (usage or {}).get(name)
                if name == "search_calls":
                    value = (usage or {}).get("web_search_requests", value)
                if name == "search_calls" and row.kind != "search":
                    value = 0
                if type(value) is int and 0 <= value <= 10_000_000:
                    safe[name] = value
            row.usage = safe
            row.status = status
            if len(safe) == 3:
                row.estimated_usd = str(self._cost(safe, row.prices))
                if row.bounds.get("accounting") == "reported_usage":
                    if safe["search_calls"] > row.bounds["search_calls"]:
                        row.status = "unknown"
                elif any(safe[name] > row.bounds[name] for name in safe):
                    row.status = "unknown"
                    row.reserved_usd = str(max(Decimal(row.reserved_usd), Decimal(row.estimated_usd)))
            elif status == "success" or row.bounds.get("accounting") == "reported_usage":
                row.status = "unknown"
            if status in ("cancelled", "unknown"):
                row.status = "unknown"
            row.finished_at = utcnow()


class FakeAPIBudgetService(APIBudgetService):
    """Tests inject this together with a Fake Provider; not selectable by GUI/env."""

    test_only = True
