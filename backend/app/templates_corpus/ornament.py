"""Procedural decorative motifs — IMPLEMENTATION_PLAN §1.2.

Reference-quality festival and promotional work is roughly half typography and half
ornament: a gold border and corner flourishes, a marigold garland along the top edge,
bunting and confetti, a starburst behind the subject, a divider under a headline. Without
any of it a design reads as a photograph with words placed on top, which is exactly how
the first version of this pipeline looked.

Ornament is generated as vector path data rather than as imagery, for four reasons that
all matter here:

  * it costs nothing and adds no latency, so a skeleton can use it freely;
  * it is exactly reproducible from a seed, which INV-2 requires;
  * it takes its colour from the palette, so it cannot clash with the design;
  * it cannot contain glyphs, so it can never trip the §1.4.6 glyph gate.

Every motif returns SVG path data in the layer's local space — origin at (0, 0), extent
`w` by `h` — which is the same string both renderers consume through `PathCmd.d`, so
ornament satisfies INV-3 by construction.
"""

from __future__ import annotations

import math
import random

# Motifs whose geometry is open contours: the slot must stroke them, not fill them.
STROKE_MOTIFS = frozenset({"border", "corners", "arch", "frame-rule", "frame-round"})

# Motifs built from closed shapes, filled by the slot's palette colour.
# Compositional, as opposed to decorative. The decorative motifs frame a design; these
# ARE the design in flat-graphic promotional work — the colour blobs a fashion sale is
# built on, the diagonal stripe field behind a sneaker, the banner a price sits in, the
# seal a discount is stamped with.
COMPOSITIONAL_MOTIFS = frozenset({
    "blob", "wave", "stripes", "ribbon", "badge", "arc-band",
})

FILL_MOTIFS = frozenset({
    "garland", "bunting", "rays", "confetti", "dots", "divider", "chevrons", "scallop",
    "grid-dots", "zigzag", "diamond", "tag", "hexagon", "arch-solid", "leaf", "triangle",
}) | COMPOSITIONAL_MOTIFS

# Pictograms. A tick beside a service line, a handset beside a phone number, a pin
# beside an address — the small vector marks that turn a list of sentences into a
# checklist and a string of digits into a "call us" block. Reference-quality promotional
# work is full of them and the corpus had no way to draw one.
#
# They are kept apart from the decorative motifs above and belong to no family, because
# substitution is meaningless here: a tick and a handset are not two takes on the same
# ornament, they are two different words. `motif_assignment` only ever remaps within a
# family, so keeping icons out of every family is what stops art direction turning a
# checklist into a row of telephones.
ICON_LINE_MOTIFS = frozenset({
    "icon-check", "icon-check-circle", "icon-phone", "icon-pin", "icon-mail",
    "icon-globe", "icon-clock", "icon-arrow", "icon-ring",
})
ICON_FILL_MOTIFS = frozenset({
    "icon-star", "icon-play", "icon-heart", "icon-quote", "icon-spark", "icon-dot",
})
ICON_MOTIFS = ICON_LINE_MOTIFS | ICON_FILL_MOTIFS

# Motifs whose geometry is fully determined by the box they are given: a frame is a
# frame. They ignore their seed, so offering to re-roll one would be a dead button.
STRUCTURAL_MOTIFS = frozenset({"border", "corners", "frame-rule", "frame-round",
                               "diamond", "hexagon", "arch-solid", "triangle", "leaf",
                               "tag", "zigzag", "grid-dots"}) | ICON_MOTIFS

MOTIFS = STROKE_MOTIFS | FILL_MOTIFS | ICON_MOTIFS

# Motifs grouped by the compositional job they do. A skeleton author places a *band*
# along the top edge or a *frame* around the canvas; which band, which frame, is a
# question about this particular design, not about the layout — a garland belongs on a
# wedding invitation and bunting on a school fete, and they occupy the same slot.
#
# Substituting within a family is safe by construction: every family is homogeneous in
# stroke-versus-fill, so a slot's authored `strokeWidthN` stays correct after a swap.
# A test enforces that, because getting it wrong floods a filled shape with an outline.
MOTIF_FAMILIES: dict[str, tuple[str, ...]] = {
    "frame": ("border", "corners", "arch", "frame-rule", "frame-round"),
    "rule": ("divider", "chevrons", "scallop", "zigzag"),
    "band": ("garland", "bunting"),
    "field": ("blob", "wave", "stripes", "arc-band"),
    "scatter": ("confetti", "dots", "rays", "grid-dots"),
    "seal": ("badge", "ribbon", "diamond", "tag"),
    # Solid silhouettes used as a graphic element in their own right — the shape a
    # photograph is masked into, the block a price sits on.
    "shape": ("hexagon", "arch-solid", "leaf", "triangle"),
}

_FAMILY_OF = {motif: family
              for family, members in MOTIF_FAMILIES.items() for motif in members}


def family_of(motif: str) -> str | None:
    """Which compositional family a motif belongs to, or None if it is unknown."""
    return _FAMILY_OF.get(motif)


