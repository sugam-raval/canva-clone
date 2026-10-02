"""The list block: any number of items (features, services, steps, menu entries) laid
out by code, so none is ever dropped and the columns always line up.

The designer writes ONE `list` element — the area (x/y/w/h), every item word for word,
and the style (bullet, divider, size, colour) — and `expand_list` turns it into real
elements: one text per item, a bullet beside each, dividers between columns (or rows).
Bullets are markers like real social-post templates use — dot, dash, ring, square,
diamond, triangle, check, check_circle, arrow_circle, plus, number, and fancier
two-part ones (check_ring, check_square, arrow_square, plus_circle, target,
diamond_outline, number_ring, glow_dot) — sized from the text and centred on each
item's first line (`bullet_marks`).

    1-4 items -> 1 column      5-6 -> 2 columns of 3      7-9 -> 3 columns of 3
                                                          (2 columns when the area is
                                                           too narrow for 3)

The font shrinks step by step until every item fits its column in at most two lines and
the whole block fits the area's height.
"""

from __future__ import annotations

import math

from app.lido_corpus.textfit import too_wide_words, wrap
from app.lido_create.kit import Element, Variant, measure

MAX_ITEMS = 9
SMALLEST = 15  # px: below this, list text stops being readable on a post
GAP = 48  # px between columns (a divider sits in the middle of it)


def columns_for(n: int, width: float) -> int:
    if n <= 4:
        return 1
    if n <= 6:
        return 2
    return 3 if width >= 720 else 2


def _bullet_colors(e: Element) -> tuple[str, str]:
    """(bullet colour, hole/number colour), readable on whatever the list sits on: a
    list in on_accent text is on an accent panel, so its bullets are on_accent too."""
    if e.stroke:
        return e.stroke, "accent" if e.stroke == "on_accent" else "bg"
    if e.color == "on_accent":
        return "on_accent", "accent"
    if e.color == "bg":
        return "bg", "ink"
    return "accent", "bg"


# Each marker's size as a share of the font size: (width, height). Small, solid and
# consistent — a bullet supports the text, it doesn't compete with it.
MARKS = {"dot": (0.34, 0.34), "dash": (0.62, 0.13), "ring": (0.44, 0.44),
         "square": (0.36, 0.36), "diamond": (0.46, 0.46), "triangle": (0.4, 0.44),
         "check": (0.62, 0.5), "check_circle": (0.82, 0.82), "arrow_circle": (0.82, 0.82),
         "plus": (0.44, 0.44), "number": (1.15, 1.15),
         "check_ring": (0.82, 0.82), "check_square": (0.78, 0.78),
         "arrow_square": (0.78, 0.78), "plus_circle": (0.78, 0.78), "target": (0.56, 0.56),
         "diamond_outline": (0.6, 0.6), "number_ring": (1.15, 1.15), "glow_dot": (0.62, 0.62)}


def marker_width(bullet: str, size: float) -> float:
    if bullet == "none":
        return 0.0
    return round(MARKS.get("dash" if bullet == "bar" else bullet, MARKS["dot"])[0] * size, 1)


