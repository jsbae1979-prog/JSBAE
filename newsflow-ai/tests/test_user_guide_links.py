"""User-facing documents keep working relative links and anchors; external links are https."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _checker():
    spec = importlib.util.spec_from_file_location("ci_docs_link_check", ROOT / "tools" / "ci_docs_link_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_documents_have_no_broken_relative_links_or_anchors():
    checker = _checker()
    files = checker.default_files(ROOT)
    assert ROOT / "README.md" in files and ROOT / "START_HERE.html" in files
    result = checker.check(files, root=ROOT)
    assert result["broken"] == [], result["broken"]
    non_https = [e for e in result["external"] if not e["https"]]
    assert non_https == [], non_https


def test_phase5c1_user_documents_exist_and_cross_link():
    guide = ROOT / "docs" / "user_guide_realcontent.md"
    checklist = ROOT / "docs" / "windows_user_verification_checklist.md"
    listening = ROOT / "docs" / "korean_tts_listening_checklist.md"
    design = ROOT / "docs" / "design" / "phase5d_higgsfield_video_provider.md"
    for path in (guide, checklist, listening, design):
        assert path.is_file(), path
    guide_text = guide.read_text(encoding="utf-8")
    assert "realcontent.md" in guide_text and "windows_user_verification_checklist.md" in guide_text
    assert "NOT VERIFIED" in checklist.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/user_guide_realcontent.md" in readme and "docs/windows_user_verification_checklist.md" in readme
