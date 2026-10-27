"""Complete array coverage and safe failure diagnostics, without external requests."""
import json
from copy import deepcopy

import pytest
from curation_wire_fixture import wire_output
from test_curation_validation_diagnostics import SNAPSHOT, output_for
from test_google_news_trends import NOW, article, no_external_calls

from newsflow.intelligence.api_providers import (
    MAX_CURATION_REQUEST_BYTES,
    AnthropicProvider,
    _claude_json_object,
)
from newsflow.intelligence.curation import CurationValidationError, enrich, validate_ranking
from newsflow.intelligence.curation_wire import decode
from newsflow.intelligence.provider import Options, ProviderResponseError

__all__ = ["no_external_calls"]


def example(count=81):
    articles = [{**article(), "id": i, "title": f"합성 주제 {i}"} for i in range(101, 101 + count)]
    evidence = enrich({"articles": articles, "groups": [[a["id"]] for a in articles]}, SNAPSHOT, NOW, top_k=3)
    output = output_for(evidence)
    return evidence, wire_output(output)


def test_fixed_schema_preserves_full_inputs_without_expanding_article_ids():
    evidence, _ = example()
    bodies = []
    adapter = AnthropicProvider(lambda: pytest.fail("No key read"))
    adapter._post = lambda body, _: bodies.append(body) or {}
    adapter._message("instruction", {"evidence": evidence}, Options(), analysis=True)
    body = bodies[0]
    schema = body["output_config"]["format"]["schema"]
    mapping = schema["properties"]["article_groups"]
    assert mapping["type"] == "array"
    assert set(mapping["items"]["required"]) == {"article_id", "group_id"}
    assert mapping["items"]["additionalProperties"] is False
    assert "article_groups" in schema["required"]
    assert schema["$defs"]["G"]["type"] == "integer"
    assert "enum" not in schema["$defs"]["G"]
    assert "number of supplied articles" in schema["$defs"]["G"]["description"]
    assert all("article_ids" not in d.get("properties", {}) for d in schema["$defs"].values())
    payload = json.loads(body["messages"][0]["content"])["evidence"]
    assert [a["title"] for a in payload["articles"]] == [a["title"] for a in evidence["articles"]]
    assert "tools" not in body


def test_grammar_is_identical_for_one_eighty_one_and_four_hundred_articles():
    schemas = []
    for count in (1, 81, 400):
        evidence, _ = example(count)
        evidence["script_prompt_version"] = "v1"
        bodies = []
        adapter = AnthropicProvider(lambda: pytest.fail("No key read"))
        adapter._post = lambda body, _, bodies=bodies: bodies.append(body) or {}
        adapter._message("instruction", {"evidence": evidence}, Options(), analysis=True)
        schemas.append(bodies[0]["output_config"]["format"]["schema"])
        transmitted = json.loads(bodies[0]["messages"][0]["content"])["evidence"]["articles"]
        assert [a["id"] for a in transmitted] == [a["id"] for a in evidence["articles"]]
    assert schemas[0] == schemas[1] == schemas[2]

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                properties = set(node["properties"])
                required = set(node["required"])
                optional = {"ad_risk", "viewer_relevance", "viewer_angle"}
                if "viewer_angle" in properties:
                    assert properties == {"group_id", "reason", "uncertainties"} | optional
                    assert required == {"group_id", "reason", "uncertainties"}
                else:
                    assert required == properties
                assert len(node["properties"]) <= 6
                assert node["additionalProperties"] is False
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)
    check(schemas[0])


def test_all_eighty_one_inputs_reach_existing_validation_and_top_three_without_repair():
    evidence, wire = example()
    before = deepcopy(wire)
    result = validate_ranking(decode(wire, evidence), evidence)
    assert wire == before
    assert sorted(i for g in result["comparisons"] for i in g["article_ids"]) == list(range(101, 182))
    assert len(result["ranking"]) == 3
    assert result["selection_reason"] == result["ranking"][0]["reason"]


def test_multiple_articles_one_issue_roundtrip_preserves_model_membership_and_source_binding():
    evidence, wire = example(3)
    wire["article_groups"][1]["group_id"] = wire["article_groups"][0]["group_id"]
    unused_label = 2
    wire["comparisons"] = [g for g in wire["comparisons"] if g["group_id"] != unused_label]
    # The two retained topics are already in descending score order.
    wire["ranking"] = [r for r in wire["ranking"] if r["group_id"] != unused_label]
    result = validate_ranking(decode(wire, evidence), evidence)
    assert sorted(sorted(g["article_ids"]) for g in result["comparisons"]) == [[101, 102], [103]]
    assert len(result["ranking"]) == 2
    assert any(len(r["sources"]) == 2 for r in result["ranking"])


