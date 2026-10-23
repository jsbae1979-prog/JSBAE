"""Reproduce summary-number contract gaps without real API, CLI or production data."""
import json
from copy import deepcopy

import pytest
from curation_wire_fixture import wire_output
from sqlalchemy import select
from test_curation_all import extend_collection
from test_curation_validation_diagnostics import SNAPSHOT, output_for
from test_google_news_trends import NOW, article, no_external_calls, prepared

from newsflow.db.models import APIRequestReservation, ContentDraft, IntelligenceRun, utcnow
from newsflow.intelligence.api_providers import MAX_REQUEST_BYTES, AnthropicProvider
from newsflow.intelligence.curation import (
    REASON_GROUNDING,
    CurationValidationError,
    enrich,
    validate_ranking,
    wire_evidence,
)
from newsflow.intelligence.provider import Options
from newsflow.intelligence.service import IntelligenceError

__all__ = ["no_external_calls", "prepared"]


def fixture():
    articles = [{**article(), "id": i, "title": f"합성 주제 {name}", "summary": text}
                for i, name, text in [(1, "가", "매출 5.8億円을 발표했습니다."),
                                      (2, "나", "합성 재료 12345개를 조사했습니다."),
                                      (3, "다", "시설 45678곳을 조사했습니다.")]]
    evidence = enrich({"articles": articles, "groups": [[1], [2], [3]]}, SNAPSHOT, NOW, top_k=3)
    return evidence, output_for(evidence)


@pytest.mark.parametrize("field", ["reason", "summary"])
@pytest.mark.parametrize("text,origin", [
    ("시설 12345곳을 조사했습니다.", "other_article_only"),
    ("사건은 2026년에 발생했습니다.", "group_metadata_only"),
    ("새 시설 999999곳을 조사했습니다.", "unmatched"),
])
def test_other_article_metadata_or_unmatched_values_remain_blocked_with_no_raw_diagnostic(text, origin, field):
    evidence, output = fixture()
    # Highest-ranked fixture is article 3, not the article containing 12345.
    assert output["ranking"][0]["article_ids"] == [3]
    output["ranking"][0][field] = text
    original = deepcopy(output)
    with pytest.raises(CurationValidationError) as caught:
        validate_ranking(output, evidence)
    assert caught.value.diagnostics() == {
        "failure_reason": "curation_numbers", "number_field": field,
        "number_check": {"position": 1, "unmatched_count": 1, "origin_hint": origin}}
    assert output == original  # No local replacement, deletion or repair of the model's response.
    assert text not in json.dumps(caught.value.diagnostics(), ensure_ascii=False)


def test_qualitative_reason_and_same_group_quantity_remain_valid_without_local_rewrite():
    evidence, output = fixture()
    reason = "생활에 영향을 줄 수 있는 시설 조사라는 점에서 관심도 후보입니다. 원문 확인이 필요합니다."
    output["ranking"][0]["reason"] = reason
    result = validate_ranking(output, evidence)
    assert result["ranking"][0]["reason"] == reason
    output["ranking"][0]["reason"] = "자료에 나온 45678곳 시설 조사는 생활 관련성이 있어 후보로 평가합니다."
    assert validate_ranking(output, evidence)["ranking"][0]["reason"] == output["ranking"][0]["reason"]


def test_diagnostic_position_identifies_later_candidate_and_cannot_whitelist_facts():
    evidence, output = fixture()
    target = next(i for i, item in enumerate(output["ranking"]) if item["article_ids"] == [1])
    output["ranking"][target]["summary"] = "발표 규모는 580000000엔입니다."
    with pytest.raises(CurationValidationError) as caught:
        validate_ranking(output, evidence)
    assert caught.value.diagnostics()["number_check"] == {
        "position": target + 1, "unmatched_count": 1, "origin_hint": "unmatched"}
    output["ranking"][target]["summary"] = "매출 5.8億円을 발표한 자료입니다."
    assert len(validate_ranking(output, evidence)["ranking"]) == 3


@pytest.mark.parametrize("payload", [
    {"position": True, "unmatched_count": 1, "origin_hint": "unmatched"},
    {"position": 1, "unmatched_count": 9999999, "origin_hint": "unmatched"},
    {"position": 1, "unmatched_count": 1, "origin_hint": "PRIVATE_VALUE"},
])
def test_mutated_diagnostics_are_filtered_again(payload):
    error = CurationValidationError("curation_numbers", number_field="summary")
    error.number_check = payload
    assert error.diagnostics() == {"failure_reason": "curation_numbers", "number_field": "summary"}


