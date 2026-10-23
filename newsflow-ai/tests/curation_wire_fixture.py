"""Encode an independently generated fixture in the Claude transport contract."""
from copy import deepcopy


def wire_output(result):
    result = deepcopy(result)
    assignment, group_labels = [], {}
    for label, group in enumerate(result["comparisons"], 1):
        ids = group.pop("article_ids")
        group_labels[frozenset(ids)] = label
        assignment.extend({"article_id": identifier, "group_id": label} for identifier in ids)
        group["group_id"] = label
    for item in result["ranking"]:
        item["group_id"] = group_labels.get(frozenset(item.pop("article_ids")), 999999)
        item.pop("rank", None)
        item.pop("score", None)
    result.pop("recommended_article_id", None)
    result.pop("selection_reason", None)
    return {"article_groups": assignment, **result}
