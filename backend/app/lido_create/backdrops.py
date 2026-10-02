"""Layered gradient backgrounds ("backdrops"): a few full-bleed gradient shapes drawn
under everything else — a two-tone split, a diagonal, slanted bands, corner glows, a
spotlight, a horizon arc.

The art director picks a style and a few knobs (`Backdrop`); this module turns it into
exact layers, so the model never has to place a diagonal edge by coordinates. The
designer is told the geometry in words, plus which text colours read in each area —
measured here with the same `surface_at` / contrast maths the checks use, so what it is
told and what is checked can't disagree.

Every layer is a normal shape element (`bleed`, marked `backdrop`): the checks hold text
to one area and to its contrast exactly as for any other shape, and the brand palette
applies because every colour is a role.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.lido_create.kit import RGB, ColorRole, Element, Gradient, H, Palette, W

BackdropStyle = Literal["split_half", "diagonal_split", "diagonal_bands", "corner_glow",
                        "spotlight", "horizon_arc"]
Side = Literal["left", "right", "top", "bottom", "center"]

STYLES: dict[str, str] = {
    "split_half": "two-tone: a gradient panel fills one side (left/right/top/bottom) — "
                  "bold, editorial, offer next to a photo",
    "diagonal_split": "the canvas split along a slanted line, a gradient panel on one "
                      "side — dynamic, sale, sport, launch",
    "diagonal_bands": "two slanted bands crossing the canvas — energetic, youth, event",
    "corner_glow": "soft colour glows bleeding in from two corners over a gentle fade "
                   "(a mesh-gradient look) — premium, tech, beauty, calm",
    "spotlight": "one large soft glow behind the hero — product launch, reveal",
    "horizon_arc": "a huge curved arc rising from one edge like a horizon — calm, "
                   "wellness, travel, real estate",
}
TEXT_ROLES = ("ink", "accent", "bg", "on_accent")  # never soft: decoration only
SMALL, LARGE = 4.5, 3.0  # contrast for body text / display text (36px+)


class Backdrop(BaseModel):
    """What the art director picks; `clean` clamps it to what looks right."""
    style: BackdropStyle
    side: Side | None = None  # which side holds the panel / glow / arc
    angle: float | None = None  # diagonal styles: tilt in degrees (10-30)
    split: float | None = None  # where the split / arc / bands sit, 0.35-0.65 of the canvas
    tone: ColorRole | None = None  # the backdrop's colour (default accent; never ink/bg)


SIDES: dict[str, tuple[str, ...]] = {  # allowed sides, the default first
    "split_half": ("right", "left", "top", "bottom"),
    "diagonal_split": ("bottom", "top"),
    "diagonal_bands": ("bottom",),
    "corner_glow": ("left", "right"),
    "spotlight": ("center", "left", "right", "top", "bottom"),
    "horizon_arc": ("bottom", "top"),
}


def clean(b: Backdrop) -> Backdrop:
    side = b.side if b.side in SIDES[b.style] else SIDES[b.style][0]
    tilt = min(30.0, max(10.0, abs(b.angle))) if b.angle else 18.0
    angle = -tilt if (b.angle or 0) < 0 else tilt
    split = min(0.65, max(0.35, b.split)) if b.split else 0.5
    tone = b.tone if b.tone in ("accent", "soft", "on_accent") else "accent"
    return Backdrop(style=b.style, side=side, angle=angle, split=split, tone=tone)


def random_backdrop(rng: random.Random, chance: float = 0.6) -> Backdrop | None:
    """For a design made without a plan: often a backdrop, in a random style."""
    if rng.random() >= chance:
        return None
    return clean(Backdrop(style=rng.choice(list(STYLES)),
                          angle=rng.choice((-1, 1)) * rng.uniform(12, 26),
                          split=rng.uniform(0.4, 0.6)))


@dataclass
class Expanded:
    base: Gradient | None  # the canvas gradient under the layers (None = flat bg)
    layers: list[Element]
    summary: str  # the geometry in one sentence, for the designer


def _layer(**kw) -> Element:
    return Element(kind="shape", bleed=True, backdrop=True, **kw)


def _fade(tone: str, angle: float, reach: float = 450) -> Gradient:
    """Solid `tone` easing to a lighter tint of it (fades towards transparent, never
    all the way): depth without a second colour."""
    return Gradient(style="linear", angle=angle, start=tone, end=None, start_at=0,
                    end_at=reach)


def _glow(tone: str) -> Gradient:
    """A radial glow fully faded before the circle's rim, so it has no visible edge."""
    return Gradient(style="radial", start=tone, end=None, start_at=0, end_at=70)


