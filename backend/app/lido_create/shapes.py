"""The geometry of what Lido.js can draw, so the Lido writer, the preview renderer and
the design checks agree (docs/LIDO_CAPABILITIES.md). This is everything the code CAN
draw; which of it the AI may USE — and the hint it reads for each — is the menu in
library/ (shapes.yaml, frames.yaml, effects.yaml, line_ends.yaml).

- SHAPES: Lido's 20 native `ShapeLayer` shapes. Outlines are in the unit square,
  measured from the editor's own rendering (lidojs_templates/lido_core/).
- frames(): Lido's photo-frame outlines (`FrameLayer.clipPath`, in
  library/frame_outlines.json), with their natural size — Lido sizes a frame as
  boxSize / scale, so a frame keeps its outline's aspect ratio.
- LINE_STYLES / LINE_ENDS / BORDER_STYLES: `LineLayer` and border options.
- TEXT_EFFECTS: `TextLayer.props.effect` presets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from app.lido_create import library
from app.lido_create.svgpath import contains, flatten

Point = tuple[float, float]


@dataclass(frozen=True)
class Shape:
    name: str
    points: tuple[Point, ...] = ()  # polygon in the unit square; empty = rect/ellipse


def _arrow(head_at: float = 0.73, body: tuple[float, float] = (0.27, 0.73)) -> tuple:
    """A right-pointing block arrow: body then a full-height head."""
    b0, b1 = body
    return ((0, b0), (head_at, b0), (head_at, 0), (1, 0.5), (head_at, 1), (head_at, b1),
            (0, b1))


def _turn(points, how: str) -> tuple:
    """Rotate/flip a unit-square polygon: 'left', 'up', 'down' from a right-facing one."""
    f = {"left": lambda x, y: (1 - x, y), "up": lambda x, y: (y, 1 - x),
         "down": lambda x, y: (y, x)}[how]
    return tuple(f(x, y) for x, y in points)


_RIGHT = _arrow()
SHAPES: dict[str, Shape] = {s.name: s for s in [
    Shape("rectangle"),
    Shape("circle"),
    Shape("triangle", ((0.5, 0), (1, 1), (0, 1))),
    Shape("triangleUpsideDown", ((0, 0), (1, 0), (0.5, 1))),
    Shape("rhombus", ((0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5))),
    Shape("pentagon", ((0.5, 0), (1, 0.38), (0.81, 1), (0.19, 1), (0, 0.38))),
    Shape("hexagonVertical", ((0.5, 0), (1, 0.25), (1, 0.75), (0.5, 1), (0, 0.75), (0, 0.25))),
    Shape("hexagonHorizontal", ((0.25, 0), (0.75, 0), (1, 0.5), (0.75, 1), (0.25, 1), (0, 0.5))),
    Shape("octagon", ((0.3, 0), (0.7, 0), (1, 0.3), (1, 0.7), (0.7, 1), (0.3, 1), (0, 0.7),
           (0, 0.3))),
    Shape("parallelogram", ((0.1, 0), (1, 0), (0.9, 1), (0, 1))),
    Shape("parallelogramUpsideDown", ((0, 0), (0.9, 0), (1, 1), (0.1, 1))),
    Shape("trapezoid", ((0.08, 0), (0.92, 0), (1, 1), (0, 1))),
    Shape("trapezoidUpsideDown", ((0, 0), (1, 0), (0.92, 1), (0.08, 1))),
    Shape("cross", ((1 / 3, 0), (2 / 3, 0), (2 / 3, 1 / 3), (1, 1 / 3), (1, 2 / 3), (2 / 3, 2 / 3),
           (2 / 3, 1), (1 / 3, 1), (1 / 3, 2 / 3), (0, 2 / 3), (0, 1 / 3), (1 / 3, 1 / 3))),
    Shape("chevron", ((0, 0), (0.9, 0), (1, 0.5), (0.9, 1), (0, 1), (0.1, 0.5))),
    Shape("arrowPentagon", ((0, 0), (0.9, 0), (1, 0.5), (0.9, 1), (0, 1))),
    Shape("arrowRight", _RIGHT),
    Shape("arrowLeft", _turn(_RIGHT, "left")),
    Shape("arrowTop", _turn(_RIGHT, "up")),
    Shape("arrowBottom", _turn(_RIGHT, "down")),
]}

BORDER_STYLES = {"solid": "solid", "dashed": "shortDashes", "dotted": "dots"}
LINE_STYLES = BORDER_STYLES
LINE_ENDS = ("none", "arrow", "triangle", "bar", "circle", "square", "diamond",
             "outlineCircle", "outlineSquare", "outlineDiamond")
TEXT_EFFECTS = {
    # name: (Lido effect name, default settings) — colours are filled in by the writer
    "shadow": ("shadow", {"offset": 30, "direction": -45, "blur": 12, "transparency": 40}),
    "lift": ("lift", {"intensity": 50}),
    "hollow": ("hollow", {"thickness": 50}),
}


def shape_contains(name: str, u: float, v: float) -> bool:
    """Is the unit-square point (u, v) inside shape `name`?"""
    shape = SHAPES.get(name) or SHAPES["rectangle"]
    if name == "circle":
        return (u - 0.5) ** 2 + (v - 0.5) ** 2 <= 0.25
    if not shape.points:
        return 0 <= u <= 1 and 0 <= v <= 1
    return contains([list(shape.points)], u, v)


# -- frames ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    name: str
    path: str
    x: float
    y: float
    w: float
    h: float
    holes: bool  # even-odd (the ring); letters are treated as solid for the checks

    @property
    def aspect(self) -> float:
        return self.w / self.h


@lru_cache(maxsize=1)
def frames() -> dict[str, Frame]:
    data = json.loads(library.path("frame_outlines.json").read_text())
    return {name: Frame(name, **spec) for name, spec in data.items()}


@lru_cache(maxsize=64)
def _frame_polys(name: str):
    f = frames()[name]
    return [[((x - f.x) / f.w, (y - f.y) / f.h) for x, y in poly] for poly in flatten(f.path)]


def frame_contains(name: str, u: float, v: float) -> bool:
    polys = _frame_polys(name)
    if frames()[name].holes:
        return contains(polys, u, v)
    return any(contains([p], u, v) for p in polys)
