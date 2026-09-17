"""Fit subject frames to the content that actually arrived — IMPLEMENTATION_PLAN §1.5.

A skeleton author places a subject slot before knowing what the generator will return.
`fit: contain` then letterboxes the cutout inside that frame, and the mismatch is paid
for entirely in subject size: a portrait cutout dropped into a landscape frame renders
at well under half the frame's width and reads as a small object stranded in open space,
with the empty band around it looking like a layout error rather than breathing room.

This pass runs after assets and before harmonisation, once `naturalSize` is known. It
reshapes the frame to the content's aspect while holding the area the skeleton author
allocated, so the subject occupies the space that was designed for it. Area is the right
invariant: it is what "the subject belongs here, at about this size" actually means, and
unlike matching a single edge it does not quietly double a tall subject's height.
"""

from __future__ import annotations

import math

import structlog

from app.schema.doc import DesignDoc, Frame, ImageLayer, walk

log = structlog.get_logger(__name__)

# Roles whose frame may be reshaped. A background or overlay is deliberately the size it
# is — reshaping it to its content's aspect would uncover the canvas.
FITTABLE_ROLES = ("subject", "object", "logo")

# No edge may grow by more than this. Area preservation alone can ask for a very tall box
# from a very wide frame; past this the composition stops being the one that was chosen.
MAX_EDGE_GROWTH = 1.6

# How far a reshaped subject may hang off the canvas, as a fraction of its own size. A
# little bleed is a composition; a third of the product missing is a mistake, and that is
# what unbounded reshaping produces when a wide frame meets a wide cutout.
MAX_OFFCANVAS_FRACTION = 0.12

# Below this the letterboxing is not worth a reflow.
MIN_ASPECT_MISMATCH = 0.06


def fit_subjects(doc: DesignDoc) -> DesignDoc:
    """Reshape `contain` subject frames to their content's aspect. Returns `doc`."""
    for layer in doc.layers:
        if not isinstance(layer, ImageLayer) or layer.fit != "contain":
            continue
        if layer.role not in FITTABLE_ROLES:
            continue
        natural_w, natural_h = layer.natural_size.w, layer.natural_size.h
        if natural_w <= 0 or natural_h <= 0:
            continue

        frame = layer.frame
        if frame.w <= 0 or frame.h <= 0:
            continue

        content_aspect = natural_w / natural_h
        frame_aspect = frame.w / frame.h
        if abs(math.log(content_aspect / frame_aspect)) < MIN_ASPECT_MISMATCH:
            continue

        fitted = _reshape(frame, content_aspect, doc.canvas.width, doc.canvas.height,
                          layer.constraints.horizontal, layer.constraints.vertical,
                          band=free_band(doc, layer))
        if fitted is None:
            continue

        log.info("fit.subject", layer_id=layer.id,
                 before=[round(frame.w), round(frame.h)],
                 after=[round(fitted.w), round(fitted.h)],
                 content_aspect=round(content_aspect, 3))
        layer.frame = fitted
        layer.meta.notes["fittedToContent"] = True
        _follow_subject(doc, layer, frame, fitted)
    return doc


# How much of the smaller of the two frames must be shared before a decoration counts as
# sitting BEHIND the subject rather than merely near it.
BACKING_OVERLAP = 0.5


def _follow_subject(doc: DesignDoc, subject: ImageLayer,
                    before: Frame, after: Frame) -> None:
    """Move and rescale the colour field a skeleton authored behind this subject.

    A halo, a blob, an arch: the author drew it around the product, and once the product
    is reshaped to its cutout the field no longer has anything to do with it — a bottle
    refitted to a third of its authored width leaves a peach lozenge three times wider
    than the thing it was backing, sitting on the canvas as an unexplained shape.

    Scaled uniformly, by the square root of the area change, so an organic blob keeps its
    own proportions instead of being squashed into a sliver by a subject that grew tall
    and narrow. Recentred on the subject, because that is the whole relationship.
    """
    if before.w <= 0 or before.h <= 0:
        return
    scale = math.sqrt((after.w * after.h) / (before.w * before.h))
    if abs(math.log(scale)) < 0.04:
        return
    subject_index = doc.layers.index(subject)
    old_cx, old_cy = before.x + before.w / 2, before.y + before.h / 2
    new_cx, new_cy = after.x + after.w / 2, after.y + after.h / 2

    for backing in doc.layers[:subject_index]:
        if backing.role != "decoration" or not backing.visible:
            continue
        if backing.frame.w <= 0 or backing.frame.h <= 0:
            continue
        shared = _overlap(backing.frame, before)
        smaller = min(backing.frame.w * backing.frame.h, before.w * before.h)
        if smaller <= 0 or shared / smaller < BACKING_OVERLAP:
            continue

        width, height = backing.frame.w * scale, backing.frame.h * scale
        # The offset from the subject's centre travels with it, scaled the same way.
        dx = (backing.frame.x + backing.frame.w / 2 - old_cx) * scale
        dy = (backing.frame.y + backing.frame.h / 2 - old_cy) * scale
        backing.frame = Frame(x=new_cx + dx - width / 2, y=new_cy + dy - height / 2,
                              w=width, h=height, rotation=backing.frame.rotation)
        backing.meta.notes["followedSubject"] = subject.id
        log.info("fit.backing_followed", layer_id=backing.id, subject_id=subject.id,
                 scale=round(scale, 3))


