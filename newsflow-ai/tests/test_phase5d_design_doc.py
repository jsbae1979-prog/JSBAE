"""Phase 5D design draft: offline checks that the document exists, is marked as unverified design, and leaks no secrets."""

import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[1] / "docs" / "design" / "phase5d_higgsfield_video_provider.md"


@pytest.fixture(scope="module")
def text() -> str:
    assert DOC.is_file(), "docs/design/phase5d_higgsfield_video_provider.md must exist"
    return DOC.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "phrase",
    [
        "NOT VERIFIED",
        "구현 없음",
        "FFmpeg",
        "FakeVideoProvider",
        "0010",
        "video_cost_ack",
        "AI 생성 장면 · 실제 영상 아님",
        "Higgsfield API/MCP 호출 0건",
    ],
)
def test_design_doc_states_required_boundaries(text: str, phrase: str) -> None:
    assert phrase in text


def test_design_doc_has_no_credential_like_literals(text: str) -> None:
    assert re.search(r"(?i)authorization:\s*key\s+[A-Za-z0-9]{8,}", text) is None
    assert re.search(r"sk-[A-Za-z0-9]{10,}", text) is None


@pytest.mark.parametrize("number", range(1, 17))
def test_design_doc_has_every_numbered_section(text: str, number: int) -> None:
    assert re.search(rf"^## {number}\. \S", text, re.MULTILINE), f"section {number} heading is missing"


def test_design_doc_is_dated_and_marked_as_draft(text: str) -> None:
    assert "2026-10-15" in text
    assert "Phase 5D 승인 후 착수" in text
    assert "GUI 변경 요약" in text