def bullet_marks(bullet: str, x: float, line_y: float, line_h: float, size: float,
                 mark: str, hole: str, number: int) -> list[Element]:
    """The elements of one bullet, its left edge at x, centred on the line that starts
    at line_y and is line_h tall."""
    kind = "dash" if bullet == "bar" else bullet
    if kind == "none":
        return []
    mw, mh = (k * size for k in MARKS.get(kind, MARKS["dot"]))
    y = line_y + (line_h - mh) / 2
    if kind == "dot":
        return [Element(kind="shape", shape="circle", x=x, y=y, w=mw, h=mh, color=mark)]
    if kind == "dash":
        return [Element(kind="shape", shape="rectangle", x=x, y=y, w=mw, h=mh, color=mark,
                        radius=mh / 2)]
    if kind == "ring":
        k = mw * 0.5  # the hole, in the colour the list sits on
        return [Element(kind="shape", shape="circle", x=x, y=y, w=mw, h=mh, color=mark),
                Element(kind="shape", shape="circle", x=x + (mw - k) / 2, y=y + (mh - k) / 2,
                        w=k, h=k, color=hole)]
    if kind == "square":
        return [Element(kind="shape", shape="rectangle", x=x, y=y, w=mw, h=mh, color=mark,
                        radius=mw * 0.18)]
    if kind == "diamond":
        return [Element(kind="shape", shape="rhombus", x=x, y=y, w=mw, h=mh, color=mark)]
    if kind == "triangle":  # Lido's triangle points up: turned a quarter, it points right
        return [Element(kind="shape", shape="triangle", x=x + (mw - mh) / 2,
                        y=y + (mh - mw) / 2, w=mh, h=mw, color=mark, rotate=90)]
    if kind == "plus":
        return [Element(kind="shape", shape="cross", x=x, y=y, w=mw, h=mh, color=mark)]
    if kind == "check":
        return [Element(kind="draw", draw="check", x=x, y=y, w=mw, h=mh, color=mark,
                        stroke_width=round(max(3.0, size * 0.13), 1))]
    line = round(max(1.6, size * 0.075), 1)  # outline weight for the outlined markers

    def outline(shape: str, ox: float, oy: float, ow: float, oh: float) -> Element:
        """An outlined shape: filled with what the list sits on, edged in the mark."""
        return Element(kind="shape", shape=shape, x=ox, y=oy, w=ow, h=oh, color=hole,
                       stroke=mark, stroke_width=line)

    def glyph(name: str, colour: str, share: float = 0.6) -> Element:
        g = mw * share
        return Element(kind="draw", doodle=name, x=x + (mw - g) / 2, y=y + (mh - g) / 2,
                       w=g, h=g, color=colour, stroke_width=round(max(2.0, size * 0.09), 1))

    if kind == "check_ring":
        return [outline("circle", x, y, mw, mh), glyph("tick", mark, 0.58)]
    if kind in ("check_square", "arrow_square"):
        return [Element(kind="shape", shape="rectangle", x=x, y=y, w=mw, h=mh, color=mark,
                        radius=mw * 0.24),
                glyph("tick" if kind == "check_square" else "chevron", hole)]
    if kind == "plus_circle":
        k = mw * 0.46
        return [Element(kind="shape", shape="circle", x=x, y=y, w=mw, h=mh, color=mark),
                Element(kind="shape", shape="cross", x=x + (mw - k) / 2, y=y + (mh - k) / 2,
                        w=k, h=k, color=hole)]
    if kind == "target":
        k = mw * 0.42
        return [outline("circle", x, y, mw, mh),
                Element(kind="shape", shape="circle", x=x + (mw - k) / 2, y=y + (mh - k) / 2,
                        w=k, h=k, color=mark)]
    if kind == "diamond_outline":
        k = mw * 0.4
        return [outline("rhombus", x, y, mw, mh),
                Element(kind="shape", shape="rhombus", x=x + (mw - k) / 2, y=y + (mh - k) / 2,
                        w=k, h=k, color=mark)]
    if kind == "glow_dot":
        k = mw * 0.5
        return [Element(kind="shape", shape="circle", x=x, y=y, w=mw, h=mh, color=mark,
                        opacity=0.25),
                Element(kind="shape", shape="circle", x=x + (mw - k) / 2, y=y + (mh - k) / 2,
                        w=k, h=k, color=mark)]
    if kind == "number_ring":
        return [outline("circle", x, y, mw, mh),
                Element(kind="text", text_type="caption", text=str(number), font="button",
                        size=round(size * 0.6), color=mark, align="center", x=x,
                        y=y + mh * 0.18, w=mw, h=0, max_lines=1, line_height=1.2)]
    if kind in ("check_circle", "arrow_circle"):
        glyph = mw * 0.62
        return [Element(kind="shape", shape="circle", x=x, y=y, w=mw, h=mh, color=mark),
                Element(kind="draw", doodle="tick" if kind == "check_circle" else "chevron",
                        x=x + (mw - glyph) / 2, y=y + (mh - glyph) / 2, w=glyph, h=glyph,
                        color=hole, stroke_width=round(max(2.0, size * 0.09), 1))]
    # number
    return [Element(kind="shape", shape="circle", x=x, y=y, w=mw, h=mh, color=mark),
            Element(kind="text", text_type="caption", text=str(number), font="button",
                    size=round(size * 0.62), color=hole, align="center", x=x,
                    y=y + mh * 0.17, w=mw, h=0, max_lines=1, line_height=1.2)]


