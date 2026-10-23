"""Claude-only wire representation; the persisted curation contract stays unchanged."""
from copy import deepcopy

from pydantic import ValidationError

from .curation import GLOBAL_PROFILE, CurationValidationError, component_total, ranking_model

SCORE_DERIVATION = {
    "version": "claude_components_v1",
    "selection": "AI selects candidates; application does not add or replace them.",
    "total": "Existing policy: sum for five components; round(sum*100/120) for six components.",
    "rounding": "Nearest integer, ties to even; unassessed components remain null.",
    "order": "Descending derived score among selected candidates; ties retain AI response order.",
}

INSTRUCTION = (
    " Curation wire format: article_groups is an array of {article_id: integer, group_id: integer}. "
    "Include EVERY supplied article ID exactly once, in supplied order; never sample or omit articles. "
    "Group labels are integers from 1 through the number of supplied articles, not article IDs. "
    "Assign the same label only to articles about the same event. "
    "comparisons has exactly one entry per used label: group_id, reason, uncertainties. "
    "ranking uses group_id instead of article_ids and contains the top requested groups. "
    "This wire format replaces the comparisons/article_ids representation in the evidence instructions; "
    "the app reconstructs article_ids from your complete assignment array. "
    "Never return article_ids in this wire format. "
    "For ranking, return group_id, components, reason and summary only. Do NOT return rank or score, "
    "even if earlier instructions request them; those fields are derived by the application. "
    "You still choose the top requested topics after comparing ALL supplied groups. "
    "The app computes totals from your component points and sorts only your selected candidates; "
    "it never substitutes candidates or invents component points. Ties keep your response order. "
    "Do not repeat numeric scores or ranking positions in prose. "
    "All numeric grounding, scoring and source rules still apply."
)


def output_schema(schema: dict, evidence: dict) -> dict:
    """Keep grammar size independent of article count; validate exact membership locally."""
    result = deepcopy(schema)
    definitions = result["$defs"]
    # A fixed array item replaces N required object properties. Expanding all IDs
    # into the schema exceeded Claude's compiled grammar limit at 81 articles.
    # IDs remain in the input evidence, not enums/properties in the grammar.
    definitions["G"] = {"type": "integer", "description": (
        "Topic group label from 1 through the number of supplied articles inclusive, not an article ID. "
        "The application enforces the range and complete coverage after generation.")}
    for definition in definitions.values():
        properties = definition.get("properties", {})
        if "article_ids" in properties:
            properties.pop("article_ids")
            properties["group_id"] = {"$ref": "#/$defs/G"}
            definition["required"] = [
                "group_id" if name == "article_ids" else name for name in definition["required"]
            ]
        if "components" in properties:
            for name in ("rank", "score"):
                properties.pop(name, None)
                if name in definition["required"]:
                    definition["required"].remove(name)
    # These are derived from ranking after validation, not another model task.
    for name in ("recommended_article_id", "selection_reason"):
        result["properties"].pop(name, None)
        if name in result.get("required", []):
            result["required"].remove(name)
    assignment = {"type": "array", "items": {
        "type": "object", "properties": {
            "article_id": {"type": "integer"}, "group_id": {"$ref": "#/$defs/G"},
        }, "required": ["article_id", "group_id"], "additionalProperties": False,
    }, "description": "Exactly one assignment per supplied article ID; no omissions or duplicates."}
    result["properties"] = {"article_groups": assignment, **result["properties"]}
    result["required"] = ["article_groups", *result["required"]]
    return result


def decode(output: dict, evidence: dict) -> dict:
    """Bind sources and derive arithmetic for AI-selected candidates, never replace their content."""
    expected = {a["id"] for a in evidence["articles"]}
    assignment = output.get("article_groups")
    if not isinstance(assignment, list):
        raise CurationValidationError("curation_coverage", coverage_check={"missing": len(expected)})
    groups, assigned = {}, set()
    duplicates = 0
    for item in assignment:
        if not isinstance(item, dict) or set(item) != {"article_id", "group_id"}:
            raise CurationValidationError("curation_schema")
        identifier, label = item["article_id"], item["group_id"]
        if type(identifier) is not int or type(label) is not int or not 1 <= label <= len(expected):
            raise CurationValidationError("curation_coverage", coverage_check={"invalid_assignment": 1})
        duplicates += int(identifier in assigned)
        assigned.add(identifier)
        groups.setdefault(label, []).append(identifier)
    missing, unexpected = expected - assigned, assigned - expected
    if missing or unexpected or duplicates:
        raise CurationValidationError("curation_coverage", coverage_check={
            "missing": len(missing), "unexpected": len(unexpected), "duplicate": duplicates})
    comparisons = output.get("comparisons")
    if not isinstance(comparisons, list):
        raise CurationValidationError("curation_schema")
    seen, converted = set(), []
    for item in comparisons:
        if not isinstance(item, dict) or type(item.get("group_id")) is not int:
            raise CurationValidationError("curation_schema")
        label = item["group_id"]
        if label in seen or label not in groups:
            raise CurationValidationError("curation_coverage", coverage_check={
                "duplicate_groups": int(label in seen), "unexpected_groups": int(label not in groups)})
        seen.add(label)
        if "article_ids" in item:
            raise CurationValidationError("curation_schema")
        converted.append({**{k: v for k, v in item.items() if k != "group_id"},
                          "article_ids": sorted(groups[label])})
    if seen != set(groups):
        raise CurationValidationError("curation_coverage", coverage_check={"missing_groups": len(set(groups) - seen)})
    ranking = output.get("ranking")
    if not isinstance(ranking, list):
        raise CurationValidationError("curation_schema")
    ranked = []
    for item in ranking:
        if not isinstance(item, dict) or type(item.get("group_id")) is not int:
            raise CurationValidationError("curation_schema")
        label = item["group_id"]
        if label not in groups:
            raise CurationValidationError("curation_group")
        if "article_ids" in item:
            raise CurationValidationError("curation_schema")
        # Do not silently fix inconsistent legacy/model totals. This contract
        # explicitly excludes derived fields from the response.
        if "score" in item or "rank" in item:
            raise CurationValidationError("curation_score_order")
        ranked.append({**{k: v for k, v in item.items() if k != "group_id"},
                       "article_ids": sorted(groups[label]), "rank": len(ranked) + 1, "score": 0})
    # Unknown fields remain for the strict local model to reject.
    result = {k: v for k, v in output.items() if k != "article_groups"}
    result.update(comparisons=converted, ranking=ranked)
    # Validate types, component keys/ranges and extra fields BEFORE arithmetic.
    # Membership, completeness, source grounding and totals are still checked
    # by validate_ranking() on the normal service path before anything is saved.
    try:
        result = ranking_model(evidence["curation_contract"]).model_validate(result).model_dump()
    except ValidationError as exc:
        raise CurationValidationError("curation_schema", schema_issues=exc.errors(
            include_input=False, include_context=False, include_url=False)) from None
    for item in result["ranking"]:
        item["score"] = component_total(item["components"], global_policy=(
            evidence["curation_contract"]["profile"] == GLOBAL_PROFILE))
    result["ranking"].sort(key=lambda item: item["score"], reverse=True)
    for rank, item in enumerate(result["ranking"], 1):
        item["rank"] = rank
    return result
