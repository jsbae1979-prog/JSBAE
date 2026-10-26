"""Export only test counts and IDs; never export raw logs, payloads or media."""
from __future__ import annotations

import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_failure_message(value, limit=1600):
    """Bound XML exception text; never export argv/env, identities or paths."""
    text = str(value or "")[:12000]
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    lines = []
    for line in text.splitlines()[:24]:
        # Exception locals can contain whole command lines, stdin or credential dictionaries.
        if re.search(r"(?i)\b(?:argv|args|environ\w*|env|stdin|stdout|stderr|payload|"
                     r"authorization|bearer|password|token|api[_ -]?key|secret|cookie|session[_ -]?key)\b", line):
            lines.append("[redacted structured/process/credential detail]")
            continue
        line = re.sub(r"(?i)\bS-\d+(?:-\d+){2,}\b", "[redacted SID]", line)
        line = re.sub(r"(?i)\b(?:https?|file)://[^\s<>\"']+", "[redacted URL]", line)
        line = re.sub(r"(?i)\b(?:sk|ghp|gho|github_pat|AIza)[-_][A-Za-z0-9_-]+", "[redacted credential]", line)
        line = re.sub(r"(?i)\b[A-Z]:[\\/].*", "[redacted filesystem path]", line)
        line = re.sub(r"\\\\[^\r\n]+", "[redacted UNC path]", line)
        line = re.sub(r"(?<!\w)/(?:[^\s/]+/)+[^\s]*", "[redacted filesystem path]", line)
        line = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted email]", line)
        line = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[redacted opaque value]", line)
        lines.append("".join(c for c in line if c == "\t" or ord(c) >= 32))
    return "\n".join(lines)[:limit]


def failure_detail(element):
    message = safe_failure_message(element.get("message", ""))
    # Only exception summary lines, never source snippets, traceback frames or locals.
    lines = []
    for raw in (element.text or "").splitlines():
        line = re.sub(r"^E\s+", "", raw.strip())
        if re.match(r"(?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*(?:Error|Exception):", line):
            lines.append(line)
    return {"message": message,
            "exception_summaries": safe_failure_message("\n".join(lines[-4:]), 1200),
            "bounded_and_redacted": True}


def native_detail(root, phase):
    path = root / phase / "evidence/native-boundary-safe.json"
    result = {"present": path.is_file(), "events": [], "powershell_exits": []}
    if not path.is_file():
        return result
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 2 * 1024 * 1024:
        result["read_status"] = "REJECTED_UNEXPECTED_EVIDENCE_SHAPE"
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        events = value.get("events", [])
        if not isinstance(events, list):
            raise ValueError
        result["total_events"] = len(events)
        result["events_truncated"] = len(events) > 200
        for event in events[:200]:
            if not isinstance(event, dict):
                continue
            kind = event.get("kind")
            if kind not in {"DENY", "Python-approved", "PowerShell-approved", "PowerShell-complete", "PowerShell-exception"}:
                continue
            safe = {"kind": kind}
            reason = event.get("reason")
            if kind == "DENY" and isinstance(reason, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", reason):
                safe["reason"] = reason
            if kind.startswith("PowerShell-") and event.get("operation") in {"identity", "validate"}:
                safe["operation"] = event["operation"]
            if kind == "PowerShell-exception" and event.get("error_type") in {"TimeoutExpired", "OSError", "PermissionError", "FileNotFoundError"}:
                safe["error_type"] = event["error_type"]
            if kind == "PowerShell-complete" and type(event.get("exit")) is int:
                safe["exit"] = event["exit"]
                result["powershell_exits"].append({k: v for k, v in safe.items() if k in {"operation", "exit"}})
            if kind == "Python-approved" and event.get("mode") in {
                "lock", "oauth_bind", "preview_boundary", "entrypoint", "main", "diagnostics", "preview", "feed_review"
            }:
                safe["mode"] = event["mode"]
            result["events"].append(safe)
        result["read_status"] = "SAFE_FIELDS_ONLY"
    except (OSError, ValueError, TypeError, AttributeError):
        result["read_status"] = "UNREADABLE_EVIDENCE"
    return result

def record_phase(root: Path, phase: str, expected: int, exit_code: int, expected_ids=None):
    xml_path = root / phase / "pytest.xml"
    result = {"phase": phase, "exit": exit_code, "expected_records": expected,
              "xml_present": xml_path.is_file(), "status": "FAIL"}
    ids, failures, details = [], [], []
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
                element = case.find(tag)
                if element is not None:
                    failures.append({"ID": identifier, "outcome": tag})
                    details.append({"ID": identifier, "outcome": tag, **failure_detail(element)})
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
    if result["status"] != "PASS":
        diagnostic_path = root / "failure-diagnostics-safe.json"
        diagnostics = json.loads(diagnostic_path.read_text(encoding="utf-8")) if diagnostic_path.exists() else []
        diagnostics.append({"phase": phase, "test_failures": details[:30],
                            "test_failures_truncated": len(details) > 30,
                            "native_boundary": native_detail(root, phase),
                            "excluded": "SID, filesystem paths, credentials, argv, environment, raw logs and payloads"})
        write_json(diagnostic_path, diagnostics)
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
             "uploaded_contents": "counts, IDs and bounded redacted failure diagnostics; no raw logs, DB, keys, media"}
    write_json(root / "ci-summary-safe.json", value)