def members_of(family: str) -> tuple[str, ...]:
    return MOTIF_FAMILIES.get(family, ())


def render_motif(motif: str, w: float, h: float, *, seed: int = 0,
                 density: int = 3) -> str:
    """SVG path data for `motif`, sized to a `w` by `h` local box.

    `density` is a coarse 1-5 dial for how much of the motif appears; it is clamped
    rather than validated, because a skeleton asking for too much ornament should be
    quietly toned down, not rejected.
    """
    if w <= 0 or h <= 0:
        return ""
    builder = _BUILDERS.get(motif)
    if builder is None:
        return ""
    density = max(1, min(5, int(density)))
    return builder(float(w), float(h), density, random.Random(seed))


def is_stroked(motif: str) -> bool:
    return motif in STROKE_MOTIFS or motif in ICON_LINE_MOTIFS


def is_icon(motif: str) -> bool:
    """Pictograms are sized, coloured and paired differently from decoration."""
    return motif in ICON_MOTIFS


# --------------------------------------------------------------------------------------
# Path primitives
# --------------------------------------------------------------------------------------


def _n(value: float) -> str:
    """Two decimals is finer than a printer resolves and keeps path strings short."""
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _circle(cx: float, cy: float, r: float) -> str:
    if r <= 0:
        return ""
    return (f"M{_n(cx - r)},{_n(cy)}"
            f"A{_n(r)},{_n(r)} 0 1,0 {_n(cx + r)},{_n(cy)}"
            f"A{_n(r)},{_n(r)} 0 1,0 {_n(cx - r)},{_n(cy)}Z")


def _rect(x: float, y: float, w: float, h: float) -> str:
    if w <= 0 or h <= 0:
        return ""
    return (f"M{_n(x)},{_n(y)}L{_n(x + w)},{_n(y)}"
            f"L{_n(x + w)},{_n(y + h)}L{_n(x)},{_n(y + h)}Z")


def _poly(points: list[tuple[float, float]]) -> str:
    if len(points) < 3:
        return ""
    head = f"M{_n(points[0][0])},{_n(points[0][1])}"
    rest = "".join(f"L{_n(x)},{_n(y)}" for x, y in points[1:])
    return head + rest + "Z"


def _diamond(cx: float, cy: float, rx: float, ry: float) -> str:
    return _poly([(cx, cy - ry), (cx + rx, cy), (cx, cy + ry), (cx - rx, cy)])


def _join(parts: list[str]) -> str:
    return "".join(p for p in parts if p)


def _clip_to_half_plane(polygon: list[tuple[float, float]], nx: float, ny: float,
                        c: float) -> list[tuple[float, float]]:
    """Sutherland-Hodgman clip of a convex polygon against {p : p.n <= c}."""
    if not polygon:
        return []
    out: list[tuple[float, float]] = []
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        cd = current[0] * nx + current[1] * ny - c
        pd = previous[0] * nx + previous[1] * ny - c
        if cd <= 0:
            if pd > 0:
                t = pd / (pd - cd)
                out.append((previous[0] + t * (current[0] - previous[0]),
                            previous[1] + t * (current[1] - previous[1])))
            out.append(current)
        elif pd <= 0:
            t = pd / (pd - cd)
            out.append((previous[0] + t * (current[0] - previous[0]),
                        previous[1] + t * (current[1] - previous[1])))
    return out


def _smooth_closed(points: list[tuple[float, float]], tension: float = 0.36) -> str:
    """A closed cubic spline through `points` — Catmull-Rom converted to Beziers.

    Used for organic shapes, where the whole effect depends on the curve never showing
    a corner.
    """
    count = len(points)
    if count < 3:
        return ""
    parts = [f"M{_n(points[0][0])},{_n(points[0][1])}"]
    for index in range(count):
        p0 = points[(index - 1) % count]
        p1 = points[index]
        p2 = points[(index + 1) % count]
        p3 = points[(index + 2) % count]
        c1 = (p1[0] + (p2[0] - p0[0]) * tension / 2,
              p1[1] + (p2[1] - p0[1]) * tension / 2)
        c2 = (p2[0] - (p3[0] - p1[0]) * tension / 2,
              p2[1] - (p3[1] - p1[1]) * tension / 2)
        parts.append(f"C{_n(c1[0])},{_n(c1[1])} {_n(c2[0])},{_n(c2[1])} "
                     f"{_n(p2[0])},{_n(p2[1])}")
    parts.append("Z")
    return "".join(parts)


# --------------------------------------------------------------------------------------
# Motifs
# --------------------------------------------------------------------------------------


def _border(w: float, h: float, density: int, rng: random.Random) -> str:
    """Concentric rules inset from the edge — the gold frame around a festival poster."""
    rings = 1 if density <= 2 else 2
    unit = min(w, h)
    parts = []
    for index in range(rings):
        inset = unit * (0.012 + 0.028 * index)
        parts.append(_rect(inset, inset, w - 2 * inset, h - 2 * inset))
    return _join(parts)


