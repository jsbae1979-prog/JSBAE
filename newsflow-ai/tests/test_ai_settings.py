"""AI settings, approval gate, monthly budget, key store and the AI connection GUI."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import AIUsage, AppSetting, NewsSource, utcnow
from newsflow.intelligence.credentials import AIKeyStore, CredentialError, FakeCipher
from newsflow.intelligence.provider import FakeProvider, Options, ProviderAuthError
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import (
    SettingsError,
    check_budget,
    external_ready,
    read_settings,
    record_usage,
    usage_this_month,
    write_settings,
)

KEY = "sk-synthetic-not-a-real-key-0123456789abcdef"


@pytest.fixture
def store(tmp_path):
    return AIKeyStore(tmp_path / "data", FakeCipher())


def test_key_store_roundtrip_clear_and_validation(store, monkeypatch):
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    assert store.status() == {"configured": False, "source": None, "stored": False, "environment": False, "storage_supported": True}
    assert store.key() == ""
    store.save("  " + KEY + "  ")
    assert store.path.read_bytes().startswith(b"FAKE") and KEY.encode() not in store.path.read_bytes()
    assert store.key() == KEY and store.status()["source"] == "stored"
    store.clear()
    assert not store.path.exists() and store.status()["configured"] is False
    for bad in ("short", "has space in it 12345678901234567890", "x" * 300):
        with pytest.raises(CredentialError):
            store.save(bad)


def test_stored_key_wins_over_environment_and_cipher_failure_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", "env-key-value-1234567890abcdef")
    store = AIKeyStore(tmp_path, FakeCipher())
    assert store.key() == "env-key-value-1234567890abcdef" and store.status()["source"] == "environment"
    store.save(KEY)
    assert store.key() == KEY
    broken = AIKeyStore(tmp_path, FakeCipher(fail=True))
    with pytest.raises(CredentialError) as failure:
        broken.key()
    assert KEY not in str(failure.value)
    unsupported = AIKeyStore(tmp_path / "other")
    if unsupported.status()["storage_supported"] is False:
        with pytest.raises(CredentialError):
            unsupported.save(KEY)


def test_settings_require_limit_for_approval_and_keep_first_approval_date(app):
    sessions = app.state.sessions
    assert read_settings(sessions).provider == "offline"
    with pytest.raises(SettingsError):
        write_settings(sessions, "openai", "gpt-4o-mini", True, 0, 20)
    with pytest.raises(SettingsError):
        write_settings(sessions, "openai", "bad model name!", True, 1000, 20)
    first = write_settings(sessions, "openai", "gpt-4o-mini", True, 50_000, 25)
    assert first.approved and first.approved_at and first.monthly_token_limit == 50_000 and first.timeout == 25
    again = write_settings(sessions, "openai", "gpt-4o-mini", True, 60_000, 25)
    assert again.approved_at == first.approved_at
    revoked = write_settings(sessions, "openai", "gpt-4o-mini", False, 60_000, 25)
    assert not revoked.approved and revoked.approved_at is None


def test_budget_counts_current_month_only_and_blocks_before_call(app, store, monkeypatch):
    sessions = app.state.sessions
    settings = write_settings(sessions, "openai", "gpt-4o-mini", True, 3000, 20)
    record_usage(sessions, run_id=None, provider="openai", model="m", kind="script", status="success",
                 usage={"prompt_tokens": 1000, "completion_tokens": 500}, elapsed_ms=10)
    with sessions.begin() as session:
        old = AIUsage(run_id=None, provider="openai", model="m", kind="script", status="success",
                      prompt_tokens=9000, completion_tokens=0, total_tokens=9000, elapsed_ms=1,
                      created_at=utcnow() - timedelta(days=40))
        session.add(old)
    assert usage_this_month(sessions)["tokens"] == 1500
    check_budget(sessions, settings, Options(max_tokens=1500))
    with pytest.raises(SettingsError):
        check_budget(sessions, settings, Options(max_tokens=1600))
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    status = external_ready(sessions, store)
    assert not status["ready"] and "API 키가 없습니다." in status["reasons"]
    store.save(KEY)
    assert external_ready(sessions, store)["ready"] is True
    record_usage(sessions, run_id=None, provider="openai", model="m", kind="script", status="success",
                 usage={"total_tokens": 2000}, elapsed_ms=10)
    assert "이번 달 토큰 한도를 모두 사용했습니다." in external_ready(sessions, store)["reasons"]


def test_service_records_usage_and_maps_auth_failure(app, store):
    sessions = app.state.sessions
    write_settings(sessions, "openai", "gpt-4o-mini", True, 100_000, 20)
    with sessions.begin() as session:
        session.add(NewsSource(name="Fixture", url="https://example.com/rss", enabled=True))
    app.state.coordinator.start()
    app.state.coordinator.future.result(timeout=10)
    provider = FakeProvider(usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
    service = IntelligenceService(sessions, provider, store)
    analysis = service.analyze([1], mode="openai", consent=True)
    service.generate(analysis, 30, mode="openai", consent=True)
    rows = usage_this_month(sessions)
    assert rows == {"tokens": 30, "calls": 2, "since": rows["since"]}
    service.provider = FakeProvider(ProviderAuthError("SECRET-DETAIL"))
    with pytest.raises(IntelligenceError) as failure:
        service.generate(analysis, 30, mode="openai", consent=True)
    assert failure.value.code == "ai_auth_failed" and "SECRET" not in str(failure.value)
    with sessions() as session:
        failed = session.scalars(select(AIUsage).where(AIUsage.status == "failed")).all()
        assert len(failed) == 1 and failed[0].total_tokens == 0


def test_gui_saves_settings_and_key_without_echo(client, app, monkeypatch):
    app.state.ai_keys = AIKeyStore(app.state.config.data_dir, FakeCipher())
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    page = client.get("/ai-settings")
    assert page.status_code == 200 and "외부 AI 사용 불가" in page.text and 'type="password"' in page.text
    token = csrf(client)
    assert client.post("/ai-settings", data={"csrf_token": token, "provider": "openai", "model": "gpt-4o-mini",
                                             "approved": "true", "monthly_token_limit": "0", "timeout": "20"}).status_code == 422
    saved = client.post("/ai-settings", data={"csrf_token": token, "provider": "openai", "model": "gpt-4o-mini",
                                              "approved": "true", "monthly_token_limit": "100000", "timeout": "30"})
    assert saved.status_code == 200 and "AI 설정을 저장했습니다" in saved.text
    stored = client.post("/ai-settings/key", data={"csrf_token": token, "api_key": KEY})
    assert stored.status_code == 200 and KEY not in stored.text and "계정 보호 저장소" in stored.text
    assert "외부 AI 사용 가능" in client.get("/ai-settings").text
    with app.state.sessions() as session:
        assert KEY not in json.dumps([(s.key, s.value) for s in session.scalars(select(AppSetting))], ensure_ascii=False)
    assert client.post("/ai-settings/key", data={"csrf_token": token, "api_key": "short"}).status_code == 422
    cleared = client.post("/ai-settings/key/clear", data={"csrf_token": token})
    assert cleared.status_code == 200 and "삭제했습니다" in cleared.text
    assert client.post("/ai-settings", data={"provider": "openai"}).status_code == 403


def test_gui_connection_check_uses_zero_token_lookup_and_stores_safe_result(client, app):
    app.state.ai_keys = AIKeyStore(app.state.config.data_dir, FakeCipher())
    app.state.ai_keys.save(KEY)
    token = csrf(client)
    client.post("/ai-settings", data={"csrf_token": token, "provider": "openai", "model": "gpt-4o-mini",
                                      "approved": "true", "monthly_token_limit": "1000", "timeout": "20"})

    class Checker:
        def check_connection(self, options):
            assert options.model == "gpt-4o-mini"
            return {"ok": True, "model": "gpt-4o-mini", "elapsed_ms": 3, "tokens": 0}

    app.state.ai_provider = Checker()
    checked = client.post("/ai-settings/check", data={"csrf_token": token})
    assert checked.status_code == 200 and "연결 성공" in checked.text and "토큰 사용 0" in checked.text

    class Broken:
        def check_connection(self, options):
            raise ProviderAuthError("AI 인증에 실패했습니다. API 키와 권한을 확인하세요.")

    app.state.ai_provider = Broken()
    failed = client.post("/ai-settings/check", data={"csrf_token": token})
    assert failed.status_code == 200 and "AI 인증에 실패" in failed.text
    with app.state.sessions() as session:
        assert "SECRET" not in session.get(AppSetting, "ai_last_check").value
    del app.state.ai_provider