def _rotated_panel(cx: float, cy: float, angle: float, depth: float, below: bool,
                   tone: str, length: float = 2600) -> Element:
    """A long rectangle whose near edge runs through (cx, cy) at `angle` degrees, lying
    below (or above) that line."""
    a = math.radians(angle)
    nx, ny = -math.sin(a), math.cos(a)  # the normal pointing down the canvas
    k = depth / 2 * (1 if below else -1)
    mx, my = cx + nx * k, cy + ny * k
    return _layer(shape="rectangle", x=round(mx - length / 2, 2), y=round(my - depth / 2, 2),
                  w=length, h=depth, rotate=round(angle, 2), color=tone,
                  gradient=_fade(tone, 180 if below else 0, 500))


def expand(b: Backdrop) -> Expanded:
    b = clean(b)
    tone, side, s, angle = b.tone, b.side, b.split, b.angle
    if b.style == "split_half":
        if side in ("left", "right"):
            edge = round(W * s)
            x, w = (edge, W - edge + 10) if side == "right" else (-10, edge + 10)
            panel = _layer(shape="rectangle", x=x, y=-10, w=w, h=H + 20, color=tone,
                           gradient=_fade(tone, 270 if side == "right" else 90))
            where = f"the {side} part from x={edge}" if side == "right" \
                else f"the {side} part up to x={edge}"
        else:
            edge = round(H * s)
            y, h = (edge, H - edge + 10) if side == "bottom" else (-10, edge + 10)
            panel = _layer(shape="rectangle", x=-10, y=y, w=W + 20, h=h, color=tone,
                           gradient=_fade(tone, 0 if side == "bottom" else 180))
            where = f"the {side} part from y={edge}" if side == "bottom" \
                else f"the {side} part down to y={edge}"
        return Expanded(None, [panel], f"a {tone} panel fills {where}; the rest is the "
                                       "plain canvas")
    if b.style == "diagonal_split":
        cy = H * s
        below = side == "bottom"
        panel = _rotated_panel(W / 2, cy, angle, 1700, below, tone)
        y0 = cy - (W / 2) * math.tan(math.radians(angle))
        y1 = cy + (W / 2) * math.tan(math.radians(angle))
        return Expanded(None, [panel],
                        f"a slanted edge runs from (0, {y0:.0f}) to ({W}, {y1:.0f}); a "
                        f"{tone} panel fills everything {'below' if below else 'above'} it")
    if b.style == "diagonal_bands":
        cy = H * s
        first = _rotated_panel(W / 2, cy, angle, 120, True, tone)
        first.gradient = None
        second = _rotated_panel(W / 2, cy + 120 / math.cos(math.radians(angle)) + 26,
                                angle, 44, True, "soft")
        second.gradient, second.opacity = None, 0.9
        y0 = cy - (W / 2) * math.tan(math.radians(angle))
        y1 = cy + (W / 2) * math.tan(math.radians(angle))
        return Expanded(None, [first, second],
                        f"two slanted bands (a 120px {tone} band, then a thin soft one) "
                        f"cross the canvas, starting along the line (0, {y0:.0f}) to "
                        f"({W}, {y1:.0f}) and running down from it — decoration, keep "
                        "text off them")
    if b.style == "corner_glow":
        first, second = ((0, 0), (W, H)) if side == "left" else ((W, 0), (0, H))
        d = 1300
        glows = [_layer(shape="circle", x=cx - d / 2, y=cy - d / 2, w=d, h=d, color=t,
                        gradient=_glow(t), opacity=o)
                 for (cx, cy), t, o in ((first, tone, 0.75), (second, "soft", 0.7))]
        base = Gradient(style="linear", angle=135 if side == "left" else 225, start="bg",
                        end="soft", start_at=0, end_at=420)
        return Expanded(base, glows, f"soft {tone} and soft-colour glows bleed in from "
                                     "two opposite corners over a gentle fade; no hard "
                                     "edges anywhere")
    if b.style == "spotlight":
        centre = {"center": (540, 520), "left": (330, 540), "right": (750, 540),
                  "top": (540, 330), "bottom": (540, 750)}[side]
        d = 980
        glow = _layer(shape="circle", x=centre[0] - d / 2, y=centre[1] - d / 2, w=d, h=d,
                      color=tone, gradient=_glow(tone), opacity=0.8)
        base = Gradient(style="linear", angle=180, start="bg", end="soft", start_at=0,
                        end_at=380)
        return Expanded(base, [glow], f"a large soft {tone} glow centred at "
                                      f"({centre[0]}, {centre[1]}) — put the hero photo "
                                      "on it")
    # horizon_arc
    d = 2200
    r = d / 2
    top = H * max(s, 0.5) if side == "bottom" else H * min(s, 0.5)
    cy = top + r if side == "bottom" else top - r
    arc = _layer(shape="circle", x=W / 2 - r, y=cy - r, w=d, h=d, color=tone,
                 gradient=_fade(tone, 180 if side == "bottom" else 0, 320))
    edge = cy - math.sqrt(r * r - (W / 2) ** 2) if side == "bottom" \
        else cy + math.sqrt(r * r - (W / 2) ** 2)
    return Expanded(None, [arc],
                    f"a huge {tone} arc rises from the {side} edge: its crest is at "
                    f"y={top:.0f} in the middle and it meets the sides at y={edge:.0f}")