def _corners(w: float, h: float, density: int, rng: random.Random) -> str:
    """A quarter-round flourish in each corner, mirrored so the four agree."""
    reach = min(w, h) * (0.10 + 0.02 * density)
    inset = min(w, h) * 0.035
    curls = 2 if density >= 3 else 1

    def one(ox: float, oy: float, sx: float, sy: float) -> str:
        parts = []
        for index in range(curls):
            span = reach * (1.0 - 0.34 * index)
            # An L-shaped bracket closed by a quarter arc, plus a small inward hook —
            # enough structure to read as ornament at a glance.
            x0, y0 = ox + sx * inset, oy + sy * (inset + span)
            x1, y1 = ox + sx * (inset + span), oy + sy * inset
            parts.append(
                f"M{_n(x0)},{_n(y0)}"
                f"Q{_n(ox + sx * inset)},{_n(oy + sy * inset)} {_n(x1)},{_n(y1)}"
            )
            hook = span * 0.28
            parts.append(
                f"M{_n(x1)},{_n(y1)}"
                f"q{_n(sx * hook)},{_n(0)} {_n(sx * hook)},{_n(sy * hook)}"
            )
        return _join(parts)

    return _join([one(0, 0, 1, 1), one(w, 0, -1, 1),
                  one(0, h, 1, -1), one(w, h, -1, -1)])


def _garland(w: float, h: float, density: int, rng: random.Random) -> str:
    """Swags of blossoms hung across the width — the marigold string over a doorway."""
    swags = max(1, density)
    span = w / swags
    blossom = min(span * 0.055, h * 0.17)
    # Every edge of the box has to clear the blossoms, which are what actually overhang:
    #   - the string sits a blossom's radius down, or its end blossoms crown over the top
    #     (the radius tapers to 0.72 at the ends, which is still more than a 6% inset);
    #   - the swag is inset by a radius at each end, so no blossom runs off the sides;
    #   - the drop clears the leaf as well as the blossom, the leaf hanging a further
    #     0.42 radius below the blossom's own 1.25 centre offset.
    string_y = max(h * 0.06, blossom * 0.75)
    drop = max(0.0, min(h * rng.uniform(0.55, 0.68),
                        h * 0.98 - string_y - blossom * 1.67))
    parts = []
    for swag in range(swags):
        left = swag * span
        steps = max(8, int(span / max(1.0, blossom * 1.5)))
        reach = max(0.0, span - 2 * blossom)
        for step in range(steps + 1):
            t = step / steps
            x = left + blossom + t * reach
            # A parabola is a close enough catenary at these spans and far cheaper.
            y = string_y + drop * (1 - (2 * t - 1) ** 2)
            radius = blossom * (0.72 + 0.28 * math.sin(t * math.pi))
            parts.append(_circle(x, y, radius))
            if step % 2 == 0:
                # A smaller leaf tucked under alternate blossoms adds depth.
                parts.append(_circle(x, y + radius * 1.25, radius * 0.42))
    return _join(parts)


def _bunting(w: float, h: float, density: int, rng: random.Random) -> str:
    """Triangular flags on a slack string."""
    flags = max(3, density * 3)
    span = w / flags
    string_y = h * 0.10
    # Bounded so string_y + sag + flag_h stays inside the box at every draw.
    sag = h * rng.uniform(0.16, 0.24)
    flag_h = h * rng.uniform(0.55, 0.64)
    parts = [_rect(0, string_y, w, max(1.0, h * 0.018))]
    for index in range(flags):
        t = (index + 0.5) / flags
        x = t * w
        y = string_y + sag * (1 - (2 * t - 1) ** 2)
        half = span * 0.38
        parts.append(_poly([(x - half, y), (x + half, y), (x, y + flag_h)]))
    return _join(parts)


def _ray_to_edge(cx: float, cy: float, angle: float, w: float,
                 h: float) -> tuple[float, float]:
    """Where a ray from the centre meets the box boundary."""
    dx, dy = math.cos(angle), math.sin(angle)
    distances = []
    if abs(dx) > 1e-9:
        distances.append(((w if dx > 0 else 0.0) - cx) / dx)
    if abs(dy) > 1e-9:
        distances.append(((h if dy > 0 else 0.0) - cy) / dy)
    reach = min(d for d in distances if d > 0) if any(d > 0 for d in distances) else 0.0
    return cx + dx * reach, cy + dy * reach


def _rays(w: float, h: float, density: int, rng: random.Random) -> str:
    """A starburst from the centre — the sunburst behind a grand-opening headline.

    Wedges terminate on the box boundary rather than at a fixed radius. Shape layers are
    not clipped to their frame, so a wedge long enough to reach the corners would other-
    wise hang a long way outside the ornament's own box and over the rest of the design.
    """
    count = 8 + density * 4
    spin = rng.uniform(0.0, math.tau / count)
    cx, cy = w / 2, h / 2
    half_angle = math.pi / count * 0.52
    # Corner directions, so a wedge spanning one wraps around it instead of cutting it.
    corners = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
    corner_angles = [(math.atan2(y - cy, x - cx) % math.tau, (x, y)) for x, y in corners]

    parts = []
    for index in range(0, count, 2):   # alternate wedges, so the ground shows between
        angle = (index / count) * math.tau + spin
        start, end = angle - half_angle, angle + half_angle
        points = [(cx, cy), _ray_to_edge(cx, cy, start, w, h)]
        for corner_angle, point in sorted(corner_angles):
            if (corner_angle - start) % math.tau <= (end - start) % math.tau:
                points.append(point)
        points.append(_ray_to_edge(cx, cy, end, w, h))
        parts.append(_poly(points))
    return _join(parts)


