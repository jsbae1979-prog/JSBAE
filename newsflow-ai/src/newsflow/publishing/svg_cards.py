"""Render a small static SVG language to pixels; never run it in a browser.

No network, filesystem references, fonts from SVG, CSS, scripting, entities,
filters or embedded images. Unknown elements/attributes fail closed.
"""
import math
import re
from io import BytesIO

from defusedxml import ElementTree
from PIL import Image, ImageDraw, ImageFont

from newsflow.video.engine import font_path

from .service import PublishingError

DISCLOSURE = "AI 구성 그래픽 · 실제 현장 사진 아님"
NS = "http://www.w3.org/2000/svg"
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
PAINT = {"fill", "stroke", "stroke-width"}
SHAPES = {"rect", "circle", "ellipse", "polygon", "polyline", "line", "path"}
ATTRS = {
    "svg": {"width", "height", "viewBox"}, "g": PAINT,
    "rect": PAINT | {"x", "y", "width", "height", "rx"},
    "circle": PAINT | {"cx", "cy", "r"},
    "ellipse": PAINT | {"cx", "cy", "rx", "ry"},
    "line": PAINT | {"x1", "y1", "x2", "y2"},
    "polygon": PAINT | {"points"}, "polyline": PAINT | {"points"},
    "path": PAINT | {"d"},
    "text": {"id", "x", "y", "fill", "font-size", "text-anchor"},
    "tspan": {"x", "y"},
}


def number(value, low=0, high=1350):
    if not isinstance(value, str) or not re.fullmatch(NUMBER, value):
        raise ValueError
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError
    return value


def color(value):
    if value == "none":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError
    return value


def tag(element):
    name = element.tag
    if not isinstance(name, str):
        raise TypeError
    if name.startswith("{" + NS + "}"):
        name = name[len(NS) + 2:]
    if name not in ATTRS or not set(element.attrib) <= ATTRS[name]:
        raise ValueError
    return name


def point_list(value):
    values = re.findall(NUMBER, value)
    if re.sub(NUMBER, "", value).strip(" ,\t\r\n") or not 4 <= len(values) <= 512 or len(values) % 2:
        raise ValueError
    points = [(number(x, high=1080), number(y)) for x, y in zip(values[::2], values[1::2], strict=True)]
    return points


def paths(value):
    """Absolute M/L/H/V/C/Q/Z with bounded, deterministic curve subdivision."""
    tokens = re.findall(r"[MLHVCQZ]|" + NUMBER, value)
    if re.sub(r"[MLHVCQZ]|" + NUMBER, "", value).strip(" ,\t\r\n") or len(tokens) > 1600:
        raise ValueError
    result, points, current, index = [], [], None, 0
    sizes = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4, "Z": 0}
    while index < len(tokens):
        command = tokens[index]
        index += 1
        if command not in sizes or index + sizes[command] > len(tokens):
            raise ValueError
        args = [number(v) for v in tokens[index:index + sizes[command]]]
        index += sizes[command]
        if command == "M":
            if points:
                result.append((points, False))
            current = (args[0], args[1])
            points = [current]
        elif current is None:
            raise ValueError
        elif command == "Z":
            if len(points) < 3:
                raise ValueError
            result.append((points, True))
            points, current = [], None
        elif command in {"C", "Q"}:
            origin = current
            controls = list(zip(args[::2], args[1::2], strict=True))
            for step in range(1, 17):
                t, u = step / 16, 1 - step / 16
                if command == "C":
                    a, b, end = controls
                    point = tuple(u**3 * origin[j] + 3*u*u*t*a[j] + 3*u*t*t*b[j] + t**3*end[j]
                                  for j in (0, 1))
                else:
                    a, end = controls
                    point = tuple(u*u*origin[j] + 2*u*t*a[j] + t*t*end[j] for j in (0, 1))
                points.append(point)
            current = controls[-1]
        else:
            current = ((args[0], args[1]) if command == "L" else
                       (args[0], current[1]) if command == "H" else (current[0], args[0]))
            points.append(current)
        if any(not 0 <= x <= 1080 or not 0 <= y <= 1350 for x, y in points):
            raise ValueError
    if points:
        result.append((points, False))
    if not result or sum(len(p) for p, _ in result) > 1200:
        raise ValueError
    return result


def compact(value):
    return re.sub(r"\s+", "", value)


def contrast(a, b):
    def luminance(rgb):
        values = [v / 255 for v in rgb]
        return sum(weight * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055)**2.4)
                   for weight, v in zip((.2126, .7152, .0722), values, strict=True))
    x, y = luminance(a), luminance(b)
    return (max(x, y) + .05) / (min(x, y) + .05)


def render_svg(svg, *, title, body, publisher):
    """Raster only output. Validate again for every preview/export of saved data."""
    try:
        return _render(svg, title=title, body=body, publisher=publisher)
    except Exception:  # noqa: BLE001 - SVG/raw response may contain secrets
        raise PublishingError("SVG 그림의 안전 형식·문구·가독성을 확인하지 못했습니다. 자동 재요청하지 않습니다.") from None


