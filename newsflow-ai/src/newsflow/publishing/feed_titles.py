"""Local Korean headlines. No translation API, silent truncation or source overwrite."""
import re
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from newsflow.video.engine import font_path
from .image_artwork import wrap
from .service import PublishingError

HEADER_BOTTOM = 260
TITLE_LAYOUT = "korean_header_v1"

def valid_title(value):
    return (isinstance(value, str) and 1 <= len(value.strip()) <= 100
            and bool(re.search(r"[가-힣]", value)) and not re.search(r"[A-Za-z]", value)
            and not value.rstrip().endswith(("…", "..."))
            and not any(ord(c) < 32 for c in value))

def choose_title(title, body):
    """Reuse Korean copy; an untranslated draft remains editable but cannot dispatch."""
    title = re.sub(r"\s+", " ", str(title)).strip()
    if valid_title(title):
        return title
    for sentence in re.split(r"(?<=[.!?。])\s+", re.sub(r"\s+", " ", str(body)).strip()):
        if valid_title(sentence):
            return sentence
    return title  # never invent a translation or silently shorten the title

def wrap_headline(draw, text, font):
    lines, current = [], ""
    for word in text.split(" "):
        candidate = current + (" " if current else "") + word
        if draw.textlength(candidate, font=font) <= 976:
            current = candidate
            continue
        if current:
            lines.append(current)
        chunks = wrap(draw, word, font, 976, 100)
        lines.extend(chunks[:-1]); current = chunks[-1] if chunks else ""
    if current:
        lines.append(current)
    return lines


def title_lines(title, height=HEADER_BOTTOM):
    if not valid_title(title):
        raise PublishingError("한국어 제목을 100자 이내로 입력하세요. 제목은 자동으로 자르지 않습니다.")
    if type(height) is not int or not 160 <= height <= 320:
        raise PublishingError("검토된 제목 영역이 필요합니다.")
    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    face_path = font_path()
    bold = face_path.with_name("malgunbd.ttf") if face_path.name.lower() == "malgun.ttf" else face_path
    face = str(bold if bold.is_file() else face_path)
    for size in range(60, 27, -1):
        font = ImageFont.truetype(face, size)
        try:
            lines = wrap_headline(draw, title, font)
        except PublishingError:
            continue
        line_height = size + 12
        if len(lines) * line_height <= height - 44:
            return font, lines, line_height
    raise PublishingError("제목 전체가 들어가도록 문구를 줄여 주세요. 잘린 이미지는 저장하지 않았습니다.")

def render_title(raw, title, *, height=HEADER_BOTTOM, hashtag_band=None, hashtags=""):
    font, lines, line_height = title_lines(title, height)
    with Image.open(BytesIO(raw)) as source:
        image = ImageOps.pad(source.convert("RGB"), (1080, 1350), method=Image.Resampling.LANCZOS, color=(11,22,40))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1079, height - 1), fill="#f7f9fc")
    y = (height - len(lines) * line_height) // 2
    for line in lines:
        draw.text((52, y), line, font=font, fill="#101e34", anchor="lt")
        y += line_height
    if hashtag_band is not None:
        if (not isinstance(hashtag_band, (list, tuple)) or len(hashtag_band) != 2
                or any(type(v) is not int for v in hashtag_band)
                or not height <= hashtag_band[0] < hashtag_band[1] <= 1350
                or hashtag_band[1] - hashtag_band[0] < 40):
            raise PublishingError("검토된 해시태그 영역이 필요합니다.")
        top, bottom = hashtag_band
        draw.rectangle((0, top, 1079, bottom-1), fill="#f7f9fc")
        small = ImageFont.truetype(str(font_path()), 30)
        draw.text((52, top+(bottom-top-36)//2), hashtags, font=small, fill="#456bb0", anchor="lt")
    out = BytesIO(); image.save(out, "JPEG", quality=95)
    return out.getvalue()