def _confetti(w: float, h: float, density: int, rng: random.Random) -> str:
    """A seeded scatter of small shapes. Same seed, same scatter — INV-2."""
    count = density * 14
    unit = min(w, h)
    parts = []
    for _ in range(count):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        size = unit * rng.uniform(0.008, 0.022)
        kind = rng.random()
        if kind < 0.4:
            parts.append(_circle(x, y, size * 0.5))
        elif kind < 0.75:
            angle = rng.uniform(0, math.pi)
            dx, dy = math.cos(angle) * size, math.sin(angle) * size
            thick = size * 0.36
            px, py = -dy / size * thick, dx / size * thick
            parts.append(_poly([(x - dx, y - dy), (x + dx, y + dy),
                                (x + dx + px, y + dy + py), (x - dx + px, y - dy + py)]))
        else:
            parts.append(_diamond(x, y, size * 0.55, size * 0.8))
    return _join(parts)


def _dots(w: float, h: float, density: int, rng: random.Random) -> str:
    """A regular dot grid — the halftone block in a promotional layout."""
    # The cell has to fit the box on BOTH axes. Deriving one square step from the width
    # alone puts the single row of a wide, short box at half a cell height — outside the
    # box entirely — and shape layers are not clipped to their frames, so those dots
    # land on whatever the ornament happens to sit above.
    columns = max(2, density * 3)
    step_x = w / columns
    rows = max(1, round(h / step_x))
    step_y = h / rows
    radius = min(step_x, step_y) * rng.uniform(0.13, 0.20)
    # Each dot may drift within its own cell, never out of it, so the grid keeps its
    # rhythm while losing the mechanical look of a perfect lattice.
    play_x = max(0.0, step_x / 2 - radius)
    play_y = max(0.0, step_y / 2 - radius)
    parts = []
    for row in range(rows):
        for column in range(columns):
            parts.append(_circle((column + 0.5) * step_x + rng.uniform(-play_x, play_x),
                                 (row + 0.5) * step_y + rng.uniform(-play_y, play_y),
                                 radius))
    return _join(parts)


def _chevrons(w: float, h: float, density: int, rng: random.Random) -> str:
    """A run of small triangles, all pointing the same way."""
    count = max(2, density * 2)
    step = w / count
    reach = rng.uniform(0.50, 0.72)
    parts = []
    for index in range(count):
        x = index * step
        parts.append(_poly([(x, 0), (x + step * reach, h / 2), (x, h)]))
    return _join(parts)


def _scallop(w: float, h: float, density: int, rng: random.Random) -> str:
    """A scalloped edge — a row of half-discs along the top."""
    # Scallops must touch to read as an edge rather than a row of dots, so the radius is
    # half the step. The bump then rises 2*radius into a band only `h` deep, so the step
    # can be at most `h` — below that the scallops overrun the band and render as a row
    # of whole circles. The step, not the radius, is what gives.
    # Jitter upward only: more scallops are smaller scallops, which is always safe,
    # whereas fewer would overrun the band depth.
    count = max(3, density * 3, math.ceil(w / max(1.0, h))) + rng.randint(0, 2)
    step = w / count
    radius = step / 2
    parts = [_circle((index + 0.5) * step, h - radius, radius) for index in range(count)]
    parts.append(_rect(0, h - radius, w, radius))
    return _join(parts)


def _divider(w: float, h: float, density: int, rng: random.Random) -> str:
    """A rule broken by a centred diamond — the mark under a ceremonial headline."""
    thickness = max(1.0, h * 0.10)
    gap = min(w * rng.uniform(0.13, 0.20), h * 2.2)
    rule = (w - gap) / 2
    mid = h / 2
    parts = [_rect(0, mid - thickness / 2, rule, thickness),
             _rect(w - rule, mid - thickness / 2, rule, thickness),
             _diamond(w / 2, mid, gap * 0.16, h * 0.42)]
    if density >= 4:
        parts.append(_diamond(w / 2 - gap * 0.3, mid, gap * 0.07, h * 0.2))
        parts.append(_diamond(w / 2 + gap * 0.3, mid, gap * 0.07, h * 0.2))
    return _join(parts)


