"""AI video provider settings, model catalog, paid-generation gate and cost limits (Phase 5D).

Kept apart from the OpenAI settings on purpose: its own provider switch (off by default), its
own dated approval, a per-execution cost limit in the user's currency, its own key file
and its own usage table. A generation runs only when every check here passes at that moment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import AppSetting, VideoAIModel, VideoAIUsage, utcnow

from .costs import CURRENCIES, MAX_PRICE_PER_SECOND, CostError, money, parse_durations, parse_money
from .model_contracts import check_model_contract

PROVIDERS = {"off": "사용 안 함 (기본 FFmpeg 제작만)", "higgsfield": "Higgsfield (유료 · 승인 필요)"}
# The official SDK (BASE_URL) and app templates (HF_API_BASE_URL) both use this one host.
HOSTS = ("api.higgsfield.ai",)
RESOLUTIONS = ("480p", "720p", "1080p")
MODEL_LIMIT = 10
PATH_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,40}(/[a-z0-9][a-z0-9._-]{0,40}){1,6}")
# Dated official schema candidates (2026-10-16); actual access/prices remain unverified.
# Exclude Kling 2.6 and Wan 2.6: their schemas differ from our four-field request body.
CANDIDATE_PATHS = (
    "kling-video/v3.0-turbo/text-to-video",
    "alibaba/wan-3.0/text-to-video",
    "alibaba/wan-3.0-prime/text-to-video",
    "wan/v2.7/text-to-video",
    "pixverse/v6/text-to-video",
    "lightricks/ltx-2.5/text-to-video/fast",
)
DISCLAIMER = (
    "모델 경로·허용 길이·단가는 사용자가 Higgsfield 공식 문서와 대시보드에서 확인해 입력한 값입니다. "
    "예상 비용은 참고용이며 실제 청구는 공급사 대시보드에서 확인하세요."
)


class VideoSettingsError(Exception):
    pass


@dataclass(frozen=True)
class VideoAISettings:
    provider: str = "off"
    host: str = HOSTS[0]
    approved_at: str | None = None
    monthly_limit: Decimal = Decimal(0)
    job_limit: Decimal = Decimal(0)
    currency: str = "USD"
    max_active: int = 2
    timeout_minutes: int = 30
    poll_seconds: int = 10

    @property
    def approved(self) -> bool:
        return bool(self.approved_at)


def _value(session: Session, key: str) -> str | None:
    row = session.get(AppSetting, key)
    return row.value if row else None


def _set(session: Session, key: str, value: str) -> None:
    row = session.get(AppSetting, key)
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))


def _int(raw: str | None, default: int, low: int, high: int) -> int:
    return int(raw) if raw and re.fullmatch(r"[0-9]{1,4}", raw) and low <= int(raw) <= high else default


def _money(raw: str | None) -> Decimal:
    try:
        return parse_money(raw) or Decimal(0)
    except CostError:
        return Decimal(0)


def read_settings(sessions: sessionmaker[Session]) -> VideoAISettings:
    with sessions() as session:
        raw = {key: _value(session, f"video_ai_{key}") for key in (
            "provider", "host", "approved_at", "monthly_limit", "job_limit", "currency", "max_active",
            "timeout_minutes", "poll_seconds",
        )}
    return VideoAISettings(
        provider=raw["provider"] if raw["provider"] in PROVIDERS else "off",
        host=raw["host"] if raw["host"] in HOSTS else HOSTS[0],
        approved_at=raw["approved_at"] or None,
        monthly_limit=_money(raw["monthly_limit"]),
        job_limit=_money(raw["job_limit"]),
        currency=raw["currency"] if raw["currency"] in CURRENCIES else "USD",
        max_active=_int(raw["max_active"], 2, 1, 4),
        timeout_minutes=_int(raw["timeout_minutes"], 30, 5, 120),
        poll_seconds=_int(raw["poll_seconds"], 10, 5, 60),
    )


def write_settings(
    sessions: sessionmaker[Session], *, provider: str, host: str, approved: bool, monthly_limit: str | None = None,
    job_limit: str, currency: str, max_active: int, timeout_minutes: int, poll_seconds: int,
) -> VideoAISettings:
    if provider not in PROVIDERS:
        raise VideoSettingsError("AI 영상 공급사를 다시 선택하세요.")
    if host not in HOSTS:
        raise VideoSettingsError("API 호스트는 목록에서만 선택할 수 있습니다.")
    if currency not in CURRENCIES:
        raise VideoSettingsError("통화는 USD 또는 KRW 중에서 선택하세요.")
    try:
        job = parse_money(job_limit) or Decimal(0)
    except CostError as exc:
        raise VideoSettingsError(str(exc)) from None
    for value, low, high, label in (
        (max_active, 1, 4, "동시 생성 수는 1~4"), (timeout_minutes, 5, 120, "장면별 제한시간은 5~120분"),
        (poll_seconds, 5, 60, "상태 확인 간격은 5~60초"),
    ):
        if type(value) is not int or not low <= value <= high:
            raise VideoSettingsError(f"{label} 사이여야 합니다.")
    if approved and job <= 0:
        raise VideoSettingsError("유료 영상 승인에는 0보다 큰 1회 실행 한도가 필요합니다.")
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        previous_currency = _value(session, "video_ai_currency") or "USD"
        if currency != previous_currency and _month_rows(session):
            raise VideoSettingsError("이번 달 사용 기록이 있어 통화를 바꿀 수 없습니다. 다음 달에 바꾸세요.")
        if currency != previous_currency:
            # Per-second prices carry no currency of their own: each must be re-entered and
            # re-confirmed in the new one before any model can be used again.
            for model in session.scalars(select(VideoAIModel)):
                model.confirmed_at = None
        previous = _value(session, "video_ai_approved_at")
        values = {
            "provider": provider, "host": host, "job_limit": money(job),
            "currency": currency, "max_active": str(max_active), "timeout_minutes": str(timeout_minutes),
            "poll_seconds": str(poll_seconds),
            # A dated, durable decision; re-saving keeps the original timestamp, unchecking clears it.
            "approved_at": (previous or utcnow().isoformat()) if approved and provider != "off" else "",
        }
        for key, value in values.items():
            _set(session, f"video_ai_{key}", value)
    return read_settings(sessions)


# --------------------------------------------------------------------------- model catalog

@dataclass(frozen=True)
class ModelEntry:
    id: int
    provider: str
    path: str
    label: str
    price_per_second: Decimal | None
    durations: tuple[int, ...]
    resolution: str
    confirmed: bool

    @property
    def usable(self) -> bool:
        return self.confirmed and self.price_per_second is not None and self.price_per_second > 0


def _entry(row: VideoAIModel) -> ModelEntry:
    try:
        price = parse_money(row.price_per_second, maximum=MAX_PRICE_PER_SECOND)
    except CostError:
        price = None
    try:
        durations = parse_durations(row.durations)
    except CostError:
        durations = (5,)
    return ModelEntry(row.id, row.provider, row.path, row.label, price, durations, row.resolution, row.confirmed_at is not None)


def list_models(sessions: sessionmaker[Session], provider: str = "higgsfield") -> list[ModelEntry]:
    with sessions() as session:
        rows = session.scalars(select(VideoAIModel).where(VideoAIModel.provider == provider).order_by(VideoAIModel.id))
        return [_entry(row) for row in rows]


def find_model(sessions: sessionmaker[Session], path: str, provider: str = "higgsfield") -> ModelEntry | None:
    return next((m for m in list_models(sessions, provider) if m.path == path), None)


def validate_path(path: str) -> str:
    path = (path or "").strip()
    if len(path) > 160 or not PATH_PATTERN.fullmatch(path) or ".." in path:
        raise VideoSettingsError("모델 경로는 공식 문서의 소문자 경로 형식(예: vendor/model/text-to-video)으로 입력하세요.")
    return path


def validate_model_fields(path: str, label: str, durations: str, resolution: str):
    """Validate locally before a price lookup can send any request."""
    path = validate_path(path)
    label = (label or "").strip()
    if not 1 <= len(label) <= 80 or any(ord(c) < 32 for c in label):
        raise VideoSettingsError("표시 이름은 1~80자로 입력하세요.")
    if resolution not in RESOLUTIONS:
        raise VideoSettingsError("해상도는 480p·720p·1080p 중에서 선택하세요.")
    try:
        allowed = parse_durations(durations)
    except CostError as exc:
        raise VideoSettingsError(str(exc)) from None
    return path, label, allowed


def model_version(row: VideoAIModel) -> tuple:
    return tuple(getattr(row, name) for name in (
        "path", "label", "price_per_second", "durations", "resolution", "confirmed_at", "updated_at"))


def model_quotes(sessions: sessionmaker[Session]) -> dict:
    """Dated, condition-bound numeric evidence; no credentials or supplier prose."""
    result = {}
    with sessions() as session:
        currency = _value(session, "video_ai_currency") or "USD"
        for model in session.scalars(select(VideoAIModel)):
            raw = _value(session, f"video_ai_model_quote_{model.id}")
            try:
                value = json.loads(raw or "null")
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict) and (
                value.get("path"), value.get("resolution"), value.get("durations"),
                value.get("unit_price"), value.get("currency"),
            ) == (model.path, model.resolution, model.durations, model.price_per_second, currency):
                try:
                    value["checked_time"] = datetime.fromisoformat(value["checked_at"])
                except (KeyError, TypeError, ValueError):
                    continue
                result[model.id] = value
    return result


def save_model(
    sessions: sessionmaker[Session], *, path: str, label: str, price_per_second: str, durations: str,
    resolution: str, confirmed: bool, provider: str = "higgsfield", model_id: int | None = None,
    official_quote: dict | None = None, expected_version: tuple | None = None,
    expected_currency: str | None = None,
) -> ModelEntry:
    path, label, allowed = validate_model_fields(path, label, durations, resolution)
    try:
        price = parse_money(price_per_second, maximum=MAX_PRICE_PER_SECOND)
    except CostError as exc:
        raise VideoSettingsError(str(exc)) from None
    if confirmed and check_model_contract(path, allowed, resolution)[0] == "FAIL":
        raise VideoSettingsError("공식 모델의 입력 규격을 확인하세요. 가격 확인과는 별개입니다.")
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        if expected_currency is not None and (_value(session, "video_ai_currency") or "USD") != expected_currency:
            raise VideoSettingsError("견적 조회 중 통화가 바뀌었습니다. 기존 가격을 유지했습니다. 새로고침해 확인하세요.")
        clash = session.scalar(select(VideoAIModel.id).where(
            VideoAIModel.provider == provider, VideoAIModel.path == path, VideoAIModel.id != (model_id or -1)))
        if clash is not None:
            raise VideoSettingsError("이미 등록된 모델 경로입니다.")
        if model_id is None:
            count = len(list(session.scalars(select(VideoAIModel.id).where(VideoAIModel.provider == provider))))
            if count >= MODEL_LIMIT:
                raise VideoSettingsError(f"모델은 최대 {MODEL_LIMIT}개까지 등록할 수 있습니다.")
            row = VideoAIModel(provider=provider, path="", price_per_second="", durations="", resolution="")
            session.add(row)
        else:
            row = session.get(VideoAIModel, model_id)
            if row is None or row.provider != provider:
                raise VideoSettingsError("모델을 찾지 못했습니다.")
            if expected_version is not None and model_version(row) != expected_version:
                raise VideoSettingsError("견적 조회 중 모델이 바뀌었습니다. 기존 값을 덮어쓰지 않았습니다. 새로고침해 확인하세요.")
        changed = (row.path, row.price_per_second, row.durations, row.resolution) != (
            path, money(price) if price is not None else "", ",".join(map(str, allowed)), resolution)
        row.path, row.label, row.resolution = path, label, resolution
        row.price_per_second = money(price) if price is not None else ""
        row.durations = ",".join(map(str, allowed))
        # Any change to what is billed needs a fresh confirmation against the official docs.
        if not confirmed:
            row.confirmed_at = None
        elif changed or row.confirmed_at is None:
            row.confirmed_at = utcnow()
        row.updated_at = utcnow()
        session.flush()
        if official_quote is not None:
            if (official_quote.get("path"), official_quote.get("resolution"),
                official_quote.get("durations"), official_quote.get("unit_price"),
                official_quote.get("currency")) != (path, resolution, row.durations, row.price_per_second, "USD"):
                raise VideoSettingsError("견적 조건이 모델 설정과 일치하지 않습니다. 기존 가격을 유지했습니다.")
            _set(session, f"video_ai_model_quote_{row.id}", json.dumps(official_quote, ensure_ascii=False))
        return _entry(row)


def delete_model(sessions: sessionmaker[Session], model_id: int, provider: str = "higgsfield") -> None:
    with sessions.begin() as session:
        row = session.get(VideoAIModel, model_id)
        if row is None or row.provider != provider:
            raise VideoSettingsError("모델을 찾지 못했습니다.")
        session.delete(row)


# --------------------------------------------------------------------------- usage and limits

def month_start(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return datetime(now.year, now.month, 1, tzinfo=UTC)


# Every reserved attempt counts except one known never to have been sent (refund rules are NOT VERIFIED).
COUNTED = ("reserved", "submitted", "completed", "failed", "unknown", "canceled")


def _month_rows(session: Session) -> list[VideoAIUsage]:
    return list(session.scalars(select(VideoAIUsage).where(
        VideoAIUsage.created_at >= month_start(), VideoAIUsage.status.in_(COUNTED))))


def _sum(rows) -> Decimal:
    total = Decimal(0)
    for row in rows:
        try:
            total += parse_money(row.estimated_cost) or Decimal(0)
        except CostError:
            continue
    return total


def usage_this_month(sessions: sessionmaker[Session]) -> dict:
    """Reserved estimates this month. Only requests known not to have been sent are excluded."""
    with sessions() as session:
        rows = _month_rows(session)
        return {"spent": _sum(rows), "requests": len(rows), "since": month_start().date().isoformat()}


def plan_spent(session: Session, plan_id: int, currency: str | None = None) -> Decimal:
    query = select(VideoAIUsage).where(VideoAIUsage.plan_id == plan_id, VideoAIUsage.status.in_(COUNTED))
    if currency is not None:
        query = query.where(VideoAIUsage.currency == currency)
    return _sum(session.scalars(query))


CURRENCY_CHANGED = "통화가 바뀌어 이 계획에는 더 생성할 수 없습니다(이전 사용액과 단위가 다름). 새 계획을 만드세요."


def plan_currency_mismatch(session: Session, plan_id: int, currency: str) -> bool:
    """True when this plan already counted spend in another currency (sums would mix units)."""
    return session.scalar(select(VideoAIUsage.id).where(
        VideoAIUsage.plan_id == plan_id, VideoAIUsage.status.in_(COUNTED), VideoAIUsage.currency != currency,
    ).limit(1)) is not None


LEDGER_INVALID = "AI 영상 비용 기록을 검증하지 못했습니다. 원본 DB를 보존하고 기록을 확인하기 전에는 새 요청을 보내지 않습니다."


def ledger_valid(session: Session) -> bool:
    """Do not silently omit malformed ledger entries when deciding whether more can be spent."""
    for row in session.scalars(select(VideoAIUsage)):
        if row.status not in (*COUNTED, "not_sent") or row.currency not in CURRENCIES:
            return False
        try:
            parse_money(row.estimated_cost, blank=False)
        except CostError:
            return False
    return True


def check_budget(session: Session, settings: VideoAISettings, plan_id: int, batch: Decimal) -> None:
    """Check this explicit generation batch, keeping every historical ledger entry."""
    if not ledger_valid(session):
        raise VideoSettingsError(LEDGER_INVALID)
    if settings.job_limit <= 0:
        raise VideoSettingsError("1회 실행 한도가 설정되지 않아 AI 영상을 생성하지 않습니다.")
    if plan_currency_mismatch(session, plan_id, settings.currency):
        raise VideoSettingsError(CURRENCY_CHANGED)
    if not batch.is_finite() or batch <= 0:
        raise VideoSettingsError("이번 영상 요청의 견적을 먼저 확인하세요.")
    if batch > settings.job_limit:
        raise VideoSettingsError(
            f"1회 실행 한도를 넘습니다: 이번 요청 예상 {money(batch)} > "
            f"한도 {money(settings.job_limit)} {settings.currency}. 장면 수를 줄이거나 한도를 확인하세요."
        )


def readiness(
    sessions: sessionmaker[Session], key_store, *, provider_override: str | None = None, submitting: bool = False, reported: bool = False,
) -> dict:
    """Why paid AI video generation can or cannot run now; safe to show in the GUI.

    ``submitting``: the worker's send-time check. The scenes it sends are already reserved inside
    this month's usage (confirmed as ``month + batch <= limit``), so only usage beyond the limit
    (a limit lowered after confirmation) stops them.
    """
    settings = read_settings(sessions)
    key = key_store.status() if key_store is not None else {"configured": False}
    usage = usage_this_month(sessions)
    models = list_models(sessions)
    reasons = []
    with sessions() as session:
        if not ledger_valid(session):
            reasons.append(LEDGER_INVALID)
    provider = provider_override or settings.provider
    if provider == "off":
        reasons.append("AI 영상 공급사가 '사용 안 함'입니다. 기본 FFmpeg 제작만 사용합니다.")
    if not settings.approved:
        reasons.append("AI 영상 유료 생성 승인이 저장되지 않았습니다.")
    if settings.job_limit <= 0:
        reasons.append("1회 실행 한도가 없습니다.")
    if provider_override is None and not key["configured"]:
        reasons.append("AI 영상 API 키가 없습니다.")
    if reported:
        from .production import model_ready
        if not any(model_ready(model) for model in models):
            reasons.append("공식 입력 규격을 확인한 모델이 없습니다. 계정 사용 가능 여부는 별도 확인이 필요합니다.")
    elif not any(m.usable for m in models):
        reasons.append("공식 문서 확인과 초당 단가를 입력한 모델이 없습니다.")
    return {
        "ready": not reasons, "reasons": reasons, "settings": settings, "provider": provider, "key": key,
        "usage": usage, "remaining": None, "limit_scope": "per_execution",
        "models": models,
    }
