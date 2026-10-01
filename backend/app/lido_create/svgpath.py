"""Just enough SVG path handling for Lido's frame outlines: flatten a `d` string into
polylines, so we can measure its bounds (Lido sizes a frame as `boxSize / scale`) and
hit-test points against it (the design checks). Curves are sampled, which is plenty
for bounds and "is this point inside" at canvas resolution."""

from __future__ import annotations

import math
import re

Point = tuple[float, float]
_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
STEPS = 12  # samples per curve segment


def _cubic(p0, p1, p2, p3, t):
    u = 1 - t
    return (u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1])


def _quad(p0, p1, p2, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def _arc(p0, rx, ry, phi, large, sweep, p1) -> list[Point]:
    """SVG elliptical arc (endpoint parameterisation) sampled into points."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    phi = math.radians(phi)
    cos, sin = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = cos * dx + sin * dy, -sin * dx + cos * dy
    rx, ry = abs(rx), abs(ry)
    lam = x1**2 / rx**2 + y1**2 / ry**2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    k = math.sqrt(max(0.0, num / den)) * (-1 if large == sweep else 1)
    cx1, cy1 = k * rx * y1 / ry, -k * ry * x1 / rx
    cx = cos * cx1 - sin * cy1 + (p0[0] + p1[0]) / 2
    cy = sin * cx1 + cos * cy1 + (p0[1] + p1[1]) / 2

    def angle(u, v):
        a = math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])
        return a

    t1 = angle((1, 0), ((x1 - cx1) / rx, (y1 - cy1) / ry))
    dt = angle(((x1 - cx1) / rx, (y1 - cy1) / ry), ((-x1 - cx1) / rx, (-y1 - cy1) / ry))
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    out = []
    for i in range(1, STEPS + 1):
        t = t1 + dt * i / STEPS
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cos * x - sin * y + cx, sin * x + cos * y + cy))
    return out


def flatten(d: str) -> list[list[Point]]:
    """The path as closed polylines, one per subpath."""
    tokens = _TOKEN.findall(d)
    subpaths: list[list[Point]] = []
    cur: list[Point] = []
    pos: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    last_ctrl: Point | None = None
    cmd = ""
    i = 0
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                if cur:
                    subpaths.append(cur)
                cur, pos, last_ctrl = [], start, None
                continue
        n = _ARGS[cmd.upper()]
        if i + n > len(tokens) or any(t.isalpha() for t in tokens[i:i + n]):
            break  # malformed tail
        a = [float(t) for t in tokens[i:i + n]]
        i += n
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = pos if rel else (0.0, 0.0)
        if c == "M":
            if cur:
                subpaths.append(cur)
            pos = (ox + a[0], oy + a[1])
            start, cur = pos, [pos]
            cmd = "l" if rel else "L"  # extra pairs after M are line-tos
            last_ctrl = None
        elif c == "L":
            pos = (ox + a[0], oy + a[1])
            cur.append(pos)
            last_ctrl = None
        elif c == "H":
            pos = ((pos[0] if rel else 0) + a[0], pos[1])
            cur.append(pos)
            last_ctrl = None
        elif c == "V":
            pos = (pos[0], (pos[1] if rel else 0) + a[0])
            cur.append(pos)
            last_ctrl = None
        elif c in "CS":
            if c == "C":
                p1 = (ox + a[0], oy + a[1])
                p2, p3 = (ox + a[2], oy + a[3]), (ox + a[4], oy + a[5])
            else:
                p1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl \
                    else pos
                p2, p3 = (ox + a[0], oy + a[1]), (ox + a[2], oy + a[3])
            cur += [_cubic(pos, p1, p2, p3, k / STEPS) for k in range(1, STEPS + 1)]
            last_ctrl, pos = p2, p3
        elif c in "QT":
            if c == "Q":
                p1, p2 = (ox + a[0], oy + a[1]), (ox + a[2], oy + a[3])
            else:
                p1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl \
                    else pos
                p2 = (ox + a[0], oy + a[1])
            cur += [_quad(pos, p1, p2, k / STEPS) for k in range(1, STEPS + 1)]
            last_ctrl, pos = p1, p2
        elif c == "A":
            end = (ox + a[5], oy + a[6])
            cur += _arc(pos, a[0], a[1], a[2], int(a[3]), int(a[4]), end)
            pos, last_ctrl = end, None
    if cur:
        subpaths.append(cur)
    return [s for s in subpaths if len(s) >= 3]


def bounds(polys: list[list[Point]]) -> tuple[float, float, float, float]:
    xs = [x for p in polys for x, _ in p]
    ys = [y for p in polys for _, y in p]
    return min(xs), min(ys), max(xs), max(ys)


def contains(polys: list[list[Point]], x: float, y: float) -> bool:
    """Even-odd fill over every subpath (so a letter's counter is a hole)."""
    inside = False
    for pts in polys:
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside
