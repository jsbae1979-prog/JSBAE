"""Real adapter + Fake HTTP, isolated DB only; never replay an operating request."""

import json
from copy import deepcopy
from decimal import Decimal

import pytest
from sqlalchemy import select
from test_api_settings import configured, reserve
from test_api_settings import sessions as sessions  # noqa: PLC0414 - shared pytest fixture
from test_api_settings import store as store  # noqa: PLC0414 - shared pytest fixture

from newsflow.db.models import (
    APIRequestReservation,
    AppSetting,
    AuditLog,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
)
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.api_settings import (
    APISettingsError,
    FakeAPIBudgetService,
    acknowledge_unknown_analysis,
)
from newsflow.intelligence.provider import AnalysisResponseError, Options
from newsflow.intelligence.schema import Analysis
from newsflow.intelligence.service import IntelligenceError, IntelligenceService

RAW = "RAW_RESPONSE_MARKER_NEVER_PERSIST"


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda *_a, **_k: pytest.fail("No real API"))
    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: pytest.fail("No CLI or rendering"))
    for key in ("NEWSFLOW_AI_API_KEY", "NEWSFLOW_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def state(sessions, store, monkeypatch):
    configured(sessions)
    with sessions.begin() as session:
        source = NewsSource(name="합성 RSS 출처", url="https://example.com/rss", enabled=False)
        session.add(source)
        session.flush()
        article = NewsArticle(source_id=source.id, publisher=source.name, title="지역 정책 합성 기사",
                              summary="실제 보도가 아닌 합성 자료입니다.", url="https://example.com/article",
                              canonical_url="https://example.com/article")
        session.add(article)
        session.flush()
        article_id = article.id
    payload = {"overview": "제공된 정책 자료에서 검토할 주제를 정리합니다.",
               "comparisons": [{"article_ids": [article_id], "reason": "정책의 영향을 설명할 수 있는 주제입니다.",
                                "uncertainties": "원문과 적용 범위는 별도로 확인해야 합니다."}],
               "recommended_article_id": article_id, "selection_reason": "제공된 자료에 근거한 설명 후보입니다."}
    document = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(payload)}],
                "usage": {"input_tokens": 1098, "output_tokens": 721}}
    adapter = AnthropicProvider(store.key)
    budget = FakeAPIBudgetService(sessions)
    value = {"sessions": sessions, "store": store, "article_id": article_id, "payload": payload,
             "document": document, "adapter": adapter, "calls": [], "budget": budget}

    def send(request, timeout, limit):
        body = json.loads(request.data)
        assert request.full_url == "https://api.anthropic.com/v1/messages" and request.method == "POST"
        assert body["model"] == "claude-sonnet-4-6" and "tools" not in body
        assert json.loads(body["messages"][0]["content"])["evidence"]["articles"][0]["id"] == article_id
        value["calls"].append(body)
        return json.dumps(value["document"]).encode()

    monkeypatch.setattr(adapter, "_open", send)
    value["service"] = IntelligenceService(sessions, api_key_stores={"claude_api": store},
                                            api_providers={"claude_api": adapter}, api_budget=budget)
    return value


def analyze(state):
    return state["service"].analyze([state["article_id"]], "claude_api", True,
                                    Options(model="claude-sonnet-4-6"))


