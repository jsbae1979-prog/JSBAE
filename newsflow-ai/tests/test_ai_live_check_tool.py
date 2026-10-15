"""Offline tests for tools/ai_live_check.py: every gate blocks before a paid call; evidence is key-free."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from newsflow.autopilot.samples import SAMPLE_NAME, SAMPLE_URL
from newsflow.db.models import AIUsage, ContentDraft, NewsArticle, NewsSource
from newsflow.intelligence.credentials import AIKeyStore, FakeCipher
from newsflow.intelligence.provider import FakeProvider, OfflineProvider, ProviderAuthError
from newsflow.intelligence.settings import write_prices, write_settings

KEY = "sk-synthetic-not-a-real-key-0123456789abcdef"
SCRIPT = {
    "title": "실제 뉴스 요약", "hook": "오늘의 보도입니다.", "summary": "보도된 내용의 요약입니다.", "closing": "원문을 확인하세요.",
    "scenes": [
        {"seconds": 10, "narration": "첫 번째 장면 UNIQUE-NARRATION 내용입니다.", "caption": "첫 장면", "material": "카드"},
        {"seconds": 10, "narration": "두 번째 장면 내용입니다.", "caption": "둘째 장면", "material": "카드"},
        {"seconds": 10, "narration": "세 번째 장면 내용입니다.", "caption": "셋째 장면", "material": "카드"},
    ],
}


class ScriptProvider(FakeProvider):
    def analyze(self, evidence, options):
        self.calls += 1
        return OfflineProvider().analyze(evidence, options)


@pytest.fixture
def tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "ai_live_check.py"
    spec = importlib.util.spec_from_file_location("ai_live_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def collected(app, monkeypatch):
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Fixture", url="https://example.com/rss", enabled=True))
    app.state.coordinator.start()
    app.state.coordinator.future.result(timeout=10)
    store = AIKeyStore(app.state.config.data_dir, FakeCipher())
    forbidden = Mock(side_effect=AssertionError("network"))
    monkeypatch.setattr("newsflow.intelligence.provider.OpenAIProvider.request", forbidden)
    return store, forbidden


def run(tool, app, store, tmp_path, **overrides):
    kwargs = {"article_id": 1, "duration": 30, "max_tokens": 1400, "output": tmp_path / "out", "yes": True,
              "sessions": app.state.sessions, "store": store, "environ": {"NEWSFLOW_AI_LIVE_TEST": "1"}}
    kwargs.update(overrides)
    return tool.run(**kwargs)


def test_blocked_without_env_flag_or_gate(tool, app, collected, tmp_path):
    store, forbidden = collected
    result = run(tool, app, store, tmp_path, environ={})
    assert result["outcome"] == "BLOCKED" and result["reason"] == "env_flag" and result["external_ai_calls"] == 0
    result = run(tool, app, store, tmp_path)
    assert result["reason"] == "gate_closed" and "API 키가 없습니다." in " ".join(result["gate"]["reasons"])
    assert run(tool, app, store, tmp_path, max_tokens=100)["reason"] == "max_tokens"
    assert not forbidden.called


def test_blocked_for_sample_article_budget_and_refused_confirmation(tool, app, collected, tmp_path):
    store, forbidden = collected
    write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 100_000, 20)
    store.save(KEY)
    with app.state.sessions.begin() as session:
        sample = NewsSource(name=SAMPLE_NAME, url=SAMPLE_URL, enabled=False)
        session.add(sample)
        session.flush()
        session.add(NewsArticle(title="[합성] 연습 기사", url="https://example.com/newsflow/synthetic/1",
                                canonical_url="https://example.com/newsflow/synthetic/1", source_id=sample.id,
                                publisher="합성", summary="합성 요약"))
        synthetic_id = session.scalar(select(NewsArticle.id).where(NewsArticle.source_id == sample.id))
    assert run(tool, app, store, tmp_path, article_id=synthetic_id)["reason"] == "article_not_real"
    assert run(tool, app, store, tmp_path, article_id=999)["reason"] == "article_missing"
    refused = run(tool, app, store, tmp_path, yes=False, confirm=lambda prompt: "아니오")
    assert refused["reason"] == "not_confirmed" and "출력 상한 1400" in refused["confirmation_summary"]
    write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 1500, 20)
    assert run(tool, app, store, tmp_path)["reason"] == "budget"
    assert not forbidden.called
    with app.state.sessions() as session:
        assert session.scalar(select(ContentDraft)) is None and session.scalar(select(AIUsage)) is None


def test_single_paid_call_writes_key_free_evidence(tool, app, collected, tmp_path):
    store, forbidden = collected
    write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 100_000, 20)
    write_prices(app.state.sessions, "0.15", "0.60", "USD")
    store.save(KEY)
    provider = ScriptProvider(SCRIPT, usage={"prompt_tokens": 900, "completion_tokens": 300, "total_tokens": 1200})
    result = run(tool, app, store, tmp_path, provider=provider, yes=False, confirm=lambda prompt: "동의")
    assert result["outcome"] == "PASS" and result["external_ai_calls"] == 1 and provider.calls == 1
    assert result["usage_rows"] == [{"status": "success", "prompt_tokens": 900, "completion_tokens": 300, "total_tokens": 1200,
                                     "elapsed_ms": 1, "model": "gpt-4o-mini"}]
    assert result["estimate"]["cost"]["currency"] == "USD" and result["prompt_ratio_actual_over_estimate"] > 0
    assert result["usage_after"]["tokens"] == 1200 and result["review_status"] == "review_required"
    target = tool.write_evidence(result, tmp_path / "out", KEY)
    text = target.read_text(encoding="utf-8")
    assert KEY not in text and "UNIQUE-NARRATION" not in text and json.loads(text)["outcome"] == "PASS"
    with pytest.raises(RuntimeError):
        tool.write_evidence({"leak": KEY}, tmp_path / "out", KEY)
    assert not forbidden.called


def test_provider_failure_is_recorded_as_fail_without_details(tool, app, collected, tmp_path):
    store, _forbidden = collected
    write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 100_000, 20)
    store.save(KEY)
    provider = ScriptProvider(ProviderAuthError("SECRET-DETAIL"))
    result = run(tool, app, store, tmp_path, provider=provider)
    assert result["outcome"] == "FAIL" and result["code"] == "ai_auth_failed" and "SECRET" not in json.dumps(result)
    assert result["external_ai_calls"] == 1 and result["retryable"] is False


def test_main_blocks_when_the_app_holds_its_locks(tool, app, tmp_path, monkeypatch):
    from filelock import FileLock

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("NEWSFLOW_AI_LIVE_TEST", "1")
    lock = FileLock(str(data / "server-8765.lock"))
    lock.acquire(timeout=0)
    try:
        result = tool.run(article_id=1, duration=30, max_tokens=1400, output=tmp_path / "o", yes=True, data_dir=data)
    finally:
        lock.release()
    assert result["outcome"] == "BLOCKED" and result["reason"] == "app_running"
