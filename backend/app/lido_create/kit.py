"""The building blocks every layout is made from: palettes, font pairings, copy themes,
the placeholder photo pool, the `Element` model and the `Canvas` helper recipes draw on.

Everything is in canvas pixels on a 1080 x 1080 post. Colours and fonts are referred to
by *role* (`ink`, `accent`, `display`, ...), never by value, so one layout can be
re-dressed in any palette or font pairing and the checks in `check.py` still apply.
"""

from __future__ import annotations

import io
import json
import random
import urllib.request
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from app.lido_corpus.loader import DEFAULT_CORPUS_DIR
from app.lido_corpus.textfit import TextMeasure, font_file, too_wide_words, wrap
from app.lido_create.draw import DRAW_PRESETS
from app.lido_create.shapes import LINE_ENDS, SHAPES, frames

CORPUS_DIR = DEFAULT_CORPUS_DIR
# a local download cache (url -> [w, h, is_cutout] or null), not data: safe to delete
PHOTO_CACHE = CORPUS_DIR / ".photo_cache.v2.json"

W = H = 1080
M = 70  # side margin every left-aligned element starts at

ColorRole = Literal["bg", "ink", "accent", "on_accent", "soft"]
FontRole = Literal["display", "body", "button", "script"]
TextType = Literal["headline", "kicker", "body", "item", "cta", "badge", "caption",
                   "website", "phone", "email", "address"]
ClipShape = Literal["rect", "rounded", "circle", "arch", "hexagon", "diamond", "blob",
                    "leaf", "cutout"]
ShapeName = Literal[tuple(SHAPES)]  # type: ignore[valid-type]
FrameName = Literal[tuple(frames())]  # type: ignore[valid-type]
DrawPreset = Literal[tuple(DRAW_PRESETS)]  # type: ignore[valid-type]
LineEnd = Literal[LINE_ENDS]  # type: ignore[valid-type]
StrokeStyle = Literal["solid", "dashed", "dotted"]
TextEffect = Literal["shadow", "lift", "hollow"]

# --------------------------------------------------------------------------------------
# Palettes: bg (ROOT colour), ink (text on bg), accent (buttons/badges), on_accent (text
# on accent), soft (decoration only — never text). Each pairing meets WCAG contrast.
# --------------------------------------------------------------------------------------

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Palette:
    name: str
    bg: RGB
    ink: RGB
    accent: RGB
    on_accent: RGB
    soft: RGB

    def color(self, role: str) -> RGB:
        return getattr(self, role)


PALETTES = [
    Palette("navy-amber", (20, 33, 61), (255, 255, 255), (252, 163, 17), (20, 33, 61),
            (52, 72, 112)),
    Palette("cream-terracotta", (245, 239, 230), (62, 44, 35), (168, 86, 62),
            (255, 248, 240), (222, 186, 168)),
    Palette("white-teal", (255, 255, 255), (20, 40, 50), (0, 109, 119), (255, 255, 255),
            (255, 140, 66)),
    Palette("forest-mustard", (28, 61, 46), (255, 248, 235), (242, 183, 5), (28, 61, 46),
            (62, 104, 82)),
    Palette("plum-coral", (36, 22, 62), (255, 255, 255), (255, 107, 107), (36, 22, 62),
            (255, 222, 150)),
    Palette("black-lime", (18, 18, 18), (255, 255, 255), (198, 255, 0), (18, 18, 18),
            (58, 58, 58)),
    Palette("blush-berry", (252, 236, 236), (60, 30, 40), (176, 48, 82), (255, 255, 255),
            (240, 190, 200)),
    Palette("sky-cobalt", (232, 242, 250), (15, 40, 70), (0, 84, 166), (255, 255, 255),
            (160, 200, 235)),
    Palette("crimson-white", (190, 34, 46), (255, 255, 255), (255, 255, 255), (190, 34, 46),
            (226, 90, 90)),
    Palette("sand-charcoal", (237, 228, 212), (28, 28, 28), (28, 28, 28), (237, 228, 212),
            (206, 186, 154)),
    Palette("mint-forest", (238, 245, 236), (26, 58, 38), (38, 118, 58), (255, 255, 255),
            (186, 216, 176)),
    Palette("midnight-gold", (15, 23, 42), (248, 250, 252), (212, 175, 55), (15, 23, 42),
            (40, 55, 92)),
]

