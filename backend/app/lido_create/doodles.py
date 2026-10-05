"""The icon library (library/icons.yaml): small line icons drawn as Lido `DrawLayer`
strokes — beside the contact lines (`decorate.add_contact_icons`) and as the glyph
inside a solid list bullet (`bullet: true` entries: lists.py's check_circle and
arrow_circle).

Each icon is SVG path data in a 24 x 24 box. Drawing one flattens it into polylines and
fits them into the element's box (keeping the icon's own proportions) as exact straight
segments, so corners stay sharp.

The library is data, meant to grow: it is checked on load (`problems()`), and
`make lido-doodles` draws every entry on one sheet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import yaml

from app.lido_create import library
from app.lido_create.svgpath import flatten

DATA = library.path("icons.yaml")
GRID = 24.0
PAIRS = ("website", "phone", "email", "address")  # text types an icon sits beside
Point = tuple[float, float]


@dataclass(frozen=True)
class Doodle:
    name: str
    themes: tuple[str, ...]
    source: str
    path: str
    pairs_with: tuple[str, ...] = ()
    bullet: bool = False  # a glyph drawn inside a solid list bullet

    @property
    def strokes(self) -> list[list[Point]]:
        return _strokes(self.path)


@lru_cache(maxsize=512)
def _strokes(path: str) -> list[list[Point]]:
    return flatten(path, strokes=True)


@lru_cache(maxsize=1)
def library() -> dict[str, Doodle]:
    raw = yaml.safe_load(DATA.read_text()) or []
    out: dict[str, Doodle] = {}
    for item in raw:
        d = Doodle(name=str(item["name"]),
                   themes=tuple(str(t).lower() for t in item.get("themes") or []),
                   source=str(item.get("source", "hand")),
                   path=" ".join(str(item.get("path", "")).split()),
                   pairs_with=tuple(str(p) for p in item.get("pairs_with") or []),
                   bullet=bool(item.get("bullet")))
        out.setdefault(d.name, d)
    return out


def problems() -> list[str]:
    """Everything wrong with the library file, so a bad entry fails loudly."""
    raw = yaml.safe_load(DATA.read_text()) or []
    found, seen = [], set()
    for item in raw:
        name = item.get("name")
        if not name:
            found.append(f"an entry has no name: {item}")
            continue
        if name in seen:
            found.append(f"{name}: duplicate name")
        seen.add(name)
        if not item.get("themes"):
            found.append(f"{name}: needs at least one theme")
        if item.get("bullet") not in (None, True, False):
            found.append(f"{name}: bullet must be true or false")
        bad = [p for p in item.get("pairs_with") or [] if p not in PAIRS]
        if bad:
            found.append(f"{name}: pairs_with {bad} — only {', '.join(PAIRS)}")
        try:
            strokes = flatten(str(item.get("path", "")), strokes=True)
        except Exception as exc:  # noqa: BLE001 — any parse failure is the entry's problem
            found.append(f"{name}: path does not parse ({exc})")
            continue
        if not strokes:
            found.append(f"{name}: path draws nothing")
            continue
        xs = [x for s in strokes for x, _ in s]
        ys = [y for s in strokes for _, y in s]
        if min(xs) < -1 or min(ys) < -1 or max(xs) > GRID + 1 or max(ys) > GRID + 1:
            found.append(f"{name}: path leaves the 24 x 24 box "
                         f"(x {min(xs):.1f}-{max(xs):.1f}, y {min(ys):.1f}-{max(ys):.1f})")
    return found


def info_icon(text_type: str) -> Doodle | None:
    """The icon that sits beside a contact line of this type, if any."""
    return next((d for d in library().values() if text_type in d.pairs_with), None)


def _thin(points: list[Point], gap: float) -> list[Point]:
    """Drop points closer than `gap` to the last kept one (keeping the ends)."""
    if len(points) <= 2:
        return points
    kept = [points[0]]
    for p in points[1:-1]:
        if math.dist(p, kept[-1]) >= gap:
            kept.append(p)
    kept.append(points[-1])
    return kept


def doodle_path(name: str, w: float, h: float, width: float,
                seed: int = 0) -> tuple[str, list[Point]]:
    """(path d, sample points) for icon `name` drawn inside a w x h box — fitted
    without stretching, centred, inset by half the stroke width."""
    pad = width / 2 + 1
    scale = max(0.1, min((w - 2 * pad) / GRID, (h - 2 * pad) / GRID))
    ox, oy = (w - GRID * scale) / 2, (h - GRID * scale) / 2
    placed = [[(ox + x * scale, oy + y * scale) for x, y in s]
              for s in library()[name].strokes]
    parts = []
    for s in placed:
        s = _thin(s, 0.8)
        parts.append(f"M {s[0][0]:.2f},{s[0][1]:.2f} "
                     + " ".join(f"L {x:.2f},{y:.2f}" for x, y in s[1:]))
    return " ".join(parts), [p for s in placed for p in s]


def stroke_width(size: float) -> float:
    """Lucide's 2px-on-24 line weight, at the size it is drawn."""
    return round(max(2.0, size / GRID * 2.0), 1)
