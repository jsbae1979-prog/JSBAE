"""Original local editorial symbols. No photos, URLs, model calls or event reconstruction."""
import re

from PIL import Image, ImageDraw


def card_theme(title, body, icon):
    """Use only displayed copy for a broad visual cue, never add factual assertions."""
    text = (title + " " + body).casefold()
    if any(word in text for word in ("어린이집", "아동 안전", "daycare")):
        return "care", "안전 · 돌봄", "#75dec6"
    if any(word in text for word in ("통행금지", "curfew", "야간 도시")):
        return "city", "도시 · 사회", "#b9afff"
    if any(word in text for word in ("의원", "의회", "parliament")):
        return "civic", "사회 · 공공", "#f5be81"
    if icon == "book" or any(word in text for word in ("도서관", "독서")):
        return "book", "교육 · 문화", "#75dec6"
    if icon == "technology" or any(word in text for word in ("반도체", "인공지능", "기술")):
        return "technology", "기술 · 변화", "#82c8ff"
    return "globe", "뉴스 브리핑", "#82c8ff"


def symbolic_panel(theme, accent):
    """A 948×420 illustration: deliberately symbolic, with no real faces or locations."""
    panel = Image.new("RGB", (948, 420), "#15273d")
    d = ImageDraw.Draw(panel)
    # Restrained depth and a common graphic language across the collection.
    for y in range(420):
        d.line((0, y, 948, y), fill=(21 + y // 35, 39 + y // 24, 61 + y // 19))
    d.ellipse((590, -130, 1060, 340), fill="#29425a")
    d.ellipse((-145, 260, 260, 650), fill="#20374c")
    for x in range(45, 925, 36):
        d.ellipse((x, 382, x + 3, 385), fill="#52657a")
    ink, white, muted = "#112236", "#edf5ff", "#8ea7bb"
    if theme == "care":
        # A generic nursery + protective shield; do not depict the reported incident.
        d.rounded_rectangle((162, 152, 547, 345), 22, fill=white)
        d.polygon([(128, 160), (355, 30), (582, 160)], fill=accent)
        d.rectangle((308, 231, 398, 345), fill="#36566c")
        for x in (202, 440):
            d.rounded_rectangle((x, 203, x + 62, 266), 9, fill="#8acbbf")
            d.line((x + 31, 203, x + 31, 266), fill=white, width=5)
        shield = [(666, 73), (791, 120), (778, 238), (742, 303), (666, 355),
                  (590, 303), (554, 238), (541, 120)]
        d.polygon(shield, fill=accent)
        d.line([(606, 210), (650, 254), (727, 166)], fill=ink, width=17)
    elif theme == "city":
        d.ellipse((678, 30, 790, 142), fill="#f4e1aa")
        d.ellipse((716, 13, 812, 113), fill="#29425a")
        for x, y, w in ((94, 187, 130), (248, 92, 145), (422, 152, 120), (568, 202, 140)):
            d.rounded_rectangle((x, y, x + w, 356), 8, fill="#456079")
            for wx in range(x + 22, x + w - 14, 36):
                for wy in range(y + 25, 332, 45):
                    d.rounded_rectangle((wx, wy, wx + 15, wy + 20), 3, fill="#c5c1f5")
        d.ellipse((691, 201, 874, 384), fill=accent)
        d.ellipse((708, 218, 857, 367), outline=ink, width=4)
        # Abstract clock, not an asserted start/end time: no numerals or hands.
        for xy in ((780, 228, 785, 244), (780, 342, 785, 358),
                   (719, 288, 735, 293), (830, 288, 846, 293)):
            d.rounded_rectangle(xy, 2, fill=ink)
        d.arc((744, 253, 823, 332), 30, 300, fill=ink, width=8)
    elif theme == "civic":
        d.polygon([(108, 161), (367, 42), (626, 161)], fill=accent)
        d.rounded_rectangle((136, 168, 599, 190), 5, fill=white)
        for x in (168, 276, 384, 492):
            d.rectangle((x, 207, x + 58, 324), fill=white)
            d.line((x + 15, 213, x + 15, 316), fill=muted, width=4)
        d.rounded_rectangle((120, 332, 617, 357), 7, fill=accent)
        d.rounded_rectangle((617, 112, 857, 276), 32, fill="#dce9f6")
        d.polygon([(656, 256), (656, 321), (716, 263)], fill="#dce9f6")
        for y, width in ((157, 140), (195, 109), (233, 72)):
            d.rounded_rectangle((653, y, 653 + width, y + 9), 4, fill="#527189")
    elif theme == "book":
        d.polygon([(180, 92), (460, 133), (460, 346), (180, 305)], fill=white)
        d.polygon([(488, 133), (768, 92), (768, 305), (488, 346)], fill=accent)
        d.line((474, 132, 474, 350), fill=muted, width=8)
        for y in (158, 207, 256):
            d.line((220, y, 419, y + 28), fill=muted, width=7)
            d.line((529, y + 28, 728, y), fill="#36566c", width=7)
    elif theme == "technology":
        d.rounded_rectangle((322, 70, 626, 354), 40, fill=accent)
        d.rounded_rectangle((382, 130, 566, 294), 20, fill=ink)
        for y in (116, 180, 244, 308):
            d.line((222, y, 322, y), fill=white, width=13)
            d.line((626, y, 726, y), fill=white, width=13)
        for x in (374, 440, 506, 572):
            d.line((x, 36, x, 70), fill=white, width=13)
            d.line((x, 354, x, 389), fill=white, width=13)
    else:
        d.ellipse((304, 40, 644, 380), outline=accent, width=12)
        d.ellipse((394, 40, 554, 380), outline=accent, width=7)
        for y in (140, 210, 280):
            d.line((320 if y != 210 else 304, y, 628 if y != 210 else 644, y), fill=accent, width=6)
        for x, y in ((230, 103), (730, 286), (746, 108)):
            d.ellipse((x - 14, y - 14, x + 14, y + 14), fill=white)
    return panel


def compact_whitespace(value):
    return re.sub(r"\s+", " ", value).strip()