def _arch(w: float, h: float, density: int, rng: random.Random) -> str:
    """A doorway arch — a frame for a centred subject."""
    # An elliptical arc, not a circular one: on a frame wider than it is tall a circular
    # arc's radius cannot span the chord, and SVG resolves that by growing the radius —
    # springing the arch up out of its own box. The springline sits at `rise` so the
    # crown lands exactly on the top edge.
    rise = min(w / 2, h) * rng.uniform(0.86, 1.0)
    return (f"M0,{_n(h)}L0,{_n(rise)}"
            f"A{_n(w / 2)},{_n(rise)} 0 0,1 {_n(w)},{_n(rise)}"
            f"L{_n(w)},{_n(h)}")


def _frame_rule(w: float, h: float, density: int, rng: random.Random) -> str:
    """A single hairline rule inset from the edge, without the second ring."""
    inset = min(w, h) * 0.02
    return _rect(inset, inset, w - 2 * inset, h - 2 * inset)


def _blob(w: float, h: float, density: int, rng: random.Random) -> str:
    """An organic colour shape. The flat-graphic backdrop, not an ornament.

    Drawn to fill the box rather than sit inside it: a blob is a region of colour and
    reads as a mistake if it floats with a margin around it.
    """
    # Few lobes, strongly varied. Many small wobbles average out into an ellipse once
    # the spline smooths them — the asymmetry has to be coarse to survive smoothing.
    lobes = 5 + density % 3
    cx, cy = w / 2, h / 2
    points = []
    for index in range(lobes):
        angle = (index / lobes) * math.tau + rng.uniform(-0.22, 0.22)
        # The 0.70 base leaves headroom for both the wobble and the spline's overshoot
        # between control points, which together would push the curve past the box.
        wobble = 0.70 * (1.0 + rng.uniform(-0.34, 0.34))
        points.append((cx + math.cos(angle) * cx * wobble,
                       cy + math.sin(angle) * cy * wobble))
    return _smooth_closed(points, tension=0.5)


def _wave(w: float, h: float, density: int, rng: random.Random) -> str:
    """A band with a sine edge — the soft division between two colour fields."""
    cycles = max(1, density - 1)
    amplitude = h * rng.uniform(0.20, 0.34)
    phase = rng.uniform(0.0, math.tau)
    mid = h * 0.5
    steps = max(24, cycles * 16)
    top = [(w * i / steps,
            mid - amplitude * math.sin(math.tau * cycles * i / steps + phase))
           for i in range(steps + 1)]
    parts = [f"M{_n(top[0][0])},{_n(top[0][1])}"]
    parts += [f"L{_n(x)},{_n(y)}" for x, y in top[1:]]
    parts.append(f"L{_n(w)},{_n(h)}L0,{_n(h)}Z")
    return "".join(parts)


def _stripes(w: float, h: float, density: int, rng: random.Random) -> str:
    """A diagonal stripe field, clipped exactly to the box.

    Each stripe is the box intersected with the band between two parallel lines, so the
    field fills its frame precisely instead of a rotated rectangle spilling past it.
    """
    angle = math.radians(rng.uniform(45.0, 75.0))
    nx, ny = math.cos(angle), math.sin(angle)
    box = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
    projections = [x * nx + y * ny for x, y in box]
    low, high = min(projections), max(projections)

    period = max(w, h) / max(3, density * 4)
    bar = period * rng.uniform(0.38, 0.52)
    parts = []
    offset = low - period
    while offset < high + period:
        clipped = _clip_to_half_plane(box, -nx, -ny, -offset)
        clipped = _clip_to_half_plane(clipped, nx, ny, offset + bar)
        if len(clipped) >= 3:
            parts.append(_poly(clipped))
        offset += period
    return _join(parts)


def _ribbon(w: float, h: float, density: int, rng: random.Random) -> str:
    """A banner with notched tails — what a price or a label sits in."""
    # A V cut INTO each end, not added onto it. Building the ends as separate outward
    # polygons bulges the banner instead of notching it.
    notch = min(w * rng.uniform(0.07, 0.13), h * 0.55)
    return _poly([
        (0, 0), (w, 0), (w - notch, h / 2), (w, h), (0, h), (notch, h / 2),
    ])


def _badge(w: float, h: float, density: int, rng: random.Random) -> str:
    """A seal with a spiked edge — the "50% OFF" stamp in a corner."""
    spikes = max(8, 10 + density * 3 + rng.randint(-2, 3))
    cx, cy = w / 2, h / 2
    outer_x, outer_y = w / 2, h / 2
    inner = rng.uniform(0.80, 0.90)
    spin = rng.uniform(0.0, math.tau / spikes)
    points = []
    for index in range(spikes * 2):
        angle = (index / (spikes * 2)) * math.tau + spin
        scale = 1.0 if index % 2 == 0 else inner
        points.append((cx + math.cos(angle) * outer_x * scale,
                       cy + math.sin(angle) * outer_y * scale))
    return _poly(points)


def _arc_band(w: float, h: float, density: int, rng: random.Random) -> str:
    """A thick curved sweep across the box — the swoosh under a hero subject."""
    # Bounded so rise + thickness cannot lift the control point out of the box.
    thickness = h * rng.uniform(0.26, 0.36)
    rise = h * rng.uniform(0.45, 0.58)
    return (f"M0,{_n(h)}"
            f"Q{_n(w / 2)},{_n(h - rise - thickness)} {_n(w)},{_n(h)}"
            f"L{_n(w)},{_n(h)}"
            f"Q{_n(w / 2)},{_n(h - rise)} 0,{_n(h)}Z")


