"""GUI-managed AI provider settings, explicit paid-call approval and monthly token budget.

External calls require all of: provider=openai, a stored approval with timestamp, a
positive monthly token limit that is not exhausted, and a configured key. Nothing here
reads the key value; it only asks the key store whether one exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import AIUsage, AppSetting, utcnow

from .provider import Options

PROVIDERS = {"offline": "기본 대본 (외부 호출 없음)", "openai": "OpenAI API (유료 · 승인 필요)"}
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_LIMIT = 200_000
MAX_LIMIT = 50_000_000


class SettingsError(Exception):
    pass


@dataclass(frozen=True)
class AISettings:
    provider: str = "offline"
    model: str = DEFAULT_MODEL
    approved: bool = False
    approved_at: str | None = None
    monthly_token_limit: int = 0
    timeout: int = 20

    def options(self, max_tokens: int = 1800) -> Options:
        return Options(model=self.model, timeout=self.timeout, max_tokens=max_tokens)


def _value(session: Session, key: str) -> str | None:
    row = session.get(AppSetting, key)
    return row.value if row else None


def _set(session: Session, key: str, value: str) -> None:
    row = session.get(AppSetting, key)
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))


def read_settings(sessions: sessionmaker[Session]) -> AISettings:
    with sessions() as session:
        provider = _value(session, "ai_provider")
        model = _value(session, "ai_model") or DEFAULT_MODEL
        approved_at = _value(session, "ai_approved_at")
        limit = _value(session, "ai_monthly_token_limit")
        timeout = _value(session, "ai_timeout")
    try:
        Options(model=model)
    except ValueError:
        model = DEFAULT_MODEL
    return AISettings(
        provider=provider if provider in PROVIDERS else "offline",
        model=model,
        approved=bool(approved_at),
        approved_at=approved_at or None,
        monthly_token_limit=int(limit) if limit and limit.isdigit() else 0,
        timeout=int(timeout) if timeout and timeout.isdigit() and 1 <= int(timeout) <= 60 else 20,
    )


def write_settings(
    sessions: sessionmaker[Session], provider: str, model: str, approved: bool, monthly_token_limit: int, timeout: int,
) -> AISettings:
    if provider not in PROVIDERS:
        raise SettingsError("AI 제공자를 다시 선택하세요.")
    if not isinstance(model, str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", model):
        raise SettingsError("모델 이름은 영문·숫자·점·하이픈 80자 이내여야 합니다.")
    if type(monthly_token_limit) is not int or not 0 <= monthly_token_limit <= MAX_LIMIT:
        raise SettingsError("월 토큰 한도는 0 이상 5천만 이하의 정수여야 합니다.")
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise SettingsError("요청 제한시간은 1~60초여야 합니다.")
    if provider == "openai" and approved and monthly_token_limit <= 0:
        raise SettingsError("외부 AI를 승인하려면 0보다 큰 월 토큰 한도를 함께 설정하세요.")
    with sessions.begin() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        previous = _value(session, "ai_approved_at")
        _set(session, "ai_provider", provider)
        _set(session, "ai_model", model)
        _set(session, "ai_monthly_token_limit", str(monthly_token_limit))
        _set(session, "ai_timeout", str(timeout))
        # Approval is a durable, dated user decision; re-saving keeps the original timestamp.
        _set(session, "ai_approved_at", (previous or utcnow().isoformat()) if approved else "")
    return read_settings(sessions)


def month_start(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def usage_this_month(sessions: sessionmaker[Session]) -> dict:
    with sessions() as session:
        total, calls = session.execute(
            select(func.coalesce(func.sum(AIUsage.total_tokens), 0), func.count(AIUsage.id)).where(
                AIUsage.provider != "offline", AIUsage.created_at >= month_start()
            )
        ).one()
    return {"tokens": int(total), "calls": int(calls), "since": month_start().date().isoformat()}


def record_usage(
    sessions: sessionmaker[Session], *, run_id: int | None, provider: str, model: str, kind: str, status: str,
    usage: dict | None, elapsed_ms: int,
) -> None:
    def count(key: str) -> int:
        value = (usage or {}).get(key, 0)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10_000_000 else 0

    with sessions.begin() as session:
        session.add(AIUsage(
            run_id=run_id, provider=provider[:20], model=model[:80], kind=kind[:20], status=status[:20],
            prompt_tokens=count("prompt_tokens"), completion_tokens=count("completion_tokens"),
            total_tokens=count("total_tokens") or count("prompt_tokens") + count("completion_tokens"),
            elapsed_ms=max(0, min(int(elapsed_ms), 3_600_000)),
        ))


def check_budget(sessions: sessionmaker[Session], settings: AISettings, options: Options) -> None:
    """Reject before any external request when the month could exceed the user's limit."""
    if settings.monthly_token_limit <= 0:
        raise SettingsError("월 토큰 한도가 설정되지 않아 외부 AI를 호출하지 않습니다.")
    used = usage_this_month(sessions)["tokens"]
    if used + options.max_tokens > settings.monthly_token_limit:
        raise SettingsError("이번 달 토큰 한도에 도달해 외부 AI를 호출하지 않습니다. 설정에서 한도를 확인하세요.")


def external_ready(sessions: sessionmaker[Session], key_store) -> dict:
    """Why external AI can or cannot run now; safe to show in the GUI."""
    settings = read_settings(sessions)
    key = key_store.status()
    usage = usage_this_month(sessions)
    reasons = []
    if settings.provider != "openai":
        reasons.append("AI 제공자가 기본 대본(외부 호출 없음)입니다.")
    if not settings.approved:
        reasons.append("유료 호출 승인이 저장되지 않았습니다.")
    if settings.monthly_token_limit <= 0:
        reasons.append("월 토큰 한도가 없습니다.")
    elif usage["tokens"] >= settings.monthly_token_limit:
        reasons.append("이번 달 토큰 한도를 모두 사용했습니다.")
    if not key["configured"]:
        reasons.append("API 키가 없습니다.")
    return {
        "ready": not reasons, "reasons": reasons, "provider": settings.provider, "model": settings.model,
        "approved": settings.approved, "approved_at": settings.approved_at, "limit": settings.monthly_token_limit,
        "usage": usage, "key": key, "timeout": settings.timeout,
    }
