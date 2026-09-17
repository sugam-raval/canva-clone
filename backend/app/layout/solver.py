"""The layout solver — IMPLEMENTATION_PLAN §1.6. Deterministic. No AI.

Order of operations is fixed; later steps assume earlier ones:

  1. measure text        2. autofit          3. pack text stacks
  4. safe margins        5. collision resolve 6. optical align
  7. grid snap           8. re-validate

§1.6: "If you build one thing well in this project, build this. Users forgive mediocre
images; they do not forgive a headline colliding with a product."
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Literal

from app.layout.measure import ShapedBlock, shape_block
from app.renderer.transform import Rect, world_bounds
from app.schema.doc import DesignDoc, GroupLayer, TextLayer, walk
from app.schema.validate import validate_doc

Severity = Literal["error", "warning"]

# Layers at or above this priority must never be left overlapping (§5.3 collision rate).
COLLISION_PRIORITY_FLOOR = 50
MAX_COLLISION_PASSES = 20
AUTOFIT_ITERATIONS = 12


@dataclass
class Violation:
    code: str
    message: str
    layer_id: str | None = None
    severity: Severity = "warning"

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "message": self.message,
            "layerId": self.layer_id, "severity": self.severity,
        }


@dataclass
class SolveOpts:
    """`measure_only` shapes text and reports violations but moves nothing.

    Used when opening a document the user expects to look untouched.
    """

    measure_only: bool = False
    grid_baseline: int = 8
    language: str = "en"
    enable_collisions: bool = True
    enable_margins: bool = True
    enable_pack: bool = True
    enable_optical: bool = True
    enable_snap: bool = True


@dataclass
class SolveResult:
    doc: DesignDoc
    violations: list[Violation] = field(default_factory=list)
    shaped: dict[str, ShapedBlock] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(v.severity == "error" for v in self.violations)


def solve(doc: DesignDoc, opts: SolveOpts | None = None) -> SolveResult:
    opts = opts or SolveOpts()
    doc = copy.deepcopy(doc)
    violations: list[Violation] = []
    shaped: dict[str, ShapedBlock] = {}

    # 1 + 2. Measure and autofit every text layer.
    for layer, _ancestors in walk(doc.layers):
        if layer.type == "text":
            block = _fit_text(layer, opts, violations)
            shaped[layer.id] = block

    if not opts.measure_only:
        if opts.enable_pack:
            _pack_text_stacks(doc, shaped, opts.grid_baseline)   # 3
        if opts.enable_margins:
            _enforce_safe_margins(doc, violations)           # 4
        if opts.enable_collisions:
            _resolve_collisions(doc, opts, shaped)           # 5
        _drop_orphaned_pairs(doc)
        if opts.enable_optical:
            _optical_align(doc, shaped)                      # 6
        if opts.enable_snap:
            _snap_to_grid(doc, opts.grid_baseline)           # 7
        if opts.enable_collisions:
            # Reported after snapping, because snapping is the last thing that can move
            # a layer and therefore the last thing that can reintroduce an overlap.
            _report_collisions(doc, violations)

    # 7. Re-validate.
    result = validate_doc(doc)
    if not result.ok:
        violations.extend(
            Violation("invalid-doc", e.message, e.layer_id, "error") for e in result.errors
        )

    return SolveResult(doc=doc, violations=violations, shaped=shaped)


def _drop_orphaned_pairs(doc: DesignDoc) -> None:
    """Hide anything whose declared partner is gone.

    Collision resolution drops a companion *group*, but a group is built from the layers
    it can see and it cannot see decoration: `_collidable` excludes it, which is what
    stops a divider being shoved around by the headline above it. So when a contact line
    is dropped, the handset beside it survives — a row of icons pointing at nothing,
    which is the most obviously broken thing a design can ship.

    Iterated, so a chain unwinds in one pass.
    """
    while True:
        live = {layer.id for layer, _ in walk(doc.layers) if layer.visible}
        orphans = [layer for layer, _ in walk(doc.layers)
                   if layer.visible and layer.constraints.pairs_with
                   and layer.constraints.pairs_with not in live]
        if not orphans:
            return
        for layer in orphans:
            layer.visible = False
            layer.meta.notes["droppedBy"] = "orphaned-pair"


# --------------------------------------------------------------------------------------
# 1 + 2. Measure and autofit
# --------------------------------------------------------------------------------------


def _shape_for(layer: TextLayer, size: float, language: str) -> ShapedBlock:
    return shape_block(
        layer.content,
        font_family=layer.font_family,
        font_weight=layer.font_weight,
        font_style=layer.font_style,
        font_size=size,
        line_height=layer.line_height,
        letter_spacing=layer.letter_spacing,
        max_width=max(1.0, layer.frame.w),
        language=language,
        text_transform=layer.text_transform,
    )


def _fit_text(layer: TextLayer, opts: SolveOpts, violations: list[Violation]) -> ShapedBlock:
    """Binary-search `fontSize` within `autoFit` bounds until the block fits the frame."""
    language = opts.language
    block = _shape_for(layer, layer.font_size, language)

    if layer.auto_height and not opts.measure_only:
        # Frame height follows content instead of clipping it — but only the height is
        # released. The width is still the column the layout allocated, and a word too
        # long to break inside it overflows however tall the frame is allowed to grow.
        # Returning here without autofitting is how a headline ends up 989px wide in a
        # 928px column: growing the frame downward cannot fix a horizontal overflow.
        if layer.auto_fit is not None:
            block = _fit_to_width(layer, block, language)
        layer.frame.h = block.height
        if block.width > layer.frame.w + 0.5 or block.overflowed_width:
            violations.append(
                Violation("text-overflow",
                          f"text is {block.width:.0f}px wide in a {layer.frame.w:.0f}px "
                          f"column even at the minimum size", layer.id, "warning")
            )
        return block

    fits = _block_fits(block, layer)
    if layer.auto_fit is None or opts.measure_only:
        if not fits:
            violations.append(
                Violation("text-overflow",
                          f"text does not fit its frame at {layer.font_size:.0f}px",
                          layer.id, "warning")
            )
        return block

    lo, hi = layer.auto_fit.min, layer.auto_fit.max
    if layer.auto_fit.mode == "shrink":
        hi = min(hi, layer.font_size)
    if hi < lo:
        lo, hi = hi, lo

    best = _shape_for(layer, lo, language)
    if not _block_fits(best, layer):
        # Even the minimum size overflows.
        layer.font_size = lo
        violations.append(
            Violation("text-overflow",
                      f"text overflows even at the minimum size {lo:.0f}px",
                      layer.id, "error")
        )
        return best

    best_size = lo
    for _ in range(AUTOFIT_ITERATIONS):
        if hi - lo < 0.5:
            break
        mid = (lo + hi) / 2
        candidate = _shape_for(layer, mid, language)
        if _block_fits(candidate, layer):
            best, best_size, lo = candidate, mid, mid
        else:
            hi = mid

    layer.font_size = round(best_size, 2)
    return best



def _fit_to_width(layer: TextLayer, block: ShapedBlock, language: str) -> ShapedBlock:
    """Shrink an auto-height layer within its autofit bounds until its width fits.

    The counterpart to `_fit_text`'s search, for the case where height is not a
    constraint. Only ever shrinks: a layer whose height follows its content has nothing
    stopping upward growth, so letting it grow here would set short copy at whatever size
    the bounds happen to allow rather than at the size the skeleton chose.
    """
    if block.width <= layer.frame.w + 0.5 and not block.overflowed_width:
        return block

    lo, hi = layer.auto_fit.min, min(layer.auto_fit.max, layer.font_size)
    if hi < lo:
        lo, hi = hi, lo

    best = _shape_for(layer, lo, language)
    if best.width > layer.frame.w + 0.5 or best.overflowed_width:
        layer.font_size = lo
        return best

    best_size = lo
    for _ in range(AUTOFIT_ITERATIONS):
        if hi - lo < 0.5:
            break
        mid = (lo + hi) / 2
        candidate = _shape_for(layer, mid, language)
        if candidate.width <= layer.frame.w + 0.5 and not candidate.overflowed_width:
            best, best_size, lo = candidate, mid, mid
        else:
            hi = mid

    layer.font_size = round(best_size, 2)
    return best

def _block_fits(block: ShapedBlock, layer: TextLayer) -> bool:
    if block.overflowed_width:
        return False
    return block.height <= layer.frame.h + 0.5 and block.width <= layer.frame.w + 0.5


# --------------------------------------------------------------------------------------
# 3. Pack text stacks
# --------------------------------------------------------------------------------------

# Two text layers belong to the same stack only if their authored gap is small relative
# to the canvas. A headline and its subhead sit a percent or two apart; a headline and a
# CTA pinned near the bottom edge are separated by a third of the canvas and are not a
# stack — pulling the CTA up would destroy the composition rather than tighten it.
MAX_STACK_GAP_N = 0.12

# Columns count as the same one when their horizontal extents overlap by at least this
# fraction of the narrower layer.
STACK_OVERLAP = 0.5

# Only ornament this short travels with a text stack. A divider or a rule is punctuation
# inside the rhythm; an arch or a garland is a frame around the composition, and lifting
# one of those with the copy pulls it off the subject it was drawn around.
MAX_STACK_ORNAMENT_N = 0.08


def _pack_text_stacks(doc: DesignDoc, shaped: dict[str, ShapedBlock],
                      baseline: int = 8) -> None:
    """Close the space a text box reserves but does not use.

    A skeleton sizes each text box for a nominal copy length. Shorter copy leaves the
    remainder as dead space *inside* the box, which renders as a hole between that layer
    and the next one down — the gap the viewer sees is the authored gap plus whatever the
    box did not spend. Here each box is trimmed to its measured ink and the layers below
    are lifted by exactly the amount reclaimed, so the designed rhythm survives contact
    with real copy.

    Only gaps are closed, never opened: a stack that is already tight is left alone.
    """
    stacks, authored = _text_stacks(doc)
    for stack in stacks:
        lifted = 0.0
        previous_ink_bottom: float | None = None
        for layer in stack:
            frame = layer.frame
            block = shaped.get(layer.id)
            # Ornament between two text layers — a divider under a headline — is part of
            # that stack's rhythm and rides up with it. It has no ink to measure, so it
            # contributes no slack of its own and simply keeps its authored gaps.
            slack = (frame.h - block.height) if block is not None else 0.0
            # Where the ink sits inside the box depends on the vertical alignment, so
            # that is where the reclaimed space has to come from.
            valign = getattr(layer, "vertical_align", "top")
            if valign == "middle":
                offset = slack / 2.0
            elif valign == "bottom":
                offset = slack
            else:
                offset = 0.0

            ink_top = frame.y + offset - lifted
            if previous_ink_bottom is not None:
                authored_gap = _authored_gap(stack, layer, authored)
                excess = (ink_top - previous_ink_bottom) - authored_gap
                if excess > 0.5:
                    lifted += excess
                    ink_top -= excess

            if block is not None and slack > 0.5:
                # Box becomes the ink, so collision resolution and margin enforcement
                # measure what a viewer actually sees instead of a padded rectangle.
                # Rounded UP to the baseline: grid snapping runs later and rounds to the
                # nearest line, which on a tight box rounds down and clips the last row
                # of glyphs by a pixel or two.
                frame.h = math.ceil(block.height / baseline) * baseline
            frame.y = ink_top
            previous_ink_bottom = ink_top + frame.h


def _authored_gap(stack: list[Any], layer: Any,
                  authored: dict[str, tuple[float, float]]) -> float:
    """The gap the skeleton put between `layer` and the one above it, before packing."""
    above = stack[stack.index(layer) - 1]
    above_y, above_h = authored[above.id]
    return max(0.0, authored[layer.id][0] - (above_y + above_h))


def _stackable(layer: Any, doc: DesignDoc, companions: dict[str, set[str]]) -> bool:
    """Text, plus the ornament threaded between it.

    Decoration is excluded from collision resolution, so if it did not travel with the
    stack a lifted subhead would simply be moved on top of the divider above it.

    A layer that belongs to a companion group is never packed: a CTA label lives on its
    pill, and lifting the label alone leaves an empty lozenge behind — the same defect
    `_companion_groups` exists to prevent during collision resolution.
    """
    if not layer.visible or layer.id in companions:
        return False
    if isinstance(layer, TextLayer):
        if layer.auto_height or is_full_bleed(layer, doc):
            return False
        # Copy set inside a full-width band — a contact strip, a footer, a header — is
        # positioned by that band, not by the column above it. Packed with the column it
        # rides up on the slack reclaimed from every box above, and a footer line ends up
        # floating above the bar it was set in, in the bar's text colour on the page.
        return not _sits_in_band(layer, doc)
    # Decoration counts as full-bleed by role so margins leave it at the edge; its own
    # size is therefore what decides whether it is punctuation or a frame.
    return (layer.type == "shape" and layer.role == "decoration"
            and layer.frame.w < doc.canvas.width - 0.5
            and layer.frame.h <= MAX_STACK_ORNAMENT_N * doc.canvas.height)


def _sits_in_band(layer: Any, doc: DesignDoc) -> bool:
    """Is this layer set inside a full-width colour band?"""
    centre = layer.frame.y + layer.frame.h / 2
    for other, ancestors in walk(doc.layers):
        if ancestors or other is layer or not other.visible:
            continue
        if other.type != "shape" or other.role == "background":
            continue
        if other.frame.w < doc.canvas.width - 1:
            continue
        if other.frame.y <= centre <= other.frame.y + other.frame.h:
            return True
    return False


def _text_stacks(doc: DesignDoc) -> tuple[list[list[Any]],
                                          dict[str, tuple[float, float]]]:
    """Top-level text layers grouped into columns, each ordered top to bottom.

    Also returns each layer's authored (y, height), captured before anything moves —
    the gaps to preserve are the ones the skeleton specified, not the ones left after
    an earlier member of the stack has already been lifted.
    """
    companions = _companion_groups([layer for layer, anc in walk(doc.layers) if not anc])
    layers = [layer for layer in doc.layers if _stackable(layer, doc, companions)]
    authored = {layer.id: (layer.frame.y, layer.frame.h) for layer in layers}
    layers.sort(key=lambda layer: layer.frame.y)

    stacks: list[list[TextLayer]] = []
    for layer in layers:
        for stack in stacks:
            if _same_column(stack[-1], layer) and _gap_below(stack[-1], layer) \
                    <= MAX_STACK_GAP_N * doc.canvas.height:
                stack.append(layer)
                break
        else:
            stacks.append([layer])
    # A run of ornament with no text in it is not a stack worth packing.
    return ([stack for stack in stacks
             if sum(isinstance(m, TextLayer) for m in stack) > 1], authored)


def _same_column(a: Any, b: Any) -> bool:
    overlap = min(a.frame.x + a.frame.w, b.frame.x + b.frame.w) - max(a.frame.x, b.frame.x)
    return overlap >= STACK_OVERLAP * min(a.frame.w, b.frame.w)


def _gap_below(a: Any, b: Any) -> float:
    return b.frame.y - (a.frame.y + a.frame.h)


# --------------------------------------------------------------------------------------
# 4. Safe margins
# --------------------------------------------------------------------------------------


def is_full_bleed(layer: Any, doc: DesignDoc) -> bool:
    """Layers that are *supposed* to cross the safe margin.

    Public because the §5.3 eval measures margin compliance and must apply exactly this
    rule. A second copy of it would drift and report phantom violations.
    """
    return (
        # Decoration sits at the bleed on purpose — a corner flourish pulled inside the
        # safe area stops being a corner flourish.
        layer.role in ("background", "overlay", "decoration")
        or layer.frame.w >= doc.canvas.width - 0.5
        or layer.frame.h >= doc.canvas.height - 0.5
        or layer.constraints.horizontal == "stretch"
    )


_is_full_bleed = is_full_bleed


def _enforce_safe_margins(doc: DesignDoc, violations: list[Violation]) -> None:
    margin = doc.canvas.safe_margin
    if margin <= 0:
        return
    safe = Rect(margin, margin, doc.canvas.width - 2 * margin, doc.canvas.height - 2 * margin)

    movable = [layer for layer, ancestors in walk(doc.layers)
               if layer.type != "group" and not ancestors and layer.visible
               and not _is_full_bleed(layer, doc)]
    # Declared pairs are nudged inside as one unit. Measured separately, a tick sitting
    # just outside the margin slides in while the line beside it does not, and the row
    # loses the gap it was authored with.
    by_id = {layer.id: layer for layer in movable}
    units: list[list[Any]] = []
    seen: set[str] = set()
    for layer in movable:
        if layer.id in seen:
            continue
        partner = by_id.get(layer.constraints.pairs_with or "")
        unit = [layer] if partner is None or partner.id in seen else [layer, partner]
        seen.update(member.id for member in unit)
        units.append(unit)

    for unit in units:
        bounds = world_bounds(unit[0], ())
        for member in unit[1:]:
            bounds = bounds.union(world_bounds(member, ()))
        dx = dy = 0.0
        if bounds.x < safe.x:
            dx = safe.x - bounds.x
        elif bounds.right > safe.right:
            dx = safe.right - bounds.right
        if bounds.y < safe.y:
            dy = safe.y - bounds.y
        elif bounds.bottom > safe.bottom:
            dy = safe.bottom - bounds.bottom

        if bounds.w > safe.w or bounds.h > safe.h:
            violations.append(
                Violation("margin-unfittable",
                          "layer is larger than the safe area and cannot be moved inside",
                          unit[0].id, "warning")
            )
            continue
        if dx or dy:
            for member in unit:
                member.frame.x += dx
                member.frame.y += dy


# --------------------------------------------------------------------------------------
# 5. Collision resolution
# --------------------------------------------------------------------------------------


def _declared_pairs(layers: list[Any]) -> dict[str, set[str]]:
    """Groups built from `pairsWith` alone, over whatever layers are handed in.

    Kept separate from `_companion_groups` because the two need different populations.
    Geometric inference only makes sense over collidable layers; a declared pairing has
    to be discovered over ALL of them, because the usual partner — a tick, a keyline, a
    rule — is decoration, which `_collidable` deliberately excludes. Built from the
    collidable set alone, the pairing is invisible exactly when it matters: the line
    moves out of the photograph it was sitting on and its tick stays behind.
    """
    groups: dict[str, set[str]] = {}
    present = {layer.id for layer in layers}
    for layer in layers:
        partner = layer.constraints.pairs_with
        if not partner or partner not in present:
            continue
        merged = (groups.setdefault(layer.id, {layer.id})
                  | groups.setdefault(partner, {partner}))
        for member in merged:
            groups[member] = merged
    return groups


def _companion_groups(layers: list[Any],
                      all_layers: list[Any] | None = None) -> dict[str, set[str]]:
    """Layers that must move as one unit.

    A CTA label drawn on its own pill is a single visual object with two layers. Left to
    itself the collision solver sees an overlap and helpfully separates them, which
    produces an empty lozenge and orphaned text. Anything sharing a semantic role where
    one layer is text and the other is its shape backing is linked here, and the linked
    set then moves together and is never resolved against itself.
    """
    # Declared pairings first. These are the ones geometry cannot infer: a tick does not
    # overlap the line it annotates and does not share its role, so every heuristic below
    # misses it, and the checklist comes apart the moment the copy is packed.
    groups: dict[str, set[str]] = _declared_pairs(all_layers or layers)

    def link(first: str, second: str) -> None:
        merged = groups.setdefault(first, {first}) | groups.setdefault(second, {second})
        for member in merged:
            groups[member] = merged

    for i, a in enumerate(layers):
        for b in layers[i + 1:]:
            if a.role != b.role or a.role in ("background", "overlay", "unknown"):
                continue
            if {a.type, b.type} != {"text", "shape"}:
                continue
            overlap = world_bounds(a).intersection(world_bounds(b))
            smaller = min(world_bounds(a).area, world_bounds(b).area)
            if smaller <= 0 or overlap.area / smaller < 0.5:
                continue
            link(a.id, b.id)
    return groups


def _overlap_declared(a: Any, b: Any) -> bool:
    """Whether this particular pair is meant to overlap.

    `allowOverlap` says a layer participates in depth — display type set behind a
    subject, a prop layered over one. It does not say the layer may overlap *anything*:
    two text layers on top of each other is unreadable no matter what either declares,
    and excusing that pair would let a script accent sit on its own headline.
    """
    if not (a.constraints.allow_overlap or b.constraints.allow_overlap):
        return False
    return not (a.type == "text" and b.type == "text")


def _collidable(layer: Any) -> bool:
    return (
        layer.visible
        and layer.type != "group"
        and layer.role not in ("background", "overlay", "decoration")
    )


def _resolve_collisions(
    doc: DesignDoc, opts: SolveOpts, shaped: dict[str, ShapedBlock],
) -> None:
    """Greedy penetration resolution on a snapped grid, iterated to a fixed point.

    §1.6 explicitly rules out full constraint programming for v1: this is sufficient and,
    more importantly, debuggable.

    Moves are quantised to the grid baseline so that step 6 (grid snap) cannot round a
    layer back into its neighbour. Reporting happens in `_report_collisions` *after*
    snapping, so what the UI is told matches the geometry actually shipped.
    """
    margin = doc.canvas.safe_margin
    safe = Rect(margin, margin, doc.canvas.width - 2 * margin, doc.canvas.height - 2 * margin)

    def top_level() -> list[Any]:
        return [layer for layer, anc in walk(doc.layers) if not anc and _collidable(layer)]

    def every_layer() -> list[Any]:
        return [layer for layer, anc in walk(doc.layers) if not anc and layer.visible]

    for _pass in range(MAX_COLLISION_PASSES):
        layers = top_level()
        all_layers = every_layer()
        companions = _companion_groups(layers, all_layers)
        # Movement is resolved over every layer, not just the collidable ones: what a
        # move has to carry with it includes the decoration that was never a candidate
        # for colliding in the first place.
        by_id = {layer.id: layer for layer in all_layers}
        bounds = {layer.id: world_bounds(layer, ()) for layer in layers}
        moved = False

        for i, a in enumerate(layers):
            for b in layers[i + 1:]:
                if not (a.visible and b.visible):
                    continue
                if b.id in companions.get(a.id, ()):
                    continue   # two halves of one object; never separate them
                if _overlap_declared(a, b):
                    continue   # the overlap is the composition — depth, not a defect
                ra, rb = bounds[a.id], bounds[b.id]
                if not ra.intersects(rb) or ra.intersection(rb).area <= 1.0:
                    continue

                # The lower-priority layer yields.
                loser, winner = (
                    (a, b) if a.constraints.priority <= b.constraints.priority else (b, a)
                )
                linked = [by_id[lid] for lid in companions.get(loser.id, {loser.id})
                          if lid in by_id]
                # Escalation order: move it, else shrink it, else drop it if optional.
                if _try_move(
                    loser, bounds[loser.id], bounds[winner.id], safe, opts.grid_baseline,
                    companions=linked,
                ) or _try_shrink(loser, shaped, opts):
                    moved = True
                elif loser.constraints.optional:
                    for member in linked:
                        member.visible = False
                        member.meta.notes["droppedBy"] = "collision"
                    moved = True
                for member in linked:
                    bounds[member.id] = world_bounds(member, ())

        if not moved:
            break


def _report_collisions(doc: DesignDoc, violations: list[Violation]) -> None:
    """Whatever still overlaps after margins, collisions, optical alignment AND grid
    snapping could not be resolved, and the UI has to be told (§1.6 step 7)."""
    layers = [
        layer for layer, anc in walk(doc.layers)
        if not anc and _collidable(layer) and layer.visible
    ]
    companions = _companion_groups(layers)
    bounds = {layer.id: world_bounds(layer, ()) for layer in layers}
    for i, a in enumerate(layers):
        for b in layers[i + 1:]:
            if b.id in companions.get(a.id, ()):
                continue
            if _overlap_declared(a, b):
                continue
            if bounds[a.id].intersection(bounds[b.id]).area <= 1.0:
                continue
            loser, winner = (
                (a, b) if a.constraints.priority <= b.constraints.priority else (b, a)
            )
            both_important = (
                min(a.constraints.priority, b.constraints.priority) >= COLLISION_PRIORITY_FLOOR
            )
            violations.append(
                Violation(
                    "unresolved-collision",
                    f"layer overlaps {winner.id!r} and cannot be moved, shrunk or dropped",
                    loser.id,
                    "error" if both_important else "warning",
                )
            )


def _quantise(distance: float, baseline: int) -> float:
    """Round a separation distance *away from zero* to a multiple of the grid baseline,
    so the later grid snap cannot undo the separation."""
    if baseline <= 1 or distance == 0:
        return distance
    steps = math.ceil(abs(distance) / baseline)
    return math.copysign(steps * baseline, distance)


def _separation_moves(loser: Rect, winner: Rect, baseline: int) -> list[tuple[float, float]]:
    """The four translations that fully separate `loser` from `winner`, nearest first.

    Each distance is the gap to clear that edge, NOT the overlap depth: pushing down
    must clear the winner's *bottom*, which is a different (usually much larger)
    distance than the overlap height.
    """
    moves = [
        (_quantise(winner.x - loser.right, baseline), 0.0),      # left
        (_quantise(winner.right - loser.x, baseline), 0.0),      # right
        (0.0, _quantise(winner.y - loser.bottom, baseline)),     # up
        (0.0, _quantise(winner.bottom - loser.y, baseline)),     # down
    ]
    return sorted(moves, key=lambda d: abs(d[0]) + abs(d[1]))


def _try_move(loser: Any, lr: Rect, wr: Rect, safe: Rect, baseline: int = 8,
              companions: list[Any] | None = None) -> bool:
    """Push the loser clear of the winner along the cheapest axis that stays legal.

    `companions` are layers linked to the loser (see `_companion_groups`); they receive
    the identical translation so the unit stays intact.
    """
    members = companions if companions else [loser]
    # The move must keep every member of the unit inside the safe area, not just the
    # layer that happened to collide.
    union = lr
    for member in members:
        bounds = world_bounds(member, ())
        union = Rect(
            min(union.x, bounds.x), min(union.y, bounds.y),
            max(union.right, bounds.right) - min(union.x, bounds.x),
            max(union.bottom, bounds.bottom) - min(union.y, bounds.y),
        )

    for dx, dy in _separation_moves(lr, wr, baseline):
        if abs(dx) + abs(dy) < 0.5:
            continue
        moved = Rect(union.x + dx, union.y + dy, union.w, union.h)
        inside = (
            moved.x >= safe.x - 0.5 and moved.y >= safe.y - 0.5
            and moved.right <= safe.right + 0.5 and moved.bottom <= safe.bottom + 0.5
        )
        if inside:
            for member in members:
                member.frame.x += dx
                member.frame.y += dy
            return True
    return False


def _try_shrink(loser: Any, shaped: dict[str, ShapedBlock], opts: SolveOpts) -> bool:
    """Shrink a text layer within its autofit bounds to buy room."""
    if loser.type != "text" or loser.auto_fit is None:
        return False
    target = loser.font_size * 0.9
    if target < loser.auto_fit.min:
        return False
    loser.font_size = round(target, 2)
    block = _shape_for(loser, loser.font_size, opts.language)
    shaped[loser.id] = block
    loser.frame.h = min(loser.frame.h, max(block.height, loser.auto_fit.min))
    return True


# --------------------------------------------------------------------------------------
# 6. Optical alignment
# --------------------------------------------------------------------------------------


def _optical_align(doc: DesignDoc, shaped: dict[str, ShapedBlock]) -> None:
    """Align text by its ink edge, not its frame edge.

    A left-aligned capital 'T' carries a small left side bearing; aligning the frame
    leaves it looking indented next to a flush-left rule or image.

    The shift is clamped to the safe area. This step runs *after* margin enforcement, so
    an unclamped nudge on a layer already sitting flush against the margin would push it
    back outside — the same ordering trap that grid snapping had.
    """
    margin = doc.canvas.safe_margin
    safe = Rect(margin, margin, doc.canvas.width - 2 * margin,
                doc.canvas.height - 2 * margin) if margin > 0 else None

    for layer, ancestors in walk(doc.layers):
        if layer.type != "text" or ancestors:
            continue
        block = shaped.get(layer.id)
        if block is None or not block.lines:
            continue

        shift = 0.0
        if layer.align == "left":
            bearing = min((line.ink_left for line in block.lines if line.text.strip()),
                          default=0.0)
            if 0 < bearing < layer.font_size * 0.25:
                shift = -bearing
        elif layer.align == "right":
            overhang = max(
                (line.ink_right - line.advance for line in block.lines if line.text.strip()),
                default=0.0,
            )
            if 0 < overhang < layer.font_size * 0.25:
                shift = overhang
        if shift == 0.0:
            continue

        if safe is not None and not is_full_bleed(layer, doc):
            bounds = world_bounds(layer, ())
            if shift < 0:
                shift = max(shift, safe.x - bounds.x)
            else:
                shift = min(shift, safe.right - bounds.right)
            if abs(shift) < 0.01:
                continue

        layer.frame.x += shift
        layer.meta.notes["opticalShiftX"] = round(shift, 3)


# --------------------------------------------------------------------------------------
# 7. Grid snap
# --------------------------------------------------------------------------------------


def _snap_to_grid(doc: DesignDoc, baseline: int) -> None:
    if baseline <= 1:
        return

    def snap(v: float) -> float:
        return round(v / baseline) * baseline

    for layer, ancestors in walk(doc.layers):
        if ancestors or isinstance(layer, GroupLayer):
            continue
        if layer.role == "background" or layer.frame.w >= doc.canvas.width - 0.5:
            continue
        # Preserve any optical shift applied in step 5 — snapping would undo it.
        shift = float(layer.meta.notes.get("opticalShiftX", 0.0) or 0.0)
        layer.frame.x = snap(layer.frame.x - shift) + shift
        layer.frame.y = snap(layer.frame.y)
        layer.frame.w = max(float(baseline), snap(layer.frame.w))
        layer.frame.h = max(float(baseline), snap(layer.frame.h))