# --------------------------------------------------------------------------------------
# Solid silhouettes
#
# The motifs above decorate a design; these ARE elements of it. A diamond holding a
# discount, a hexagon behind an icon, an arch a portrait is masked into, a leaf tucked
# under a headline. They are deterministic — a diamond is a diamond — so they ignore
# their seed and live in STRUCTURAL_MOTIFS.
# --------------------------------------------------------------------------------------


def _diamond_motif(w: float, h: float, density: int, rng: random.Random) -> str:
    return _diamond(w / 2, h / 2, w / 2, h / 2)


def _hexagon(w: float, h: float, density: int, rng: random.Random) -> str:
    """Flat-top hexagon. Density 4+ turns it point-top, which reads very differently."""
    cx, cy, rx, ry = w / 2, h / 2, w / 2, h / 2
    if density >= 4:
        return _poly([(cx, cy - ry), (cx + rx, cy - ry / 2), (cx + rx, cy + ry / 2),
                      (cx, cy + ry), (cx - rx, cy + ry / 2), (cx - rx, cy - ry / 2)])
    return _poly([(cx - rx / 2, cy - ry), (cx + rx / 2, cy - ry), (cx + rx, cy),
                  (cx + rx / 2, cy + ry), (cx - rx / 2, cy + ry), (cx - rx, cy)])


def _arch_solid(w: float, h: float, density: int, rng: random.Random) -> str:
    """A filled arch — the window shape a portrait sits in. The hollow `arch` outlines
    the same silhouette; this one fills it, so a skeleton can put it behind a subject."""
    r = min(w / 2, h)
    return (f"M0,{_n(h)}L0,{_n(r)}"
            f"A{_n(w / 2)},{_n(r)} 0 0,1 {_n(w)},{_n(r)}"
            f"L{_n(w)},{_n(h)}Z")


def _leaf(w: float, h: float, density: int, rng: random.Random) -> str:
    """A pointed oval — a botanical accent that is not a photograph."""
    return (f"M{_n(w / 2)},0"
            f"C{_n(w)},{_n(h * 0.30)} {_n(w)},{_n(h * 0.70)} {_n(w / 2)},{_n(h)}"
            f"C0,{_n(h * 0.70)} 0,{_n(h * 0.30)} {_n(w / 2)},0Z")


def _triangle(w: float, h: float, density: int, rng: random.Random) -> str:
    return _poly([(w / 2, 0), (w, h), (0, h)])


def _tag(w: float, h: float, density: int, rng: random.Random) -> str:
    """A price tag: a rectangle with one end cut to a point."""
    point = min(w * 0.22, h * 0.5)
    return _poly([(0, h / 2), (point, 0), (w, 0), (w, h), (point, h)])


def _frame_round(w: float, h: float, density: int, rng: random.Random) -> str:
    """A rounded-rectangle outline — the hairline keyline around a photograph."""
    inset = min(w, h) * (0.02 + 0.015 * (density - 1))
    x, y = inset, inset
    bw, bh = w - inset * 2, h - inset * 2
    if bw <= 0 or bh <= 0:
        return ""
    r = min(bw, bh) * 0.12
    return (f"M{_n(x + r)},{_n(y)}L{_n(x + bw - r)},{_n(y)}"
            f"A{_n(r)},{_n(r)} 0 0,1 {_n(x + bw)},{_n(y + r)}"
            f"L{_n(x + bw)},{_n(y + bh - r)}"
            f"A{_n(r)},{_n(r)} 0 0,1 {_n(x + bw - r)},{_n(y + bh)}"
            f"L{_n(x + r)},{_n(y + bh)}"
            f"A{_n(r)},{_n(r)} 0 0,1 {_n(x)},{_n(y + bh - r)}"
            f"L{_n(x)},{_n(y + r)}"
            f"A{_n(r)},{_n(r)} 0 0,1 {_n(x + r)},{_n(y)}Z")


def _grid_dots(w: float, h: float, density: int, rng: random.Random) -> str:
    """A regular dot lattice. `dots` scatters; this one lines up, which is what a
    halftone corner block or a retro shadow field needs."""
    cols = 2 + density * 2
    rows = max(2, round(cols * h / w)) if w > 0 else 3
    r = min(w / cols, h / rows) * 0.22
    parts = []
    for row in range(rows):
        for col in range(cols):
            cx = (col + 0.5) * w / cols
            cy = (row + 0.5) * h / rows
            parts.append(_circle(cx, cy, r))
    return _join(parts)


def _zigzag(w: float, h: float, density: int, rng: random.Random) -> str:
    """A filled chevron ribbon running the width of the box — a rule with energy."""
    teeth = 2 + density * 2
    step = w / teeth
    thickness = h * 0.45
    top = [(index * step, 0 if index % 2 == 0 else h - thickness)
           for index in range(teeth + 1)]
    bottom = [(x, y + thickness) for x, y in reversed(top)]
    return _poly(top + bottom)


