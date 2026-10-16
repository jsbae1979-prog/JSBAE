"""AI connection settings: provider, model, dated paid-call approval, token limit and key storage.

The key is accepted once from a form field, stored through the key store and never
rendered back. The connection check is a zero-token model lookup.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from newsflow.db.models import AIUsage, AppSetting, utcnow
from newsflow.intelligence.api_settings import invalidate_api_verification
from newsflow.intelligence.credentials import CredentialError
from newsflow.intelligence.provider import OpenAIProvider, ProviderError
from newsflow.intelligence.settings import (
    CURRENCIES,
    PRICE_DISCLAIMER,
    PROVIDERS,
    SettingsError,
    external_ready,
    read_settings,
    write_prices,
    write_settings,
)

from .routes import go, page

router = APIRouter()


def _store(request: Request):
    return request.app.state.ai_keys


@router.get("/ai-settings", response_class=HTMLResponse)
def ai_settings(request: Request, saved: str = "") -> HTMLResponse:
    sessions = request.app.state.sessions
    settings = read_settings(sessions)
    status = external_ready(sessions, _store(request))
    with sessions() as session:
        row = session.get(AppSetting, "ai_last_check")
        last_check = json.loads(row.value) if row else None
        usage = list(session.scalars(select(AIUsage).order_by(AIUsage.id.desc()).limit(20)))
    return page(
        request, "ai_settings.html", active="simple-settings", settings=settings, status=status,
        providers=PROVIDERS, last_check=last_check, usage=usage, saved=saved[:20],
        estimate=status["estimate"], prices=status["prices"], currencies=CURRENCIES, disclaimer=PRICE_DISCLAIMER,
    )


@router.post("/ai-settings")
def save_ai_settings(
    request: Request, provider: str = Form(max_length=20), model: str = Form(max_length=80),
    approved: bool = Form(False), monthly_token_limit: int = Form(0), timeout: int = Form(20),
) -> RedirectResponse:
    try:
        write_settings(request.app.state.sessions, provider, model.strip(), approved, monthly_token_limit, timeout)
    except SettingsError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/ai-settings?saved=settings")


@router.post("/ai-settings/prices")
def save_prices(
    request: Request, input_per_1m: str = Form("", max_length=20), output_per_1m: str = Form("", max_length=20),
    currency: str = Form("USD", max_length=3),
) -> RedirectResponse:
    """User-entered unit prices for the estimate only; they never allow or block a call."""
    try:
        write_prices(request.app.state.sessions, input_per_1m, output_per_1m, currency)
    except SettingsError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/ai-settings?saved=prices")


@router.post("/ai-settings/key")
def save_key(request: Request, api_key: str = Form("")) -> RedirectResponse:
    try:
        _store(request).save(api_key)
        invalidate_api_verification(request.app.state.sessions, "openai")
    except CredentialError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/ai-settings?saved=key")


@router.post("/ai-settings/key/clear")
def clear_key(request: Request) -> RedirectResponse:
    try:
        _store(request).clear()
        invalidate_api_verification(request.app.state.sessions, "openai")
    except CredentialError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/ai-settings?saved=cleared")


@router.post("/ai-settings/check")
def check_connection(request: Request) -> RedirectResponse:
    """Explicit user action; proves key, network and model without spending tokens."""
    sessions = request.app.state.sessions
    settings = read_settings(sessions)
    store = _store(request)
    provider = getattr(request.app.state, "ai_provider", None)
    result: dict = {"checked_at": utcnow().isoformat(), "model": settings.model}
    try:
        if settings.provider != "openai":
            raise SettingsError("기본 대본 모드에서는 외부 연결을 확인하지 않습니다. 제공자를 OpenAI로 저장한 뒤 확인하세요.")
        checker = provider if provider is not None and hasattr(provider, "check_connection") else OpenAIProvider(store.key)
        outcome = checker.check_connection(settings.options())
        result.update({"ok": True, "message": "연결 성공 · 모델 확인 · 토큰 사용 0", "elapsed_ms": outcome.get("elapsed_ms", 0)})
    except (ProviderError, SettingsError, CredentialError) as exc:
        result.update({"ok": False, "message": str(exc), "code": getattr(exc, "code", "settings")})
    except Exception:  # noqa: BLE001 - never surface raw network/provider details
        result.update({"ok": False, "message": "연결 확인에 실패했습니다. 네트워크와 설정을 확인하세요.", "code": "unknown"})
    with sessions.begin() as session:
        row = session.get(AppSetting, "ai_last_check")
        payload = json.dumps(result, ensure_ascii=False)[:200]
        if row:
            row.value = payload
        else:
            session.add(AppSetting(key="ai_last_check", value=payload))
    return go("/ai-settings?saved=check")
