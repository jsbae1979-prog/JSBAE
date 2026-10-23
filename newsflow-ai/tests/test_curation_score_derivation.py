"""Arithmetic is deterministic; AI choices, evidence and failure guards stay intact."""
from copy import deepcopy

import pytest
from test_curation_wire_coverage import example
from test_google_news_trends import no_external_calls

from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.curation import CurationValidationError, component_total, validate_ranking
from newsflow.intelligence.curation_wire import decode
from newsflow.intelligence.provider import Options

__all__ = ["no_external_calls"]


def test_claude_schema_requests_components_not_redundant_totals_or_positions():
    evidence, _ = example()
    bodies = []
    adapter = AnthropicProvider(lambda: pytest.fail("No key access"))
    adapter._post = lambda body, _: bodies.append(body) or {}
    adapter._message("instruction", {"evidence": evidence}, Options(), analysis=True)
    schema = bodies[0]["output_config"]["format"]["schema"]
    ranked = next(d for d in schema["$defs"].values() if "components" in d.get("properties", {}))
    assert set(ranked["properties"]) == set(ranked["required"]) == {
        "group_id", "components", "reason", "summary"}
    assert "Do NOT return rank or score" in bodies[0]["system"]


@pytest.mark.parametrize("values,expected", [
    ([20, 20, 20, 20, 20, 20], 100),
    ([20, 7, None, None, None, None], 22),  # 22.5, ties to even.
    ([20, 13, None, None, None, None], 28),  # 27.5, ties to even.
    ([None] * 6, 0),
])
def test_existing_six_component_rounding_is_shared_not_reinterpreted(values, expected):
    assert component_total(dict(enumerate(values)), global_policy=True) == expected
    assert component_total(dict(enumerate(values[:5])), global_policy=False) == sum(v or 0 for v in values[:5])


def test_unsorted_candidates_are_ordered_without_changing_choices_points_or_prose():
    evidence, wire = example(4)
    # Only three AI-selected candidates are present. Do not rank/select the fourth locally.
    candidate_ids = {r["group_id"] for r in wire["ranking"]}
    for item, points in zip(wire["ranking"], (5, 19, 12), strict=True):
        item["components"].update(public_interest=points, impact=points, interest=points, shareability=points)
    before = deepcopy(wire)
    result = validate_ranking(decode(wire, evidence), evidence)
    assert wire == before
    assert len(result["ranking"]) == 3 and len(result["comparisons"]) == 4
    assert [r["rank"] for r in result["ranking"]] == [1, 2, 3]
    assert [r["score"] for r in result["ranking"]] == sorted(
        (r["score"] for r in result["ranking"]), reverse=True)
    labels = {item["article_id"]: item["group_id"] for item in wire["article_groups"]}
    assert {labels[r["article_ids"][0]] for r in result["ranking"]} == candidate_ids
    originals = {r["group_id"]: r for r in before["ranking"]}
    for row in result["ranking"]:
        original = originals[labels[row["article_ids"][0]]]
        assert all(row[k] == original[k] for k in ("components", "reason", "summary"))
        assert row["components"]["exposure_frequency"] is None


def test_equal_totals_keep_ai_candidate_order():
    evidence, wire = example(3)
    for row in wire["ranking"]:
        row["components"] = deepcopy(wire["ranking"][0]["components"])
    wire["ranking"].reverse()
    before = [r["group_id"] for r in wire["ranking"]]
    result = validate_ranking(decode(wire, evidence), evidence)
    labels = {r["article_id"]: r["group_id"] for r in wire["article_groups"]}
    assert [labels[r["article_ids"][0]] for r in result["ranking"]] == before


@pytest.mark.parametrize("value", [True, "20", 20.0, -1, 21])
def test_invalid_points_are_rejected_before_calculation(value):
    evidence, wire = example(3)
    wire["ranking"][0]["components"]["impact"] = value
    with pytest.raises(CurationValidationError) as caught:
        decode(wire, evidence)
    assert caught.value.failure_reason == "curation_schema"


@pytest.mark.parametrize("field", ["rank", "score"])
def test_unrequested_derived_fields_are_rejected_not_repaired(field):
    evidence, wire = example(3)
    wire["ranking"][0][field] = 999
    with pytest.raises(CurationValidationError) as caught:
        decode(wire, evidence)
    assert caught.value.failure_reason == "curation_score_order"


def test_missing_or_duplicate_candidates_still_fail():
    evidence, wire = example(3)
    missing = deepcopy(wire)
    missing["ranking"].pop()
    with pytest.raises(CurationValidationError) as caught:
        validate_ranking(decode(missing, evidence), evidence)
    assert caught.value.failure_reason == "curation_ranking_count"
    wire["ranking"][1] = deepcopy(wire["ranking"][0])
    with pytest.raises(CurationValidationError) as caught:
        validate_ranking(decode(wire, evidence), evidence)
    assert caught.value.failure_reason == "curation_group"
