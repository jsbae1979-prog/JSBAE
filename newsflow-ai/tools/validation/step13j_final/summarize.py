"""Export only test counts and IDs; never export raw logs, payloads or media."""
from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def record_phase(root: Path, phase: str, expected: int, exit_code: int, expected_ids=None):
    xml_path = root / phase / "pytest.xml"
    result = {"phase": phase, "exit": exit_code, "expected_records": expected,
              "xml_present": xml_path.is_file(), "status": "FAIL"}
    ids, failures = [], []
    if xml_path.is_file():
        tree = ET.parse(xml_path)
        cases = list(tree.iter("testcase"))
        counts = {key: sum(int(suite.get(key, 0)) for suite in tree.iter("testsuite"))
                  for key in ("tests", "failures", "errors", "skipped")}
        result.update(counts, testcase_records=len(cases))
        for case in cases:
            identifier = case.get("classname", "") + "::" + case.get("name", "")
            ids.append(identifier)
            for tag in ("failure", "error", "skipped"):
                if case.find(tag) is not None:
                    failures.append({"ID": identifier, "outcome": tag})
        result["count_matches"] = counts["tests"] == len(cases) == expected
        result["unique_IDs"] = len(set(ids)) == len(ids)
        result["ID_set_matches"] = (expected_ids is None or
            (len(expected_ids) == expected and set(ids) == set(expected_ids)))
        if (exit_code == 0 and result["count_matches"] and result["unique_IDs"]
                and result["ID_set_matches"] and not failures):
            result["status"] = "PASS"
    result["failed_IDs"] = failures
    collected_path = root / "ci-collected-IDs-safe.json"
    collected = json.loads(collected_path.read_text(encoding="utf-8")) if collected_path.exists() else []
    collected.append({"phase": phase, "expected_records": expected, "IDs": ids})
    write_json(collected_path, collected)
    failure_path = root / "failure-IDs-safe.json"
    previous = json.loads(failure_path.read_text(encoding="utf-8")) if failure_path.exists() else []
    if result["status"] != "PASS":
        previous.append({"phase": phase, "exit": exit_code, "xml_present": xml_path.is_file(),
                         "count_matches": result.get("count_matches", False), "failed": failures})
    write_json(failure_path, previous)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def write_summary(root: Path, definitions: list[dict], completed: list[dict]):
    finished = {item["phase"]: item for item in completed}
    phases = [finished.get(item["name"], {"phase": item["name"], "status": "NOT RUN",
                                        "expected_records": item["expected"]})
              for item in definitions]
    value = {"Python": "3.14.7", "scope": "selected Fake tests only",
             "status": "PASS" if all(p["status"] == "PASS" for p in phases) else "INCOMPLETE_OR_FAILED",
             "phases": phases, "production_profile_used": False,
             "real_provider_execution_authorized": False,
             "provider_environment_inherited": False,
             "complete_OS_isolation_claimed": False,
             "browser_background_network": "NOT VERIFIED by Playwright request mocks",
             "uploaded_contents": "summary counts and test IDs only; no raw logs, DB, keys, media"}
    write_json(root / "ci-summary-safe.json", value)