# --------------------------------------------------------------------------------------
# What the designer is told: where text can go, and in which colours
# --------------------------------------------------------------------------------------


# Without a palette (the designer picks its colours in the same call), the advice
# follows the role rules the designer already works by; the checks then verify it.
ROLE_TEXT = {"accent": "on_accent", "soft": "ink", "on_accent": "accent"}
MAX_AREAS = 4


def _role_areas(ex: Expanded, step: int) -> list[str]:
    from app.lido_create.check import surface_at
    from app.lido_create.kit import PALETTES

    groups: dict[tuple, list[tuple[float, float]]] = {}
    for gy in range(step // 2, H, step):
        for gx in range(step // 2, W, step):
            sid, _ = surface_at(ex.layers, len(ex.layers), gx, gy, PALETTES[0], ex.base)
            groups.setdefault(sid, []).append((gx, gy))
    lines = []
    for sid, pts in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:MAX_AREAS]:
        if len(pts) < 6:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        box = (f"x {max(0, min(xs) - step // 2)}-{min(W, max(xs) + step // 2)}, "
               f"y {max(0, min(ys) - step // 2)}-{min(H, max(ys) + step // 2)}")
        layer = next((ex.layers[i] for i in sid if isinstance(i, int)), None)
        if layer is None:
            reads = "text in ink or accent"
            if any(e.gradient and e.gradient.style == "radial" for e in ex.layers):
                reads += " (the glows tint it: keep small text out of their bright centres)"
            what = "the plain canvas"
        else:
            reads = f"text in {ROLE_TEXT.get(layer.color or 'accent', 'ink')}"
            what = f"the {layer.color} backdrop panel"
        lines.append(f"- {what} (about {box}): {reads}")
    return lines


def text_areas(ex: Expanded, palette: Palette | None, step: int = 60) -> list[str]:
    """One line per area the backdrop makes (the plain canvas, a panel…): its rough box
    and the text colours readable everywhere in it — measured when the palette is known
    (brand colours), from the role rules otherwise."""
    from app.lido_create.check import contrast, surface_at

    if palette is None:
        return _role_areas(ex, step)

    def readable(colours: list[RGB], need: float) -> list[str]:
        return [r for r in TEXT_ROLES
                if min(contrast(palette.color(r), c) for c in colours) >= need]

    # group the canvas by surface AND by which colours read there, so a glow's bright
    # centre and its faded surroundings get their own advice
    groups: dict[tuple, list[tuple[float, float, RGB]]] = {}
    for gy in range(step // 2, H, step):
        for gx in range(step // 2, W, step):
            sid, rgb = surface_at(ex.layers, len(ex.layers), gx, gy, palette, ex.base)
            key = (sid, tuple(readable([rgb], SMALL)), tuple(readable([rgb], LARGE)))  # type: ignore[list-item]
            groups.setdefault(key, []).append((gx, gy, rgb))  # type: ignore[arg-type]
    lines = []
    for (sid, _, _), pts in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:MAX_AREAS]:
        if len(pts) < 6:  # a sliver: not somewhere to put text
            continue
        colours = [c for _, _, c in pts]
        body = readable(colours, SMALL)
        big = [r for r in readable(colours, LARGE) if r not in body]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        box = (f"x {max(0, min(xs) - step // 2)}-{min(W, max(xs) + step // 2)}, "
               f"y {max(0, min(ys) - step // 2)}-{min(H, max(ys) + step // 2)}")
        what = "the plain canvas" if sid == ("canvas",) else "the backdrop panel"
        if body:
            reads = f"text in {' or '.join(body)}"
            if big:
                reads += f" (big display text may also use {' or '.join(big)})"
        elif big:
            reads = f"only big display text (36px+), in {' or '.join(big)}"
        else:
            reads = "no text here (nothing reads on it)"
        lines.append(f"- {what} (about {box}): {reads}")
    return lines


def brief_for(ex: Expanded, palette: Palette | None) -> str:
    """The backdrop as the designer reads it."""
    return ("BACKDROP — drawn for you underneath everything; do not draw it yourself and "
            f"set background to null: {ex.summary}.\nText areas:\n"
            + "\n".join(text_areas(ex, palette))
            + "\nKeep every text (and its pill or badge) entirely inside ONE area, never "
              "across an edge between areas. Photos and decoration may sit anywhere.")
