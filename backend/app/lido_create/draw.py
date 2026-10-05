"""Hand-drawn marker strokes for Lido's `DrawLayer` — a model can't draw freehand, so it
picks a preset and a box, and this draws a slightly wobbly path into it (deterministic
per box, so a template re-renders identically). Paths are in the layer's own space
(0..w, 0..h, written with `scale` 1), smoothed into cubic curves like the editor's."""

from __future__ import annotations

import math
import random

Point = tuple[float, float]

# Every preset `draw_path` can draw. Which of them the AI may use, and the hint it reads
# for each, is the menu in library/draw.yaml.
DRAW_PRESETS = ("underline", "double_underline", "circle", "arrow", "squiggle", "zigzag",
                "sparkle", "check")


def _smooth(points: list[Point]) -> str:
    """Catmull-Rom through the points, as a cubic path."""
    if len(points) < 2:
        return ""
    out = [f"M {points[0][0]:.2f},{points[0][1]:.2f}"]
    pts = [points[0], *points, points[-1]]
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        out.append(f"C {c1[0]:.2f},{c1[1]:.2f} {c2[0]:.2f},{c2[1]:.2f} {p2[0]:.2f},{p2[1]:.2f}")
    return " ".join(out)


def _line(a: Point, b: Point, n: int, rng: random.Random, wobble: float) -> list[Point]:
    return [(a[0] + (b[0] - a[0]) * t + rng.uniform(-wobble, wobble) * 0.3,
             a[1] + (b[1] - a[1]) * t + rng.uniform(-wobble, wobble))
            for t in (i / (n - 1) for i in range(n))]


def draw_path(preset: str, w: float, h: float, width: float, seed: int = 0) -> tuple[str, list[Point]]:
    """(path d, sample points along the stroke) for a preset drawn inside w x h. The
    stroke is inset by half its width so it stays inside the box."""
    rng = random.Random(seed)
    m = width / 2 + 1
    x0, y0, x1, y1 = m, m, max(m + 1, w - m), max(m + 1, h - m)
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    wob = min(h, w) * 0.06 + 1
    strokes: list[list[Point]] = []
    if preset == "underline":
        # a flat marker stroke that rises slightly, the way a hand draws it
        strokes.append(_line((x0, cy + ry * 0.3), (x1, cy - ry * 0.3), 7, rng, wob * 0.5))
    elif preset == "double_underline":
        strokes.append(_line((x0, y0 + ry * 0.5), (x1, y0 + ry * 0.3), 6, rng, wob * 0.4))
        strokes.append(_line((x0 + rx * 0.15, y1 - ry * 0.3), (x1 - rx * 0.1, y1 - ry * 0.5),
                             6, rng, wob * 0.4))
    elif preset == "circle":
        start = rng.uniform(-2.6, -2.2)
        pts = []
        for i in range(19):  # a bit more than a full turn: the end overlaps the start
            t = start + i / 18 * 2 * math.pi * 1.08
            k = 1 + rng.uniform(-0.04, 0.04)
            pts.append((cx + rx * k * math.cos(t), cy + ry * k * math.sin(t)))
        strokes.append(pts)
    elif preset == "arrow":
        a, b = (x0, y1), (x1, y0 + ry * 0.35)
        bend = (cx - rx * 0.2, cy - ry * 0.55)
        shaft = [((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * bend[0] + t * t * b[0],
                  (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * bend[1] + t * t * b[1])
                 for t in (i / 8 for i in range(9))]
        strokes.append(shaft)
        ang = math.atan2(b[1] - shaft[-2][1], b[0] - shaft[-2][0])
        head = min(w, h) * 0.28
        for side in (-1, 1):
            a2 = ang + math.pi - side * 0.5
            strokes.append([b, (b[0] + head * math.cos(a2), b[1] + head * math.sin(a2))])
    elif preset == "squiggle":
        n = max(3, round(w / max(h, 1) * 1.5))
        strokes.append([(x0 + (x1 - x0) * i / (n * 4), cy + ry * 0.8 * math.sin(i * math.pi / 2)
                         + rng.uniform(-wob, wob) * 0.2) for i in range(n * 4 + 1)])
    elif preset == "zigzag":
        n = max(3, round(w / max(h, 1) * 1.2))
        strokes.append([(x0 + (x1 - x0) * i / (n * 2), y0 if i % 2 else y1)
                        for i in range(n * 2 + 1)])
        return " ".join(f"M {p[0]:.2f},{p[1]:.2f}" if i == 0 else f"L {p[0]:.2f},{p[1]:.2f}"
                        for s in strokes for i, p in enumerate(s)), strokes[0]
    elif preset == "sparkle":
        base, reach = (cx, y1), min(rx, y1 - y0)  # rays fan upwards from the bottom middle
        for ang in (-150, -90, -30):
            r = math.radians(ang + rng.uniform(-6, 6))
            strokes.append([(base[0] + reach * 0.35 * math.cos(r), base[1] + reach * 0.35 * math.sin(r)),
                            (base[0] + reach * math.cos(r), base[1] + reach * math.sin(r))])
    elif preset == "check":
        strokes.append([(x0, cy), (x0 + rx * 0.7, y1), (x1, y0)])
        return (f"M {strokes[0][0][0]:.2f},{strokes[0][0][1]:.2f} "
                + " ".join(f"L {x:.2f},{y:.2f}" for x, y in strokes[0][1:])), strokes[0]
    else:
        raise ValueError(f"unknown draw preset {preset!r}")
    path = " ".join(_smooth(s) if len(s) > 2 else
                    f"M {s[0][0]:.2f},{s[0][1]:.2f} L {s[1][0]:.2f},{s[1][1]:.2f}"
                    for s in strokes)
    samples = [p for s in strokes for p in s]
    return path, samples
