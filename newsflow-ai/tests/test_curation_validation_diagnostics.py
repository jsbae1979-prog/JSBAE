"""81-article Claude wire fixtures; no live API, production DB, CLI, TTS or video."""
import json
from copy import deepcopy

import pytest
from curation_wire_fixture import wire_output
from sqlalchemy import select
from test_api_settings import reserve
from test_curation_all import extend_collection
from test_global_news_policy import GlobalAI
from test_google_news_trends import no_external_calls, prepared

from newsflow.db.models import APIRequestReservation, ContentDraft, IntelligenceRun, utcnow
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.api_settings import APISettingsError
from newsflow.intelligence.curation import CurationValidationError, enrich, validate_ranking
from newsflow.intelligence.provider import Options
from newsflow.intelligence.service import IntelligenceError

__all__ = ["no_external_calls", "prepared"]
RAW = "UNTRUSTED_KEY_AND_VALUE_NEVER_PERSIST"
SNAPSHOT = {"collection_policy": "global_trends_v1", "collection_context_id": 1}


def output_for(evidence):
    output = GlobalAI("claude_api").analyze(evidence, Options())
    # These RSS-only fixtures have no edition appearances. Unknown remains null.
    for item in output["ranking"]:
        item["components"]["exposure_frequency"] = None
        item["score"] = round(sum(v or 0 for v in item["components"].values()) * 100 / 120)
    return output


@pytest.mark.parametrize("prepared", ["claude_api"], indirect=True)
@pytest.mark.parametrize("kind,rule", [
    ("valid", None), ("schema_type", "curation_schema"), ("schema_count", "curation_schema"),
    ("coverage", "curation_coverage"), ("count", "curation_ranking_count"),
    ("group", "curation_group"), ("numbers", "curation_numbers"),
    ("score", "curation_score_order"), ("search", "curation_search"),
    ("exposure", "curation_exposure"),
])
def test_real_adapter_fake_json_keeps_rules_and_persists_only_safe_diagnostics(
        client, app, prepared, monkeypatch, kind, rule):
    svc, _fake, _mode, _options, _ids = prepared
    ctx = extend_collection(app, 81)
    ids = sorted(a.id for a in ctx["articles"])
    evidence = enrich(svc.evidence_for(ids), SNAPSHOT, utcnow(), top_k=3)
    output = output_for(evidence)
    if kind == "schema_type":
        output["ranking"][0]["components"]["impact"] = RAW
        output["ranking"][0][RAW] = RAW
    elif kind == "schema_count":
        output["ranking"].append(deepcopy(output["ranking"][-1]))
    elif kind == "coverage":
        output["comparisons"].pop()
    elif kind == "count":
        output["ranking"].pop()
    elif kind == "group":
        output["ranking"][0]["article_ids"] = [999999]
    elif kind == "numbers":
        output["ranking"][0]["summary"] = "미확인 수치 999999를 주장합니다."
    elif kind == "score":
        output["ranking"][0]["score"] -= 1
    elif kind == "search":
        output["ranking"][0]["components"]["search_growth"] = 10
    elif kind == "exposure":
        output["ranking"][0]["components"]["exposure_frequency"] = 10
    wire = wire_output(output)
    if kind == "score":
        # A model-supplied total remains rejected, not silently repaired.
        wire["ranking"][0]["score"] = output["ranking"][0]["score"]
    document = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(wire)}],
                "usage": {"input_tokens": 19000, "output_tokens": 6300}}
    calls = []
    adapter = AnthropicProvider(lambda: "fixture-only-not-a-key")

    def send(request, timeout, _limit):
        calls.append((json.loads(request.data), timeout))
        return json.dumps(document).encode()

    monkeypatch.setattr(adapter, "_open", send)
    svc.api_providers["claude_api"] = adapter
    options = Options("claude-sonnet-4-6", timeout=180, max_tokens=7000)
    if rule:
        with pytest.raises(IntelligenceError) as error:
            svc.analyze(ids, "claude_api", True, options, curate=True, trend_snapshot=SNAPSHOT, curation_top_k=3)
        assert error.value.code == "ai_bad_response" and error.value.retryable is False
        assert RAW not in str(error.value)
    else:
        svc.analyze(ids, "claude_api", True, options, curate=True, trend_snapshot=SNAPSHOT, curation_top_k=3)
    assert len(calls) == 1 and calls[0][1] == 180 and not adapter.last_retried
    body = calls[0][0]
    assert "min(evidence.curation_contract.top_k, number of groups)" in body["system"]
    assert "top min(10" not in body["system"] and "tools" not in body
    contract = json.loads(body["messages"][0]["content"])["evidence"]["curation_contract"]
    assert contract["top_k"] == 3 and "최대 3개" in contract["instructions"]
    assert contract["score_derivation"]["version"] == "claude_components_v1"
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis"))
        reservation = session.scalar(select(APIRequestReservation))
        assert reservation.status == run.status == ("failed" if rule else "success")
        assert reservation.usage["completion_tokens"] == 6300
        assert reservation.bounds["search_calls"] == 0 and reservation.test_only
        assert session.scalar(select(ContentDraft)) is None
        if rule:
            diagnostic = run.result["analysis_failure"]
            assert diagnostic["failure_reason"] == rule
            assert RAW not in json.dumps(run.result) + run.message
            if kind == "schema_type":
                assert {"loc": ["ranking", 0, "components", "impact"], "type": "int_type"} in diagnostic["schema_issues"]
                assert {"loc": ["ranking", 0, "other"], "type": "extra_forbidden"} in diagnostic["schema_issues"]
            with pytest.raises(APISettingsError, match="이미 기록된 요청"):
                reserve(svc.api_budget, svc.api_key_stores["claude_api"], f"intelligence:{run.id}")
        else:
            assert len(run.result["comparisons"]) == 81 and len(run.result["ranking"]) == 3
    assert len(calls) == 1


def test_diagnostics_revalidate_mutated_attributes_and_remain_value_error_compatible():
    error = CurationValidationError("curation_schema", schema_issues=[
        {"loc": ["ranking", 0, RAW], "type": RAW, "input": RAW, "msg": RAW}] * 100)
    assert isinstance(error, ValueError)
    assert len(error.diagnostics()["schema_issues"]) == 8
    assert RAW not in json.dumps(error.diagnostics())
    error.failure_reason = {"private": RAW}
    error.schema_issues = [{"loc": [RAW], "type": RAW}]
    error.args = (RAW,)
    assert error.diagnostics() == {"failure_reason": "response_envelope"}
    assert RAW not in str(error.safe_copy())


def test_global_integer_scores_are_still_not_repaired_or_coerced():
    evidence = enrich({"articles": [{"id": 1, "title": "합성 제목", "summary": "합성 설명",
                       "published_at": None, "sources": []}], "groups": [[1]]}, SNAPSHOT, utcnow(), top_k=3)
    output = output_for(evidence)
    output["ranking"][0]["components"]["impact"] = "20"
    with pytest.raises(CurationValidationError) as error:
        validate_ranking(output, evidence)
    assert error.value.failure_reason == "curation_schema"