# --------------------------------------------------------------------------------------
# Fonts: real Google Fonts only (the fit checks measure with the actual file). Display
# faces are single heavy weights, so no "bold" style is ever needed — the pipeline
# measures each family with one font file.
# --------------------------------------------------------------------------------------

FONT_URLS = {
    "Anton": "https://fonts.gstatic.com/s/anton/v27/1Ptgg87LROyAm0K08i4gS7lu.ttf",
    "Archivo Black": "https://fonts.gstatic.com/s/archivoblack/v23/"
                     "HTxqL289NzCGg4MzN6KJ7eW6OYuP_x7yx3A.ttf",
    "Bebas Neue": "https://fonts.gstatic.com/s/bebasneue/v16/JTUSjIg69CK48gW7PXooxW4.ttf",
    "DM Serif Display": "https://fonts.gstatic.com/s/dmserifdisplay/v17/"
                        "-nFnOHM81r4j6k0gjAW3mujVU2B2K_c.ttf",
    "Playfair Display": "https://fonts.gstatic.com/s/playfairdisplay/v40/"
                        "nuFvD-vYSZviVYUb_rj3ij__anPXJzDwcbmjWBN2PKdFvUDQ.ttf",
    "Montserrat": "https://fonts.gstatic.com/s/montserrat/v31/"
                  "JTUHjIg1_i6t8kCHKm4532VJOt5-QNFgpCtr6Ew-Y3tcoqK5.ttf",
    "Oswald": "https://fonts.gstatic.com/s/oswald/v57/"
              "TK3_WkUHHAIjg75cFRf3bXL8LICs1_FvgUFoZAaRliE.ttf",
    "Great Vibes": "https://fonts.gstatic.com/s/greatvibes/v21/RWmMoKWR9v4ksMfaWd_JN-XC.ttf",
}


@dataclass(frozen=True)
class FontSet:
    name: str
    display: str
    display_upper: bool  # condensed poster faces read best in capitals, serifs don't
    display_lh: float
    body: str = "Montserrat"
    button: str = "Oswald"
    script: str = "Great Vibes"

    def family(self, role: str) -> str:
        return getattr(self, role)


FONT_SETS = [
    FontSet("condensed-poster", "Anton", True, 1.05),
    FontSet("heavy-grotesk", "Archivo Black", False, 1.1),
    FontSet("modern-serif", "DM Serif Display", False, 1.1),
    FontSet("editorial-serif", "Playfair Display", False, 1.15),
    FontSet("tall-caps", "Bebas Neue", True, 1.0),
]

# --------------------------------------------------------------------------------------
# Themes: placeholder copy + which corpus photos suit it. The copy is rewritten for every
# real brief; it only has to look right in the preview and let the metadata draft tell
# what the template is for.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    name: str
    keywords: tuple[str, ...]  # matched against the corpus templates' tags/names
    kicker: str
    headline: str
    body: str
    cta: str
    badge: str
    items: tuple[str, str, str]
    script: str = "Don't Miss Out"
    date: str = "Sat, 12 October · 7 PM"
    website: str = "www.yourwebsite.com"
    phone: str = "+123-456-7890"
    email: str = "hello@yourwebsite.com"
    address: str = "123 Anywhere St., Any City"
    price: str = "$29.99"


