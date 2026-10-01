"""Mechanical design checks every generated layout must pass before it is saved.

These are the rules from docs/TEMPLATE_DESIGN_GUIDE.md and TEMPLATE_EXPORT_RULES.md that
can be checked from coordinates alone:

- every text fits its box and line budget, measured with the real font
- no text overlaps other text, the logo, or a photo, and nothing is drawn on top of it
- every text sits on ONE flat colour (not straddling a shape's edge) with WCAG contrast
- text, logo and non-bleeding shapes/photos stay inside the canvas
- the headline is the largest free text, so the loader infers the right roles
"""

from __future__ import annotations

import math
import re

from app.lido_create.draw import draw_path
from app.lido_create.kit import RGB, Design, Element, Gradient, H, Palette, Variant, W, line_count
from app.lido_create.shapes import frame_contains, shape_contains

EDGE = 30  # minimum distance from text/logo to the canvas edge
# Emoji, pictographs and bullet/check marks: the template fonts have no glyphs for them.
UNDRAWABLE = re.compile("[\u2022\u2023\u25a0-\u25ff\u2600-\u27bf\u2b00-\u2bff"
                        "\U0001f000-\U0001faff]")
FREE_TEXT = {"headline", "kicker", "body", "item", "cta", "badge", "caption"}
MAX_TEXTS = 12
HOLLOW_MIN_PX = 56  # outline-only letters are only readable when big
STROKES = ("line", "draw")  # thin marks: never a text's backdrop, never through text
# Procedural photo crops as polygons in the unit square (lido.clip_path draws the same).
POLYGONS = {
    "hexagon": ((0.25, 0), (0.75, 0), (1, 0.5), (0.75, 1), (0.25, 1), (0, 0.5)),
    "diamond": ((0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)),
}

# -- geometry ---------------------------------------------------------------------------


def _in_polygon(points, x: float, y: float) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _unrotate(e: Element, px: float, py: float) -> tuple[float, float]:
    """The point in the element's own, unrotated frame."""
    if not e.rotate:
        return px, py
    cx, cy = e.x + e.w / 2, e.y + e.h / 2
    a = math.radians(-e.rotate)
    dx, dy = px - cx, py - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


def covers(e: Element, px: float, py: float) -> bool:
    px, py = _unrotate(e, px, py)
    if not (e.x <= px <= e.x + e.w and e.y <= py <= e.y + e.h):
        return False
    u, v = (px - e.x) / (e.w or 1), (py - e.y) / (e.h or 1)
    if e.kind == "photo":
        if e.frame:
            return frame_contains(e.frame, u, v)
        if e.clip in POLYGONS:
            return _in_polygon(POLYGONS[e.clip], u, v)
        if e.clip in ("circle", "blob"):
            return (u - 0.5) ** 2 + (v - 0.5) ** 2 <= 0.25
        if e.clip == "arch" and py < e.y + e.w / 2:
            r = e.w / 2
            return (px - e.x - r) ** 2 + (py - e.y - r) ** 2 <= r * r
        return True
    if e.kind == "shape":
        return shape_contains(e.shape or "rectangle", u, v)
    return True


def text_extent(e: Element, v: Variant) -> tuple[float, float, float, float]:
    """The box the glyphs actually occupy (a 420px box holding a 270px line only has
    ink on 270px of it, aligned left/centre/right)."""
    from app.lido_create.kit import measure
    lines, _ = line_count(v.fonts, e)
    m = measure(v.fonts, e.font or "body", e.size or 16, bool(e.uppercase),
                e.letter_spacing or 0)
    ink = min(e.w, max((m.width(line) for line in lines), default=0))
    x0 = {"center": e.x + (e.w - ink) / 2, "right": e.x + e.w - ink}.get(e.align or "", e.x)
    return x0, e.y, x0 + ink, e.y + e.h


def _samples(box: tuple[float, float, float, float], nx: int = 6, ny: int = 3):
    x0, y0, x1, y1 = box
    for i in range(nx):
        for j in range(ny):
            yield (x0 + (x1 - x0) * (i + 0.5) / nx, y0 + (y1 - y0) * (j + 0.5) / ny)


def _blend(top: RGB, under: RGB, alpha: float) -> RGB:
    return tuple(round(t * alpha + u * (1 - alpha)) for t, u in zip(top, under))  # type: ignore[return-value]


