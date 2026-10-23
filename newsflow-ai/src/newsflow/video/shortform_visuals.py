"""Local, bounded Pillow/ASS styling; no image generation or external assets."""
import re
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFont, ImageOps

# Leave the bottom 35% and right 180px free of editorial captions.
CAPTION_BOX = (90, 672, 900, 1248)


def wrap(text, draw, font, width=780):
    lines, line = [], ""
    for word in text.replace("\n", " ").replace("\r", " ").split():
        candidate = (line + " " + word).strip()
        if line and draw.textlength(candidate, font=font) > width:
            lines.append(line)
            line = ""
        for char in word:
            candidate = (line + char) if line else char
            if line and draw.textlength(candidate, font=font) > width:
                lines.append(line)
                line = ""
            line += char
        line += " "
    if line.strip():
        lines.append(line.strip())
    return [line.strip() for line in lines]


def caption_chunks(cues, font_path, size):
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = ImageFont.truetype(str(font_path), size)
    result = []
    for cue in cues:
        lines = wrap(cue["text"], draw, font, width=740)
        chunks = [lines[i:i+2] for i in range(0, len(lines), 2)]
        weights = [sum(map(len, chunk)) for chunk in chunks]
        total, used = sum(weights), 0
        for chunk, weight in zip(chunks, weights):
            start = cue["start_ms"] + round((cue["end_ms"] - cue["start_ms"]) * used / total)
            used += weight
            end = cue["start_ms"] + round((cue["end_ms"] - cue["start_ms"]) * used / total)
            if end <= start:
                raise ValueError("자막 표시 시간이 너무 짧습니다.")
            result.append({"start_ms": start, "end_ms": end, "lines": chunk})
    return result


def write_captions(path, cues, font_path, size=64):
    chunks = caption_chunks(cues, font_path, size)
    def timestamp(ms):
        cs = round(ms / 10)
        return f"{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}"
    def safe(text):
        return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
    lines = ["[Script Info]", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 2", "[V4+ Styles]",
             "Format: Name,Fontname,Fontsize,Bold,PrimaryColour,OutlineColour,BackColour,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV",
             f"Style: Default,Malgun Gothic,{size},-1,&H00FFFFFF,&H00261710,&H90261710,3,5,0,5,90,180,0",
             "[Events]", "Format: Layer,Start,End,Style,Text"]
    for cue in chunks:
        text = r"\N".join(safe(line) for line in cue["lines"])
        # Only locally constructed ASS tags; every input character was escaped above.
        text = re.sub(r"(\d+(?:[.,]\d+)*)", lambda m: r"{\c&H00D7FF&}" + m[0] + r"{\c&HFFFFFF&}", text)
        if not re.search(r"\d", text):
            keyword = safe(cue["lines"][0].split()[0])
            text = text.replace(keyword, r"{\c&H00D7FF&}" + keyword + r"{\c&HFFFFFF&}", 1)
        lines.append(f"Dialogue: 0,{timestamp(cue['start_ms'])},{timestamp(cue['end_ms'])},Default,{{\\an5\\pos(495,960)\\fad(100,60)}}{text}")
    path.write_text("\n".join(lines), encoding="utf-8-sig")
    return chunks


def visual(plan, scene, target, font_path, *, transparent=False):
    image = Image.new("RGBA" if transparent else "RGB", (1080, 1920),
                      (0, 0, 0, 0) if transparent else "#0b1526")
    if scene.image and not transparent:
        # Use the existing local image loader's validation before this function.
        with Image.open(scene.image) as asset:
            image.paste(ImageOps.fit(asset.convert("RGB"), (1080, 1920)), (0, 0))
        shade = Image.new("RGBA", image.size, (5, 14, 30, 110))
        image = Image.alpha_composite(image.convert("RGBA"), shade).convert("RGB")
    draw = ImageDraw.Draw(image)
    small = ImageFont.truetype(str(font_path), 30)
    title = ImageFont.truetype(str(font_path), 52)
    if not transparent and not scene.image:
        draw.ellipse((300, 440, 1160, 1300), fill="#142d49")
        draw.rounded_rectangle((85, 530, 230, 544), radius=7, fill="#3b82f6")
    if plan.shortform.source:
        names = list(dict.fromkeys(s.get("publisher") or urlsplit(s.get("url", "")).hostname or "출처 미상" for s in plan.sources))
        label = "출처: " + " · ".join(names)
        for i, line in enumerate(wrap(label, draw, small)[:2]):
            draw.rectangle((75, 65 + i*40, 930, 108 + i*40), fill="#0b1526")
            draw.text((90, 70+i*40), line, font=small, fill="#dae8fc", stroke_width=1)
    for i, line in enumerate(wrap(plan.title, draw, title)[:4]):
        draw.rectangle((75, 205+i*70, 930, 275+i*70), fill="#0b1526")
        draw.text((90, 210+i*70), line, font=title, fill="#ffffff", stroke_width=1)
    if scene.clip is not None:
        draw.rectangle((75, 510, 930, 562), fill="#f5c443")
        draw.text((90, 517), "AI 생성 장면 · 실제 현장 아님", font=small, fill="#111111")
    if not plan.shortform.captions and scene.caption:
        body = ImageFont.truetype(str(font_path), plan.font_size)
        lines = wrap(scene.caption, draw, body)
        if len(lines) > 4:
            raise ValueError("기존 자막이 너무 깁니다.")
        for i, line in enumerate(lines):
            draw.rectangle((75, plan.subtitle_y+i*65, 960, plan.subtitle_y+(i+1)*65), fill="#0b1526")
            draw.text((90, plan.subtitle_y+i*65), line, font=body, fill="#ffffff")
    image.save(target, format="PNG")