THEMES = [
    Theme("fashion", ("fashion",), "New Collection", "Summer Style Sale",
          "Fresh looks for every day, for a limited time only.", "Shop Now", "50% Off",
          ("New Arrivals", "Free Delivery", "Easy Returns"), script="Just Dropped"),
    Theme("interior", ("interior", "home decor", "furniture"), "Home & Living",
          "Designed for Living", "Thoughtful spaces, crafted around you.", "Book a Visit",
          "30% Off", ("Custom Furniture", "Space Planning", "Home Styling"),
          script="Welcome Home"),
    Theme("business", ("business", "corporate", "agency", "marketing", "finance", "loan"),
          "What We Offer", "Expert Business Solutions",
          "Strategies that help your business grow faster.", "Contact Us", "Free Consult",
          ("Strategy & Planning", "Marketing Support", "Financial Advice"),
          script="Let's Grow Together"),
    Theme("food", ("food", "restaurant", "cafe", "juice", "drinks"), "Chef's Special",
          "Taste the Season", "Fresh ingredients and bold flavours, made daily.",
          "Order Now", "20% Off", ("Fresh Ingredients", "Fast Delivery", "Family Meals"),
          script="Made with Love"),
    Theme("event", ("events", "announcement", "opening"), "Save the Date",
          "Grand Opening Night", "Join us for an evening of food, music and friends.",
          "Reserve a Spot", "Free Entry", ("Live Music", "Welcome Drinks", "Special Guests"),
          script="You're Invited"),
    Theme("beauty", ("salon", "beauty", "hair"), "Beauty Studio", "Glow Up This Season",
          "Treat yourself to expert care and a fresh new look.", "Book Now", "25% Off",
          ("Hair Styling", "Skin Care", "Nail Art"), script="Feel Beautiful"),
    Theme("education", ("education", "college", "admissions"), "Admissions Open",
          "Learn Without Limits", "Courses built to shape the career you want.",
          "Apply Now", "Enroll Today", ("Expert Teachers", "Flexible Classes",
                                         "Career Support"), script="Start Your Journey"),
    Theme("wellness", ("wellness", "counseling", "fitness", "mental health"),
          "Wellness Program", "Feel Your Best", "Personal care that helps you live better.",
          "Join Today", "First Week Free", ("Personal Coaching", "Group Sessions",
                                            "Nutrition Plans"), script="Start Today"),
]

THEMES_BY_NAME = {t.name: t for t in THEMES}
PALETTES_BY_NAME = {p.name: p for p in PALETTES}
FONT_SETS_BY_NAME = {f.name: f for f in FONT_SETS}

LOGOS = {
    "white": "https://assets.quickhub.ai/qh-assets/logo_white.png",
    "black": "https://assets.quickhub.ai/qh-assets/logo_black.png",
}
LOGO_RATIO = 103 / 127  # both logo files are 127 x 103

# --------------------------------------------------------------------------------------
# The element model — what recipes and the LLM both produce, before it becomes Lido JSON.
# --------------------------------------------------------------------------------------


class Gradient(BaseModel):
    """A Lido gradient fill: two stops. `start` defaults to the element's own colour
    (the canvas colour for a background); no `end` means the start colour fading to
    transparent. Angle is CSS-style: 0 = towards the top, 90 = right, 180 = bottom."""
    style: Literal["linear", "radial"]
    angle: float | None = None
    start: ColorRole | None = None
    end: ColorRole | None = None
    start_at: float | None = None  # percent along the gradient, 0-100
    end_at: float | None = None


