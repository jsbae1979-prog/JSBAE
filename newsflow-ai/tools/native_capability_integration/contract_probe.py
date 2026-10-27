"""Read installed filelock source/metadata WITHOUT executing package code."""
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path

def inspect_installed(snapshot_path):
    expected = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    dist = importlib.metadata.distribution("filelock")
    actual = {}
    for name, data in expected["modules"].items():
        path = dist.locate_file("filelock/" + name)
        raw = Path(path).read_bytes()
        tree = ast.parse(raw)
        digest = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
        actual[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "ast_sha256": digest,
                        "matches_local_installed_AST": digest == data["ast_sha256"]}
    guard = expected["existing_guard"]
    return {"version": dist.version, "expected_version": expected["filelock_version"],
            "all_source_contracts_match": dist.version == expected["filelock_version"] and all(x["matches_local_installed_AST"] for x in actual.values()),
            "modules": actual,
            "existing_Guard_registration": "BLOCKED" if not guard["registration_hook_present"] else "NOT VERIFIED",
            "upstream_runtime_compatibility": "BLOCKED",
            "reason": "Existing Guard has no reviewed capability hook; upstream needs raw CRT fd and additional native binding contracts.",
            "full_app_allowed": False}
