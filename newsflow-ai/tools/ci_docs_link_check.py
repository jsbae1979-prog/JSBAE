"""Offline link check for the user-facing documents: relative targets and heading anchors.

External http(s) links are listed, never fetched. Used by tests/test_user_guide_links.py
and by the Windows workflow; exits 1 only when a relative link or anchor is broken.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = ("README.md", "START_HERE.html")
DEFAULT_GLOBS = ("docs/*.md", "docs/design/*.md", "docs/reports/phase5c1_*.md")
_MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_HREF = re.compile(r"href=\"([^\"]+)\"")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.MULTILINE)
_HTML_ID = re.compile(r"id=\"([^\"]+)\"")


def slug(heading: str) -> str:
    """GitHub-style anchor: lowercase, punctuation removed, spaces to hyphens; Unicode letters kept."""
    text = re.sub(r"`([^`]*)`", r"\1", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = unicodedata.normalize("NFC", text).strip().lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in " -_" or unicodedata.category(ch).startswith("M"))
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    found: set[str] = set()
    counts: dict[str, int] = {}
    if path.suffix.lower() == ".md":
        for heading in _HEADING.findall(text):
            base = slug(heading)
            number = counts.get(base, 0)
            counts[base] = number + 1
            found.add(base if number == 0 else f"{base}-{number}")
    found.update(_HTML_ID.findall(text))
    return found


def links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    pattern = _HTML_HREF if path.suffix.lower() in {".html", ".htm"} else _MD_LINK
    return pattern.findall(text)


def check(files: list[Path], root: Path = ROOT) -> dict:
    result: dict = {"files": [], "broken": [], "external": [], "checked": 0}
    for path in files:
        entry = {"file": str(path.relative_to(root)), "links": 0}
        for target in links(path):
            entry["links"] += 1
            result["checked"] += 1
            if target.startswith(("http://", "https://", "mailto:")):
                result["external"].append({"file": entry["file"], "url": target, "https": target.startswith("https://")})
                continue
            if target.startswith("#"):
                if target[1:] not in anchors(path):
                    result["broken"].append({"file": entry["file"], "link": target, "reason": "anchor"})
                continue
            location, _, fragment = target.partition("#")
            resolved = (path.parent / location).resolve()
            if not resolved.exists() or root not in resolved.parents and resolved != root:
                result["broken"].append({"file": entry["file"], "link": target, "reason": "missing"})
                continue
            if fragment and resolved.is_file() and fragment not in anchors(resolved):
                result["broken"].append({"file": entry["file"], "link": target, "reason": "anchor"})
        result["files"].append(entry)
    result["status"] = "PASS" if not result["broken"] else "FAIL"
    return result


def default_files(root: Path = ROOT) -> list[Path]:
    files = [root / name for name in DEFAULT_FILES if (root / name).is_file()]
    for pattern in DEFAULT_GLOBS:
        files.extend(sorted(root.glob(pattern)))
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check(default_files())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "docs-links.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"status": result["status"], "checked": result["checked"], "broken": result["broken"][:20],
               "external_non_https": [e["url"] for e in result["external"] if not e["https"]][:20]}
    print("::notice title=NewsFlow docs links::" + json.dumps(summary, ensure_ascii=True, separators=(",", ":"))[:3900])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
