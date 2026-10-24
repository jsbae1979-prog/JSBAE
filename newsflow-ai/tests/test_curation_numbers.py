"""Numeric notation and evaluation metadata must not become a factual-number bypass."""
import json

import pytest
from curation_wire_fixture import wire_output
from sqlalchemy import select
from test_curation_all import extend_collection
from test_curation_validation_diagnostics import SNAPSHOT, output_for
from test_google_news_trends import NOW, CuratorResponse, article, no_external_calls, prepared

from newsflow.db.models import APIRequestReservation, ContentDraft, IntelligenceRun, utcnow
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.curation import CurationValidationError, enrich, validate_ranking
from newsflow.intelligence.provider import Options
from newsflow.intelligence.service import IntelligenceError

__all__ = ["no_external_calls", "prepared"]


def example(source="구체적 수치가 없는 합성 자료입니다."):
    evidence = enrich({"articles": [{**article(), "title": "합성 뉴스", "summary": source}],
                       "groups": [[1]]}, None, NOW, top_k=3)
    result = CuratorResponse("claude_api").analyze(evidence, Options())
    return evidence, result


@pytest.mark.parametrize("source,text", [
    ("1,000명", "1000명"), ("1000명", "1,000명"),
    ("비율 5.80%", "비율 5.8%"), ("비율 5.8%", "비율 5.800%"),
    ("금액 １２，３４５.００원", "금액 12345원"),
    ("2026-01-02 발표", "2026년 1월 2일 발표"),
    ("전년 대비 -5%", "전년 대비 −5.0%"),
    ("COVID-19 관련", "코로나19 관련"), ("신형 GPT5", "신형 GPT5"),
])
def test_unambiguous_equal_notation_is_accepted_without_rewriting_text(source, text):
    evidence, output = example(source)
    output["ranking"][0]["summary"] = text
    result = validate_ranking(output, evidence)
    assert result["ranking"][0]["summary"] == text
    assert evidence["articles"][0]["summary"] == source


@pytest.mark.parametrize("source,text", [
    ("1,000명", "1001명"), ("금액 1,000원", "금액 1.000원"),
    ("비율 5,8%", "비율 5.8%"), ("비율 5.8%", "비율 58%"),
    ("관측 1,2", "관측 12"), ("기준 1억 원", "기준 100000000원"),
    ("전년 대비 -5%", "전년 대비 5%"), ("전년 대비 5%", "전년 대비 -5%"),
    ("합성 GPT5 소개", "합성 GPT6 소개"),
    ("분수 ½만 확인", "수량 2개"), ("면적 단위 m²만 확인", "수량 2개"),
])
def test_changed_values_ambiguous_locale_and_unit_conversion_still_fail(source, text):
    evidence, output = example(source)
    output["ranking"][0]["summary"] = text
    with pytest.raises(CurationValidationError) as error:
        validate_ranking(output, evidence)
    diagnostic = error.value.diagnostics()
    assert diagnostic["failure_reason"] == "curation_numbers" and diagnostic["number_field"] == "summary"
    assert diagnostic["number_check"]["position"] == 1
    assert diagnostic["number_check"]["unmatched_count"] >= 1


@pytest.mark.parametrize("template", [
    "AI 평가 점수 {score}점 · 이번 평가 {rank}위. 자료 범위의 편집 추정입니다.",
    "화제성 총점 {score}/100점 · 추천 순위 {rank}위. 실제 조회수 예측은 아닙니다.",
    "이번 화제성 평가 점수 {score}.0/100.0점 · AI 평가 {rank}위입니다.",
])
def test_explicit_matching_evaluation_metadata_is_reason_only(template):
    evidence, output = example()
    item = output["ranking"][0]
    reason = template.format(score=item["score"], rank=item["rank"])
    item["reason"] = reason
    result = validate_ranking(output, evidence)
    assert result["ranking"][0]["reason"] == reason
    item["summary"] = reason
    with pytest.raises(CurationValidationError) as error:
        validate_ranking(output, evidence)
    assert error.value.number_field == "summary"