def gradient_at(g: Gradient, box: tuple[float, float, float, float], px: float,
                py: float, palette: Palette, base: str) -> tuple[RGB, float]:
    """(colour, opacity) of a gradient fill at a point — CSS geometry: a linear angle
    of 0 runs towards the top, 90 to the right; radial spreads from the centre to the
    farthest corner."""
    x0, y0, w, h = box
    cx, cy = x0 + w / 2, y0 + h / 2
    if g.style == "radial":
        t = math.hypot((px - cx) / (w / 2 or 1), (py - cy) / (h / 2 or 1)) / math.sqrt(2)
    else:
        a = math.radians(180 if g.angle is None else g.angle)
        dx, dy = math.sin(a), -math.cos(a)
        length = abs(w * dx) + abs(h * dy) or 1
        t = ((px - cx) * dx + (py - cy) * dy) / length + 0.5
    s0, s1 = (g.start_at or 0) / 100, (100 if g.end_at is None else g.end_at) / 100
    k = 0.0 if t <= s0 else 1.0 if t >= s1 or s1 <= s0 else (t - s0) / (s1 - s0)
    start = palette.color(g.start or base)
    end = palette.color(g.end) if g.end else start
    end_alpha = 1.0 if g.end else 0.0
    return _blend(end, start, k), 1.0 + (end_alpha - 1.0) * k


def _paint(e: Element, px: float, py: float, palette: Palette) -> tuple[RGB, float]:
    """An element's own colour and opacity at a point, before what's beneath shows."""
    alpha = 1.0 if e.opacity is None else e.opacity
    if e.gradient is not None:
        rgb, ga = gradient_at(e.gradient, (e.x, e.y, e.w, e.h), *_unrotate(e, px, py),
                              palette, e.color or "accent")
        return rgb, alpha * ga
    return palette.color(e.color or "accent"), alpha


def surface_at(els: list[Element], index: int, px: float, py: float, palette: Palette,
               background: Gradient | None = None) -> tuple[tuple, RGB | str]:
    """(which surfaces, colour) directly under (px, py) beneath element `index`. The
    surface id says which layers make up the colour, so a text over the edge between
    two of them is caught even when the colours happen to be close."""
    for j in range(index - 1, -1, -1):
        e = els[j]
        if e.kind in ("text", "logo", *STROKES) or not covers(e, px, py):
            continue
        if e.kind == "photo":
            return ("photo",), "photo"
        rgb, alpha = _paint(e, px, py, palette)
        if alpha >= 0.999:
            # solid layers of the same colour read as one surface (a panel and its arrow
            # tip); a gradient is its own surface
            return ((j,) if e.gradient else ("solid", e.color)), rgb
        under_id, under = surface_at(els, j, px, py, palette, background)
        if under == "photo":
            return (j, *under_id), "photo"
        return (j, *under_id), _blend(rgb, under, alpha)  # type: ignore[arg-type]
    if background is not None:
        rgb, alpha = gradient_at(background, (0, 0, W, H), px, py, palette, "bg")
        return ("canvas",), _blend(rgb, (255, 255, 255), alpha)
    return ("canvas",), palette.bg


def background_at(els: list[Element], index: int, px: float, py: float,
                  palette: Palette, background: Gradient | None = None) -> RGB | str:
    """Colour directly under point (px, py) beneath element `index` — or 'photo'."""
    return surface_at(els, index, px, py, palette, background)[1]


def stroke_points(e: Element) -> list[tuple[float, float]]:
    """Points along a line's or hand-drawn stroke's centre, in canvas pixels."""
    if e.kind == "line":
        cx, cy = e.x + e.w / 2, e.y + e.h / 2
        a = math.radians(e.rotate or 0)
        return [(cx + (t - 0.5) * e.w * math.cos(a), cy + (t - 0.5) * e.w * math.sin(a))
                for t in (i / 24 for i in range(25))]
    if e.kind == "draw":
        _, pts = draw_path(e.draw or "underline", e.w, e.h, e.stroke_width or 6,
                           seed=draw_seed(e))
        return [(e.x + x, e.y + y) for x, y in pts]
    return []


def draw_seed(e: Element) -> int:
    return int(e.x * 7 + e.y * 13 + e.w)


