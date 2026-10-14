"""Publish JUnit counts as a safe GitHub check annotation."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree


def main() -> None:
    root = ElementTree.parse(Path(sys.argv[1])).getroot()
    cases = root.findall(".//testcase")
    skipped = sum(case.find("skipped") is not None for case in cases)
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    summary = {
        "tests": len(cases),
        "passed": len(cases) - skipped - failures - errors,
        "skipped": skipped,
        "failures": failures,
        "errors": errors,
    }
    print("::notice title=NewsFlow pytest::" + json.dumps(summary, separators=(",", ":")))
    # Runner logs/artifact redirects may be unavailable to Cloud. Export bounded failure
    # locations and fixed classifications, never raw exception messages or parameter values.
    for case in [c for c in cases if c.find("failure") is not None or c.find("error") is not None][:8]:
        node = case.find("error")
        if node is None:
            node = case.find("failure")
        trace = (node.text or "").replace("\\", "/")
        diagnostic = {
            "name": case.get("name", "").split("[", 1)[0][:120],
            "class": case.get("classname", "")[:120],
            "kind": node.tag,
            "exception_types": [name for name in (
                "AssertionError", "AttributeError", "ValueError", "TypeError", "PermissionError",
                "FileNotFoundError", "OSError", "VaultError", "OperationalError", "ProgrammingError",
                "IntegrityError", "NotImplementedError", "RuntimeError",
            ) if name in trace],
            "markers": [value for value in (
                "database is locked", "closed database", "WinError 32", "WinError 5",
                "FOREIGN KEY constraint failed", "UNIQUE constraint failed", "unable to open database file",
            ) if value in trace],
            "locations": re.findall(r"((?:tests|src/newsflow)/[A-Za-z0-9_/.-]+\.py):([0-9]+)", trace)[:8],
        }
        encoded = json.dumps(diagnostic, ensure_ascii=True, separators=(",", ":"))
        assert len(encoded.encode()) < 3500
        print("::notice title=NewsFlow pytest diagnostic::" + encoded)


if __name__ == "__main__":
    main()
