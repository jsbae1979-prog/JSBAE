"""Phase 5D implemented design and reports: they exist, quote the code's own constants and leak no secrets."""

import re
from pathlib import Path

import pytest

from newsflow.video.ai.contracts import ERROR_MESSAGES
from newsflow.video.ai.policy import SCENE_LABEL, STYLE_GUARD
from newsflow.video.ai.settings import HOSTS
from newsflow.video.engine import CLIP_FILTER

DOCS = Path(__file__).resolve().parents[1] / "docs"
FILES = {
    "design": DOCS / "design" / "phase5d_ai_video_implementation.md",
    "verification": DOCS / "reports" / "phase5d_higgsfield_api_verification.md",
    "analysis": DOCS / "reports" / "phase5d_existing_analysis.md",
    "guide": DOCS / "user_guide_ai_video.md",
}


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    for name, path in FILES.items():
        assert path.is_file(), f"{name}: {path} must exist"
    return {name: path.read_text(encoding="utf-8") for name, path in FILES.items()}


def test_design_quotes_the_code_constants(texts):
    design = texts["design"]
    assert SCENE_LABEL in design and STYLE_GUARD in design and "0010" in design
    assert all(f"`{code}`" in design for code in (
        "video_ai_key_missing", "video_ai_unknown_submit", "video_ai_request_missing", "video_ai_disk_full"))
    assert all(code in ERROR_MESSAGES for code in ("video_ai_request_missing", "video_ai_disk_full"))
    assert "setsar=0" in CLIP_FILTER and "setsar=0" in design
    assert HOSTS == ("api.higgsfield.ai",) and "api.higgsfield.ai" in design


@pytest.mark.parametrize("name", ["design", "verification", "analysis", "guide"])
def test_documents_mark_vendor_facts_and_leak_no_secrets(texts, name):
    text = texts[name]
    assert "NOT VERIFIED" in text
    assert re.search(r"(?i)authorization:\s*key\s+[A-Za-z0-9_\-]{8,}", text) is None
    assert re.search(r"sk-[A-Za-z0-9]{10,}", text) is None


def test_verification_report_lists_the_seven_items_and_zero_calls(texts):
    report = texts["verification"]
    for number in range(1, 8):
        assert re.search(rf"^### 2\.{number} \S", report, re.MULTILINE), f"item 2.{number} is missing"
    assert "Higgsfield REST API 호출: 0건" in report


def test_user_guide_explains_both_modes_and_the_label(texts):
    guide = texts["guide"]
    assert "기본 모드" in guide and "AI 고품질 모드" in guide and SCENE_LABEL in guide
    assert "외부 영상 API" in guide