def luminance(c: RGB) -> float:
    def ch(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = c
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: RGB, b: RGB) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _overlap(a, b, pad: float = 4) -> bool:
    return a[0] < b[2] - pad and b[0] < a[2] - pad and a[1] < b[3] - pad and b[1] < a[3] - pad


# -- the checks -------------------------------------------------------------------------


def rotated_extent(e: Element) -> tuple[float, float, float, float]:
    """Bounding box of a (possibly rotated) element."""
    if not e.rotate:
        return e.x, e.y, e.x + e.w, e.y + e.h
    a = math.radians(e.rotate)
    hw = (abs(e.w * math.cos(a)) + abs(e.h * math.sin(a))) / 2
    hh = (abs(e.w * math.sin(a)) + abs(e.h * math.cos(a))) / 2
    cx, cy = e.x + e.w / 2, e.y + e.h / 2
    return cx - hw, cy - hh, cx + hw, cy + hh


# The feature families beyond plain circles and rectangles; AI designs must use a few.
FEATURE_FAMILIES = {
    "shape": "a Lido shape beyond rectangle/circle (chevron, arrow, parallelogram, "
             "hexagon, triangle, arrow-tag…)",
    "gradient": "a gradient (radial spotlight, deepening background, fading panel)",
    "border": "a dashed or dotted outline (coupon box, dotted frame)",
    "line": "lines (dividers, corner brackets, a pointer with an arrow end)",
    "draw": "a hand-drawn accent (underline a key word, circle the price, arrow at the "
            "product)",
    "frame": "a photo frame from FRAMES (brush stroke, torn paper, scallop, gem, letter…)",
    "effect": "a text effect (hollow outline word, lift or shadow on the headline)",
}
MIN_FAMILIES = 2


def families_used(design: Design) -> set[str]:
    used = set()
    if design.background is not None:
        used.add("gradient")
    for e in design.elements:
        if e.kind == "shape" and e.shape not in (None, "rectangle", "circle"):
            used.add("shape")
        if e.gradient is not None:
            used.add("gradient")
        if e.kind == "shape" and e.stroke and e.stroke_style in ("dashed", "dotted"):
            used.add("border")
        if e.kind in ("line", "draw"):
            used.add(e.kind)
        if e.kind == "photo" and e.frame:
            used.add("frame")
        if e.kind == "text" and e.effect:
            used.add("effect")
    return used


def _richness(els: list[Element], texts, extents, name) -> list[str]:
    """What separates a designed template from a wireframe — enforced on AI designs."""
    errors = []
    # A shape only stops counting as decoration when it is a snug container for its
    # text (a pill, badge or tag). Frames, panels and stages with text on them still
    # decorate.
    on_shape: dict[int, list[tuple[float, float, float, float]]] = {}
    for i, _ in texts:
        box = extents[i]
        for j in range(i):
            e = els[j]
            if e.kind == "shape" and all(covers(e, px, py) for px, py in _samples(box)):
                on_shape.setdefault(j, []).append(box)
    backing = set()
    for j, boxes in on_shape.items():
        uw = max(b[2] for b in boxes) - min(b[0] for b in boxes)
        uh = max(b[3] for b in boxes) - min(b[1] for b in boxes)
        e = els[j]
        if e.w <= uw + 200 and e.h <= uh + 150:
            backing.add(j)
    shapes = [(j, e) for j, e in enumerate(els) if e.kind == "shape" and j not in backing]
    big = sum(1 for _, e in shapes if min(e.w, e.h) >= 24 or max(e.w, e.h) >= 80) \
        + sum(1 for e in els if e.kind in STROKES)
    textures = 1 if any(max(e.w, e.h) < 24 for _, e in shapes) else 0
    if big + textures < 3:
        errors.append(f"the design looks bare: only {big + textures} decorative element(s) "
                      "besides text pills and badges — add at least 3 (a big background "
                      "shape, a dot grid, a ring or frame, a corner accent, lines...)")
    for p, photo in enumerate(els):
        if photo.kind != "photo":
            continue
        area = photo.w * photo.h
        for s in els[:p]:
            if s.kind != "shape":
                continue
            x0, y0, x1, y1 = rotated_extent(s)
            ox = max(0.0, min(x1, photo.x + photo.w) - max(x0, photo.x))
            oy = max(0.0, min(y1, photo.y + photo.h) - max(y0, photo.y))
            if ox * oy > 0.1 * area:
                errors.append("a shape is placed behind a photo — photos sit directly on "
                              "the background; put decoration around the photo, not under "
                              "it (badges may overlap its edge if drawn on top)")
                break
    for i, e in texts:
        if e.text_type != "item":
            continue
        x0, y0, x1, _ = extents[i]
        first_line = (y0, y0 + (e.size or 20) * (e.line_height or 1.3))
        marker = any(
            s.kind == "shape" and s.y < first_line[1] and s.y + s.h > first_line[0]
            and (0 <= x0 - (s.x + s.w) <= 60 or 0 <= s.x - x1 <= 60)
            and max(s.w, s.h) <= 60
            for s in els)
        if not marker:
            errors.append(f"{name(e)}: list item has no bullet marker — put a small shape "
                          "(dot, ring, bar) just beside it, vertically centred on its line")
    return errors


