"""Bounded declarative drawing data, never SVG/HTML, paths, URLs or executable code."""
from typing import Literal

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=1000)


class DrawingElement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["rectangle", "ellipse", "polygon", "line", "symbol"]
    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=1000)
    width: int = Field(ge=20, le=1000)
    height: int = Field(ge=20, le=1000)
    color: Literal["accent", "white", "muted", "ink", "warm"]
    symbol: Literal["none", "house", "shield", "city", "moon", "speech", "book", "chip", "globe"]
    points: list[Point] = Field(max_length=8)
    line_width: int = Field(ge=1, le=12)

    @model_validator(mode="after")
    def bounded(self):
        if self.x + self.width > 1000 or self.y + self.height > 1000:
            raise ValueError("element outside illustration region")
        if self.kind == "symbol":
            if self.symbol == "none" or self.points:
                raise ValueError("symbol requires an allowlisted glyph, no points")
        elif self.symbol != "none":
            raise ValueError("symbol is not a shape parameter")
        if self.kind in {"polygon", "line"}:
            if len(self.points) < (3 if self.kind == "polygon" else 2):
                raise ValueError("not enough points")
        elif self.points:
            raise ValueError("unexpected points")
        return self


class CardDesign(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[2]
    layout: Literal["visual_first", "headline_first"]
    accent: Literal["mint", "lavender", "amber", "blue"]
    elements: list[DrawingElement] = Field(min_length=1, max_length=8)


ACCENTS = {"mint": "#75dec6", "lavender": "#b9afff", "amber": "#f5be81", "blue": "#82c8ff"}


def glyph(name, color):
    """Fixed original symbolic glyphs; the model chooses their placement and combination."""
    image = Image.new("RGBA", (200, 200))
    d = ImageDraw.Draw(image)
    ink = "#15273d"
    if name == "house":
        d.rounded_rectangle((30, 85, 170, 185), 8, fill=color)
        d.polygon([(10, 88), (100, 16), (190, 88)], fill=color)
        d.rectangle((82, 126, 118, 185), fill=ink)
        for x in (46, 134):
            d.rounded_rectangle((x, 106, x + 20, 132), 3, fill=ink)
    elif name == "shield":
        d.polygon([(100, 12), (182, 44), (171, 117), (143, 161), (100, 190),
                   (57, 161), (29, 117), (18, 44)], fill=color)
        d.line([(59, 94), (91, 125), (145, 69)], fill=ink, width=13)
    elif name == "city":
        for x, y, w in ((12, 85, 46), (69, 22, 52), (133, 63, 55)):
            d.rectangle((x, y, x + w, 185), fill=color)
            for wx in range(x + 11, x + w - 4, 18):
                for wy in range(y + 14, 175, 25):
                    d.rectangle((wx, wy, wx + 6, wy + 10), fill=ink)
    elif name == "moon":
        d.ellipse((20, 20, 180, 180), fill=color)
        d.ellipse((68, 0, 199, 139), fill=(0, 0, 0, 0))
    elif name == "speech":
        d.rounded_rectangle((15, 22, 185, 147), 22, fill=color)
        d.polygon([(45, 130), (45, 187), (100, 142)], fill=color)
        for y, w in ((57, 105), (87, 84), (117, 52)):
            d.line((43, y, 43 + w, y), fill=ink, width=7)
    elif name == "book":
        d.polygon([(15, 35), (95, 53), (95, 181), (15, 161)], fill=color)
        d.polygon([(105, 53), (185, 35), (185, 161), (105, 181)], fill=color)
        for y in (78, 110, 142):
            d.line((31, y, 78, y + 9), fill=ink, width=5)
            d.line((122, y + 9, 169, y), fill=ink, width=5)
    elif name == "chip":
        d.rounded_rectangle((42, 42, 158, 158), 15, fill=color)
        d.rectangle((71, 71, 129, 129), outline=ink, width=7)
        for xy in (61, 100, 139):
            d.line((10, xy, 42, xy), fill=color, width=8)
            d.line((158, xy, 190, xy), fill=color, width=8)
            d.line((xy, 10, xy, 42), fill=color, width=8)
            d.line((xy, 158, xy, 190), fill=color, width=8)
    elif name == "globe":
        d.ellipse((15, 15, 185, 185), outline=color, width=8)
        d.ellipse((63, 15, 137, 185), outline=color, width=5)
        d.line((15, 100, 185, 100), fill=color, width=5)
    else:
        raise ValueError("unknown glyph")
    return image


def designed_panel(design):
    """Revalidate on every rendering boundary, including saved JSON preview/export."""
    spec = CardDesign.model_validate(design)
    colors = {"accent": ACCENTS[spec.accent], "white": "#edf5ff", "muted": "#526b86",
              "ink": "#15273d", "warm": "#f4d596"}
    panel = Image.new("RGB", (948, 420), "#20374c")
    d = ImageDraw.Draw(panel)
    for e in spec.elements:
        x, y = round(e.x * 948 / 1000), round(e.y * 420 / 1000)
        w, h = round(e.width * 948 / 1000), round(e.height * 420 / 1000)
        color = colors[e.color]
        box = (x, y, x + w - 1, y + h - 1)
        if e.kind == "symbol":
            sprite = glyph(e.symbol, color).resize((w, h), Image.Resampling.LANCZOS)
            panel.paste(sprite, (x, y), sprite)
        elif e.kind == "rectangle":
            d.rounded_rectangle(box, radius=min(18, w // 4, h // 4), fill=color)
        elif e.kind == "ellipse":
            d.ellipse(box, fill=color)
        else:
            points = [(x + round(p.x * (w - 1) / 1000), y + round(p.y * (h - 1) / 1000))
                      for p in e.points]
            if e.kind == "polygon":
                d.polygon(points, fill=color)
            else:
                d.line(points, fill=color, width=e.line_width, joint="curve")
    return panel, spec
