"""Token/cost estimates, user-entered prices, per-duration caps and the stricter AI gate."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from unittest.mock import patch

import pytest
import test_api_news_pipeline
from conftest import csrf
from sqlalchemy import select
from test_api_news_pipeline import settled, start

from newsflow.db.models import AIUsage, AppSetting, IntelligenceRun, NewsSource
from newsflow.intelligence.credentials import AIKeyStore, FakeCipher
from newsflow.intelligence.estimate import (
    estimate_call,
    estimate_cost,
    estimate_job,
    estimate_tokens,
    parse_price,
    representative_evidence,
)
from newsflow.intelligence.provider import (
    SCRIPT_INSTRUCTION,
    FakeProvider,
    OpenAIProvider,
    Options,
    user_message,
    prompt_instruction,
)
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import (
    ANALYSIS_MAX_TOKENS,
    SCRIPT_MAX_TOKENS,
    SettingsError,
    check_budget,
    external_ready,
    job_estimate,
    max_tokens_for,
    read_prices,
    read_settings,
    write_prices,
    write_settings,
    write_studio_settings,
)

api_pipeline = test_api_news_pipeline.api_pipeline

KEY = "sk-synthetic-not-a-real-key-0123456789abcdef"


def test_estimate_tokens_is_conservative_and_monotone():
    assert estimate_tokens("") == 0
    korean = "정부는 오늘 내년도 예산안을 발표했습니다." * 5
    ascii_text = "The government announced next year's budget today." * 5
    assert estimate_tokens(korean) >= len(korean.replace(" ", "").replace(".", "")) * 0.8  # ~1 token per syllable
    assert estimate_tokens(ascii_text) < len(ascii_text) / 2
    assert estimate_tokens(korean + korean) > estimate_tokens(korean)
    assert estimate_tokens("a") == 1


def test_estimate_call_counts_exactly_what_the_provider_sends():
    for version in ("v1", "v2"):
        payload = {"duration": 30, "evidence": {**representative_evidence(), "script_prompt_version": version}}
        instruction = prompt_instruction("script", payload["evidence"])
        output_maximum = 1400 + (600 if version == "v2" else 0)
        estimate = estimate_call(instruction, payload, output_maximum)
        assert estimate["prompt_tokens"] > 0 and estimate["total_max"] == estimate["prompt_tokens"] + output_maximum
        assert estimate["prompt_chars"] == len(instruction) + len(user_message(payload))

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        body = {"choices": [{"message": {"content": json.dumps({"title": "x"})}}]}
        captured = {}

        class Opener:
            def open(self, request, timeout=None):
                captured["data"] = request.data
                return Response(json.dumps(body).encode())

        provider = OpenAIProvider(lambda: KEY)
        with patch("urllib.request.build_opener", return_value=Opener()):
            provider.complete(payload["evidence"], 30, Options(max_tokens=1400))
        sent = json.loads(captured["data"])
        assert sent["messages"][1]["content"] == user_message(payload)
        assert sent["messages"][0]["content"] == instruction and sent["max_tokens"] == output_maximum


def test_estimate_job_counts_two_calls_and_per_duration_caps():
    estimate = estimate_job(representative_evidence(), 60, max_tokens_for(60), ANALYSIS_MAX_TOKENS)
    assert estimate["calls"] == 2 and [c["kind"] for c in estimate["per_call"]] == ["analysis", "script"]
    assert estimate["output_tokens_max"] == ANALYSIS_MAX_TOKENS + SCRIPT_MAX_TOKENS[60]
    assert estimate["total_max"] == sum(c["total_max"] for c in estimate["per_call"])
    assert max_tokens_for(30) == 1400 and max_tokens_for(45) == 1800 and max_tokens_for(99) == 1800
    assert all(200 <= value <= 3000 for value in SCRIPT_MAX_TOKENS.values())
    single = estimate_job(representative_evidence(), 30, 1400, None)
    assert single["calls"] == 1 and single["per_call"][0]["kind"] == "script"


def test_prices_and_cost_math():
    assert parse_price("") is None and parse_price(None) is None and parse_price(" 0.15 ") == Decimal("0.15")
    for bad in ("-1", "abc", "1.1234567", "100001", "sk-abcdef1234567890"):
        with pytest.raises(ValueError):
            parse_price(bad)
    estimate = {"prompt_tokens": 1000, "output_tokens_max": 1800}
    assert estimate_cost(estimate, {"input_per_1m": None, "output_per_1m": Decimal(1)}) is None
    cost = estimate_cost(estimate, {"input_per_1m": Decimal("0.15"), "output_per_1m": Decimal("0.60"), "currency": "USD"})
    assert cost == {"amount": "0.0012", "currency": "USD", "basis": "사용자 입력 단가 · 참고용 추정치"}


def test_write_prices_round_trip_and_estimate_in_readiness(app, monkeypatch):
    sessions = app.state.sessions
    assert read_prices(sessions) == {"input_per_1m": None, "output_per_1m": None, "currency": "USD"}
    with pytest.raises(SettingsError):
        write_prices(sessions, "0.15", "bad", "USD")
    with pytest.raises(SettingsError):
        write_prices(sessions, "0.15", "0.60", "EUR")
    saved = write_prices(sessions, "0.15", "0.60", "USD")
    assert saved["input_per_1m"] == Decimal("0.15") and saved["output_per_1m"] == Decimal("0.60")
    estimate = job_estimate(sessions, 30)
    assert estimate["calls"] == 2 and estimate["cost"]["currency"] == "USD" and estimate["representative"] is True
    store = AIKeyStore(app.state.config.data_dir, FakeCipher())
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    status = external_ready(sessions, store)
    assert status["estimate"]["total_max"] > 0 and status["prices"]["configured"] is True
    assert status["remaining_tokens"] == 0
    write_prices(sessions, "", "", "KRW")
    assert read_prices(sessions)["input_per_1m"] is None and job_estimate(sessions, 45)["cost"] is None
    with app.state.sessions() as session:
        assert all("sk-" not in s.value for s in session.scalars(select(AppSetting)))


def test_check_budget_reserves_prompt_estimate_with_numbers(app):
    sessions = app.state.sessions
    settings = write_settings(sessions, "openai", "gpt-4o-mini", True, 3000, 20)
    check_budget(sessions, settings, Options(max_tokens=1500), prompt_estimate=1500)
    with pytest.raises(SettingsError) as failure:
        check_budget(sessions, settings, Options(max_tokens=1500), prompt_estimate=1501)
    assert "사용 0" in str(failure.value) and "한도 3000" in str(failure.value)


def _collect_fixture(app):
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Fixture", url="https://example.com/rss", enabled=True))
    app.state.coordinator.start()
    app.state.coordinator.future.result(timeout=10)


def test_evidence_for_matches_stored_analysis_and_gate_requires_openai_provider(app, monkeypatch):
    _collect_fixture(app)
    sessions = app.state.sessions
    store = AIKeyStore(app.state.config.data_dir, FakeCipher())
    store.save(KEY)
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    service = IntelligenceService(sessions, None, store)
    evidence = service.evidence_for([1, 2])
    analysis_id = service.analyze([1, 2])
    with sessions() as session:
        assert session.get(IntelligenceRun, analysis_id).evidence == evidence
    with pytest.raises(IntelligenceError):
        service.evidence_for([999])
    # Approval and limit present but provider left on 기본 대본: no external call is made.
    write_settings(sessions, "offline", "gpt-4o-mini", True, 100_000, 20)
    provider = FakeProvider()
    service.provider = provider
    with pytest.raises(IntelligenceError) as failure:
        service.generate(analysis_id, 30, mode="openai", consent=True)
    assert failure.value.code == "ai_consent" and provider.calls == 0
    write_settings(sessions, "openai", "gpt-4o-mini", True, 100_000, 20)
    service.generate(analysis_id, 30, mode="openai", consent=True)
    assert provider.calls == 1


def test_unreadable_stored_key_maps_to_key_missing_without_leaking(app, monkeypatch):
    _collect_fixture(app)
    sessions = app.state.sessions
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    good = AIKeyStore(app.state.config.data_dir, FakeCipher())
    good.save(KEY)
    broken = AIKeyStore(app.state.config.data_dir, FakeCipher(fail=True))
    write_settings(sessions, "openai", "gpt-4o-mini", True, 100_000, 20)
    service = IntelligenceService(sessions, None, broken)
    analysis_id = service.analyze([1])
    with pytest.raises(IntelligenceError) as failure:
        service.generate(analysis_id, 30, mode="openai", consent=True)
    assert failure.value.code == "ai_key_missing" and not failure.value.retryable and KEY not in str(failure.value)
    with sessions() as session:
        failed = session.scalars(select(AIUsage).where(AIUsage.status == "failed")).all()
        assert len(failed) == 1 and failed[0].total_tokens == 0
    assert read_settings(sessions).provider == "openai"


def test_gui_prices_form_and_estimate_text(client, app, monkeypatch):
    app.state.ai_keys = AIKeyStore(app.state.config.data_dir, FakeCipher())
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    page = client.get("/ai-settings")
    assert page.status_code == 200 and page.url.path == "/simple-settings"
    assert 'id="ai-estimate"' not in page.text and 'action="/ai-settings/prices"' not in page.text
    assert 'action="/api-settings/openai"' in page.text
    assert "실제 청구액은 공급사에서 확인하세요" in page.text
    token = csrf(client)
    assert client.post("/ai-settings/prices", data={"csrf_token": token, "input_per_1m": "x", "output_per_1m": "1", "currency": "USD"}).status_code == 422
    assert client.post("/ai-settings/prices", data={"csrf_token": token, "input_per_1m": "0.15", "output_per_1m": "0.60", "currency": "XYZ"}).status_code == 422
    saved = client.post("/ai-settings/prices", data={"csrf_token": token, "input_per_1m": "0.15", "output_per_1m": "0.60", "currency": "USD"})
    assert saved.status_code == 200 and "기존 단가 기록을 저장했습니다" in saved.text
    assert read_prices(app.state.sessions)["input_per_1m"] == Decimal("0.15")
    assert read_prices(app.state.sessions)["output_per_1m"] == Decimal("0.60")
    assert client.post("/ai-settings/prices", data={"input_per_1m": "1"}).status_code == 403
    _collect_fixture(app)
    write_settings(app.state.sessions, "openai", "gpt-4.1-mini", False, 0, 25)
    write_studio_settings(app.state.sessions, "openai", "gpt-4.1-mini")
    studio = client.get("/ai")
    assert studio.status_code == 200
    assert 'value="gpt-4.1-mini"' in studio.text  # analysis form defaults to the saved model
    analysis_id = IntelligenceService(app.state.sessions).analyze([1])
    with_estimate = client.get(f"/ai?analysis_id={analysis_id}").text
    # An existing Offline analysis keeps its own execution identity, not new global defaults.
    assert 'value="25"' in with_estimate and 'value="offline" selected' in with_estimate
    assert 'value="gpt-4.1-mini"' not in with_estimate
    assert 'id="studio-estimate"' not in with_estimate and "단가 미입력" not in with_estimate
    assert 'action="/ai-settings/prices"' not in with_estimate
    assert read_prices(app.state.sessions)["currency"] == "USD"
    assert read_prices(app.state.sessions)["input_per_1m"] == Decimal("0.15")


def test_start_and_job_pages_show_estimate_then_actual_usage(client, app, api_pipeline, monkeypatch):
    """Historical name retained; the approved UI shows returned usage, not a pre-call quote."""
    coordinator, backend, provider, sessions, mode, _ = api_pipeline
    monkeypatch.setattr(app.state, "autopilot", coordinator)
    monkeypatch.setattr(app.state, "autopilot_backend", backend)
    page = client.get("/autopilot/start").text
    assert 'id="start-ai-estimate"' not in page and "제작 시작은 홈에서" in page
    assert provider.calls == []
    identifier = start(api_pipeline, acquisition_policy="rss")
    job = settled(api_pipeline, identifier)
    assert (job["status"], job["current_stage"]) == ("waiting_review", "script")
    page = client.get(f"/autopilot/jobs/{identifier}").text
    assert 'id="ai-actual"' in page and "로컬 기록 400 토큰 (호출 2회" in page
    assert 'id="ai-estimate"' not in page
    assert provider.calls == ["analysis", "script"]
    with sessions() as session:
        runs = list(session.scalars(select(IntelligenceRun).where(IntelligenceRun.provider == mode)))
        assert {run.options["script_prompt_version"] for run in runs} == {"v2"}
        assert {run.options["max_tokens"] for run in runs} == {ANALYSIS_MAX_TOKENS + 400, SCRIPT_MAX_TOKENS[30] + 600}
        assert all(run.options["base_max_tokens"] == (ANALYSIS_MAX_TOKENS if run.kind == "analysis" else SCRIPT_MAX_TOKENS[30]) for run in runs)
        assert all(run.options["output_token_allowance"] == (400 if run.kind == "analysis" else 600) for run in runs)
        assert all(run.options["model"] == job["ai_model"] for run in runs)
        assert sum(row.total_tokens for row in session.scalars(select(AIUsage))) == 400


def test_rendered_price_form_carries_its_own_csrf_token_and_saves(client, app, monkeypatch):
    """Submit exactly the fields the rendered form contains, as a browser would."""
    import re

    app.state.ai_keys = AIKeyStore(app.state.config.data_dir, FakeCipher())
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    page = client.get("/ai-settings").text
    assert 'action="/ai-settings/prices"' not in page
    form = re.search(r'<form method="post" action="/api-settings/openai".*?</form>', page, re.DOTALL).group(0)
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form).group(1)
    fields = {"csrf_token": token}
    assert token, "the canonical API cost form must render csrf_field()"
    fields.update({"input_per_1m": "0.15", "output_per_1m": "0.60", "currency": "USD"})
    saved = client.post("/ai-settings/prices", data=fields)
    assert saved.status_code == 200 and "기존 단가 기록을 저장했습니다" in saved.text
    assert read_prices(app.state.sessions)["input_per_1m"] == Decimal("0.15")
    # Every POST form on the page renders its own token.
    assert page.count('name="csrf_token"') == page.count('method="post"')


def test_retried_failed_script_tokens_stay_in_the_job_total(client, app, api_pipeline, monkeypatch):
    """Retain failed usage; the approved no-replay policy replaces the old retry expectation."""
    from newsflow.autopilot.contracts import AutopilotConflict
    from newsflow.gui.autopilot_routes import _ai_usage
    from newsflow.intelligence.provider import ProviderResponseError

    coordinator, backend, provider, sessions, _, _ = api_pipeline
    monkeypatch.setattr(app.state, "autopilot", coordinator)
    monkeypatch.setattr(app.state, "autopilot_backend", backend)
    complete = provider.complete

    def invalid_response(*args):
        complete(*args)  # Records a synthetic returned usage event before schema rejection.
        raise ProviderResponseError()

    monkeypatch.setattr(provider, "complete", invalid_response)
    identifier = start(api_pipeline, acquisition_policy="rss")
    failed = settled(api_pipeline, identifier)
    assert failed["status"] == "failed" and failed["error_code"] == "ai_bad_response"
    assert failed["retryable"] is False and provider.calls == ["analysis", "script"]
    with pytest.raises(AutopilotConflict):
        coordinator.retry(identifier, failed["revision"])
    assert coordinator.recover() == 0
    assert provider.calls == ["analysis", "script"]
    with sessions() as session:
        rows = list(session.scalars(select(AIUsage).order_by(AIUsage.id)))
        assert [row.status for row in rows] == ["success", "failed"]
        assert sum(row.total_tokens for row in rows) == 400
    from types import SimpleNamespace

    _, actual = _ai_usage(SimpleNamespace(app=app), failed, None)
    assert (actual["total"], actual["calls"], actual["failed"]) == (400, 2, 1)
    page = client.get(f"/autopilot/jobs/{identifier}").text
    assert "대본" in page and 'action="/autopilot/jobs/' + identifier + '/retry"' not in page
