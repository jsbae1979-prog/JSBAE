"""API configuration in the existing settings page; saving never calls a vendor."""

from fastapi import APIRouter, Form, HTTPException, Request

from newsflow.intelligence.api_settings import (
    APIPolicyError,
    invalidate_api_verification,
    save_api_settings,
)
from newsflow.intelligence.credentials import CredentialError
from newsflow.intelligence.settings import SettingsError, read_settings, validate_settings, write_settings

from .routes import go

router = APIRouter()


def connection_status(request: Request, provider: str, capability: str = "search") -> dict:
    """Use the same local gates as the worker, without credential reads or HTTP calls."""
    return request.app.state.autopilot_backend.intelligence.api_readiness(provider, capability)


def _store(request: Request, provider: str):
    if provider not in {"openai", "claude_api"}:
        raise HTTPException(422, "API 제공자를 다시 선택하세요.")
    return request.app.state.api_keys[provider]


@router.post("/api-settings/{provider}")
def save_configuration(
    request: Request, provider: str, model: str = Form(max_length=80),
    approved: bool = Form(False), search_enabled: bool = Form(False), search_approved: bool = Form(False),
    request_limit_usd: str = Form("", max_length=20), monthly_limit_usd: str = Form("", max_length=20),
    input_price_per_1m: str = Form("", max_length=20), output_price_per_1m: str = Form("", max_length=20),
    search_price_per_1k: str = Form("", max_length=20), billing_confirmed: bool = Form(False),
    account_remaining_usd: str = Form("", max_length=20),
    monthly_token_limit: int | None = Form(None), timeout: int | None = Form(None),
):
    _store(request, provider)
    try:
        if provider == "openai":
            previous = read_settings(request.app.state.sessions)
            monthly_token_limit = previous.monthly_token_limit if monthly_token_limit is None else monthly_token_limit
            timeout = previous.timeout if timeout is None else timeout
            # Check all existing token/timeout rules before changing either API policy.
            validate_settings("openai", model.strip(), approved, monthly_token_limit, timeout)
        save_api_settings(
            request.app.state.sessions, provider, model=model.strip(), approved=approved,
            search_enabled=search_enabled, search_approved=search_approved,
            request_limit_usd=request_limit_usd, monthly_limit_usd=monthly_limit_usd,
            input_price_per_1m=input_price_per_1m, output_price_per_1m=output_price_per_1m,
            search_price_per_1k=search_price_per_1k, billing_confirmed=billing_confirmed,
            account_remaining_usd=account_remaining_usd,
        )
        if provider == "openai":
            write_settings(request.app.state.sessions, "openai", model.strip(), approved, monthly_token_limit, timeout)
    except (APIPolicyError, SettingsError) as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/simple-settings?saved=true#selected-ai")


@router.post("/api-settings/{provider}/key")
def save_key(request: Request, provider: str, api_key: str = Form("")):
    # Validate in the store: FastAPI field errors otherwise echo submitted secrets.
    store = _store(request, provider)
    try:
        store.save(api_key)
        invalidate_api_verification(request.app.state.sessions, provider)
    except CredentialError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/simple-settings?saved=true#selected-ai")


@router.post("/api-settings/{provider}/key/clear")
def clear_key(request: Request, provider: str):
    store = _store(request, provider)
    try:
        store.clear()
        invalidate_api_verification(request.app.state.sessions, provider)
    except CredentialError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/simple-settings?saved=true#selected-ai")