def validate(design: Design, v: Variant, *, creative: bool = False) -> list[str]:
    """`creative` adds the richness rules asked of AI-designed layouts."""
    els, pal = design.elements, v.palette
    errors: list[str] = []
    texts = [(i, e) for i, e in enumerate(els) if e.kind == "text"]
    logos = [e for e in els if e.kind == "logo"]

    def name(e: Element) -> str:
        return f"{e.text_type} {e.text!r}" if e.kind == "text" else e.kind

    if len(logos) != 1:
        errors.append(f"needs exactly one logo, has {len(logos)}")
    headlines = [e for _, e in texts if e.text_type == "headline"]
    if len(headlines) != 1:
        errors.append(f"needs exactly one headline, has {len(headlines)}")
    photos = sum(e.kind == "photo" for e in els)
    if not 1 <= photos <= 2:
        errors.append(f"{photos} photos — use 1 or 2 (the photo slot is what makes a "
                      "generated design fit the brief)")
    if not 3 <= len(texts) <= MAX_TEXTS:
        errors.append(f"{len(texts)} text boxes — keep between 3 and {MAX_TEXTS}")
    if any(e.kind == "dots" for e in els):
        errors.append("unexpanded dots element")
    for kind in ("website", "phone", "email", "address"):
        if sum(e.text_type == kind for _, e in texts) > 1:
            errors.append(f"more than one {kind} line")

    extents = {i: text_extent(e, v) for i, e in texts}

    for i, e in texts:
        lines, wide = line_count(v.fonts, e)
        if wide:
            errors.append(f"{name(e)}: word(s) {wide} wider than the {e.w:.0f}px box")
        if e.max_lines and len(lines) > e.max_lines:
            errors.append(f"{name(e)}: wraps to {len(lines)} lines, limit {e.max_lines}")
        x0, y0, x1, y1 = extents[i]
        if x0 < EDGE or y0 < EDGE or x1 > W - EDGE or y1 > H - EDGE:
            errors.append(f"{name(e)}: closer than {EDGE}px to the canvas edge")
        if "\n" in (e.text or ""):
            errors.append(f"{name(e)}: contains a line break — a text box is one "
                          "paragraph; put each line (each list item) in its own text box")
        if UNDRAWABLE.search(e.text or ""):
            errors.append(f"{name(e)}: has emoji/icon/bullet characters the fonts can't "
                          "draw — plain text only")
        if e.color == "soft":
            errors.append(f"{name(e)}: 'soft' is a decoration colour, never text")

        if e.effect == "hollow" and (e.size or 0) < HOLLOW_MIN_PX:
            errors.append(f"{name(e)}: hollow (outline) letters need at least "
                          f"{HOLLOW_MIN_PX}px to read — use it on big display text only")

        # what sits under it: one surface (a flat colour or one gradient), readable at
        # every point
        surfaces: set = set()
        colours: list = []
        for px, py in _samples(extents[i]):
            sid, rgb = surface_at(els, i, px, py, pal, design.background)
            surfaces.add(sid)
            colours.append(rgb)
            for j in range(i + 1, len(els)):
                if els[j].kind in ("shape", "photo", "logo") and covers(els[j], px, py):
                    errors.append(f"{name(e)}: a {els[j].kind} is drawn on top of it")
                    break
        # sampling can step over a small shape (a 9px dot between sample points), so any
        # small shape whose box touches the text counts too
        box = extents[i]
        for j in range(i):
            s = els[j]
            if s.kind == "shape" and max(s.w, s.h) < 60 \
                    and _overlap(rotated_extent(s), box, pad=0) \
                    and not all(covers(s, px, py) for px, py in _samples(box)):
                surfaces.add(("small shape", j))
        if "photo" in colours:
            errors.append(f"{name(e)}: sits on a photo — put it on a flat colour")
        elif len(surfaces) > 1:
            errors.append(f"{name(e)}: straddles the edge of a shape (sits on "
                          f"{len(surfaces)} different surfaces)")
        elif colours:
            need = 3.0 if (e.size or 0) >= 36 else 4.5
            ink = pal.color(e.color or "ink")
            ratio = min(contrast(ink, c) for c in colours)  # type: ignore[arg-type]
            if ratio < need:
                where = " at its weakest point (the gradient fades there)" \
                    if len(set(colours)) > 1 else ""
                errors.append(f"{name(e)}: contrast {ratio:.1f}:1 against what's behind "
                              f"it{where}, needs {need}:1")

    for a in range(len(texts)):
        for b in range(a + 1, len(texts)):
            (i, ei), (j, ej) = texts[a], texts[b]
            if _overlap(extents[i], extents[j]):
                errors.append(f"{name(ei)} overlaps {name(ej)}")

    for li, logo in ((i, e) for i, e in enumerate(els) if e.kind == "logo"):
        box = (logo.x, logo.y, logo.x + logo.w, logo.y + logo.h)
        if box[0] < EDGE - 10 or box[1] < EDGE - 10 or box[2] > W - EDGE + 10 \
                or box[3] > H - EDGE + 10:
            errors.append("logo is too close to the canvas edge")
        under = {surface_at(els, li, px, py, pal, design.background)[0]
                 for px, py in _samples(box, 3, 3)}
        if ("photo",) in under or len(under) > 1:
            errors.append("logo must sit on one flat colour (it's swapped for the brand's "
                          "own logo and needs a predictable backdrop)")
        for i, e in texts:
            if _overlap(box, extents[i]):
                errors.append(f"logo overlaps {name(e)}")

    for e in els:
        x0, y0, x1, y1 = rotated_extent(e)
        off = x0 < -1 or y0 < -1 or x1 > W + 1 or y1 > H + 1
        if e.kind in ("shape", "photo", *STROKES) and not e.bleed and off:
            errors.append(f"{e.kind} at ({e.x:.0f},{e.y:.0f}) runs off the canvas "
                          "without bleed")
        if e.kind == "photo" and min(e.w, e.h) < 200:
            errors.append(f"photo {e.w:.0f}x{e.h:.0f} is too small to read")

    # lines and hand-drawn strokes decorate around text — never through it
    for e in els:
        if e.kind not in STROKES:
            continue
        pts = stroke_points(e)
        for i, t in texts:
            x0, y0, x1, y1 = extents[i]
            if any(x0 + 3 < px < x1 - 3 and y0 + 3 < py < y1 - 3 for px, py in pts):
                what = f"hand-drawn {e.draw}" if e.kind == "draw" else "line"
                errors.append(f"{what} crosses {name(t)} — put it under, beside or "
                              "around the text")
    if design.background is not None and design.background.end is None:
        errors.append("a background gradient must end in a colour role (a transparent "
                      "canvas has nothing behind it)")

    if headlines:
        top = headlines[0].size or 0
        for _, e in texts:
            if e.text_type in FREE_TEXT and e is not headlines[0] and (e.size or 0) >= top:
                errors.append(f"{name(e)} is as large as the headline — the loader would "
                              "take it for the headline")
    if creative:
        errors += _richness(els, texts, extents, name)
        used = families_used(design)
        if len(used) < MIN_FAMILIES:
            missing = "; ".join(f"{k}: {v}" for k, v in FEATURE_FAMILIES.items()
                                if k not in used)
            errors.append(f"the design only uses circles and rectangles"
                          f"{' plus ' + ', '.join(sorted(used)) if used else ''} — use at "
                          f"least {MIN_FAMILIES} of these feature families: {missing}")
    return list(dict.fromkeys(errors))