class Element(BaseModel):
    kind: Literal["shape", "photo", "logo", "text", "dots", "line", "draw", "list"]
    x: float
    y: float
    w: float  # line: its length
    h: float  # line: its thickness
    color: ColorRole | None = None
    shape: ShapeName | None = None
    gradient: Gradient | None = None  # shapes: fill with a gradient instead of flat colour
    radius: float | None = None  # corner radius in px (rectangles, "rounded" photo clips)
    opacity: float | None = None
    rotate: float | None = None  # shapes: degrees clockwise, around the shape's centre
    stroke: ColorRole | None = None  # shapes: outline colour (fill still drawn)
    stroke_width: float | None = None  # shapes: outline width in px; draw: marker width
    stroke_style: StrokeStyle | None = None  # shape outline / line style
    line_start: LineEnd | None = None  # line: end markers
    line_end: LineEnd | None = None
    draw: DrawPreset | None = None  # draw: which hand-drawn stroke fills x/y/w/h
    items: list[str] | None = None  # list: every item, word for word (lists.py lays it out)
    columns: int | None = None  # list: 1-3, or null = automatic from the item count
    bullet: Literal["dot", "ring", "bar", "check", "number", "none"] | None = None
    divider: Literal["line", "dotted", "none"] | None = None  # list: between columns/rows
    rows: int | None = None  # dots: a rows x cols grid of dots filling x/y/w/h
    cols: int | None = None
    dot: float | None = None  # dots: diameter of each dot in px
    clip: ClipShape | None = None  # photos; "cutout" = transparent subject, no crop
    frame: FrameName | None = None  # photos: a Lido frame outline (keeps its aspect)
    focus: float | None = None  # 0 = keep the top of the photo, 0.5 = centre
    text: str | None = None
    text_type: TextType | None = None
    font: FontRole | None = None
    size: float | None = None
    align: Literal["left", "center", "right"] | None = None
    max_lines: int | None = None
    uppercase: bool | None = None
    letter_spacing: float | None = None  # em
    line_height: float | None = None
    effect: TextEffect | None = None  # text: shadow, lift (soft glow) or hollow (outline)
    effect_color: ColorRole | None = None  # text: the shadow's colour
    bleed: bool | None = None  # allowed to run off the canvas (decoration or photo)
    subject: str | None = None  # photos: what the picture should show (for generation)


class Design(BaseModel):
    recipe: str
    theme: str
    palette: str
    fonts: str
    mirrored: bool = False
    background: Gradient | None = None  # a gradient canvas instead of the flat bg colour
    elements: list[Element]


# --------------------------------------------------------------------------------------
# Placeholder photos: the ones the existing corpus templates already use (hosted on
# assets.quickhub.ai), tagged with their template's tags. The pipeline regenerates every
# photo slot per brief, so these only need to look right in the preview.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Photo:
    url: str
    w: int
    h: int
    tags: tuple[str, ...]
    cutout: bool = False  # a transparent subject (no backdrop) rather than a photo