def _render(svg, *, title, body, publisher):
    if not isinstance(svg, str) or len(svg.encode("utf-8")) > 32_000:
        raise ValueError
    if any(marker in svg for marker in ("<!", "<?")):
        raise ValueError
    root = ElementTree.fromstring(svg, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if tag(root) != "svg" or root.attrib != {"width": "1080", "height": "1350", "viewBox": "0 0 1080 1350"}:
        raise ValueError
    canvas = Image.new("RGB", (1080, 1350), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    expected = {"title": title, "body": body, "source": "출처: " + publisher, "disclosure": DISCLOSURE}
    seen, boxes = set(), []
    count, text_started = 0, False

    def walk(element, inherited, depth=0):
        nonlocal count, text_started
        count += 1
        if count > 160 or depth > 8:
            raise ValueError
        name, a = tag(element), element.attrib
        paint = inherited | {k: v for k, v in a.items() if k in PAINT}
        fill, stroke = color(paint["fill"]), color(paint["stroke"])
        width = round(number(paint["stroke-width"], 1, 24))
        if name in {"svg", "g"}:
            if (element.text or "").strip():
                raise ValueError
            for child in element:
                if (child.tail or "").strip():
                    raise ValueError
                walk(child, paint, depth + 1)
            return
        if name == "text":
            text_started = True
            role = a.get("id")
            if role not in expected or role in seen or fill is None:
                raise ValueError
            size = round(number(a.get("font-size", ""), 36 if role == "title" else 26 if role == "body" else 22,
                                90 if role == "title" else 60))
            anchor = a.get("text-anchor", "start")
            if anchor not in {"start", "middle", "end"}:
                raise ValueError
            if compact("".join(element.itertext())) != compact(expected[role]):
                raise ValueError
            x, y = number(a.get("x", ""), high=1080), number(a.get("y", ""))
            if len(element):
                if (element.text or "").strip() or len(element) > 12:
                    raise ValueError
                lines = []
                for child in element:
                    count += 1
                    if tag(child) != "tspan" or len(child) or (child.tail or "").strip():
                        raise ValueError
                    lines.append((number(child.attrib.get("x", ""), high=1080),
                                  number(child.attrib.get("y", "")), child.text or ""))
            else:
                lines = [(x, y, element.text or "")]
            font = ImageFont.truetype(str(font_path()), size)
            for x, y, line in lines:
                if not line.strip():
                    raise ValueError
                anch = {"start": "ls", "middle": "ms", "end": "rs"}[anchor]
                box = draw.textbbox((x, y), line, font=font, anchor=anch)
                left, top, right, bottom = box
                if left < 24 or top < 24 or right > 1056 or bottom > 1326:
                    raise ValueError
                if any(left < b[2] and right > b[0] and top < b[3] and bottom > b[1] for b in boxes):
                    raise ValueError
                rgb = tuple(bytes.fromhex(fill[1:]))
                # Check across the entire text background before painting any glyphs.
                for px in range(math.floor(left), math.ceil(right), 12):
                    for py in range(math.floor(top), math.ceil(bottom), 8):
                        if contrast(rgb, canvas.getpixel((px, py))) < 3:
                            raise ValueError
                boxes.append(box)
                draw.text((x, y), line, font=font, fill=fill, anchor=anch)
            seen.add(role)
            return
        if name not in SHAPES or len(element) or (element.text or "").strip() or text_started:
            raise ValueError
        if fill is None and stroke is None:
            raise ValueError
        if name == "rect":
            x, y = number(a.get("x", "0"), high=1080), number(a.get("y", "0"))
            w, h = number(a.get("width", ""), .1, 1080), number(a.get("height", ""), .1)
            if x + w > 1080 or y + h > 1350:
                raise ValueError
            draw.rounded_rectangle((x, y, x+w, y+h), radius=number(a.get("rx", "0"), 0, min(w, h)/2),
                                   fill=fill, outline=stroke, width=width)
        elif name in {"circle", "ellipse"}:
            x, y = number(a.get("cx", ""), high=1080), number(a.get("cy", ""))
            rx = number(a.get("r" if name == "circle" else "rx", ""), .1)
            ry = rx if name == "circle" else number(a.get("ry", ""), .1)
            if x-rx < 0 or x+rx > 1080 or y-ry < 0 or y+ry > 1350:
                raise ValueError
            draw.ellipse((x-rx, y-ry, x+rx, y+ry), fill=fill, outline=stroke, width=width)
        else:
            if name == "path":
                segments = paths(a.get("d", ""))
                if fill is not None and len(segments) > 1:
                    raise ValueError  # Avoid silently changing compound-path/hole fill semantics.
            elif name == "line":
                segments = [([(number(a.get("x1", ""), high=1080), number(a.get("y1", ""))),
                              (number(a.get("x2", ""), high=1080), number(a.get("y2", "")))], False)]
            else:
                segments = [(point_list(a.get("points", "")), name == "polygon")]
                if name == "polygon" and len(segments[0][0]) < 3:
                    raise ValueError
            for points, closed in segments:
                if closed and fill:
                    draw.polygon(points, fill=fill)
                elif fill and name == "path":
                    raise ValueError  # No silently different SVG implicit-fill semantics.
                if stroke:
                    draw.line(points + ([points[0]] if closed else []), fill=stroke, width=width, joint="curve")
                elif not closed:
                    raise ValueError
    walk(root, {"fill": "#000000", "stroke": "none", "stroke-width": "1"})
    if seen != set(expected) or count > 160:
        raise ValueError
    output = BytesIO()
    canvas.save(output, format="JPEG", quality=90)
    return output.getvalue()
