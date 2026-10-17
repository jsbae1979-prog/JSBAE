"""First-search budget checks use isolated SQLite and synthetic status only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AppSetting, utcnow
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.intelligence.api_settings import (
    DEFAULT_MODELS,
    FIRST_SEARCH_OUTPUT_TOKENS,
    SEARCH_CONTEXT_BOUNDS,
    APIBudgetService,
    APISettingsError,
    FakeAPIBudgetService,
    api_readiness,
    first_search_readiness,
    invalidate_api_verification,
    save_api_settings,
)
from newsflow.intelligence.settings import _set


@pytest.fixture(autouse=True)
def forbid_external(monkeypatch):
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: pytest.fail("no real HTTP"))
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("no CLI checks"))


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(tmp_path / "isolated.sqlite3")
    migrate(engine)
    yield session_factory(engine)
    engine.dispose()


class StatusOnlyStore:
    def status(self):
        return {"configured": True}

    def key(self):
        pytest.fail("budget and readiness must not read the key")


def configured(sessions, provider="claude_api", **changes):
    options = {"model": DEFAULT_MODELS[provider], "approved": True, "search_enabled": True,
               "search_approved": True, "request_limit_usd": "10", "monthly_limit_usd": "30",
               "input_price_per_1m": "0.001", "output_price_per_1m": "0.001", "search_price_per_1k": "0.001",
               "billing_confirmed": True, "account_remaining_usd": "30"}
    options.update(changes)
    save_api_settings(sessions, provider, **options)
    stamp = utcnow().isoformat()
    with sessions.begin() as session:
        _set(session, f"api_{provider}_authentication_verified_at", stamp)
        _set(session, f"api_{provider}_verified_model", options["model"])
    return stamp


def reserve(sessions, stamp, provider="claude_api", **changes):
    options = {"provider": provider, "model": DEFAULT_MODELS[provider], "authentication_at": stamp,
               "key_store": StatusOnlyStore(), "consent": True, "max_cost_usd": "10"}
    options.update(changes)
    return APIBudgetService(sessions).reserve_first_search(**options)


def settings_values(sessions):
    with sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


@pytest.mark.parametrize("provider,expected", [("openai", "0.433831"), ("claude_api", "3.055000")])
def test_only_first_search_proof_is_exempt_and_quote_equals_atomic_reservation(sessions, provider, expected):
    stamp = configured(sessions, provider)
    before = settings_values(sessions)
    normal = api_readiness(sessions, provider, StatusOnlyStore())
    assert not normal["ready"] and "실제 웹 검색 미검증 · BLOCKED" in normal["reasons"]
    quote = first_search_readiness(sessions, provider, StatusOnlyStore())
    assert quote["ready"] and quote["reserved_usd"] == expected
    assert quote["authentication_at"] == stamp and quote["model"] == DEFAULT_MODELS[provider]
    assert settings_values(sessions) == before  # GET quote is read-only.
    result = reserve(sessions, stamp, provider)
    assert result.request_id == quote["request_id"] and result.reserved_usd == Decimal(expected)
    with sessions() as session:
        row = session.get(APIRequestReservation, result.id)
        assert row.bounds == {"prompt_tokens": SEARCH_CONTEXT_BOUNDS[DEFAULT_MODELS[provider]],
                              "completion_tokens": FIRST_SEARCH_OUTPUT_TOKENS, "search_calls": 1}
        assert not row.test_only and row.status == "reserved"
    assert settings_values(sessions) == before
    assert not api_readiness(sessions, provider, StatusOnlyStore())["ready"]


@pytest.mark.parametrize("consent", [False, None, "true", 1])
def test_consent_is_explicit_and_no_record_created(sessions, consent):
    stamp = configured(sessions)
    with pytest.raises(APISettingsError, match="별도 실행 동의"):
        reserve(sessions, stamp, consent=consent)
    with sessions() as session:
        assert session.scalar(select(APIRequestReservation.id)) is None


def test_fake_budget_cannot_bypass_authentication_for_first_search(sessions):
    stamp = configured(sessions)
    with pytest.raises(APISettingsError, match="Fake"):
        FakeAPIBudgetService(sessions).reserve_first_search(
            provider="claude_api", model=DEFAULT_MODELS["claude_api"], authentication_at=stamp,
            key_store=StatusOnlyStore(), consent=True, max_cost_usd="10",
        )


@pytest.mark.parametrize("changes,reason", [
    ({"approved": False}, "API 사용 승인"),
    ({"search_enabled": False}, "꺼져"),
    ({"search_approved": False}, "별도 승인"),
    ({"input_price_per_1m": "0"}, "단가"),
    ({"output_price_per_1m": "0"}, "단가"),
    ({"search_price_per_1k": "0"}, "단가"),
    ({"billing_confirmed": False}, "24시간"),
    ({"request_limit_usd": "3"}, "USD 한도"),
    ({"monthly_limit_usd": "3"}, "USD 한도"),
    ({"account_remaining_usd": "3"}, "잔여 예산"),
])
def test_all_existing_gates_apply_to_quote_and_reservation(sessions, changes, reason):
    stamp = configured(sessions, **changes)
    quote = first_search_readiness(sessions, "claude_api", StatusOnlyStore())
    assert not quote["ready"] and any(reason in text for text in quote["reasons"])
    with pytest.raises(APISettingsError, match=reason):
        reserve(sessions, stamp)


@pytest.mark.parametrize("field,value,reason", [
    ("authentication_verified_at", "stale", "API 연결 미확인"),
    ("verified_model", "other", "API 연결 미확인"),
    ("billing_confirmed_at", "stale", "24시간"),
    ("connection_check_id", "active-check", "연결 확인 중"),
])
def test_stale_proof_and_active_auth_check_block(sessions, field, value, reason):
    stamp = configured(sessions)
    value = (utcnow() - timedelta(hours=25)).isoformat() if value == "stale" else value
    with sessions.begin() as session:
        _set(session, "api_claude_api_" + field, value)
    if field == "authentication_verified_at":
        stamp = value
    quote = first_search_readiness(sessions, "claude_api", StatusOnlyStore())
    assert not quote["ready"] and any(reason in text for text in quote["reasons"])
    with pytest.raises(APISettingsError, match=reason):
        reserve(sessions, stamp)


def test_submitted_authentication_and_model_must_match_under_lock(sessions):
    stamp = configured(sessions)
    with pytest.raises(APISettingsError, match="인증 상태가 변경"):
        reserve(sessions, (utcnow() - timedelta(seconds=1)).isoformat())
    with pytest.raises(APISettingsError, match="실행 모델이 달라"):
        reserve(sessions, stamp, model="claude-haiku-4-5-20251001")
    with pytest.raises(APISettingsError, match="API Key 미등록"):
        reserve(sessions, stamp, key_store=None)


def test_price_increase_after_quote_cannot_exceed_the_displayed_consent_cap(sessions):
    stamp = configured(sessions)
    quote = first_search_readiness(sessions, "claude_api", StatusOnlyStore())
    assert quote["reserved_usd"] == "3.055000"
    with sessions.begin() as session:
        _set(session, "api_claude_api_input_price_per_1m", "4")
    with pytest.raises(APISettingsError, match="화면에서 승인한 금액보다"):
        reserve(sessions, stamp, max_cost_usd=quote["reserved_usd"])
    with sessions() as session:
        assert session.scalar(select(APIRequestReservation.id)) is None


@pytest.mark.parametrize("cap", ["", "0", "NaN", "Infinity", "-1"])
def test_invalid_displayed_consent_cap_blocks_without_reservation(sessions, cap):
    stamp = configured(sessions)
    with pytest.raises(APISettingsError):
        reserve(sessions, stamp, max_cost_usd=cap)
    with sessions() as session:
        assert session.scalar(select(APIRequestReservation.id)) is None


@pytest.mark.parametrize("status", ["success", "failed", "unknown", "cancelled"])
def test_repeat_and_restart_never_reuse_same_authentication_attempt(sessions, status):
    stamp = configured(sessions)
    reservation = reserve(sessions, stamp)
    APIBudgetService(sessions).finish(reservation.id, status=status,
                                    usage={"prompt_tokens": 100, "completion_tokens": 100, "search_calls": 1})
    with pytest.raises(APISettingsError, match="이미 기록된 요청"):
        reserve(sessions, stamp)  # New service object simulates app restart.
    quote = first_search_readiness(sessions, "claude_api", StatusOnlyStore())
    assert not quote["ready"] and quote["reservation_id"] == reservation.id
    assert quote["attempt_status"] == ("unknown" if status == "cancelled" else status)
    with sessions() as session:
        assert session.get(APIRequestReservation, reservation.id).reserved_usd == "3.055000"


@pytest.mark.parametrize("status", ["reserved", "unknown"])
def test_other_pending_or_unknown_request_blocks_first_search(sessions, status):
    stamp = configured(sessions)
    with sessions.begin() as session:
        session.add(APIRequestReservation(id="old", request_id="old:request", provider="claude_api", kind="analysis",
                                          model=DEFAULT_MODELS["claude_api"], status=status, reserved_usd="0.1",
                                          bounds={}, prices={}, usage={}, test_only=False, created_at=utcnow()))
    quote = first_search_readiness(sessions, "claude_api", StatusOnlyStore())
    assert not quote["ready"] and any("결과 불명" in text for text in quote["reasons"])
    with pytest.raises(APISettingsError, match="결과 불명"):
        reserve(sessions, stamp)


@pytest.mark.parametrize("limit,reason", [("monthly_limit_usd", "USD 한도"),
                                         ("account_remaining_usd", "잔여 예산")])
def test_prior_completed_reservations_still_consume_month_and_account_limits(sessions, limit, reason):
    stamp = configured(sessions, **{limit: "6"})
    result = reserve(sessions, stamp)
    APIBudgetService(sessions).finish(result.id, status="failed")
    new_stamp = utcnow().isoformat()
    with sessions.begin() as session:
        _set(session, "api_claude_api_authentication_verified_at", new_stamp)
    assert not first_search_readiness(sessions, "claude_api", StatusOnlyStore())["ready"]
    with pytest.raises(APISettingsError, match=reason):
        reserve(sessions, new_stamp)


def test_concurrent_first_search_is_reserved_once(sessions):
    stamp = configured(sessions)

    def attempt(_):
        try:
            return reserve(sessions, stamp)
        except APISettingsError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (1, 2)))
    assert sum(result is not None for result in results) == 1
    with sessions() as session:
        assert len(list(session.scalars(select(APIRequestReservation)))) == 1


def test_invalidating_one_provider_clears_summary_without_touching_other_provider(sessions):
    configured(sessions)
    configured(sessions, "openai")
    with sessions.begin() as session:
        _set(session, "api_claude_api_search_check_summary", "old-summary")
        _set(session, "api_openai_search_check_summary", "keep-other")
    before = settings_values(sessions)
    invalidate_api_verification(sessions, "claude_api")
    after = settings_values(sessions)
    assert after["api_claude_api_search_check_summary"] == ""
    assert after["api_claude_api_monthly_limit_usd"] == before["api_claude_api_monthly_limit_usd"]
    assert all(after[key] == value for key, value in before.items() if key.startswith("api_openai_"))
