"""Local JPEG artwork only. No image scraping, generative API or voice synthesis."""
import warnings
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import ValidationError

from newsflow.video.engine import font_path

from .card_design import ACCENTS, designed_panel
from .card_symbols import card_theme, compact_whitespace, symbolic_panel
from .service import PublishingError

MAX_IMAGE_BYTES = 4 * 1024 * 1024

PALETTES = {"navy": ("#101e34", "#65a8ff"), "teal": ("#102d32", "#65d5bf"),
            "plum": ("#2b1834", "#d7a2f0")}


def card_artwork(title, body, publisher, plan):
    """Render validated data with local primitives; never evaluate model-generated code."""
    if "svg" in plan:
        from .svg_cards import render_svg
        # An already composed SVG cannot silently diverge from the edited caption.
        if (title.strip(), body.strip()) != (plan.get("title"), plan.get("body")):
            raise PublishingError("SVG 안의 문구는 자동 편집되지 않습니다. 미리보기와 같은 문구로 저장하세요.")
        return render_svg(plan["svg"], title=title, body=body, publisher=publisher)
    if (plan.get("palette") not in PALETTES or plan.get("icon") not in {"globe", "book", "technology"}
            or not 1 <= len(title.strip()) <= 60 or not 1 <= len(body.strip()) <= 200):
        raise PublishingError("카드 제목은 60자·요약은 200자 이내로 입력하세요.")
    background, _ = PALETTES[plan["palette"]]
    layout = "visual_first"
    if "design" in plan:
        try:
            panel, spec = designed_panel(plan["design"])
        except (ValidationError, ValueError, TypeError):
            raise PublishingError("그림 설계가 안전한 형식·범위를 벗어났습니다. 자동 재요청하지 않습니다.") from None
        label, accent, layout = "뉴스 그래픽", ACCENTS[spec.accent], spec.layout
    else:
        # Saved legacy results remain usable, without another API request.
        theme, label, accent = card_theme(title, body, plan["icon"])
        panel = symbolic_panel(theme, accent)
    canvas = Image.new("RGB", (1080, 1350), background)
    panel_y, title_y, label_y = (160, 654, 600) if layout == "visual_first" else (420, 160, 112)
    canvas.paste(panel, (66, panel_y))
    draw = ImageDraw.Draw(canvas)
    face = str(font_path())
    small = ImageFont.truetype(face, 25)
    brand = ImageFont.truetype(face, 30)
    draw.text((66, 60), "NewsFlow", font=brand, fill="white", stroke_width=1)
    draw.text((254, 65), " /  NEWS BRIEF", font=small, fill=accent)
    draw.text((1014 - draw.textlength(label, font=small), 65), label, font=small, fill=accent)
    draw.rounded_rectangle((66, label_y + 6, 74, label_y + 32), radius=4, fill=accent)
    draw.text((91, label_y), "한눈에 보는 뉴스", font=small, fill=accent)
    heading, title_lines = fitted_lines(draw, compact_whitespace(title), face, 56, 40, 3)
    for index, line in enumerate(title_lines):
        draw.text((66, title_y + index * 65), line, font=heading, fill="white", stroke_width=1)
    draw.line((66, 864, 1014, 864), fill="#3d5268", width=2)
    text, body_lines = fitted_lines(draw, compact_whitespace(body), face, 35, 28, 7)
    for index, line in enumerate(body_lines):
        draw.text((66, 894 + index * 41), line, font=text, fill="#e1e8f0")
    for index, line in enumerate(wrap(draw, f"출처: {publisher}", small, 948, 2)):
        draw.text((66, 1204 + index * 34), line, font=small, fill=accent)
    draw.text((66, 1290), "AI 구성 · 설명용 그래픽 / 실제 현장 사진 아님", font=small, fill="#d6e1f4")
    output = BytesIO()
    canvas.save(output, format="JPEG", quality=90)
    return output.getvalue()


def fitted_lines(draw, value, face, start, minimum, maximum):
    """Shrink within a readable range; never clip or discard reviewed copy."""
    for size in range(start, minimum - 1, -1):
        font = ImageFont.truetype(face, size)
        try:
            return font, wrap(draw, value, font, 948, maximum)
        except PublishingError:
            continue
    raise PublishingError("카드에 문구를 모두 표시할 수 없습니다. 문구를 줄여 주세요.")


def wrap(draw, text, font, width, maximum):
    lines, line = [], ""
    for character in text.replace("\r", ""):
        if character == "\n" or draw.textlength(line + character, font=font) > width:
            lines.append(line)
            line = "" if character == "\n" else character
        else:
            line += character
    if line:
        lines.append(line)
    if len(lines) > maximum:
        raise PublishingError("이미지 문구가 너무 깁니다. 제목이나 출처 표시를 줄여 주세요.")
    return lines


def artwork(title: str, publisher: str, photo: bytes | None = None, *, ai=False, body="") -> bytes:
    canvas = Image.new("RGB", (1080, 1350), "#101e34")
    if photo:
        if len(photo) > MAX_IMAGE_BYTES:
            raise PublishingError("사진은 4MB 이하의 JPEG·PNG·WebP를 사용하세요.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(photo)) as image:
                    if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 16_000_000:
                        raise ValueError
                    if min(image.size) < 320:
                        raise ValueError
                    image.load()
                    picture = ImageOps.fit(ImageOps.exif_transpose(image).convert("RGB"), canvas.size)
                    canvas.paste(picture)
        except Exception:  # noqa: BLE001 - reject malformed decoder inputs without leaking metadata
            raise PublishingError("사진 형식·해상도를 확인하세요. 짧은 변 320px 이상이 필요합니다.") from None
    overlay = Image.new("RGBA", canvas.size)
    shade = ImageDraw.Draw(overlay)
    for y in range(600, 1350):
        shade.line((0, y, 1080, y), fill=(4, 12, 25, int(240 * (y - 600) / 749)))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    face = str(font_path())
    heading = ImageFont.truetype(face, 62)
    small = ImageFont.truetype(face, 28)
    lines = wrap(draw, title, heading, 948, 4)
    top = (940 if body else 1170) - len(lines) * 90
    draw.rounded_rectangle((66, 65, 300, 117), radius=12, fill="#2364ce")
    draw.text((86, 72), "NewsFlow AI", font=small, fill="white")
    for index, line in enumerate(lines):
        draw.text((66, top + 90 * index), line, font=heading, fill="white", stroke_width=1)
    if body:
        text, body_lines = fitted_lines(draw, compact_whitespace(body), face, 34, 28, 5)
        for index, line in enumerate(body_lines):
            draw.text((66, 970 + index * 40), line, font=text, fill="#e1e8f0")
    for index, line in enumerate(wrap(draw, f"출처: {publisher}", small, 948, 2)):
        draw.text((66, 1200 + index * 38), line, font=small, fill="#d6e1f4")
    if ai:
        draw.text((66, 1300), "AI 생성 이미지 · 실제 현장 사진 아님", font=small, fill="white")
    output = BytesIO()
    # Fresh raster does not carry EXIF, location, comments or original file metadata.
    canvas.save(output, format="JPEG", quality=90)
    return output.getvalue()
