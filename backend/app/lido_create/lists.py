"""The list block: any number of items (features, services, steps, menu entries) laid
out by code, so none is ever dropped and the columns always line up.

The designer writes ONE `list` element — the area (x/y/w/h), every item word for word,
and the style (bullet, divider, size, colour) — and `expand_list` turns it into real
elements: one text per item, a bullet beside each, dividers between columns (or rows).

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


def _fit(e: Element, v: Variant, items: list[str], cols: int, bullet: str):
    """The largest size (from the requested one down) at which every item fits."""
    font, lh = e.font or "body", e.line_height or 1.3
    per = math.ceil(len(items) / cols)
    col_w = (e.w - GAP * (cols - 1)) / cols
    size = float(e.size or 26)
    while True:
        bsz = round(size * 0.55)
        indent = 0 if bullet == "none" else (size * 1.5 if bullet == "number" else bsz + 14)
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
    size, bsz, indent, col_w, per, heights, gap, tallest = _fit(e, v, items, cols, bullet)
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
            if bullet in ("dot", "ring"):
                out.append(Element(kind="shape", shape="circle", x=x, y=y + (first - bsz) / 2,
                                   w=bsz, h=bsz, color=mark))
                if bullet == "ring":
                    k = bsz * 0.46
                    out.append(Element(kind="shape", shape="circle", x=x + (bsz - k) / 2,
                                       y=y + (first - k) / 2, w=k, h=k, color=hole))
            elif bullet == "bar":
                out.append(Element(kind="shape", shape="rectangle", x=x,
                                   y=y + first / 2 - 3, w=bsz, h=6, color=mark, radius=3))
            elif bullet == "check":
                out.append(Element(kind="draw", draw="check", x=x, y=y + (first - bsz) / 2,
                                   w=bsz, h=bsz, color=mark, stroke_width=max(3, size / 8)))
            elif bullet == "number":
                d = size * 1.15
                out.append(Element(kind="shape", shape="circle", x=x, y=y + (first - d) / 2,
                                   w=d, h=d, color=mark))
                out.append(Element(kind="text", text_type="caption", text=str(i + 1),
                                   font="button", size=round(size * 0.62), color=hole,
                                   align="center", x=x, y=y + (first - d) / 2 + d * 0.17,
                                   w=d, h=0, max_lines=1, line_height=1.2))
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
