"""Pinned model prices and configuration-only invalidation; no external calls."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from newsflow.db.models import AppSetting, utcnow
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.gui.production_routes import preferences
from newsflow.intelligence.api_providers import API_MODELS
from newsflow.intelligence.api_settings import (
    PRICE_FLOORS,
    SEARCH_CONTEXT_BOUNDS,
    api_readiness,
    read_api_settings,
)
from newsflow.intelligence.settings import _set, write_studio_settings

CLAUDE_CONTRACTS = {
    "claude-sonnet-4-6": (Decimal(3), Decimal(15), 1_000_000),
    "claude-haiku-4-5-20251001": (Decimal(1), Decimal(5), 200_000),
    "claude-opus-4-6": (Decimal(5), Decimal(25), 1_000_000),
}
PROOF_NAMES = ("authentication_verified_at", "search_verified_at", "request_succeeded_at", "verified_model",
               "connection_check_id", "connection_check_code", "connection_checked_at", "connection_check_started_at")


@pytest.fixture(autouse=True)
def no_external_work(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("settings tests must not invoke network or voice/CLI discovery")

    monkeypatch.setattr("urllib.request.build_opener", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("newsflow.gui.production_routes.validate_voice_preferences", forbidden)


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(tmp_path / "isolated-model-choices.sqlite3")
    migrate(engine)
    yield session_factory(engine)
    engine.dispose()


def save_values(sessions, values):
    with sessions.begin() as session:
        for name, value in values.items():
            _set(session, name, value)


def saved_values(sessions):
    with sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def proof(provider, model):
    timestamp = utcnow().isoformat()
    result = {f"api_{provider}_{key}": timestamp for key in PROOF_NAMES}
    result.update({f"api_{provider}_verified_model": model, f"api_{provider}_connection_check_id": "in-flight-id",
                   f"api_{provider}_connection_check_code": "checking",
                   f"api_{provider}_monthly_limit_usd": "99", f"api_{provider}_search_approved_at": timestamp})
    return result


def write_model(sessions, path, provider, model):
    if path == "studio":
        return write_studio_settings(sessions, provider, model)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(sessions=sessions)))
    response = preferences(request, provider=provider, model=model, source="sample", duration=30,
                           platform="youtube", voice="offline-silence", rate="0", pause_ms="250",
                           video_provider="off", acquisition_policy="rss", category="all", period="today")
    assert response.status_code == 303
    assert response.headers["location"] == "/simple-settings?saved=true"


@pytest.mark.parametrize("model", CLAUDE_CONTRACTS)
def test_pinned_claude_models_have_exact_tariffs_and_context_without_writing(sessions, model):
    assert set(API_MODELS["claude_api"]) == set(CLAUDE_CONTRACTS)
    input_price, output_price, context = CLAUDE_CONTRACTS[model]
    assert tuple(Decimal(value) for value in PRICE_FLOORS[model]) == (input_price, output_price)
    assert SEARCH_CONTEXT_BOUNDS[model] == context
    save_values(sessions, {"studio_model_claude_api": model})
    before = saved_values(sessions)
    statements = []
    engine = sessions.kw["bind"]

    def observed(connection, cursor, statement, parameters, context, many):
        statements.append(statement.lstrip().split(maxsplit=1)[0].upper())

    event.listen(engine, "before_cursor_execute", observed)
    try:
        settings = read_api_settings(sessions, "claude_api")
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert settings.input_price_per_1m == input_price and settings.output_price_per_1m == output_price
    assert settings.search_price_per_1k == Decimal(10)
    assert not {"INSERT", "UPDATE", "DELETE", "REPLACE"}.intersection(statements)
    assert saved_values(sessions) == before
    assert not settings.approved and not settings.authentication_verified_at


@pytest.mark.parametrize("field", ["input_price_per_1m", "output_price_per_1m", "search_price_per_1k"])
@pytest.mark.parametrize("stored", ["0", "invalid-tariff"])
def test_explicit_zero_or_invalid_rate_is_preserved_and_blocks_execution(sessions, field, stored):
    key = "api_claude_api_" + field
    save_values(sessions, {key: stored})
    before = saved_values(sessions)
    settings = read_api_settings(sessions, "claude_api")
    assert getattr(settings, field) == (Decimal(0) if stored == "0" else None)
    store = SimpleNamespace(status=lambda: {"configured": True})
    status = api_readiness(sessions, "claude_api", store, "search")
    assert not status["ready"] and "공식 요금표에서 확인한 단가 입력 필요" in status["reasons"]
    assert saved_values(sessions) == before


def test_custom_rates_are_preserved_and_unknown_or_openai_model_has_no_claude_fallback(sessions):
    save_values(sessions, {"api_claude_api_input_price_per_1m": "6.25",
                           "api_claude_api_output_price_per_1m": "31.50",
                           "api_claude_api_search_price_per_1k": "12"})
    configured = read_api_settings(sessions, "claude_api")
    assert (configured.input_price_per_1m, configured.output_price_per_1m, configured.search_price_per_1k) == (
        Decimal("6.25"), Decimal("31.50"), Decimal(12))
    save_values(sessions, {"studio_model_claude_api": "claude-unverified-custom"})
    assert read_api_settings(sessions, "claude_api").input_price_per_1m == Decimal("6.25")
    openai = read_api_settings(sessions, "openai")
    assert openai.input_price_per_1m is None and openai.output_price_per_1m is None
    assert openai.search_price_per_1k is None


def test_unknown_claude_model_stays_saved_and_has_no_assumed_tariff(sessions):
    save_values(sessions, {"studio_model_claude_api": "claude-unverified-custom"})
    before = saved_values(sessions)
    result = read_api_settings(sessions, "claude_api")
    assert result.model == "claude-unverified-custom"
    assert result.input_price_per_1m is None and result.output_price_per_1m is None
    assert result.search_price_per_1k is None and saved_values(sessions) == before


@pytest.mark.parametrize("path", ["studio", "production"])
def test_changing_model_clears_auth_and_inflight_check_without_touching_other_provider(sessions, path):
    current = "claude-sonnet-4-6"
    preserved = proof("openai", "gpt-4.1-mini")
    save_values(sessions, {**proof("claude_api", current), **preserved, "studio_model_claude_api": current,
                           "studio_model_openai": "gpt-4.1-mini", "ai_approved_at": "other-approval",
                           "api_claude_api_approved_at": "current-approval"})
    write_model(sessions, path, "claude_api", "claude-haiku-4-5-20251001")
    after = saved_values(sessions)
    assert all(after["api_claude_api_" + key] == "" for key in PROOF_NAMES)
    assert after["studio_model_claude_api"] == "claude-haiku-4-5-20251001"
    assert after["api_claude_api_approved_at"] == "current-approval"
    assert after["api_claude_api_monthly_limit_usd"] == "99"
    assert after["studio_model_openai"] == "gpt-4.1-mini" and after["ai_approved_at"] == "other-approval"
    assert all(after[key] == value for key, value in preserved.items())


@pytest.mark.parametrize("path", ["studio", "production"])
@pytest.mark.parametrize("provider,model", [("claude_api", "claude-sonnet-4-6"), ("openai", "gpt-4o-mini")])
@pytest.mark.parametrize("explicit_model", [False, True])
def test_unchanged_effective_model_preserves_verification_even_without_studio_override(
    sessions, path, provider, model, explicit_model,
):
    existing = proof(provider, model)
    existing["ai_model"] = "gpt-4o-mini"
    if explicit_model:
        existing["studio_model_" + provider] = model
    save_values(sessions, existing)
    write_model(sessions, path, provider, model)
    after = saved_values(sessions)
    assert all(after[key] == value for key, value in existing.items())
    assert after["studio_model_" + provider] == model