def latest(state):
    with state["sessions"]() as session:
        run = session.scalars(select(IntelligenceRun).order_by(IntelligenceRun.id.desc())).first()
        row = session.scalars(select(APIRequestReservation).order_by(APIRequestReservation.created_at.desc())).first()
        return run, row


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("presentation", ["plain", "fence", "split"])
def test_one_complete_json_object_is_accepted_with_unchanged_source_and_schema_checks(state, presentation, version, monkeypatch):
    monkeypatch.setenv("NEWSFLOW_SCRIPT_PROMPT_VERSION", version)
    text = json.dumps(state["payload"], ensure_ascii=False)
    if presentation == "fence":
        text = "```json\n" + text + "\n```"
    blocks = [{"type": "text", "text": text}]
    if presentation == "split":
        blocks = [{"type": "text", "text": text[:20]}, {"type": "text", "text": text[20:]}]
    state["document"]["content"] = blocks
    identifier = analyze(state)
    run, row = latest(state)
    assert run.id == identifier and run.status == row.status == "success"
    assert run.result == state["payload"] and len(state["calls"]) == 1
    assert row.usage == {"prompt_tokens": 1098, "completion_tokens": 721, "search_calls": 0}
    assert Decimal(row.reserved_usd) == Decimal('0.267000' if version == 'v1' else '0.273000')
    assert not state["adapter"].last_retried
    body = state["calls"][0]
    schema = body["output_config"]["format"]["schema"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert schema["additionalProperties"] is False and schema["$defs"]["Comparison"]["additionalProperties"] is False
    assert schema["properties"]["overview"]["type"] == "string"
    assert "maxLength" not in schema["properties"]["overview"]
    assert "600" in schema["properties"]["overview"]["description"]
    assert "maxItems" not in schema["properties"]["comparisons"]
    assert "minimum" not in schema["properties"]["recommended_article_id"]["anyOf"][0]
    assert Analysis.model_json_schema()["properties"]["overview"]["maxLength"] == 600
    assert "no Markdown" in body["system"] and body["max_tokens"] == (2200 if version == "v2" else 1800)
    assert ("recommended_angle" in schema["properties"]) == (version == "v2")


@pytest.mark.parametrize("kind,reason", [
    ("truncated", "result_json"), ("prose", "result_json"), ("two_objects", "result_json"),
    ("fence_trailing_prose", "result_json"), ("array", "result_json"),
    ("non_text_block", "response_text"), ("missing_text", "response_text"),
    ("wrong_type", "analysis_schema"), ("too_long", "analysis_schema"), ("extra_field", "analysis_schema"),
    ("wrong_source", "source_binding"), ("wrong_recommendation", "source_binding"),
])
def test_failures_keep_precise_safe_stage_and_never_retry_or_generate(state, kind, reason):
    payload = deepcopy(state["payload"])
    text = json.dumps(payload)
    if kind == "truncated":
        text = '{"overview":"' + RAW
    elif kind == "prose":
        text = RAW + "\n" + text
    elif kind == "two_objects":
        text += "\n{}"
    elif kind == "fence_trailing_prose":
        text = "```json\n" + text + "\n```\n" + RAW
    elif kind == "array":
        text = "[]"
    elif kind == "wrong_type":
        payload["comparisons"][0]["uncertainties"] = [RAW]
        text = json.dumps(payload)
    elif kind == "too_long":
        payload["overview"] = "가" * 601
        text = json.dumps(payload)
    elif kind == "extra_field":
        payload["untrusted_extra"] = RAW
        text = json.dumps(payload)
    elif kind == "wrong_source":
        payload["comparisons"][0]["article_ids"] = [99999]
        text = json.dumps(payload)
    elif kind == "wrong_recommendation":
        payload["recommended_article_id"] = 99999
        text = json.dumps(payload)
    state["document"]["content"][0]["text"] = text
    if kind == "non_text_block":
        state["document"]["content"] = [{"type": "tool_use", "input": {"secret": RAW}}]
    elif kind == "missing_text":
        state["document"]["content"] = [{"type": "text", "private": RAW}]
    with pytest.raises(IntelligenceError) as caught:
        analyze(state)
    assert caught.value.code == "ai_bad_response" and not caught.value.retryable
    run, row = latest(state)
    diagnostic = {"failure_reason": reason}
    if reason in {"result_json", "response_text"}:
        diagnostic["stop_reason"] = "end_turn"
    assert run.result == {"analysis_failure": diagnostic}
    assert run.status == row.status == "failed" and row.usage["completion_tokens"] == 721
    assert row.estimated_usd is not None and RAW not in json.dumps(run.result) + run.message
    assert len(state["calls"]) == 1 and not state["adapter"].last_retried
    with pytest.raises(APISettingsError, match="이미 기록된 요청"):
        reserve(state["budget"], state["store"], f"intelligence:{run.id}")
    assert len(state["calls"]) == 1


@pytest.mark.parametrize("stop_reason,expected", [("max_tokens", "max_tokens"), ("refusal", "refusal"),
                                                (None, None), ({"private": RAW}, "other")])
def test_incomplete_or_refused_response_is_not_continued(state, stop_reason, expected):
    state["document"]["stop_reason"] = stop_reason
    with pytest.raises(IntelligenceError):
        analyze(state)
    run, row = latest(state)
    failure = {"failure_reason": "incomplete_response"}
    if expected is not None:
        failure["stop_reason"] = expected
    assert run.result == {"analysis_failure": failure, **({"output_limit": {"stop_reason": "max_tokens"}}
                                                        if stop_reason == "max_tokens" else {})}
    assert row.status == "failed" and len(state["calls"]) == 1
    assert RAW not in json.dumps(run.result) + run.message


def test_missing_usage_still_records_parser_stage_and_keeps_unknown_cost_block(state):
    state["document"]["usage"] = {}
    state["document"]["content"][0]["text"] = RAW
    with pytest.raises(IntelligenceError):
        analyze(state)
    run, row = latest(state)
    assert row.status == "unknown" and row.estimated_usd is None
    assert run.result == {"analysis_failure": {"failure_reason": "result_json", "stop_reason": "end_turn"}}
    with pytest.raises(APISettingsError, match="결과 불명"):
        reserve(state["budget"], state["store"], "another:analysis")
    assert len(state["calls"]) == 1


def test_previous_unknown_legacy_amount_acknowledgement_and_failed_run_are_immutable(state):
    sessions, store, budget = state["sessions"], state["store"], state["budget"]
    old = reserve(budget, store, "old:analysis")
    budget.finish(old.id, status="unknown")
    with sessions.begin() as session:
        session.get(APIRequestReservation, old.id).reserved_usd = "9.165"
        failure = IntelligenceRun(kind="analysis", status="failed", provider="claude_api", options={},
                                  evidence={}, result={}, message="기존 합성 실패 기록")
        session.add(failure)
        session.flush()
        old_run_id = failure.id
    review = budget.readiness("claude_api", store, "analysis")["unknown_analysis_reviews"][0]
    acknowledge_unknown_analysis(sessions, "claude_api", reservation_id=old.id,
                                 fingerprint=review["fingerprint"], consent=True)
    with sessions() as session:
        before_row = {c.name: getattr(session.get(APIRequestReservation, old.id), c.name)
                      for c in APIRequestReservation.__table__.columns}
        before_ack = [(a.id, a.message) for a in session.scalars(select(AuditLog))]
        before_settings = [(v.key, v.value) for v in session.scalars(select(AppSetting).order_by(AppSetting.key))]
    encrypted = store.path.read_bytes()
    state["document"]["content"][0]["text"] = RAW
    with pytest.raises(IntelligenceError):
        analyze(state)
    with sessions() as session:
        after_row = {c.name: getattr(session.get(APIRequestReservation, old.id), c.name)
                     for c in APIRequestReservation.__table__.columns}
        assert after_row == before_row
        assert [(a.id, a.message) for a in session.scalars(select(AuditLog))] == before_ack
        assert session.get(IntelligenceRun, old_run_id).message == "기존 합성 실패 기록"
        assert [(v.key, v.value) for v in session.scalars(select(AppSetting).order_by(AppSetting.key))] == before_settings
    assert store.path.read_bytes() == encrypted and len(state["calls"]) == 1


def test_diagnostic_attributes_are_revalidated_without_exception_text():
    failure = AnalysisResponseError("result_json", stop_reason="end_turn")
    failure.failure_reason = {"private": RAW}
    failure.stop_reason = RAW
    failure.args = (RAW,)
    assert failure.diagnostics() == {"failure_reason": "response_envelope", "stop_reason": "other"}
    assert RAW not in str(failure.safe_copy())