def test_numeric_contract_reaches_real_claude_wire_and_schema_without_inventing_numbers():
    evidence, _ = fixture()
    before = deepcopy(evidence)
    body = []
    provider = AnthropicProvider(lambda: "fixture-not-a-key")
    provider._post = lambda request, _options: body.append(request) or {}
    provider._message("fixture instruction", {"evidence": evidence}, Options("claude-sonnet-4-6"), analysis=True)
    payload = json.loads(body[0]["messages"][0]["content"])["evidence"]
    policy = payload["curation_contract"]["numeric_grounding"]
    assert "original quantity" in policy["summary"] and "Do not translate numeric units" in policy["summary"]
    assert "not evidence" in policy["metadata"] and "never the factual summary" in policy["reason"]
    assert policy["reason"] == REASON_GROUNDING
    assert "same group_id" in policy["reason"] and "not from other candidates" in policy["reason"]
    descriptions = [definition.get("properties", {}).get("summary", {}).get("description", "")
                    for definition in body[0]["output_config"]["format"]["schema"]["$defs"].values()]
    assert any("original units/scales" in text for text in descriptions)
    ranked_definitions = [definition for definition in
                          body[0]["output_config"]["format"]["schema"]["$defs"].values()
                          if "components" in definition.get("properties", {})]
    assert ranked_definitions
    assert all(REASON_GROUNDING in definition["properties"]["reason"]["description"]
               for definition in ranked_definitions)
    assert payload["articles"] == wire_evidence(evidence)["articles"]
    assert evidence == before and "tools" not in body[0]
    assert len(json.dumps(body[0], ensure_ascii=False).encode()) <= MAX_REQUEST_BYTES


@pytest.mark.parametrize("prepared", ["claude_api"], indirect=True)
@pytest.mark.parametrize("invalid", [False, True])
@pytest.mark.parametrize("field", ["reason", "summary"])
def test_eighty_one_article_fake_response_preserves_usage_and_single_call_contract(
        client, app, prepared, monkeypatch, invalid, field):
    svc, _fake, _mode, _options, _ids = prepared
    ctx = extend_collection(app, 81)
    ids = sorted(a.id for a in ctx["articles"])
    evidence = enrich(svc.evidence_for(ids), SNAPSHOT, utcnow(), top_k=3)
    output = output_for(evidence)
    if invalid:
        output["ranking"][1][field] = "보도되지 않은 수량 999999개입니다."
    calls = []
    adapter = AnthropicProvider(lambda: "fixture-not-a-key")
    def send(request, timeout, _limit):
        calls.append((json.loads(request.data), timeout))
        return json.dumps({"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(wire_output(output))}],
                           "usage": {"input_tokens": 19500, "output_tokens": 6500}}).encode()
    monkeypatch.setattr(adapter, "_open", send)
    svc.api_providers["claude_api"] = adapter
    if invalid:
        with pytest.raises(IntelligenceError) as caught:
            svc.analyze(ids, "claude_api", True, Options("claude-sonnet-4-6", timeout=300, max_tokens=100_000),
                        curate=True, trend_snapshot=SNAPSHOT, curation_top_k=3)
        assert caught.value.code == "ai_bad_response" and not caught.value.retryable
    else:
        svc.analyze(ids, "claude_api", True, Options("claude-sonnet-4-6", timeout=300, max_tokens=100_000),
                    curate=True, trend_snapshot=SNAPSHOT, curation_top_k=3)
    assert len(calls) == 1 and calls[0][1] == 300 and "tools" not in calls[0][0]
    assert calls[0][0]["max_tokens"] == 100_000
    assert not adapter.last_retried
    with app.state.sessions() as s:
        run = s.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis"))
        record = s.scalar(select(APIRequestReservation))
        assert run.status == record.status == ("failed" if invalid else "success")
        assert record.usage["completion_tokens"] == 6500 and record.bounds["search_calls"] == 0
        assert s.scalar(select(ContentDraft)) is None
        if invalid:
            assert run.result["analysis_failure"]["number_field"] == field
            assert run.result["analysis_failure"]["number_check"]["position"] == 2
            assert "999999" not in json.dumps(run.result)
        else:
            assert len(run.result["comparisons"]) == 81 and len(run.result["ranking"]) == 3