# --------------------------------------------------------------------------------------
# Pictograms
#
# Authored in a unit square and centred in whatever box the slot gives them, so a tick
# in a 0.03-wide slot and one in a 0.08-wide slot are the same drawing. Line icons are
# open contours the slot strokes; solid ones are closed and filled. Neither uses the
# seed: an icon that re-rolled into a different drawing would be a bug, not variety.
# --------------------------------------------------------------------------------------


def _icon_space(w: float, h: float):
    """Returns (unit, point-formatter) for a square centred in the slot's box."""
    unit = min(w, h)
    ox, oy = (w - unit) / 2, (h - unit) / 2

    def at(x: float, y: float) -> str:
        return f"{_n(ox + x * unit)},{_n(oy + y * unit)}"

    return unit, ox, oy, at


def _icon_check(w: float, h: float, density: int, rng: random.Random) -> str:
    _, _, _, at = _icon_space(w, h)
    return f"M{at(0.14, 0.52)}L{at(0.39, 0.77)}L{at(0.86, 0.25)}"


def _icon_check_circle(w: float, h: float, density: int, rng: random.Random) -> str:
    """A tick inside a ring — the bullet the reference checklists are built from."""
    unit, ox, oy, at = _icon_space(w, h)
    ring = _circle(ox + unit / 2, oy + unit / 2, unit * 0.46)
    return ring + f"M{at(0.28, 0.52)}L{at(0.44, 0.68)}L{at(0.73, 0.34)}"


def _icon_phone(w: float, h: float, density: int, rng: random.Random) -> str:
    _, _, _, at = _icon_space(w, h)
    return (f"M{at(0.22, 0.14)}"
            f"C{at(0.24, 0.09)} {at(0.30, 0.09)} {at(0.33, 0.13)}"
            f"L{at(0.44, 0.25)}"
            f"C{at(0.47, 0.29)} {at(0.46, 0.33)} {at(0.42, 0.36)}"
            f"L{at(0.35, 0.41)}"
            f"C{at(0.41, 0.54)} {at(0.48, 0.61)} {at(0.61, 0.66)}"
            f"L{at(0.66, 0.59)}"
            f"C{at(0.69, 0.55)} {at(0.73, 0.54)} {at(0.77, 0.57)}"
            f"L{at(0.89, 0.68)}"
            f"C{at(0.93, 0.71)} {at(0.93, 0.77)} {at(0.88, 0.79)}"
            f"C{at(0.70, 0.90)} {at(0.44, 0.80)} {at(0.27, 0.62)}"
            f"C{at(0.12, 0.45)} {at(0.12, 0.26)} {at(0.22, 0.14)}Z")


def _icon_pin(w: float, h: float, density: int, rng: random.Random) -> str:
    unit, ox, oy, at = _icon_space(w, h)
    r = unit * 0.32
    body = (f"M{at(0.50, 0.96)}"
            f"C{at(0.50, 0.96)} {at(0.18, 0.60)} {at(0.18, 0.38)}"
            f"A{_n(r)},{_n(r)} 0 1,1 {at(0.82, 0.38)}"
            f"C{at(0.82, 0.60)} {at(0.50, 0.96)} {at(0.50, 0.96)}Z")
    return body + _circle(ox + unit * 0.50, oy + unit * 0.36, unit * 0.12)


def _icon_mail(w: float, h: float, density: int, rng: random.Random) -> str:
    unit, ox, oy, at = _icon_space(w, h)
    body = _rect(ox + unit * 0.08, oy + unit * 0.22, unit * 0.84, unit * 0.56)
    return body + f"M{at(0.08, 0.24)}L{at(0.50, 0.56)}L{at(0.92, 0.24)}"


def _icon_globe(w: float, h: float, density: int, rng: random.Random) -> str:
    unit, ox, oy, at = _icon_space(w, h)
    cx, cy, r = ox + unit / 2, oy + unit / 2, unit * 0.44
    meridian = (f"M{at(0.50, 0.06)}"
                f"A{_n(unit * 0.22)},{_n(r)} 0 0,0 {at(0.50, 0.94)}"
                f"A{_n(unit * 0.22)},{_n(r)} 0 0,0 {at(0.50, 0.06)}Z")
    equator = f"M{at(0.06, 0.50)}L{at(0.94, 0.50)}"
    return _circle(cx, cy, r) + meridian + equator


def _icon_clock(w: float, h: float, density: int, rng: random.Random) -> str:
    unit, ox, oy, at = _icon_space(w, h)
    return (_circle(ox + unit / 2, oy + unit / 2, unit * 0.44)
            + f"M{at(0.50, 0.24)}L{at(0.50, 0.53)}L{at(0.71, 0.64)}")


def _icon_arrow(w: float, h: float, density: int, rng: random.Random) -> str:
    _, _, _, at = _icon_space(w, h)
    return (f"M{at(0.10, 0.50)}L{at(0.86, 0.50)}"
            f"M{at(0.60, 0.26)}L{at(0.88, 0.50)}L{at(0.60, 0.74)}")


