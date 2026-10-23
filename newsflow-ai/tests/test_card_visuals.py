"""Local-only editorial artwork layout and preservation contracts."""
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from newsflow.publishing.card_symbols import card_theme, symbolic_panel
from newsflow.publishing.image_artwork import card_artwork, fitted_lines
from newsflow.publishing.service import PublishingError
from newsflow.video.engine import font_path


@pytest.mark.parametrize(("title", "theme"), [
    ("어린이집 안전 점검", "care"), ("프랑스 일부 지역 통행금지", "city"),
    ("호주 의원 사건", "civic"), ("도서관 독서 모임", "book"),
    ("반도체 기술", "technology"), ("새 소식", "globe"),
])
def test_symbolic_topics_offline(title, theme, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network call"))
    kind, _label, accent = card_theme(title, "저장한 요약", "globe")
    assert kind == theme
    panel = symbolic_panel(kind, accent)
    assert panel.size == (948, 420)
    raw = card_artwork(title, "검토된 문구를 그대로 사용합니다.", "테스트 출처",
                       {"palette": "navy", "icon": "globe"})
    with Image.open(BytesIO(raw)) as image:
        assert image.size == (1080, 1350) and image.format == "JPEG"
        assert not image.getexif()


@pytest.mark.parametrize("text,maximum,start,minimum", [
    ("가" * 60, 3, 56, 40), ("W" * 60, 3, 56, 40),
    ("가" * 200, 7, 35, 28), ("W" * 200, 7, 35, 28),
])
def test_maximum_copy_fits_without_lost_characters(text, maximum, start, minimum):
    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    face, lines = fitted_lines(draw, text, str(font_path()), start, minimum, maximum)
    assert "".join(lines) == text
    assert len(lines) <= maximum and all(draw.textlength(line, font=face) <= 948 for line in lines)


def test_untrusted_palette_still_rejected_and_plan_unchanged():
    plan = {"palette": "navy", "icon": "globe"}
    before = dict(plan)
    card_artwork("어린이집", "원래 내용", "출처", plan)
    assert plan == before
    with pytest.raises(PublishingError):
        card_artwork("제목", "내용", "출처", {"palette": "url(evil)", "icon": "globe"})


def test_distinct_symbols_have_distinct_pixels():
    themes = ("care", "city", "civic", "book", "technology", "globe")
    assert len({symbolic_panel(t, "#82c8ff").tobytes() for t in themes}) == len(themes)
