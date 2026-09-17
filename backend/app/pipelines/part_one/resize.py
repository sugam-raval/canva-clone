"""Resize to another format — IMPLEMENTATION_PLAN §4.2.

"this is where Constraints pays off."

  1. if the source template has a variant for the target aspect, use its slot frames
  2. otherwise apply each layer's constraints: pinned edges stay pinned, center
     recentres, scale scales proportionally, stretch fills
  3. backgrounds re-crop around the saliency centroid; past a 25% aspect change,
     outpaint instead of cropping
  4. re-run the solver with the new safe margin, dropping optional layers by ascending
     priority while violations remain
  5. return a NEW document; never mutate the original
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.layout.solver import SolveOpts, solve
from app.pipelines.part_one.compose import apply_variant
from app.pipelines.part_one.retrieve import nearest_aspect
from app.schema.doc import Crop, DesignDoc, DuplicatedProvenance, walk
from app.templates_corpus.skeletons import by_id

log = structlog.get_logger(__name__)

# Past this relative aspect change, cropping a background destroys the composition and
# outpainting is the better answer (§4.2 step 3).
OUTPAINT_ASPECT_THRESHOLD = 0.25
MAX_SOLVER_ROUNDS = 6


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


async def resize_document(session: AsyncSession, doc: DesignDoc, width: int, height: int,
                          user_id: str | None) -> DesignDoc:
    resized = doc.model_copy(deep=True)
    resized.id = str(uuid.uuid4())
    resized.provenance = DuplicatedProvenance(fromDocId=doc.id)
    resized.created_at = resized.updated_at = _now()
    resized.title = f"{doc.title} — {width}×{height}"

    old_w, old_h = doc.canvas.width, doc.canvas.height
    scale_x, scale_y = width / old_w, height / old_h

    variant_slots = _variant_slots_for(doc, width, height)
    if variant_slots is not None:
        log.info("resize.using_variant", doc_id=doc.id)
        _apply_variant_frames(resized, variant_slots, width, height)
    else:
        for layer, ancestors in walk(resized.layers):
            if ancestors:
                continue  # group children move with their group
            _apply_constraints(layer, old_w, old_h, width, height, scale_x, scale_y)

    resized.canvas.width = width
    resized.canvas.height = height
    resized.canvas.safe_margin = round(min(width, height) * 0.0667)

    _recrop_backgrounds(resized, old_w / old_h, width / height)
    _rescale_type(resized, scale_x, scale_y)

    # 4. Solve, dropping optional layers by ascending priority while violations remain.
    result = solve(resized, SolveOpts())
    for _ in range(MAX_SOLVER_ROUNDS):
        blocking = [v for v in result.violations if v.severity == "error"]
        if not blocking:
            break
        droppable = sorted(
            (layer for layer, _a in walk(result.doc.layers)
             if layer.constraints.optional and layer.visible),
            key=lambda layer: layer.constraints.priority)
        if not droppable:
            break
        droppable[0].visible = False
        droppable[0].meta.notes["droppedBy"] = "resize"
        result = solve(result.doc, SolveOpts())

    result.doc.id = resized.id
    result.doc.title = resized.title
    result.doc.provenance = resized.provenance
    result.doc.created_at = resized.created_at
    result.doc.updated_at = _now()
    if result.violations:
        log.info("resize.violations", count=len(result.violations),
                 codes=[v.code for v in result.violations[:4]])
    return result.doc


def _variant_slots_for(doc: DesignDoc, width: int, height: int):
    """§4.2 step 1 — by far the best result when the source template has a variant
    authored for the target aspect family."""
    provenance = doc.provenance
    template_id = getattr(provenance, "template_id", None)
    if not template_id:
        return None
    base_id = template_id.split("#")[0]
    skeleton = by_id(base_id)
    if skeleton is None:
        return None
    if skeleton.aspect != nearest_aspect(width, height):
        return None
    variant_id = template_id.split("#")[1] if "#" in template_id else None
    return {slot.slot_id: slot for slot in apply_variant(skeleton, variant_id)}


def _apply_variant_frames(doc: DesignDoc, slots: dict, width: int, height: int) -> None:
    for layer, ancestors in walk(doc.layers):
        if ancestors:
            continue
        slot = slots.get(layer.id.removeprefix("l_"))
        if slot is None:
            continue
        frame_n = slot.frame_n
        layer.frame.x = frame_n.x * width
        layer.frame.y = frame_n.y * height
        layer.frame.w = max(1.0, frame_n.w * width)
        layer.frame.h = max(1.0, frame_n.h * height)


def _apply_constraints(layer, old_w: int, old_h: int, new_w: int, new_h: int,
                       scale_x: float, scale_y: float) -> None:
    frame = layer.frame
    constraints = layer.constraints

    right_gap = old_w - (frame.x + frame.w)
    bottom_gap = old_h - (frame.y + frame.h)

    # Horizontal
    if constraints.horizontal == "stretch" or constraints.horizontal == "scale":
        frame.x, frame.w = frame.x * scale_x, frame.w * scale_x
    elif constraints.horizontal == "left":
        frame.w = frame.w * scale_x if constraints.lock_aspect else frame.w
    elif constraints.horizontal == "right":
        frame.x = new_w - right_gap - frame.w
    elif constraints.horizontal == "center":
        centre_ratio = (frame.x + frame.w / 2) / max(1, old_w)
        frame.x = centre_ratio * new_w - frame.w / 2

    # Vertical
    if constraints.vertical in ("stretch", "scale"):
        frame.y, frame.h = frame.y * scale_y, frame.h * scale_y
    elif constraints.vertical == "bottom":
        frame.y = new_h - bottom_gap - frame.h
    elif constraints.vertical == "middle":
        centre_ratio = (frame.y + frame.h / 2) / max(1, old_h)
        frame.y = centre_ratio * new_h - frame.h / 2

    # A locked-aspect layer scales uniformly by the smaller factor, so a subject never
    # distorts when the canvas changes shape.
    if constraints.lock_aspect and layer.type == "image":
        uniform = min(scale_x, scale_y)
        centre_x, centre_y = frame.x + frame.w / 2, frame.y + frame.h / 2
        frame.w *= uniform
        frame.h *= uniform
        frame.x, frame.y = centre_x - frame.w / 2, centre_y - frame.h / 2

    if layer.role in ("background", "overlay") or constraints.horizontal == "stretch":
        frame.x = 0.0
        frame.w = float(new_w)
    if layer.role == "background":
        frame.y = 0.0
        frame.h = float(new_h)


def _recrop_backgrounds(doc: DesignDoc, old_aspect: float, new_aspect: float) -> None:
    """§4.2 step 3: re-crop `fit: cover` backgrounds; flag big changes for outpainting."""
    change = abs(new_aspect - old_aspect) / max(old_aspect, 1e-6)
    for layer in doc.layers:
        if layer.type != "image" or layer.role != "background":
            continue
        layer.fit = "cover"
        layer.crop = None   # cover-cropping is recomputed by the renderer
        if change > OUTPAINT_ASPECT_THRESHOLD:
            # §4.2: "outpaint the background to the new aspect instead of cropping —
            # much better than a hard crop." The flag is what the editor surfaces as a
            # one-click action; doing it inline would make resize a GPU-cost operation.
            layer.meta.notes["outpaintSuggested"] = True
            layer.meta.notes["aspectChange"] = round(change, 3)


def _rescale_type(doc: DesignDoc, scale_x: float, scale_y: float) -> None:
    """Type scales uniformly with the canvas, then autofit refines it during the solve.

    Uniform (rather than per-axis) scaling is deliberate: scaling font size by the
    vertical factor alone makes type comically large when a square becomes a banner.
    """
    factor = min(scale_x, scale_y)
    for layer, _ in walk(doc.layers):
        if layer.type != "text":
            continue
        layer.font_size = max(6.0, layer.font_size * factor)
        layer.letter_spacing *= factor
        if layer.auto_fit is not None:
            layer.auto_fit.min = max(6.0, layer.auto_fit.min * factor)
            layer.auto_fit.max = max(layer.auto_fit.min + 1, layer.auto_fit.max * factor)
        if layer.backdrop is not None:
            layer.backdrop.padding *= factor
            layer.backdrop.radius *= factor


def crop_for_aspect(natural_w: float, natural_h: float, target_aspect: float,
                    centroid: tuple[float, float] = (0.5, 0.5)) -> Crop:
    """Largest sub-rect of the given aspect, centred on a saliency centroid."""
    source_aspect = natural_w / max(1.0, natural_h)
    if source_aspect > target_aspect:
        w = target_aspect / source_aspect
        h = 1.0
    else:
        w = 1.0
        h = source_aspect / target_aspect
    x = min(max(centroid[0] - w / 2, 0.0), 1.0 - w)
    y = min(max(centroid[1] - h / 2, 0.0), 1.0 - h)
    return Crop(x=x, y=y, w=w, h=h)
