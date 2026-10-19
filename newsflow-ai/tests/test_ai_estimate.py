"""Token/cost estimates, user-entered prices, per-duration caps and the stricter AI gate."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from conftest import csrf
from sqlalchemy import select

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
)

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
    payload = {"duration": 30, "evidence": representative_evidence()}
    estimate = estimate_call(SCRIPT_INSTRUCTION, payload, 1400)
    assert estimate["prompt_tokens"] > 0 and estimate["total_max"] == estimate["prompt_tokens"] + 1400
    assert estimate["prompt_chars"] == len(SCRIPT_INSTRUCTION) + len(user_message(payload))

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
    assert sent["messages"][0]["content"] == SCRIPT_INSTRUCTION and sent["max_tokens"] == 1400


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
    studio = client.get("/ai")
    assert studio.status_code == 200
    assert 'value="gpt-4.1-mini"' in studio.text  # analysis form defaults to the saved model
    analysis_id = IntelligenceService(app.state.sessions).analyze([1])
    with_estimate = client.get(f"/ai?analysis_id={analysis_id}").text
    assert 'value="25"' in with_estimate and with_estimate.count('value="gpt-4.1-mini"') == 2
    assert 'id="studio-estimate"' in with_estimate and "단가 미입력" not in with_estimate and " USD" in with_estimate


class _ScriptProvider(FakeProvider):
    def analyze(self, evidence, options):
        self.calls += 1
        from newsflow.intelligence.provider import OfflineProvider

        return OfflineProvider().analyze(evidence, options)


def test_start_and_job_pages_show_estimate_then_actual_usage(client, app, monkeypatch):
    from newsflow.video.engine import FakeRenderAdapter
    from newsflow.video.tts import FakeTTS

    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", KEY)
    _collect_fixture(app)
    sessions = app.state.sessions
    write_settings(sessions, "openai", "gpt-4o-mini", True, 100_000, 20)
    start = client.get("/autopilot/start").text
    assert 'id="start-ai-estimate"' in start and "예상 최대 약" in start and "단가 미입력" in start and "준비 안 됨" not in start
    script = {
        "title": "실제 뉴스 요약", "hook": "오늘의 보도입니다.", "summary": "보도된 내용의 요약입니다.", "closing": "원문을 확인하세요.",
        "scenes": [{"seconds": 10, "narration": f"{n} 장면 내용입니다.", "caption": "자막", "material": "카드"} for n in ("첫", "둘째", "셋째")],
    }
    provider = _ScriptProvider(script, usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70})
    app.state.autopilot_backend.intelligence.provider = provider
    app.state.video.tts, app.state.video.engine = FakeTTS(), FakeRenderAdapter()
    response = client.post("/autopilot/start", data={"csrf_token": csrf(client), "source": "feeds", "mode": "guided", "ai": "openai", "duration": "30"}, follow_redirects=False)
    assert response.status_code == 303
    app.state.autopilot.future.result(timeout=20)
    job_id = response.headers["location"].rsplit("/", 1)[1]
    snapshot = app.state.autopilot.snapshot(job_id)
    assert snapshot["status"] == "waiting_review" and snapshot["current_stage"] == "select"
    before = client.get(f"/autopilot/jobs/{job_id}").text
    assert 'id="ai-estimate"' in before and "호출 2회" in before and "참고용 추정치" in before and provider.calls == 0
    app.state.autopilot.resume(job_id, snapshot["revision"], article_id=snapshot["article_id"])
    app.state.autopilot.future.result(timeout=20)
    after = client.get(f"/autopilot/jobs/{job_id}").text
    assert app.state.autopilot.snapshot(job_id)["current_stage"] == "script"
    assert 'id="ai-actual"' in after and "실제 사용 140 토큰 (호출 2회" in after and 'id="ai-estimate"' not in after
    with sessions() as session:
        runs = session.scalars(select(IntelligenceRun).where(IntelligenceRun.provider == "openai")).all()
        assert {run.options["max_tokens"] for run in runs} == {ANALYSIS_MAX_TOKENS, SCRIPT_MAX_TOKENS[30]}
        assert all(run.options["model"] == "gpt-4o-mini" and run.options["timeout"] == 20 for run in runs)


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


def test_retried_failed_script_tokens_stay_in_the_job_total(client, app, monkeypatch):
    from newsflow.video.engine import FakeRenderAdapter
    from newsflow.video.tts import FakeTTS

    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", KEY)
    _collect_fixture(app)
    write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 100_000, 20)
    usage = {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}
    good = {
        "title": "실제 뉴스 요약", "hook": "오늘의 보도입니다.", "summary": "보도된 내용의 요약입니다.", "closing": "원문을 확인하세요.",
        "scenes": [{"seconds": 10, "narration": f"{n} 장면 내용입니다.", "caption": "자막", "material": "카드"} for n in ("첫", "둘째", "셋째")],
    }
    backend = app.state.autopilot_backend
    backend.intelligence.provider = _ScriptProvider({"title": "형식이 틀린 응답"}, usage=usage)
    app.state.video.tts, app.state.video.engine = FakeTTS(), FakeRenderAdapter()
    response = client.post("/autopilot/start", data={"csrf_token": csrf(client), "source": "feeds", "mode": "easy", "ai": "openai", "duration": "30"}, follow_redirects=False)
    app.state.autopilot.future.result(timeout=20)
    job_id = response.headers["location"].rsplit("/", 1)[1]
    failed = app.state.autopilot.snapshot(job_id)
    assert failed["status"] == "failed" and failed["error_code"] == "ai_bad_response" and failed["retryable"]
    backend.intelligence.provider = _ScriptProvider(good, usage=usage)
    app.state.autopilot.retry(job_id, failed["revision"])
    app.state.autopilot.future.result(timeout=20)
    assert app.state.autopilot.snapshot(job_id)["current_stage"] == "script"
    page = client.get(f"/autopilot/jobs/{job_id}").text
    # analysis 70 + failed script 70 + successful script 70; the failed attempt is not dropped after the retry.
    assert "실제 사용 210 토큰 (호출 3회 · 실패 1회 포함" in page
