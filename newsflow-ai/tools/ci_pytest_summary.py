"""Publish JUnit counts as a safe GitHub check annotation."""

from __future__ import annotations

import json
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


if __name__ == "__main__":
    main()