def _usable(data: bytes) -> tuple[int, int, bool] | None:
    """(width, height, is_cutout), or None for anything that is no use as a photo."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:  # noqa: BLE001 — anything PIL can't open is simply skipped
        return None
    if min(im.size) < 300:  # logos and icons
        return None
    cutout = False
    if im.mode in ("RGBA", "LA", "P"):
        alpha = im.convert("RGBA").getchannel("A").resize((64, 64))
        clear = sum(1 for a in alpha.getdata() if a < 20) / (64 * 64)
        cutout = clear > 0.1  # a real transparent backdrop, not a stray soft edge
        if not cutout and alpha.getextrema()[0] < 250:
            return None  # partly see-through photo: neither a clean photo nor a cutout
    return im.size[0], im.size[1], cutout


def photo_pool() -> list[Photo]:
    cache = json.loads(PHOTO_CACHE.read_text()) if PHOTO_CACHE.is_file() else {}
    pool, changed = {}, False
    for path in sorted(CORPUS_DIR.glob("template_*.json")):
        root = json.loads(path.read_text())[0]
        meta = root.get("meta") or {}
        tags = tuple(t.lower() for t in (meta.get("tags") or []))
        tags += tuple((meta.get("name") or "").lower().split())
        for layer in root["layers"].values():
            if layer["type"]["resolvedName"] not in ("FrameLayer", "ImageLayer"):
                continue
            if layer["type"].get("type") == "logo" or "clipPath" not in layer["props"]:
                continue
            url = (layer["props"].get("image") or {}).get("url")
            if not url or url in pool:
                continue
            if url not in cache:
                # The CDN answers urllib's default user agent with 403.
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                try:
                    with urllib.request.urlopen(req, timeout=20) as r:
                        size = _usable(r.read())
                except OSError:
                    continue
                cache[url], changed = (list(size) if size else None), True
            if cache[url]:
                prior = pool.get(url)
                w, h, cutout = cache[url]
                pool[url] = Photo(url, w, h, tags + (prior.tags if prior else ()), cutout)
    if changed:
        PHOTO_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PHOTO_CACHE.write_text(json.dumps(cache, indent=1))
    return list(pool.values())


# --------------------------------------------------------------------------------------
# Canvas: what a recipe draws on. Text helpers measure with the real font, so every box
# is sized exactly and headlines shrink until they fit their line budget.
# --------------------------------------------------------------------------------------


@dataclass
class Variant:
    palette: Palette
    fonts: FontSet
    theme: Theme
    rng: random.Random
    photos: list[Photo]
    used_photos: set[str] = field(default_factory=set)


def measure(fonts: FontSet, font_role: str, size: float, upper: bool,
            ls: float) -> TextMeasure:
    family = fonts.family(font_role)
    return TextMeasure(font_file(family, (FONT_URLS[family],)), size,
                       "uppercase" if upper else None, ls)


def line_count(fonts: FontSet, e: Element) -> tuple[list[str], list[str]]:
    """(wrapped lines, words too wide for the box) for a text element."""
    m = measure(fonts, e.font or "body", e.size or 16, bool(e.uppercase),
                e.letter_spacing or 0)
    return wrap(e.text or "", m, e.w), too_wide_words(e.text or "", m, e.w)


class Canvas:
    def __init__(self, v: Variant):
        self.v = v
        self.els: list[Element] = []
        self.background: Gradient | None = None  # a gradient canvas, when a recipe sets one

    # -- text --------------------------------------------------------------------------

    def fits(self, text: str, font: str, size: float, w: float, max_lines: int,
             upper: bool, ls: float) -> bool:
        m = measure(self.v.fonts, font, size, upper, ls)
        return not too_wide_words(text, m, w) and len(wrap(text, m, w)) <= max_lines

    def fit(self, text: str, font: str, w: float, max_lines: int, start: float,
            smallest: float, upper: bool = False, ls: float = 0.0) -> float:
        size = start
        while size > smallest and not self.fits(text, font, size, w, max_lines, upper, ls):
            size -= 2
        return size

    def text(self, text: str, text_type: str, *, x: float, y: float, w: float,
             font: str = "body", size: float = 26, color: str = "ink", align: str = "left",
             max_lines: int = 1, upper: bool = False, ls: float = 0.0,
             lh: float | None = None, fit_from: float | None = None,
             smallest: float | None = None, effect: str | None = None,
             effect_color: str | None = None) -> Element:
        """A text box whose height is exactly its wrapped lines. `fit_from` shrinks the
        size from that value until the copy fits `max_lines`."""
        if lh is None:
            lh = self.v.fonts.display_lh if font == "display" else (
                1.2 if font in ("button", "script") else 1.4)
        if fit_from is not None:
            size = self.fit(text, font, w, max_lines, fit_from, smallest or fit_from * 0.6,
                            upper, ls)
        e = Element(kind="text", x=x, y=y, w=w, h=0, text=text, text_type=text_type,
                    font=font, size=size, color=color, align=align, max_lines=max_lines,
                    uppercase=upper, letter_spacing=ls, line_height=lh, effect=effect,
                    effect_color=effect_color)
        lines, _ = line_count(self.v.fonts, e)
        e.h = round(len(lines) * size * lh, 2)
        self.els.append(e)
        return e

    def headline(self, text: str, *, x: float, y: float, w: float, max_lines: int,
                 start: float, smallest: float, color: str = "ink",
                 align: str = "left") -> Element:
        f = self.v.fonts
        return self.text(text, "headline", x=x, y=y, w=w, font="display", color=color,
                         align=align, max_lines=max_lines, upper=f.display_upper,
                         fit_from=start, smallest=smallest)

    def kicker(self, text: str, *, x: float, y: float, w: float, color: str = "accent",
               align: str = "left", size: float = 24) -> Element:
        return self.text(text, "kicker", x=x, y=y, w=w, size=size, color=color, align=align,
                         upper=True, ls=0.2, fit_from=size, smallest=18)

    def button(self, text: str, *, x: float, y: float, h: float = 78,
               w: float | None = None, center_x: float | None = None,
               fill: str = "accent", ink: str = "on_accent", radius: float | None = None,
               text_type: str = "cta") -> tuple[Element, Element]:
        """A pill with its label centred on it; width follows the label unless given."""
        size = 30
        if w is None:
            m = measure(self.v.fonts, "button", size, True, 0.08)
            w = max(240.0, round(m.width(text) + 110))
        if center_x is not None:
            x = center_x - w / 2
        pill = self.shape(x, y, w, h, fill, radius=h / 2 if radius is None else radius)
        label = self.text(text, text_type, x=x, y=0, w=w, font="button", size=size,
                          color=ink, align="center", upper=True, ls=0.08,
                          fit_from=size, smallest=20)
        label.y = round(y + (h - label.h) / 2, 2)
        return pill, label

    def contact(self, kind: str, *, x: float, y: float, w: float, color: str = "ink",
                align: str = "left", size: float = 24) -> Element:
        return self.text(getattr(self.v.theme, kind), kind, x=x, y=y, w=w, size=size,
                         color=color, align=align, fit_from=size, smallest=18)

    # -- shapes, photos, logo ----------------------------------------------------------

    def shape(self, x: float, y: float, w: float, h: float, color: str, *,
              circle: bool = False, radius: float = 0, opacity: float | None = None,
              bleed: bool = False, rotate: float = 0, stroke: str | None = None,
              stroke_width: float | None = None, kind: str | None = None,
              gradient: Gradient | None = None,
              stroke_style: str | None = None) -> Element:
        """`kind` is any Lido shape name (shapes.SHAPES); `circle=True` is shorthand."""
        e = Element(kind="shape", x=x, y=y, w=w, h=h, color=color,
                    shape=kind or ("circle" if circle else "rectangle"), radius=radius or None,
                    opacity=opacity, bleed=bleed or None, rotate=rotate or None,
                    stroke=stroke, stroke_width=stroke_width if stroke else None,
                    stroke_style=stroke_style if stroke else None, gradient=gradient)
        self.els.append(e)
        return e

    def line(self, x: float, y: float, length: float, *, color: str = "accent",
             thickness: float = 4, rotate: float = 0, style: str = "solid",
             start: str = "none", end: str = "none") -> Element:
        """A Lido line from (x, y) rightwards, rotated around its middle."""
        e = Element(kind="line", x=x, y=y - thickness / 2, w=length, h=thickness,
                    color=color, rotate=rotate or None, stroke_style=style,
                    line_start=start, line_end=end)
        self.els.append(e)
        return e

    def draw(self, preset: str, x: float, y: float, w: float, h: float, *,
             color: str = "accent", width: float = 6, opacity: float | None = None) -> Element:
        """A hand-drawn marker stroke (draw.DRAW_PRESETS) filling the box."""
        e = Element(kind="draw", x=x, y=y, w=w, h=h, color=color, draw=preset,
                    stroke_width=width, opacity=opacity)
        self.els.append(e)
        return e

    def dots(self, x: float, y: float, cols: int, rows: int, *, gap: float = 24,
             dot: float = 9, color: str = "accent", opacity: float | None = None) -> None:
        """A dot-grid texture: `cols` x `rows` small circles, `gap` apart."""
        for r in range(rows):
            for col in range(cols):
                self.shape(x + col * gap, y + r * gap, dot, dot, color, circle=True,
                           opacity=opacity)

    def bullet(self, x: float, y: float, style: str = "ring", size: float = 26,
               color: str = "accent", inner: str = "bg") -> None:
        """A list marker: a solid dot, a ring (dot with a hole) or a short bar."""
        if style == "bar":
            self.shape(x, y + size / 2 - 3, size, 6, color, radius=3)
            return
        self.shape(x, y, size, size, color, circle=True)
        if style == "ring":
            hole = size * 0.46
            self.shape(x + (size - hole) / 2, y + (size - hole) / 2, hole, hole, inner,
                       circle=True)

    def contact_block(self, kind: str, label: str, *, x: float, y: float, w: float,
                      align: str = "left", color: str = "ink",
                      label_color: str = "accent") -> tuple[Element, Element]:
        """A small caps label ("CALL US") above the contact value, the way pro
        templates set phone/website lines."""
        cap = self.text(label, "caption", x=x, y=y, w=w, size=18, color=label_color,
                        align=align, upper=True, ls=0.15, fit_from=18, smallest=14)
        value = self.text(getattr(self.v.theme, kind), kind, x=x, y=cap.y + cap.h + 2, w=w,
                          size=26, color=color, align=align, fit_from=26, smallest=18)
        return cap, value

    def photo(self, x: float, y: float, w: float, h: float, *, clip: str = "rect",
              radius: float = 0, focus: float = 0.4, bleed: bool = False,
              frame: str | None = None) -> Element:
        """clip="cutout" is a transparent subject that floats over the design unframed.
        `frame` is a Lido frame outline (shapes.frames()); it keeps its own aspect, so h
        is recomputed from w."""
        if frame:
            h = round(w / frames()[frame].aspect, 2)
        e = Element(kind="photo", x=x, y=y, w=w, h=h, clip=None if frame else clip,
                    radius=radius or None, focus=focus, bleed=bleed or None, frame=frame)
        self.els.append(e)
        return e

    def logo(self, x: float, y: float, w: float = 110) -> Element:
        e = Element(kind="logo", x=x, y=y, w=w, h=round(w * LOGO_RATIO, 2))
        self.els.append(e)
        return e


# Corpus tags overlap ("business" is on the food flyer, "services" on the salon), so each
# photo belongs to exactly one theme: the first match, most specific themes first.
THEME_PRIORITY = ("fashion", "interior", "food", "beauty", "education", "wellness",
                  "business", "event")


def photo_theme(photo: Photo) -> str | None:
    for name in THEME_PRIORITY:
        if any(k in t for k in THEMES_BY_NAME[name].keywords for t in photo.tags):
            return name
    return None


def on_theme(theme: Theme, photo: Photo) -> bool:
    if photo_theme(photo) == theme.name:
        return True
    # "event" is an occasion, not a subject: any photo from an events/opening template fits
    return theme.name == "event" and any(k in t for k in theme.keywords for t in photo.tags)


def theme_photo_count(theme: Theme, photos: list[Photo]) -> int:
    """On-theme framed photos (cutouts are few, so any cutout stands in for any theme)."""
    return sum(on_theme(theme, p) for p in photos if not p.cutout)


def pick_photo(v: Variant, w: float, h: float, cutout: bool = False) -> Photo:
    """A theme photo whose shape suits the frame, preferring ones not used yet; for a
    cutout frame, a transparent subject."""
    if cutout:
        # a real cutout when one suits the theme; otherwise an on-theme photo (drawn
        # blob-cropped) — the corpus has almost no cutouts to stand in with
        pool = ([p for p in v.photos if p.cutout and on_theme(v.theme, p)]
                or [p for p in v.photos if not p.cutout] or v.photos)
    else:
        pool = [p for p in v.photos if not p.cutout] or v.photos

    def score(p: Photo) -> tuple:
        aspect_gap = abs((p.w / p.h) - (w / h))
        return (p.url in v.used_photos, not on_theme(v.theme, p), round(aspect_gap, 1),
                v.rng.random())

    best = min(pool, key=score)
    v.used_photos.add(best.url)
    return best