def _fit(e: Element, v: Variant, items: list[str], cols: int, bullet: str):
    """The largest size (from the requested one down) at which every item fits."""
    font, lh = e.font or "body", e.line_height or 1.3
    per = math.ceil(len(items) / cols)
    col_w = (e.w - GAP * (cols - 1)) / cols
    size = float(e.size or 26)
    while True:
        bsz = marker_width(bullet, size)
        indent = 0 if bullet == "none" else bsz + max(10.0, size * 0.55)
        m = measure(v.fonts, font, size, bool(e.uppercase), e.letter_spacing or 0)
        text_w = col_w - indent
        heights, ok = [], text_w > 40
        for item in items:
            lines = wrap(item, m, text_w)
            ok = ok and len(lines) <= 2 and not too_wide_words(item, m, text_w)
            heights.append(len(lines) * size * lh)
        gap = size * 0.6
        tallest = max(sum(heights[c * per:(c + 1) * per])
                      + gap * (len(heights[c * per:(c + 1) * per]) - 1) for c in range(cols))
        if (ok and tallest <= e.h) or size <= SMALLEST:
            return size, bsz, indent, col_w, per, heights, gap, tallest
        size -= 1


def expand_list(e: Element, v: Variant) -> list[Element]:
    items = [" ".join(t.split()) for t in (e.items or []) if t and t.strip()][:MAX_ITEMS]
    if not items:
        return []
    bullet = e.bullet or "dot"
    cols = max(1, min(e.columns or columns_for(len(items), e.w), 3, len(items)))
    size, _, indent, col_w, per, heights, gap, tallest = _fit(e, v, items, cols, bullet)
    lh = e.line_height or 1.3
    mark, hole = _bullet_colors(e)
    divider = e.divider or "none"
    out: list[Element] = []
    for c in range(cols):
        x = e.x + c * (col_w + GAP)
        y = e.y
        chunk = list(enumerate(items))[c * per:(c + 1) * per]
        for row, (i, item) in enumerate(chunk):
            h = heights[i]
            first = size * lh  # bullets centre on the item's first line
            out += bullet_marks(bullet, x, y, first, size, mark, hole, i + 1)
            out.append(Element(kind="text", text_type="item", text=item, x=x + indent, y=y,
                               w=col_w - indent, h=h, font=e.font or "body", size=size,
                               color=e.color or "ink", align="left", max_lines=2,
                               uppercase=e.uppercase, letter_spacing=e.letter_spacing,
                               line_height=lh))
            if divider != "none" and cols == 1 and row < len(chunk) - 1:
                ly = y + h + gap / 2
                out.append(Element(kind="line", x=x, y=ly - 1, w=col_w, h=2, color="soft",
                                   stroke_style="dotted" if divider == "dotted" else "solid",
                                   line_start="none", line_end="none"))
            y += h + gap
        if divider != "none" and c < cols - 1:
            # a vertical line in the middle of the gap, as tall as the block
            cx, cy = x + col_w + GAP / 2, e.y + tallest / 2
            out.append(Element(kind="line", x=cx - tallest / 2, y=cy - 1, w=tallest, h=2,
                               rotate=90, color="soft",
                               stroke_style="dotted" if divider == "dotted" else "solid",
                               line_start="none", line_end="none"))
    return out