def _overlap(a: Frame, b: Frame) -> float:
    w = max(0.0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    h = max(0.0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    return w * h


# A layer that is meant to sit over the subject, or behind everything, is not a
# neighbour the subject has to make room for.
_TRANSPARENT_TO_SUBJECT = ("background", "overlay", "decoration")

# Breathing room left between the subject and the layer above or below it, as a fraction
# of the canvas's shorter side. Growing flush to a headline is not a collision, but it
# reads as one.
BAND_GUTTER = 0.012


def free_band(doc: DesignDoc, subject: ImageLayer) -> tuple[float, float]:
    """The vertical range this subject may occupy without displacing anything.

    A skeleton allocates the subject a BAND of the canvas, and the layers above and below
    it are the design. Area preservation alone does not know that: a tall cutout dropped
    into a wide frame grows on its long axis until it spans two thirds of the canvas, and
    the collision solver then evicts whatever it landed on — which is how a headline
    authored across the top of a product card ended up underneath the product, below the
    fold, with the CTA pill pushed off its own label.

    Only layers that actually share the subject's columns count. A prop tucked beside it,
    or a caption in the other half of the canvas, constrains nothing.
    """
    top, bottom = 0.0, float(doc.canvas.height)
    left, right = subject.frame.x, subject.frame.x + subject.frame.w
    centre = subject.frame.y + subject.frame.h / 2

    for other, ancestors in walk(doc.layers):
        if ancestors or other is subject or not other.visible:
            continue
        if other.role in _TRANSPARENT_TO_SUBJECT or other.constraints.allow_overlap:
            continue
        if other.frame.w <= 0 or other.frame.h <= 0:
            continue
        # Side by side, not stacked: no vertical claim on the subject's band.
        if other.frame.x + other.frame.w <= left or other.frame.x >= right:
            continue
        other_bottom = other.frame.y + other.frame.h
        if other_bottom <= centre:
            top = max(top, other_bottom)
        elif other.frame.y >= centre:
            bottom = min(bottom, other.frame.y)

    gutter = min(doc.canvas.width, doc.canvas.height) * BAND_GUTTER
    top = min(top + gutter, centre)
    bottom = max(bottom - gutter, centre)
    return top, bottom


def _reshape(frame: Frame, content_aspect: float, canvas_w: int, canvas_h: int,
             horizontal: str, vertical: str,
             band: tuple[float, float] | None = None) -> Frame | None:
    """A frame of `content_aspect` with the same area, anchored as the skeleton asked."""
    area = frame.w * frame.h
    height = math.sqrt(area / content_aspect)
    width = content_aspect * height

    # Never taller than the free band, however much area that costs. The alternative is
    # the subject taking the space and the layout losing a layer to make room.
    band_height = (band[1] - band[0]) if band else float(canvas_h)
    band_height = max(band_height, frame.h) if band else band_height

    # Clamp growth per edge, then re-derive the other edge so the aspect still holds —
    # the whole point is that the frame matches the content.
    scale = min(1.0,
                MAX_EDGE_GROWTH * frame.w / width,
                MAX_EDGE_GROWTH * frame.h / height,
                band_height / height if height > band_height else 1.0,
                canvas_w / width if width > canvas_w else 1.0,
                canvas_h / height if height > canvas_h else 1.0)
    width, height = width * scale, height * scale
    if width <= 0 or height <= 0:
        return None

    x = _anchor(frame.x, frame.w, width, horizontal, ("left", "right"))
    y = _anchor(frame.y, frame.h, height, vertical, ("top", "bottom"))

    # Keep the reshaped frame on the canvas unless the original already bled off it, in
    # which case the bleed was deliberate and is preserved by the anchor above.
    if frame.x >= 0 and frame.x + frame.w <= canvas_w:
        x = max(0.0, min(x, canvas_w - width))
    if frame.y >= 0 and frame.y + frame.h <= canvas_h:
        y = max(0.0, min(y, canvas_h - height))

    # An authored bleed is a direction, not a blank cheque. Reshaping can carry a frame
    # far past the edge the author nudged it over — a subject authored 4% off the right
    # grows on its long axis and ends up a third off-canvas, which reads as a cropping
    # accident rather than as a composition.
    x, y, width, height = _limit_bleed(x, y, width, height, canvas_w, canvas_h)
    if band is not None:
        # Anchoring can still push a frame that FITS the band outside it.
        y = min(max(y, band[0]), max(band[0], band[1] - height))
    return Frame(x=x, y=y, w=width, h=height, rotation=frame.rotation)


def _limit_bleed(x: float, y: float, w: float, h: float,
                 canvas_w: int, canvas_h: int) -> tuple[float, float, float, float]:
    """Slide, then shrink, until no more than `MAX_OFFCANVAS_FRACTION` is off each edge.

    Sliding first preserves the subject's size, which is what the area invariant above
    was protecting; shrinking is the fallback for a frame too large to fit either way.
    """
    allow_x, allow_y = w * MAX_OFFCANVAS_FRACTION, h * MAX_OFFCANVAS_FRACTION
    if w - 2 * allow_x > canvas_w:
        scale = canvas_w / (w - 2 * allow_x)
        w, h = w * scale, h * scale
        allow_x, allow_y = w * MAX_OFFCANVAS_FRACTION, h * MAX_OFFCANVAS_FRACTION
    if h - 2 * allow_y > canvas_h:
        scale = canvas_h / (h - 2 * allow_y)
        w, h = w * scale, h * scale
        allow_x, allow_y = w * MAX_OFFCANVAS_FRACTION, h * MAX_OFFCANVAS_FRACTION

    x = min(max(x, -allow_x), canvas_w - w + allow_x)
    y = min(max(y, -allow_y), canvas_h - h + allow_y)
    return x, y, w, h


def _anchor(origin: float, old: float, new: float, mode: str,
            edges: tuple[str, str]) -> float:
    """Where the resized box starts, holding whichever edge the constraint pins."""
    near, far = edges
    if mode == near:
        return origin
    if mode == far:
        return origin + old - new
    return origin + (old - new) / 2.0
