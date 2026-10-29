"""API configuration in the existing settings page; saving never calls a vendor."""

from fastapi import APIRouter, Form, HTTPException, Request

from newsflow.intelligence.api_connection import check_api_connection, check_claude_connection
from newsflow.intelligence.api_search_check import check_api_search, read_search_check
from newsflow.intelligence.api_settings import (
    APIPolicyError,
    acknowledge_unknown_analysis,
    first_search_readiness,
    invalidate_api_verification,
    save_api_settings,
)
from newsflow.intelligence.credentials import CredentialError
from newsflow.intelligence.settings import SettingsError, read_settings, validate_settings, write_settings

from .routes import go

router = APIRouter()


@router.post("/api-settings/{provider}/acknowledge-unknown-analysis")
def acknowledge_analysis(request: Request, provider: str, reservation_id: str = Form(""),
                         fingerprint: str = Form(""), consent: bool = Form(False)):
    _store(request, provider)
    try:
        acknowledge_unknown_analysis(request.app.state.sessions, provider, reservation_id=reservation_id,
                                     fingerprint=fingerprint, consent=consent)
    except APIPolicyError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/simple-settings?saved=analysis-ack#selected-ai")


@router.post("/api-settings/{provider}/check")
def check_connection(request: Request, provider: str, consent: bool = Form(False)):
    store = _store(request, provider)
    if provider == "claude_api":
        result = check_claude_connection(
            request.app.state.sessions, store, consent=consent,
            transport=getattr(request.app.state, "claude_connection_transport", None),
        )
    else:
        result = check_api_connection(
            request.app.state.sessions, store, provider=provider, consent=consent,
            transport=getattr(request.app.state, "openai_connection_transport", None),
        )
    if not result.ok:
        raise HTTPException(422, result.message)
    return go("/simple-settings?saved=connection#selected-ai")


@router.post("/api-settings/{provider}/check-search")
def check_search(
    request: Request, provider: str, consent: bool = Form(False),
    model: str = Form("", max_length=80), authentication_at: str = Form("", max_length=80),
    max_cost_usd: str = Form("", max_length=20),
):
    result = check_api_search(
        request.app.state.sessions, _store(request, provider), provider=provider,
        consent=consent, model=model, authentication_at=authentication_at, max_cost_usd=max_cost_usd,
        transport=getattr(request.app.state, "api_search_check_transports", {}).get(provider),
    )
    if not result.ok:
        raise HTTPException(422, result.message)
    return go("/simple-settings?saved=search-check#selected-ai")


def connection_status(request: Request, provider: str, capability: str = "search") -> dict:
    """Use the same local gates as the worker, without credential reads or HTTP calls."""
    status = request.app.state.autopilot_backend.intelligence.api_readiness(provider, capability)
    if capability == "search":
        status["first_search"] = first_search_readiness(request.app.state.sessions, provider, _store(request, provider))
        status["search_check"] = read_search_check(request.app.state.sessions, provider)
    return status


def _store(request: Request, provider: str):
    if provider not in {"openai", "claude_api"}:
        raise HTTPException(422, "API 제공자를 다시 선택하세요.")
    return request.app.state.api_keys[provider]


@router.post("/api-settings/{provider}")
def save_configuration(
    request: Request, provider: str, model: str = Form(max_length=80),
    approved: bool = Form(False), search_enabled: bool = Form(False), search_approved: bool = Form(False),
    request_limit_usd: str | None = Form(None, max_length=20),
    input_price_per_1m: str = Form("", max_length=20), output_price_per_1m: str = Form("", max_length=20),
    search_price_per_1k: str = Form("", max_length=20), billing_confirmed: bool = Form(False),
    account_remaining_usd: str = Form("", max_length=20),
    request_token_limit: int | None = Form(None), timeout: int | None = Form(None),
):
    _store(request, provider)
    try:
        if provider == "openai":
            previous = read_settings(request.app.state.sessions)
            request_token_limit = previous.request_token_limit if request_token_limit is None else request_token_limit
            timeout = previous.timeout if timeout is None else timeout
            # Check all existing token/timeout rules before changing either API policy.
            validate_settings("openai", model.strip(), approved, request_token_limit, timeout)
        save_api_settings(
            request.app.state.sessions, provider, model=model.strip(), approved=approved,
            search_enabled=search_enabled, search_approved=search_approved,
            request_limit_usd=request_limit_usd,
            input_price_per_1m=input_price_per_1m, output_price_per_1m=output_price_per_1m,
            search_price_per_1k=search_price_per_1k, billing_confirmed=billing_confirmed,
            account_remaining_usd=account_remaining_usd,
        )
        if provider == "openai":
            write_settings(request.app.state.sessions, "openai", model.strip(), approved, timeout=timeout, request_token_limit=request_token_limit)
    except (APIPolicyError, SettingsError) as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/simple-settings?saved=api#selected-ai")


@router.post("/api-settings/{provider}/key")
def save_key(request: Request, provider: str, api_key: str = Form("")):
    # Validate in the store: FastAPI field errors otherwise echo submitted secrets.
    store = _store(request, provider)
    try:
        store.save(api_key)
        invalidate_api_verification(request.app.state.sessions, provider)
    except CredentialError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/simple-settings?saved=key#selected-ai")


@router.post("/api-settings/{provider}/key/clear")
def clear_key(request: Request, provider: str):
    store = _store(request, provider)
    try:
        store.clear()
        invalidate_api_verification(request.app.state.sessions, provider)
    except CredentialError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/simple-settings?saved=key_removed#selected-ai")