def _icon_ring(w: float, h: float, density: int, rng: random.Random) -> str:
    """A bare circle outline — a bullet, a counter, a floating accent."""
    unit, ox, oy, _ = _icon_space(w, h)
    return _circle(ox + unit / 2, oy + unit / 2, unit * 0.46)


def _icon_star(w: float, h: float, density: int, rng: random.Random) -> str:
    unit, ox, oy, _ = _icon_space(w, h)
    cx, cy = ox + unit / 2, oy + unit / 2
    points = []
    for index in range(10):
        angle = -math.pi / 2 + index * math.pi / 5
        radius = unit * (0.48 if index % 2 == 0 else 0.20)
        points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return _poly(points)


def _icon_play(w: float, h: float, density: int, rng: random.Random) -> str:
    unit, ox, oy, _ = _icon_space(w, h)
    return _poly([(ox + unit * 0.24, oy + unit * 0.12),
                  (ox + unit * 0.88, oy + unit * 0.50),
                  (ox + unit * 0.24, oy + unit * 0.88)])


def _icon_heart(w: float, h: float, density: int, rng: random.Random) -> str:
    _, _, _, at = _icon_space(w, h)
    return (f"M{at(0.50, 0.90)}"
            f"C{at(0.16, 0.66)} {at(0.06, 0.44)} {at(0.14, 0.28)}"
            f"C{at(0.23, 0.10)} {at(0.44, 0.13)} {at(0.50, 0.30)}"
            f"C{at(0.56, 0.13)} {at(0.77, 0.10)} {at(0.86, 0.28)}"
            f"C{at(0.94, 0.44)} {at(0.84, 0.66)} {at(0.50, 0.90)}Z")


def _icon_quote(w: float, h: float, density: int, rng: random.Random) -> str:
    """A pair of solid opening quotes — the mark a pull-quote hangs from."""
    _, _, _, at = _icon_space(w, h)
    def comma(x: float) -> str:
        return (f"M{at(x, 0.20)}"
                f"C{at(x + 0.22, 0.20)} {at(x + 0.30, 0.38)} {at(x + 0.24, 0.56)}"
                f"C{at(x + 0.19, 0.72)} {at(x + 0.08, 0.80)} {at(x, 0.80)}"
                f"C{at(x + 0.10, 0.64)} {at(x + 0.12, 0.54)} {at(x + 0.06, 0.48)}"
                f"C{at(x - 0.04, 0.44)} {at(x - 0.08, 0.34)} {at(x, 0.20)}Z")
    return comma(0.10) + comma(0.52)


def _icon_spark(w: float, h: float, density: int, rng: random.Random) -> str:
    """A four-point sparkle — the "new", "shine", "fresh" mark."""
    _, _, _, at = _icon_space(w, h)
    return (f"M{at(0.50, 0.02)}"
            f"C{at(0.56, 0.36)} {at(0.64, 0.44)} {at(0.98, 0.50)}"
            f"C{at(0.64, 0.56)} {at(0.56, 0.64)} {at(0.50, 0.98)}"
            f"C{at(0.44, 0.64)} {at(0.36, 0.56)} {at(0.02, 0.50)}"
            f"C{at(0.36, 0.44)} {at(0.44, 0.36)} {at(0.50, 0.02)}Z")


def _icon_dot(w: float, h: float, density: int, rng: random.Random) -> str:
    unit, ox, oy, _ = _icon_space(w, h)
    return _circle(ox + unit / 2, oy + unit / 2, unit * 0.40)


_BUILDERS = {
    "blob": _blob,
    "wave": _wave,
    "stripes": _stripes,
    "ribbon": _ribbon,
    "badge": _badge,
    "arc-band": _arc_band,
    "border": _border,
    "corners": _corners,
    "garland": _garland,
    "bunting": _bunting,
    "rays": _rays,
    "confetti": _confetti,
    "dots": _dots,
    "chevrons": _chevrons,
    "scallop": _scallop,
    "divider": _divider,
    "arch": _arch,
    "frame-rule": _frame_rule,
    "frame-round": _frame_round,
    "diamond": _diamond_motif,
    "hexagon": _hexagon,
    "arch-solid": _arch_solid,
    "leaf": _leaf,
    "triangle": _triangle,
    "tag": _tag,
    "grid-dots": _grid_dots,
    "zigzag": _zigzag,
    "icon-check": _icon_check,
    "icon-check-circle": _icon_check_circle,
    "icon-phone": _icon_phone,
    "icon-pin": _icon_pin,
    "icon-mail": _icon_mail,
    "icon-globe": _icon_globe,
    "icon-clock": _icon_clock,
    "icon-arrow": _icon_arrow,
    "icon-ring": _icon_ring,
    "icon-star": _icon_star,
    "icon-play": _icon_play,
    "icon-heart": _icon_heart,
    "icon-quote": _icon_quote,
    "icon-spark": _icon_spark,
    "icon-dot": _icon_dot,
}
