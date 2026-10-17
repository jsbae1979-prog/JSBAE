"""Local-only API policy contracts. No CLI, auth probe or vendor HTTP request."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AppSetting, utcnow
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.intelligence.api_providers import API_MODELS
from newsflow.intelligence.api_settings import (
    APIBudgetService,
    APISettingsError,
    FakeAPIBudgetService,
    api_readiness,
    invalidate_api_verification,
    read_api_settings,
    save_api_settings,
)
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, FakeCipher
from newsflow.intelligence.settings import _set, write_settings, write_studio_settings

KEY = "sk-synthetic-api-policy-test-0123456789"


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(tmp_path / "isolated.sqlite3")
    migrate(engine)
    yield session_factory(engine)
    engine.dispose()


@pytest.fixture
def store(tmp_path):
    value = AnthropicKeyStore(tmp_path / "secrets", FakeCipher())
    value.save(KEY)
    return value


def configured(sessions, provider="claude_api", **changes):
    options = {"model": "claude-sonnet-4-6" if provider == "claude_api" else "gpt-4.1-mini",
               "approved": True, "search_enabled": True, "search_approved": True, "request_limit_usd": "10",
               "monthly_limit_usd": "30", "input_price_per_1m": "3", "output_price_per_1m": "15",
               "search_price_per_1k": "10", "billing_confirmed": True, "account_remaining_usd": "30"}
    options.update(changes)
    return save_api_settings(sessions, provider, **options)


def reserve(budget, store, request_id="analysis:1", **changes):
    options = {"provider": "claude_api", "request_id": request_id, "kind": "analysis", "model": "claude-sonnet-4-6",
               "max_input_tokens": 1000, "max_output_tokens": 1000, "key_store": store}
    options.update(changes)
    return budget.reserve(**options)


def test_anthropic_key_has_distinct_dpapi_file_entropy_and_environment(tmp_path, monkeypatch):
    openai = AIKeyStore(tmp_path, FakeCipher())
    anthropic = AnthropicKeyStore(tmp_path, FakeCipher())
    monkeypatch.delenv("NEWSFLOW_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", KEY)
    assert not anthropic.status()["configured"]
    openai.save(KEY)
    anthropic.save(KEY + "-anthropic")
    assert anthropic.FILE != openai.FILE and anthropic.ENTROPY != openai.ENTROPY
    assert KEY.encode() not in anthropic.path.read_bytes()
    anthropic.clear()
    assert openai.key() == KEY


def test_save_preserves_selected_provider_rss_and_legacy_openai_token_policy(sessions):
    write_settings(sessions, "openai", "gpt-4o-mini", True, 12345, 20)
    write_studio_settings(sessions, "claude_code", "sonnet")
    with sessions.begin() as session:
        _set(session, "production_acquisition_policy", "rss")
    configured(sessions, "openai", search_approved=False)
    with sessions() as session:
        assert session.get(AppSetting, "studio_provider").value == "claude_code"
        assert session.get(AppSetting, "production_acquisition_policy").value == "rss"
        assert session.get(AppSetting, "ai_monthly_token_limit").value == "12345"
        assert session.get(AppSetting, "ai_model").value == "gpt-4o-mini"
    assert read_api_settings(sessions, "openai").model == "gpt-4.1-mini"
    assert not read_api_settings(sessions, "openai").search_approved


def test_existing_inference_approval_never_grants_search(sessions, store):
    write_settings(sessions, "openai", "gpt-4o-mini", True, 100000, 20)
    assert read_api_settings(sessions, "openai").approved
    assert not read_api_settings(sessions, "openai").search_approved
    assert "웹 검색 비용 별도 승인 필요" in api_readiness(sessions, "openai", store)["reasons"]


def test_unsupported_legacy_model_stays_saved_with_explicit_supported_model_hint(sessions, store):
    from newsflow.intelligence.api_settings import PRICE_FLOORS, SEARCH_CONTEXT_BOUNDS

    supported = {model for models in API_MODELS.values() for model in models}
    assert set(PRICE_FLOORS) == set(SEARCH_CONTEXT_BOUNDS) == supported
    configured(sessions, "openai", model="gpt-4o-mini")
    status = FakeAPIBudgetService(sessions).readiness("openai", store)
    assert not status["ready"] and status["model"] == "gpt-4o-mini"
    assert any("지원 모델: gpt-4.1-mini" in reason for reason in status["reasons"])
    assert read_api_settings(sessions, "openai").model == "gpt-4o-mini"


def test_configured_is_not_authenticated_or_successful_and_get_never_reads_key(sessions, store, monkeypatch):
    configured(sessions)
    monkeypatch.setattr(store, "key", lambda: pytest.fail("readiness must not decrypt a key"))
    state = api_readiness(sessions, "claude_api", store)
    assert state["configured"] and not state["ready"]
    assert not state["authentication_verified"] and not state["request_succeeded"]
    assert state["account_evidence"] == "USER CONFIRMED"
    assert state["usage"]["vendor_billing"] == "NOT VERIFIED"
    with pytest.raises(APISettingsError, match="실제 API 연결 미확인"):
        reserve(APIBudgetService(sessions), store)


def test_missing_key_store_blocks_without_authentication_attempt(sessions):
    configured(sessions)
    result = api_readiness(sessions, "claude_api", None)
    assert not result["ready"] and not result["configured"]
    assert "API Key 미등록" in result["reasons"]


def test_official_search_usage_field_is_recorded(sessions, store):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    reservation = reserve(budget, store, kind="search", max_search_calls=1)
    budget.finish(reservation.id, status="success", usage={"prompt_tokens": 100, "completion_tokens": 50,
                                                         "web_search_requests": 1})
    with sessions() as session:
        row = session.get(APIRequestReservation, reservation.id)
        assert row.status == "success" and row.usage["search_calls"] == 1


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1000001", "0.000000001"])
def test_invalid_money_fails_closed(sessions, value):
    with pytest.raises(APISettingsError):
        configured(sessions, monthly_limit_usd=value)


def test_fake_uses_all_budget_gates_but_never_records_actual_authentication(sessions, store):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    assert budget.readiness("claude_api", store)["ready"]
    reservation = reserve(budget, store)
    budget.finish(reservation.id, status="success", usage={"prompt_tokens": 80, "completion_tokens": 50})
    assert not api_readiness(sessions, "claude_api", store)["authentication_verified"]
    state = budget.readiness("claude_api", store)
    assert state["usage"]["test_calls"] == 1
    assert Decimal(state["usage"]["held_usd"]) == 0
    assert Decimal(state["usage"]["estimated_usd"]) == Decimal("0.000990")
    assert state["usage"]["vendor_billing"] == "NOT VERIFIED"


def test_duplicate_id_blocked_after_success_restart_and_failed_result(sessions, store):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    result = reserve(budget, store)
    budget.finish(result.id, status="failed")
    with pytest.raises(APISettingsError, match="이미 기록된 요청"):
        reserve(FakeAPIBudgetService(sessions), store)
    with sessions() as session:
        assert Decimal(session.get(APIRequestReservation, result.id).reserved_usd) == 0


@pytest.mark.parametrize("status", ["unknown", "cancelled"])
def test_uncertain_outcome_retains_reservation_and_blocks_next_request(sessions, store, status):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    result = reserve(budget, store)
    budget.finish(result.id, status=status)
    with pytest.raises(APISettingsError, match="결과 불명"):
        reserve(FakeAPIBudgetService(sessions), store, "analysis:2")


def test_reported_usage_exceeding_requested_tokens_is_recorded_without_guessing_cost(sessions, store):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    result = reserve(budget, store)
    budget.finish(result.id, status="success", usage={"prompt_tokens": 1001, "completion_tokens": 1001,
                                                     "api_key": KEY})
    with sessions() as session:
        row = session.get(APIRequestReservation, result.id)
        assert row.status == "success"
        assert Decimal(row.reserved_usd) == result.reserved_usd == 0
        assert Decimal(row.estimated_usd) == Decimal("0.018018")
        assert KEY not in str(row.usage)


def test_search_does_not_price_full_model_context_but_retains_reported_usage_prices(sessions, store):
    configured(sessions, input_price_per_1m="0.001", output_price_per_1m="0.001", search_price_per_1k="0.001")
    budget = FakeAPIBudgetService(sessions)
    result = reserve(budget, store, kind="search", max_search_calls=1)
    assert result.reserved_usd == 0
    with sessions() as session:
        row = session.get(APIRequestReservation, result.id)
        assert row.bounds == {"accounting": "reported_usage", "search_calls": 1}
        assert row.prices == {"input": "3", "output": "15", "search": "10"}


def test_monthly_and_account_limits_use_reported_usage_not_ignored_request_limit(sessions, store):
    budget = FakeAPIBudgetService(sessions)
    configured(sessions, request_limit_usd="0.000001", monthly_limit_usd="0.01", account_remaining_usd="0.01")
    result = reserve(budget, store)
    budget.finish(result.id, status="success", usage={"prompt_tokens": 1000, "completion_tokens": 1000})
    with pytest.raises(APISettingsError, match="월별"):
        reserve(budget, store, "analysis:2")
    # Updating a monthly limit must not renew the vendor-balance confirmation.
    with sessions.begin() as session:
        _set(session, "api_claude_api_monthly_limit_usd", "30")
    with pytest.raises(APISettingsError, match="잔여 예산"):
        reserve(budget, store, "analysis:2")


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": 1},
                                   {"prompt_tokens": "1", "completion_tokens": 2},
                                   {"prompt_tokens": True, "completion_tokens": 2}])
def test_missing_or_malformed_reported_usage_blocks_new_requests(sessions, store, usage):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    result = reserve(budget, store)
    budget.finish(result.id, status="success", usage=usage)
    with sessions() as session:
        row = session.get(APIRequestReservation, result.id)
        assert row.status == "unknown" and row.estimated_usd is None
        assert Decimal(row.reserved_usd) == 0
    with pytest.raises(APISettingsError, match="결과 불명"):
        reserve(budget, store, "analysis:2")


def test_reported_search_count_above_one_still_blocks(sessions, store):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)
    result = reserve(budget, store, kind="search", max_search_calls=1)
    budget.finish(result.id, status="success",
                  usage={"prompt_tokens": 100, "completion_tokens": 50, "search_calls": 2})
    with sessions() as session:
        row = session.get(APIRequestReservation, result.id)
        assert row.status == "unknown" and row.usage["search_calls"] == 2
    with pytest.raises(APISettingsError, match="결과 불명"):
        reserve(budget, store, "analysis:2")


def test_old_large_reservation_is_preserved_without_counting_it_as_a_bill(sessions, store):
    configured(sessions, request_limit_usd="0.000001", monthly_limit_usd="1", account_remaining_usd="1")
    with sessions.begin() as session:
        old = APIRequestReservation(id="old", request_id="old:search", provider="claude_api", kind="search",
                                    model="claude-sonnet-4-6", status="failed", reserved_usd="999.00",
                                    estimated_usd="0.01", bounds={"prompt_tokens": 1000000,
                                    "completion_tokens": 3000, "search_calls": 1},
                                    prices={"input": "3", "output": "15", "search": "10"},
                                    usage={"prompt_tokens": 0, "completion_tokens": 0, "search_calls": 1},
                                    test_only=True, created_at=utcnow(), finished_at=utcnow())
        session.add(old)
    with sessions() as session:
        row = session.get(APIRequestReservation, "old")
        snapshot = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    budget = FakeAPIBudgetService(sessions)
    assert budget.readiness("claude_api", store)["ready"]
    result = reserve(budget, store, kind="search", max_input_tokens=1000000,
                     max_output_tokens=9000, max_search_calls=1)
    assert result.reserved_usd == 0
    with sessions() as session:
        row = session.get(APIRequestReservation, "old")
        assert {column.name: getattr(row, column.name) for column in row.__table__.columns} == snapshot


def test_optional_request_limit_omission_preserves_existing_setting(sessions):
    old = configured(sessions, request_limit_usd="3.10")
    saved = save_api_settings(
        sessions, "claude_api", model=old.model, approved=old.approved,
        search_enabled=old.search_enabled, search_approved=old.search_approved,
        monthly_limit_usd=str(old.monthly_limit_usd), input_price_per_1m=str(old.input_price_per_1m),
        output_price_per_1m=str(old.output_price_per_1m), search_price_per_1k=str(old.search_price_per_1k),
        billing_confirmed=False, account_remaining_usd=str(old.account_remaining_usd),
    )
    assert saved.request_limit_usd == Decimal("3.10")
    assert saved.monthly_limit_usd == old.monthly_limit_usd
    assert saved.approved_at == old.approved_at and saved.search_approved_at == old.search_approved_at


def test_legacy_reserved_request_keeps_its_original_finish_semantics(sessions, store):
    configured(sessions)
    with sessions.begin() as session:
        session.add(APIRequestReservation(
            id="legacy", request_id="legacy:search", provider="claude_api", kind="search",
            model="claude-sonnet-4-6", status="reserved", reserved_usd="3.055",
            bounds={"prompt_tokens": 1000000, "completion_tokens": 3000, "search_calls": 1},
            prices={"input": "3", "output": "15", "search": "10"}, usage={}, test_only=True,
            created_at=utcnow(),
        ))
    APIBudgetService(sessions).finish("legacy", status="failed",
                                    usage={"prompt_tokens": 11651, "completion_tokens": 3060, "search_calls": 1})
    with sessions() as session:
        row = session.get(APIRequestReservation, "legacy")
        assert row.status == "unknown" and row.reserved_usd == "3.055"
        assert row.estimated_usd == "0.090853"


def test_stale_account_evidence_and_unknown_model_block(sessions, store):
    configured(sessions)
    with sessions.begin() as session:
        _set(session, "api_claude_api_billing_confirmed_at", (utcnow() - timedelta(hours=25)).isoformat())
    with pytest.raises(APISettingsError, match="24시간"):
        reserve(FakeAPIBudgetService(sessions), store)
    configured(sessions, model="claude-unknown")
    with pytest.raises(APISettingsError, match="미검증"):
        reserve(FakeAPIBudgetService(sessions), store, model="claude-unknown")


def test_key_rotation_and_model_mismatch_invalidate_prior_proof(sessions, store):
    configured(sessions)
    with sessions.begin() as session:
        for name in ("authentication_verified_at", "search_verified_at", "request_succeeded_at"):
            _set(session, "api_claude_api_" + name, utcnow().isoformat())
        _set(session, "api_claude_api_verified_model", "claude-sonnet-4-6")
    assert api_readiness(sessions, "claude_api", store)["ready"]
    with sessions.begin() as session:
        _set(session, "studio_model_claude_api", "claude-haiku-4-5")
    assert not api_readiness(sessions, "claude_api", store)["ready"]
    invalidate_api_verification(sessions, "claude_api")
    state = read_api_settings(sessions, "claude_api")
    assert state.authentication_verified_at is None and state.billing_confirmed_at is None


def test_concurrent_reservations_are_atomic(sessions, store):
    configured(sessions)
    budget = FakeAPIBudgetService(sessions)

    def attempt(index):
        try:
            return reserve(budget, store, f"analysis:{index}")
        except APISettingsError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (1, 2)))
    assert sum(result is not None for result in results) == 1
    with sessions() as session:
        assert len(list(session.scalars(select(APIRequestReservation)))) == 1