@pytest.mark.parametrize("template", [
    "AI 평가 점수 {wrong}점", "이번 평가 {wrong}위", "AI 평가 점수 {score}/200점",
    "이 사건으로 {score}명이 피해를 입었습니다.", "세계 {rank}위 기업입니다.",
    "AI 평가 점수 {score}점. 사고 피해자는 {score}명입니다.",
    "이번 평가 {rank}위. 회사가 시장 {rank}위로 올라섰습니다.",
])
def test_metadata_never_globally_whitelists_matching_factual_values(template):
    evidence, output = example()
    item = output["ranking"][0]
    item["reason"] = template.format(score=item["score"], rank=item["rank"], wrong=item["score"] + 1)
    with pytest.raises(CurationValidationError) as error:
        validate_ranking(output, evidence)
    diagnostic = error.value.diagnostics()
    assert diagnostic["failure_reason"] == "curation_numbers" and diagnostic["number_field"] == "reason"
    assert diagnostic["number_check"]["position"] == 1
    assert diagnostic["number_check"]["unmatched_count"] >= 1


def test_valid_label_does_not_repair_a_wrong_json_score():
    evidence, output = example()
    item = output["ranking"][0]
    item["score"] += 1
    item["reason"] = f"AI 평가 점수 {item['score']}점 · 이번 평가 1위"
    with pytest.raises(CurationValidationError) as error:
        validate_ranking(output, evidence)
    assert error.value.failure_reason == "curation_score_order"


@pytest.mark.parametrize("prepared", ["claude_api"], indirect=True)
@pytest.mark.parametrize("factual_collision", [False, True])
def test_eighty_one_article_fake_wire_preserves_billing_and_blocks_factual_collision(
        client, app, prepared, monkeypatch, factual_collision):
    svc, _fake, _mode, _options, _ids = prepared
    ctx = extend_collection(app, 81)
    ids = sorted(a.id for a in ctx["articles"])
    evidence = enrich(svc.evidence_for(ids), SNAPSHOT, utcnow(), top_k=3)
    output = output_for(evidence)
    for item in output["ranking"]:
        item["reason"] = f"AI 평가 점수 {item['score']}점 · 이번 평가 {item['rank']}위. 자료 범위의 AI 추정입니다."
    if factual_collision:
        first = output["ranking"][0]
        first["reason"] += f" 이 사건의 피해자는 {first['score']}명입니다."
    document = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(wire_output(output))}],
                "usage": {"input_tokens": 19000, "output_tokens": 6000}}
    calls = []
    adapter = AnthropicProvider(lambda: "fixture-only-not-a-key")

    def send(request, timeout, _limit):
        calls.append((request, timeout))
        return json.dumps(document).encode()

    monkeypatch.setattr(adapter, "_open", send)
    svc.api_providers["claude_api"] = adapter
    options = Options("claude-sonnet-4-6", timeout=180, max_tokens=7000)
    if factual_collision:
        with pytest.raises(IntelligenceError) as caught:
            svc.analyze(ids, "claude_api", True, options, curate=True, trend_snapshot=SNAPSHOT, curation_top_k=3)
        assert caught.value.code == "ai_bad_response" and not caught.value.retryable
    else:
        svc.analyze(ids, "claude_api", True, options, curate=True, trend_snapshot=SNAPSHOT, curation_top_k=3)
    assert len(calls) == 1 and calls[0][1] == 180 and not adapter.last_retried
    assert "tools" not in json.loads(calls[0][0].data)
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis"))
        reservation = session.scalar(select(APIRequestReservation))
        assert run.status == reservation.status == ("failed" if factual_collision else "success")
        assert reservation.usage["completion_tokens"] == 6000 and reservation.test_only
        assert reservation.bounds["search_calls"] == 0
        assert session.scalar(select(ContentDraft)) is None
        if factual_collision:
            assert run.result == {"analysis_failure": {
                "failure_reason": "curation_numbers", "number_field": "reason",
                "number_check": {"position": 1, "unmatched_count": 1, "origin_hint": "evaluation_metadata_only"}}}
        else:
            assert len(run.result["comparisons"]) == 81 and len(run.result["ranking"]) == 3


def test_numeric_diagnostic_attributes_are_whitelisted_again_on_save():
    error = CurationValidationError("curation_numbers", number_field="reason")
    error.number_field = {"private": "DO_NOT_PERSIST"}
    assert error.diagnostics() == {"failure_reason": "curation_numbers"}
