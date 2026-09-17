"""Coordinate system and transforms — IMPLEMENTATION_PLAN §0.6.

Origin top-left, y down, units = canvas px at scale 1. `rotation` is degrees clockwise
about the frame **centre**. Group transforms compose: a child's frame is relative to
its group's frame origin.

§0.6: "Never duplicate transform math in the editor or the exporter. Both call these."
Per ADR 0001 the editor calls them transitively, by consuming the draw list this module
produces.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.schema.doc import Frame, GroupLayer


@dataclass(frozen=True)
class Mat:
    """Affine 2x3, canvas2d convention: x' = a*x + c*y + e ; y' = b*x + d*y + f."""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def mul(self, o: Mat) -> Mat:
        """self ∘ o — apply `o` first, then `self`."""
        return Mat(
            a=self.a * o.a + self.c * o.b,
            b=self.b * o.a + self.d * o.b,
            c=self.a * o.c + self.c * o.d,
            d=self.b * o.c + self.d * o.d,
            e=self.a * o.e + self.c * o.f + self.e,
            f=self.b * o.e + self.d * o.f + self.f,
        )

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def det(self) -> float:
        return self.a * self.d - self.b * self.c

    def invert(self) -> Mat:
        det = self.det()
        if abs(det) < 1e-12:
            raise ValueError("matrix is singular and cannot be inverted")
        return Mat(
            a=self.d / det,
            b=-self.b / det,
            c=-self.c / det,
            d=self.a / det,
            e=(self.c * self.f - self.d * self.e) / det,
            f=(self.b * self.e - self.a * self.f) / det,
        )

    def as_dict(self) -> dict[str, float]:
        return {"a": self.a, "b": self.b, "c": self.c, "d": self.d, "e": self.e, "f": self.f}


IDENTITY = Mat()


def translate(tx: float, ty: float) -> Mat:
    return Mat(e=tx, f=ty)


def scale(sx: float, sy: float | None = None) -> Mat:
    return Mat(a=sx, d=sx if sy is None else sy)


def rotate_deg(deg: float) -> Mat:
    r = math.radians(deg)
    cos, sin = math.cos(r), math.sin(r)
    return Mat(a=cos, b=sin, c=-sin, d=cos)


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def intersects(self, o: Rect) -> bool:
        return not (self.right <= o.x or o.right <= self.x
                    or self.bottom <= o.y or o.bottom <= self.y)

    def intersection(self, o: Rect) -> Rect:
        x0, y0 = max(self.x, o.x), max(self.y, o.y)
        x1, y1 = min(self.right, o.right), min(self.bottom, o.bottom)
        return Rect(x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0))

    def union(self, o: Rect) -> Rect:
        """The smallest rect containing both — how a pair of linked layers is measured."""
        x0, y0 = min(self.x, o.x), min(self.y, o.y)
        x1, y1 = max(self.right, o.right), max(self.bottom, o.bottom)
        return Rect(x0, y0, x1 - x0, y1 - y0)

    def inflate(self, by: float) -> Rect:
        return Rect(self.x - by, self.y - by, self.w + 2 * by, self.h + 2 * by)

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


def frame_matrix(frame: Frame) -> Mat:
    """Map the layer's local space (origin = frame top-left, unrotated) into its parent.

    Rotation and flips are about the frame centre, per §0.6.
    """
    cx, cy = frame.w / 2, frame.h / 2
    m = translate(frame.x + cx, frame.y + cy)
    if frame.rotation:
        m = m.mul(rotate_deg(frame.rotation))
    if frame.flip_x or frame.flip_y:
        m = m.mul(scale(-1 if frame.flip_x else 1, -1 if frame.flip_y else 1))
    return m.mul(translate(-cx, -cy))


def local_to_world(layer: Any, ancestors: Iterable[GroupLayer] = ()) -> Mat:
    """Compose outermost ancestor first, then inwards, then the layer itself."""
    m = IDENTITY
    for group in ancestors:
        m = m.mul(frame_matrix(group.frame))
    return m.mul(frame_matrix(layer.frame))


def world_bounds(layer: Any, ancestors: Iterable[GroupLayer] = ()) -> Rect:
    """Axis-aligned bounding box of the layer's frame in canvas space."""
    m = local_to_world(layer, ancestors)
    w, h = layer.frame.w, layer.frame.h
    pts = [m.apply(0, 0), m.apply(w, 0), m.apply(w, h), m.apply(0, h)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def contains_point(layer: Any, ancestors: Iterable[GroupLayer], px: float, py: float) -> bool:
    """Exact (rotation-aware) containment, by inverting into the layer's local space."""
    if layer.frame.w <= 0 or layer.frame.h <= 0:
        return False
    try:
        inv = local_to_world(layer, ancestors).invert()
    except ValueError:
        return False
    lx, ly = inv.apply(px, py)
    return 0 <= lx <= layer.frame.w and 0 <= ly <= layer.frame.h


def hit_test(doc: Any, px: float, py: float, *, include_locked: bool = False) -> str | None:
    """Topmost layer under the point, or None. Paint order is bottom-first, so search
    the list in reverse."""

    def search(layers: list[Any], ancestors: tuple[GroupLayer, ...]) -> str | None:
        for layer in reversed(layers):
            if not layer.visible:
                continue
            if layer.locked and not include_locked:
                continue
            if layer.type == "group":
                hit = search(layer.children, ancestors + (layer,))
                if hit:
                    return hit
                continue
            if contains_point(layer, ancestors, px, py):
                return layer.id
        return None

    return search(doc.layers, ())
