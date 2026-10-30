"""Explicit API approvals and atomic request/response usage accounting.

Each new request is checked against its configured per-execution USD ceiling.
Token/tool bounds are conservative checks, not a vendor invoice. Reported usage
is retained after a response; historical totals never block an independent run.
Legacy reservations remain unchanged. Explicitly acknowledged unknown analyses
may permit new analyses only; request replay and all other gates still block.
Only an injected Fake budget skips proof of a real authenticated API connection.
Neither settings saves nor readiness reads perform any network operation.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_UP, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import APIRequestReservation, AuditLog, IntelligenceRun, utcnow

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
    "한 번의 요청에 설정한 한도와 입력·출력·검색 상한을 비교한 뒤 실행합니다. "
    "사용량 추정과 공급사 실제 청구액은 다르며 누적 사용액은 다음 요청을 제한하지 않습니다. "
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
                "search_check_summary"):
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
    search_approved: bool, request_limit_usd: str | None = None, monthly_limit_usd: str | None = None, input_price_per_1m: str,
    output_price_per_1m: str, search_price_per_1k: str, billing_confirmed: bool = False,
    account_remaining_usd: str = "",
) -> APISettings:
    _provider(provider)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", model or ""):
        raise APISettingsError("모델 이름은 영문·숫자·점·하이픈 80자 이내여야 합니다.")
    if (provider == "claude_api") != model.startswith("claude-"):
        raise APISettingsError("선택한 API 제공자의 모델을 입력하세요.")
    for value in (approved, search_enabled, search_approved):
        if type(value) is not bool:
            raise APISettingsError("승인 설정을 다시 확인하세요.")
    values = {
        "input_price_per_1m": _amount(input_price_per_1m, optional=True),
        "output_price_per_1m": _amount(output_price_per_1m, optional=True),
        "search_price_per_1k": _amount(search_price_per_1k, optional=True),
    }
    # Keep legacy monthly values unchanged. Only the explicit request ceiling gates execution.
    if request_limit_usd is not None:
        values["request_limit_usd"] = _amount(request_limit_usd)
    # Deprecated balance arguments remain accepted for old clients. Neither a
    # normal save nor key/model changes overwrite the retained historical values.
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        old = _read(session, provider)
        if approved and values.get("request_limit_usd", old.request_limit_usd) <= 0:
            raise APISettingsError("API 사용 승인에는 0보다 큰 1회 실행 USD 한도가 필요합니다.")
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
    if settings.request_limit_usd <= 0:
        reasons.append("1회 실행 비용 한도 필요")
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
        reviews = _unknown_analysis_reviews(session, settings, rows)
        rejected = _confirmed_rejections(session, rows)
    key = key_store.status() if key_store is not None else {"configured": False}
    usage = _usage(rows, now)
    reasons = _reasons(settings, key, capability, now, fake=fake)
    acknowledged = {row["id"] for row in reviews if row["acknowledged"]}
    reasons.extend(_limit_reasons(settings, rows, now, capability=capability, acknowledged=acknowledged,
                                 rejected=rejected))
    auth = settings.verified_model == settings.model and _recent(settings.authentication_verified_at, now)
    return {"ready": not reasons, "state": "ready" if not reasons else "blocked", "reasons": reasons,
            "provider": provider, "model": settings.model, "capability": capability, "key": key,
            "configured": bool(key.get("configured")), "authentication_verified": auth,
            "request_succeeded": bool(auth and settings.request_succeeded_at), "settings": settings,
            "connection_check": asdict(read_connection_check(sessions, provider)),
            "usage": usage, "unknown_analysis_reviews": reviews,
            "acknowledged_unknown_analyses": len(acknowledged),
            "disclaimer": DISCLAIMER, "account_evidence": "USER CONFIRMED" if
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


def _unknown_fingerprint(row: APIRequestReservation) -> str:
    # Bind the confirmation to the entire original journal entry without copying
    # its payload into the audit log. A changed entry requires a fresh review.
    original = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    encoded = json.dumps(original, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _unknown_analysis_reviews(session: Session, settings: APISettings,
                              rows: list[APIRequestReservation]) -> list[dict]:
    confirmations = set()
    for entry in session.scalars(select(AuditLog).where(AuditLog.event == "api_unknown_analysis_ack")):
        try:
            value = json.loads(entry.message)
            if isinstance(value, dict) and value.get("scope") == "new_analysis_only":
                confirmations.add((value["provider"], value["model"], value["reservation_id"], value["fingerprint"]))
        except (ValueError, KeyError, TypeError):
            continue
    reviews = []
    for row in rows:
        if (row.status != "unknown" or row.kind != "analysis" or row.finished_at is None
                or row.model != settings.model):
            continue
        fingerprint = _unknown_fingerprint(row)
        reviews.append({"id": row.id, "request_id": row.request_id, "model": row.model,
                        "fingerprint": fingerprint,
                        "acknowledged": (settings.provider, settings.model, row.id, fingerprint) in confirmations})
    return reviews


def acknowledge_unknown_analysis(sessions: sessionmaker[Session], provider: str, *, reservation_id: str,
                                 fingerprint: str, consent: bool) -> None:
    """Append a local risk acknowledgement; never alter/replay the old request.

    This is not execution consent, an authentication/billing proof or a refund.
    Search and script requests cannot use this exception. Duplicate POSTs are
    idempotent, and the original unique request ID remains permanently blocked.
    """
    _provider(provider)
    if consent is not True:
        raise APISettingsError("기존 요청의 처리·과금 미확인 상태에 대한 명시적 인지 확인이 필요합니다.")
    if not re.fullmatch(r"[a-f0-9]{32}", reservation_id) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise APISettingsError("결과 불명 요청 정보를 다시 확인하세요.")
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        settings = _read(session, provider)
        row = session.get(APIRequestReservation, reservation_id)
        if row is None or row.provider != provider:
            raise APISettingsError("해당 API의 결과 불명 분석 요청을 찾을 수 없습니다.")
        reviews = _unknown_analysis_reviews(session, settings, [row])
        if not reviews or reviews[0]["fingerprint"] != fingerprint:
            raise APISettingsError("요청 상태 또는 모델이 변경되었습니다. 결과 불명 분석 기록을 다시 확인하세요.")
        if reviews[0]["acknowledged"]:
            return
        message = {"provider": provider, "model": settings.model, "reservation_id": row.id,
                   "fingerprint": fingerprint, "scope": "new_analysis_only"}
        session.add(AuditLog(level="info", event="api_unknown_analysis_ack",
                             message=json.dumps(message, separators=(",", ":"))))


def _confirmed_rejections(session: Session, rows: list[APIRequestReservation]) -> set[str]:
    """Read-only interpretation of recorded Claude rejection evidence, not a refund.

    Legacy unknown rows and acknowledgements stay byte-for-byte intact. Only a
    matching, completed failure with an explicit invalid-request response can
    stop blocking a *new* request. Original request IDs remain non-replayable.
    """
    rejected = set()
    for row in rows:
        match = re.fullmatch(r"intelligence:([1-9][0-9]*)", row.request_id)
        if (row.provider != "claude_api" or row.kind not in {"analysis", "script"}
                or row.status not in {"reserved", "unknown"} or not match
                or (row.status == "unknown" and row.finished_at is None)
                or not isinstance(row.usage, dict)
                or any(type(value) is not int or value != 0 for value in row.usage.values())):
            continue
        run = session.get(IntelligenceRun, int(match[1]))
        if (not run or run.status != "failed" or run.finished_at is None
                or run.provider != row.provider or run.kind != row.kind
                or not isinstance(run.options, dict) or run.options.get("model") != row.model
                or not isinstance(run.result, dict)):
            continue
        detail = run.result.get(f"{row.kind}_failure")
        if (isinstance(detail, dict) and detail.get("failure_reason") == "request_rejected"
                and type(detail.get("http_status")) is int and detail["http_status"] == 400
                and detail.get("error_type") == "invalid_request_error"):
            rejected.add(row.id)
    return rejected


def _card_unknown_review(session, settings, rows, context):
    rejected = _confirmed_rejections(session, rows)
    unknown = [r for r in rows if r.status == "unknown" and r.id not in rejected]
    if (not unknown or any(r.status == "reserved" for r in rows)
            or any(r.finished_at is None for r in unknown)):
        return {"token": "", "requests": [], "ids": set()}
    value = {"scope": "new_feed_card_once", "model": settings.model, "context": context,
             "unknowns": {r.id: _unknown_fingerprint(r) for r in unknown}}
    token = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"token": token, "requests": [r.request_id for r in unknown], "ids": {r.id for r in unknown}}


def _limit_reasons(settings: APISettings, rows: list[APIRequestReservation], now: datetime, *,
                   capability: str = "search", acknowledged: set[str] | None = None,
                   script_exception: bool = False, rejected: set[str] | None = None,
                   scoped_unknowns: set[str] | None = None) -> list[str]:
    reasons = []
    acknowledged = acknowledged or set()
    rejected = rejected or set()
    scoped_unknowns = scoped_unknowns or set()
    if any(row.status == "reserved" or (row.status == "unknown" and row.id not in rejected and row.id not in scoped_unknowns and not (
            (capability == "analysis" or script_exception) and row.id in acknowledged)) for row in rows):
        reasons.append("진행 중이거나 결과 불명인 API 요청이 있어 새 호출을 차단합니다.")
    # Preserve all usage/unknown records. Completed historical spending is not a run limit.
    return reasons


def allow_script_once(sessions: sessionmaker[Session], provider: str, *, analysis_id: int,
                      model: str, duration: int, consent: bool, previous_script_id: int | None = None) -> None:
    """Append one scoped approval; never edit the old unknown or acknowledgement."""
    _provider(provider)
    if consent is not True or type(analysis_id) is not int or duration not in (30, 45, 60):
        raise APISettingsError("대상 분석·길이와 이번 대본 1회에 대한 명시적 승인이 필요합니다.")
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        settings = _read(session, provider)
        analysis = session.get(IntelligenceRun, analysis_id)
        if (not analysis or analysis.kind != "analysis" or analysis.status != "success"
                or analysis.provider != provider or analysis.options.get("model") != model or settings.model != model):
            raise APISettingsError("성공한 분석과 저장된 API·모델이 일치해야 합니다.")
        rows = list(session.scalars(select(APIRequestReservation).where(APIRequestReservation.provider == provider)))
        reviewed = _unknown_analysis_reviews(session, settings, rows)
        acknowledged = {row["id"] for row in reviewed if row["acknowledged"]}
        if not acknowledged or _limit_reasons(settings, rows, utcnow(), capability="analysis", acknowledged=acknowledged,
                                              rejected=_confirmed_rejections(session, rows)):
            raise APISettingsError("기존 결과 불명 인지 확인과 다른 실행 차단 조건을 먼저 확인하세요.")
        previous = [run for run in session.scalars(select(IntelligenceRun).where(IntelligenceRun.kind == "script"))
                    if run.options.get("analysis_run_id") == analysis_id]
        if previous_script_id is not None:
            if (type(previous_script_id) is not int or not previous
                    or max(run.id for run in previous) != previous_script_id):
                raise APISettingsError("명시적으로 재검증할 마지막 실패 대본을 확인하세요.")
            for run in previous:
                request = session.scalar(select(APIRequestReservation).where(
                    APIRequestReservation.request_id == f"intelligence:{run.id}"))
                if (run.status != "failed" or run.provider != provider or run.options.get("model") != model
                        or run.options.get("duration") != duration or request is None or request.status != "failed"
                        or request.provider != provider or request.model != model or request.kind != "script"
                        or request.finished_at is None or request.estimated_usd is None
                        or any(type(request.usage.get(key)) is not int for key in
                               ("prompt_tokens", "completion_tokens", "search_calls"))):
                    raise APISettingsError("성공·진행 중·결과 불명 대본은 재검증 승인 대상이 아닙니다.")
        elif previous:
            raise APISettingsError("이미 대본 요청 기록이 있는 분석입니다. 자동 재생성하지 않습니다.")
        consumed = {json.loads(entry.message).get("approval_id") for entry in session.scalars(
            select(AuditLog).where(AuditLog.event == "api_script_once_consumed"))}
        for entry in session.scalars(select(AuditLog).where(AuditLog.event == "api_script_once_approval")):
            value = json.loads(entry.message)
            if value.get("analysis_id") == analysis_id and (
                    previous_script_id is None or value.get("previous_script_id") == previous_script_id
                    or entry.id not in consumed):
                raise APISettingsError("이 분석의 대본 1회 승인이 이미 기록되어 있습니다. 재승인하지 않습니다.")
        value = {"analysis_id": analysis_id, "provider": provider, "model": model, "duration": duration,
                 "analysis_fingerprint": _unknown_fingerprint(analysis),
                 "unknowns": {row["id"]: row["fingerprint"] for row in reviewed if row["acknowledged"]},
                 "expires_at": (utcnow() + timedelta(minutes=30)).isoformat()}
        if previous_script_id is not None:
            value.update(previous_script_id=previous_script_id,
                         previous_scripts={str(run.id): _unknown_fingerprint(run) for run in previous})
        session.add(AuditLog(level="info", event="api_script_once_approval",
                             message=json.dumps(value, separators=(",", ":"))))


def _script_approval(session: Session, settings: APISettings, request_id: str, kind: str,
                     rows: list[APIRequestReservation], acknowledged: set[str]) -> int | None:
    """Resolve an exact script run, then consume its approval inside the reservation transaction."""
    if kind != "script" or not re.fullmatch(r"intelligence:[1-9][0-9]*", request_id):
        return None
    run = session.get(IntelligenceRun, int(request_id.split(":")[1]))
    if not run or run.kind != "script" or run.status != "running" or run.provider != settings.provider:
        return None
    analysis_id = run.options.get("analysis_run_id")
    analysis = session.get(IntelligenceRun, analysis_id) if type(analysis_id) is int else None
    if not analysis or analysis.kind != "analysis" or analysis.status != "success":
        return None
    for entry in session.scalars(select(AuditLog).where(AuditLog.event == "api_script_once_approval")):
        try:
            grant = json.loads(entry.message)
            if (grant.get("analysis_id") != analysis_id or grant.get("provider") != settings.provider
                    or grant.get("model") != settings.model or run.options.get("model") != settings.model
                    or grant.get("duration") != run.options.get("duration")
                    or grant.get("analysis_fingerprint") != _unknown_fingerprint(analysis)
                    or datetime.fromisoformat(grant["expires_at"]) <= utcnow()):
                continue
            expected = {row.id: _unknown_fingerprint(row) for row in rows if row.status == "unknown"}
            if not expected or grant.get("unknowns") != expected or not set(expected) <= acknowledged:
                continue
            previous = {str(other.id): _unknown_fingerprint(other) for other in session.scalars(
                select(IntelligenceRun).where(IntelligenceRun.kind == "script", IntelligenceRun.id != run.id))
                if other.options.get("analysis_run_id") == analysis_id}
            if previous != grant.get("previous_scripts", {}):
                continue
            if any(json.loads(used.message).get("approval_id") == entry.id for used in session.scalars(
                    select(AuditLog).where(AuditLog.event == "api_script_once_consumed"))):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        return entry.id
    return None


def first_search_readiness(sessions: sessionmaker[Session], provider: str, key_store) -> dict:
    """Local readiness for one explicit check; no speculative quote or request."""
    now = utcnow()
    with sessions() as session:
        settings = _read(session, provider)
        rows = list(session.scalars(select(APIRequestReservation).where(APIRequestReservation.provider == provider)))
        connection_busy = bool(_value(session, f"api_{provider}_connection_check_id"))
        rejected = _confirmed_rejections(session, rows)
    key = key_store.status() if key_store is not None else {"configured": False}
    reasons = _reasons(settings, key, "search", now, first_search=True)
    if connection_busy:
        reasons.append("API 연결 확인 중입니다. 완료 후 검색 검증을 실행하세요.")
    stamp = settings.authentication_verified_at or ""
    request_id = _first_search_id(provider, settings.model, stamp)
    attempt = next((row for row in rows if row.request_id == request_id), None)
    if attempt is not None:
        reasons.append("이미 기록된 최초 검색 검증입니다. 실패·결과 불명 요청도 재전송하지 않습니다.")
    reasons.extend(_limit_reasons(settings, rows, now, rejected=rejected))
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

    def feed_card_review(self, key_store, context):
        """Preview only. GET never saves acknowledgement or grants an execution."""
        with self.sessions() as session:
            settings = _read(session, "claude_api")
            rows = list(session.scalars(select(APIRequestReservation).where(
                APIRequestReservation.provider == "claude_api")))
            review = _card_unknown_review(session, settings, rows, context)
            reasons = _reasons(settings, key_store.status(), "script", utcnow(), fake=self.test_only)
            reasons += _limit_reasons(settings, rows, utcnow(), capability="script",
                                     rejected=_confirmed_rejections(session, rows) | review["ids"])
        return {"token": review["token"], "requests": review["requests"],
                "ready": bool(review["token"]) and not reasons}

    def reserve_feed_card(self, *, run_id, model, key_store, review_token="", review_consent=False,
                          max_output_tokens=2000):
        if review_token and review_consent is not True:
            raise APISettingsError("기존 결과 불명 요청을 확인하고 이번 카드 1회에 동의해 주세요.")
        return self._reserve(provider="claude_api", request_id=f"feed-card:{run_id}", kind="script",
                             model=model, max_output_tokens=max_output_tokens, key_store=key_store,
                             card_review_token=review_token if review_consent is True else "")

    def reserve(self, *, provider: str, request_id: str, kind: str, model: str, max_input_tokens: int | None = None,
                max_output_tokens: int, key_store, max_search_calls: int = 0) -> Reservation:
        return self._reserve(provider=provider, request_id=request_id, kind=kind, model=model,
                             max_input_tokens=max_input_tokens, max_output_tokens=max_output_tokens,
                             key_store=key_store, max_search_calls=max_search_calls)

    def reserve_episode_story(self, *, provider, request_id, model, max_output_tokens, key_store, story_review):
        return self._reserve(provider=provider, request_id=request_id, kind="script", model=model,
                             max_output_tokens=max_output_tokens, key_store=key_store,
                             episode_review=story_review)

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
                 first_search_authentication: str | None = None, card_review_token: str = "", episode_review=None) -> Reservation:
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
            from .api_providers import MAX_CURATION_REQUEST_BYTES, MAX_REQUEST_BYTES
            # Curation schemas have a larger transport ceiling; stories retain the normal one.
            direct_bound = (MAX_CURATION_REQUEST_BYTES if provider == "claude_api" and kind == "analysis"
                            else MAX_REQUEST_BYTES)
            input_bound = SEARCH_CONTEXT_BOUNDS[model] if max_search_calls else direct_bound
            prices = _prices(settings)
            upper = self._cost({"prompt_tokens": input_bound, "completion_tokens": max_output_tokens,
                                "search_calls": max_search_calls}, prices)
            if upper > settings.request_limit_usd:
                raise APISettingsError("이번 요청의 입력·출력·검색 상한이 1회 실행 비용 한도를 넘습니다.")
            bounds = {"accounting": "per_execution", "prompt_tokens": input_bound,
                      "completion_tokens": max_output_tokens, "search_calls": max_search_calls,
                      "request_limit_usd": str(settings.request_limit_usd)}
            rows = list(session.scalars(select(APIRequestReservation).where(APIRequestReservation.provider == provider)))
            reviews = _unknown_analysis_reviews(session, settings, rows)
            acknowledged = {row["id"] for row in reviews if row["acknowledged"]}
            script_approval = _script_approval(session, settings, request_id, kind, rows, acknowledged)
            card_ids = set()
            if card_review_token:
                match = re.fullmatch(r"feed-card:([1-9][0-9]*)", request_id)
                run = session.get(IntelligenceRun, int(match[1])) if match else None
                if (provider != "claude_api" or kind != "script" or max_search_calls != 0
                        or not run or run.kind != "feed_card" or run.status != "running"
                        or run.provider != provider or run.options.get("model") != model):
                    raise APISettingsError("이번 카드 구성에만 적용할 수 있는 인지 확인입니다.")
                context = {k: run.options.get(k) for k in ("article_id", "analysis_id", "rank", "draft_id")}
                context["source"] = run.evidence
                review = _card_unknown_review(session, settings, rows, context)
                if not review["token"] or card_review_token != review["token"]:
                    raise APISettingsError("뉴스·모델·결과 불명 기록이 변경되었습니다. 화면을 새로 확인하세요.")
                card_ids = review["ids"]
            episode_ids = set()
            if episode_review is not None:
                from newsflow.character.story_review import consume

                episode_ids = consume(session, settings, rows, episode_review,
                    request_id=request_id, kind=kind, model=model, max_output_tokens=max_output_tokens)
            from .comparison_approval import CONSUMED, authorize_step

            comparison = authorize_step(session, settings, request_id, kind, rows, max_output_tokens)
            reasons = _limit_reasons(settings, rows, now, capability=kind, acknowledged=acknowledged,
                                     script_exception=script_approval is not None,
                                     rejected=_confirmed_rejections(session, rows) | card_ids,
                                     scoped_unknowns=episode_ids | (set(comparison["unknown_ids"]) if comparison else set()))
            if reasons:
                raise APISettingsError(" / ".join(reasons))
            row = APIRequestReservation(id=uuid.uuid4().hex, request_id=request_id, provider=provider, kind=kind,
                                        model=model, status="reserved", reserved_usd=str(upper), bounds=bounds,
                                        prices=prices, usage={}, test_only=self.test_only, created_at=now)
            session.add(row)
            if comparison:
                session.add(AuditLog(level='info', event=CONSUMED, message=json.dumps(
                    comparison, separators=(',', ':'))))
            if card_ids:
                session.add(AuditLog(level="info", event="api_feed_card_once_ack", message=json.dumps({
                    "scope": "new_feed_card_once", "request_id": request_id, "model": model,
                    "review_fingerprint": card_review_token, "unknown_ids": sorted(card_ids)}, separators=(",", ":"))))
            if script_approval is not None:
                session.add(AuditLog(level="info", event="api_script_once_consumed", message=json.dumps(
                    {"approval_id": script_approval, "request_id": request_id}, separators=(",", ":"))))
        return Reservation(row.id, request_id, upper)

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
            rejected = status == "failed" and row.id in _confirmed_rejections(session, [row])
            row.status = status
            if len(safe) == 3:
                row.estimated_usd = str(self._cost(safe, row.prices))
                if row.bounds.get("accounting") == "reported_usage":
                    if safe["search_calls"] > row.bounds["search_calls"]:
                        row.status = "unknown"
                elif any(safe[name] > row.bounds[name] for name in safe):
                    row.status = "unknown"
                    row.reserved_usd = str(max(Decimal(row.reserved_usd), Decimal(row.estimated_usd)))
            elif not rejected and (status == "success" or row.bounds.get("accounting") in {"reported_usage", "per_execution"}):
                row.status = "unknown"
            if status in ("cancelled", "unknown"):
                row.status = "unknown"
            row.finished_at = utcnow()
            from .comparison_approval import record_finished

            record_finished(session, row)


class FakeAPIBudgetService(APIBudgetService):
    """Tests inject this together with a Fake Provider; not selectable by GUI/env."""

    test_only = True