@pytest.mark.parametrize("failure,expected", [
    ("missing", {"missing": 1}), ("unexpected", {"unexpected": 1}),
    ("duplicate", {"duplicate": 1}),
    ("bool_label", {"invalid_assignment": 1}), ("invalid_label", {"invalid_assignment": 1}),
    ("missing_group", {"missing_groups": 1}), ("duplicate_group", {"duplicate_groups": 1}),
    ("unexpected_group", {"unexpected_groups": 1}),
])
def test_incomplete_or_inconsistent_assignments_fail_without_filling_or_disclosing(failure, expected):
    evidence, wire = example()
    if failure == "missing":
        wire["article_groups"].pop(0)
    elif failure == "unexpected":
        wire["article_groups"].append({"article_id": 999999, "group_id": 1})
    elif failure == "duplicate":
        wire["article_groups"].append(deepcopy(wire["article_groups"][0]))
    elif failure == "bool_label":
        wire["article_groups"][0]["group_id"] = True
    elif failure == "invalid_label":
        wire["article_groups"][0]["group_id"] = 999999
    elif failure == "missing_group":
        wire["comparisons"].pop()
    elif failure == "duplicate_group":
        wire["comparisons"].append(deepcopy(wire["comparisons"][0]))
    elif failure == "unexpected_group":
        wire["comparisons"][0]["group_id"] = 999999
    before = deepcopy(wire)
    with pytest.raises(CurationValidationError) as caught:
        decode(wire, evidence)
    assert caught.value.diagnostics() == {"failure_reason": "curation_coverage", "coverage_check": expected}
    assert wire == before
    assert "PRIVATE" not in json.dumps(caught.value.diagnostics())


@pytest.mark.parametrize("item", [
    {"article_id": True, "group_id": 1},
    {"article_id": "101", "group_id": 1},
    {"article_id": 101.0, "group_id": 1},
    {"article_id": 101, "group_id": "1"},
    {"article_id": 101, "group_id": 0},
    {"article_id": 101, "group_id": 1, "PRIVATE": "PRIVATE"},
    {"article_id": 101},
    None,
])
def test_assignment_types_and_extra_fields_are_not_repaired(item):
    evidence, wire = example(3)
    wire["article_groups"][0] = item
    before = deepcopy(wire)
    with pytest.raises(CurationValidationError) as caught:
        decode(wire, evidence)
    assert wire == before and "PRIVATE" not in json.dumps(caught.value.diagnostics())


def test_assignment_order_never_changes_source_membership():
    evidence, wire = example(3)
    wire["article_groups"].reverse()
    result = validate_ranking(decode(wire, evidence), evidence)
    assert [r["article_ids"] for r in result["comparisons"]] == [[101], [102], [103]]


@pytest.mark.parametrize("text", [
    '{"article_groups":{"101":1,"101":2}}',
    '{"article_groups":{},"article_groups":{"101":1}}',
])
def test_duplicate_json_keys_cannot_be_silently_overwritten(text):
    with pytest.raises(ProviderResponseError):
        _claude_json_object(text)


def test_legacy_diagnostics_distinguish_missing_unexpected_and_repeated_without_values():
    evidence, wire = example(3)
    output = decode(wire, evidence)
    output["comparisons"][0]["article_ids"] = [102, 102, 999999]
    with pytest.raises(CurationValidationError) as caught:
        validate_ranking(output, evidence)
    assert caught.value.diagnostics() == {
        "failure_reason": "curation_coverage", "coverage_check": {"missing": 1, "unexpected": 1, "duplicate": 2}}
    caught.value.coverage_check = {"missing": True, "unexpected": "SECRET", "SECRET": 2}
    assert caught.value.diagnostics() == {"failure_reason": "curation_coverage"}


def test_curation_schema_overhead_has_a_bounded_limit_and_never_splits_requests(monkeypatch):
    evidence, wire = example(3)
    adapter = AnthropicProvider(lambda: "fixture-key")
    calls = []
    raw = json.dumps({"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(wire)}]}).encode()
    monkeypatch.setattr(adapter, "_open", lambda req, *_: calls.append(req) or raw)
    options = Options("claude-sonnet-4-6", timeout=300)
    evidence["articles"][0]["summary"] = ""
    assert adapter.analyze(evidence, options)["comparisons"]
    overhead = len(calls[0].data)
    assert MAX_CURATION_REQUEST_BYTES == 80_000 and overhead + 64_000 == 81_131
    evidence["articles"][0]["summary"] = "x" * (80_000 - overhead)
    assert adapter.analyze(evidence, options)["comparisons"]
    assert len(calls) == 2 and len(calls[-1].data) == MAX_CURATION_REQUEST_BYTES
    # Each rejected input stays intact and never reaches the Fake transport.
    for text, expected_bytes in (("x" * 64_000, 81_131),
                                 ("x" * (80_001 - overhead), 80_001),
                                 ("x" * (80_000 - overhead) + "한", 80_003),
                                 ("x" * 80_000, overhead + 80_000)):
        evidence["articles"][0]["summary"] = text
        before = deepcopy(evidence)
        assert overhead + len(text.encode("utf-8")) == expected_bytes > 80_000
        with pytest.raises(ProviderResponseError):
            adapter.analyze(evidence, options)
        assert len(calls) == 2 and evidence == before
