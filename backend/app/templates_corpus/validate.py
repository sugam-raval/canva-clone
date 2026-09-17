"""Corpus validation — IMPLEMENTATION_PLAN §1.2 ("validates each skeleton against Zod").

Catches the authoring mistakes that are invisible in JSON but obvious on screen:
slots outside the canvas, required slots overlapping before a single word of copy has
been placed, autofit bounds that cannot converge, and variant patches that name a slot
that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schema.template import Slot, TemplateSkeleton
from app.templates_corpus.ornament import ICON_MOTIFS, MOTIFS, is_stroked

# Ornament thinner than this in either axis is a rule or a divider rather than a field,
# and is the kind that disappears entirely when it is authored behind a subject.
LINE_ORNAMENT_THICKNESS = 0.06

# Slots may bleed off the canvas deliberately (full-bleed images, subjects running off
# an edge), but not by an absurd amount — that is almost always a typo.
MAX_BLEED = 0.35


@dataclass
class CorpusIssue:
    template_id: str
    code: str
    message: str
    slot_id: str | None = None
    severity: str = "error"


def _overlap_area(a: Slot, b: Slot) -> float:
    ax0, ay0 = a.frame_n.x, a.frame_n.y
    ax1, ay1 = ax0 + a.frame_n.w, ay0 + a.frame_n.h
    bx0, by0 = b.frame_n.x, b.frame_n.y
    bx1, by1 = bx0 + b.frame_n.w, by0 + b.frame_n.h
    w = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    h = max(0.0, min(ay1, by1) - max(ay0, by0))
    return w * h


def validate_skeleton(skeleton: TemplateSkeleton) -> list[CorpusIssue]:
    issues: list[CorpusIssue] = []
    ids = [s.slot_id for s in skeleton.slots]

    if len(ids) != len(set(ids)):
        issues.append(CorpusIssue(skeleton.id, "duplicate-slot-id",
                                  "two slots share a slotId"))
    if len(skeleton.description.split()) < 12:
        issues.append(CorpusIssue(
            skeleton.id, "thin-description",
            "description is embedded for retrieval and should read like a design brief",
            severity="warning"))

    for slot in skeleton.slots:
        frame = slot.frame_n
        if frame.x < -MAX_BLEED or frame.y < -MAX_BLEED:
            issues.append(CorpusIssue(skeleton.id, "slot-off-canvas",
                                      f"origin ({frame.x}, {frame.y}) is far off-canvas",
                                      slot.slot_id))
        if frame.x + frame.w > 1 + MAX_BLEED or frame.y + frame.h > 1 + MAX_BLEED:
            issues.append(CorpusIssue(skeleton.id, "slot-off-canvas",
                                      "slot extends far beyond the canvas", slot.slot_id))

        if slot.layer_type == "text":
            if slot.text is None:
                issues.append(CorpusIssue(skeleton.id, "missing-text-spec",
                                          "text slot has no text spec", slot.slot_id))
            else:
                fit = slot.text.auto_fit_n
                if fit.min > fit.max:
                    issues.append(CorpusIssue(skeleton.id, "bad-autofit",
                                              f"autofit min {fit.min} exceeds max {fit.max}",
                                              slot.slot_id))
                if not (fit.min <= slot.text.size_n <= fit.max * 1.001):
                    issues.append(CorpusIssue(
                        skeleton.id, "size-outside-autofit",
                        f"sizeN {slot.text.size_n} is outside its autofit bounds "
                        f"[{fit.min}, {fit.max}]", slot.slot_id))
                if slot.text.max_chars < 4:
                    issues.append(CorpusIssue(skeleton.id, "tiny-max-chars",
                                              "maxChars is too small to hold any copy",
                                              slot.slot_id))
        if slot.layer_type == "image" and slot.image is None:
            issues.append(CorpusIssue(skeleton.id, "missing-image-spec",
                                      "image slot has no image spec", slot.slot_id))
        if slot.layer_type == "shape" and slot.shape is None:
            issues.append(CorpusIssue(skeleton.id, "missing-shape-spec",
                                      "shape slot has no shape spec", slot.slot_id))
        if slot.shape is not None and slot.shape.motif:
            if slot.shape.motif not in MOTIFS:
                issues.append(CorpusIssue(
                    skeleton.id, "unknown-motif",
                    f"motif {slot.shape.motif!r} is not in the ornament library",
                    slot.slot_id))
            elif slot.shape.shape != "path":
                issues.append(CorpusIssue(
                    skeleton.id, "motif-wrong-shape",
                    "a motif slot must declare shape 'path'", slot.slot_id))
            elif is_stroked(slot.shape.motif) and slot.shape.stroke_width_n <= 0:
                issues.append(CorpusIssue(
                    skeleton.id, "motif-needs-stroke",
                    f"motif {slot.shape.motif!r} draws open contours and would flood "
                    f"if filled; it needs a strokeWidthN", slot.slot_id))
            if slot.required:
                issues.append(CorpusIssue(
                    skeleton.id, "required-ornament",
                    "ornament must be optional so the solver can drop it under pressure",
                    slot.slot_id, severity="warning"))

    # Required, visible, non-background slots must not overlap before any copy exists.
    # A CTA label sitting on its own pill is the one legitimate exception.
    positional = [s for s in skeleton.slots
                  if s.required and s.role not in ("background", "overlay", "decoration")]
    for i, a in enumerate(positional):
        for b in positional[i + 1:]:
            if _paired_label(a, b):
                continue
            if (a.constraints.allow_overlap or b.constraints.allow_overlap) and not (
                    a.layer_type == "text" and b.layer_type == "text"):
                continue   # declared depth: type behind a subject, a prop over one
            overlap = _overlap_area(a, b)
            smaller = min(a.frame_n.w * a.frame_n.h, b.frame_n.w * b.frame_n.h)
            if smaller > 0 and overlap / smaller > 0.12:
                issues.append(CorpusIssue(
                    skeleton.id, "required-slots-overlap",
                    f"required slots {a.slot_id!r} and {b.slot_id!r} overlap by "
                    f"{overlap / smaller:.0%} of the smaller slot", a.slot_id))

    issues.extend(_check_pairings(skeleton))
    issues.extend(_check_icons(skeleton))

    known = set(ids)
    for variant in skeleton.variants:
        for slot_id in variant.patch:
            if slot_id not in known:
                issues.append(CorpusIssue(
                    skeleton.id, "variant-unknown-slot",
                    f"variant {variant.id!r} patches unknown slot {slot_id!r}", slot_id))

    issues.extend(_check_ornament_depth(skeleton))
    issues.extend(_check_coverage(skeleton))

    if "text-only" in skeleton.tags:
        subjects = [s.slot_id for s in skeleton.slots if s.role == "subject"]
        if subjects:
            issues.append(CorpusIssue(
                skeleton.id, "text-only-has-subject",
                f"tagged text-only but declares subject slots {subjects}; retrieval "
                f"filters on this tag so the mismatch would surface the wrong template"))
    return issues


def aspect_ratio(aspect: str) -> float:
    """'4:5' -> 0.8. Width over height, the factor between the two normalised axes."""
    try:
        w, h = (float(part) for part in aspect.split(":", 1))
        return w / h if h else 1.0
    except (ValueError, ZeroDivisionError):
        return 1.0


def _check_pairings(skeleton: TemplateSkeleton) -> list[CorpusIssue]:
    """`pairsWith` must name a real slot, and the partner must be the one that carries
    the content. A tick paired with another tick survives on nothing."""
    issues: list[CorpusIssue] = []
    by_id = {s.slot_id: s for s in skeleton.slots}
    for slot in skeleton.slots:
        partner_id = slot.pairs_with
        if partner_id is None:
            continue
        if partner_id == slot.slot_id:
            issues.append(CorpusIssue(skeleton.id, "self-pairing",
                                      "a slot cannot pair with itself", slot.slot_id))
            continue
        partner = by_id.get(partner_id)
        if partner is None:
            issues.append(CorpusIssue(
                skeleton.id, "pairs-with-unknown-slot",
                f"pairsWith names {partner_id!r}, which no slot declares",
                slot.slot_id))
            continue
        if partner.pairs_with is not None:
            issues.append(CorpusIssue(
                skeleton.id, "pairing-chain",
                f"{slot.slot_id!r} pairs with {partner_id!r}, which is itself paired; "
                f"pair with the slot that actually carries the content",
                slot.slot_id, severity="warning"))
        if slot.required and not partner.required:
            issues.append(CorpusIssue(
                skeleton.id, "required-slot-paired-to-optional",
                f"{slot.slot_id!r} is required but its partner {partner_id!r} is not, "
                f"so it can outlive what it annotates", slot.slot_id))
    return issues


def _check_icons(skeleton: TemplateSkeleton) -> list[CorpusIssue]:
    """Pictograms must be square in PIXELS and must annotate something.

    Both mistakes are invisible in the numbers and obvious on screen: an icon authored
    square in normalised units comes out 20 percent tall on a 4:5 post, and one with no
    `pairsWith` outlives the line it belongs to and points at empty space.
    """
    issues: list[CorpusIssue] = []
    ratio = aspect_ratio(skeleton.aspect)
    for slot in skeleton.slots:
        if slot.shape is None or slot.shape.motif not in ICON_MOTIFS:
            continue
        drawn = (slot.frame_n.w * ratio) / slot.frame_n.h if slot.frame_n.h else 0.0
        if not 0.92 <= drawn <= 1.08:
            issues.append(CorpusIssue(
                skeleton.id, "icon-not-square",
                f"pictogram renders at {drawn:.2f}:1; icons are drawn in a unit square "
                f"and letterbox inside a non-square slot", slot.slot_id))
        if slot.pairs_with is None:
            issues.append(CorpusIssue(
                skeleton.id, "unpaired-icon",
                "a pictogram annotates something; give it pairsWith so it is dropped "
                "with whatever it annotates", slot.slot_id, severity="warning"))
    return issues


def _check_ornament_depth(skeleton: TemplateSkeleton) -> list[CorpusIssue]:
    """A motif that overlaps a subject must sit in front of it.

    This is about *line* ornament specifically — a divider, a rule, a flourish. A blob, an
    arch or a colour sweep behind a subject is a backdrop and belongs there; a hairline
    rule behind one is not subtly obscured, it is gone, except for the two stubs poking
    out at either end, which look exactly like a rendering bug. The subject is also the
    one slot whose frame is reshaped at runtime to match the cutout that arrives, so a
    rule that clears it in the skeleton may not clear it on screen; depth is the only
    thing that holds.
    """
    issues: list[CorpusIssue] = []
    subjects = [s for s in skeleton.slots if s.role == "subject"]
    motifs = [s for s in skeleton.slots
              if s.shape is not None and s.shape.motif and s.role == "decoration"]
    for motif in motifs:
        # Thin in one axis and not spanning the other: a rule, not a field.
        thin = min(motif.frame_n.w, motif.frame_n.h) <= LINE_ORNAMENT_THICKNESS
        if not thin:
            continue
        for subject in subjects:
            if _overlap_area(motif, subject) <= 0:
                continue
            if motif.z_index > subject.z_index:
                continue
            issues.append(CorpusIssue(
                skeleton.id, "ornament-behind-subject",
                f"motif {motif.slot_id!r} (z={motif.z_index}) overlaps subject "
                f"{subject.slot_id!r} (z={subject.z_index}) and would be hidden by it",
                motif.slot_id))
    return issues


def _check_coverage(skeleton: TemplateSkeleton) -> list[CorpusIssue]:
    """Warn when a skeleton leaves a large band of the canvas with nothing in it.

    Flat-colour grounds are excluded from the measurement on purpose: colour under nothing
    is precisely the dead space being looked for. A full-bleed *photograph* is not
    excluded — it is real content, and a poster that is one big image with a line of type
    is a poster, not an empty canvas. The canvas is scanned as horizontal bands because
    that is how emptiness actually shows up: a design is rarely empty down one side, it is
    empty across the bottom third.
    """
    # A skeleton that declares itself minimal is not accidentally empty. Whitespace is
    # the design, and the check has nothing to tell its author.
    if {"minimal", "whitespace"} & set(skeleton.tags):
        return []

    bands = 12
    occupied = [False] * bands
    for slot in skeleton.slots:
        if slot.role == "overlay":
            continue
        # A flat ground — a colour panel, or a texture with no subject in it — is the
        # backdrop the emptiness is measured against, not content filling it.
        if slot.role == "background" and slot.layer_type != "image":
            continue
        if slot.layer_type == "shape" and not (slot.shape and slot.shape.motif) \
                and slot.frame_n.w >= 0.99 and slot.frame_n.h >= 0.99:
            continue
        top = max(0.0, slot.frame_n.y)
        bottom = min(1.0, slot.frame_n.y + slot.frame_n.h)
        for band in range(bands):
            lo, hi = band / bands, (band + 1) / bands
            if min(bottom, hi) - max(top, lo) > 0:
                occupied[band] = True

    run = best = 0
    for filled in occupied:
        run = 0 if filled else run + 1
        best = max(best, run)
    if best >= 4:
        return [CorpusIssue(
            skeleton.id, "dead-band",
            f"{best}/{bands} of the canvas height is one unbroken band with no slot in "
            f"it; the design will read as unfinished", severity="warning")]
    return []


def _paired_label(a: Slot, b: Slot) -> bool:
    """A CTA text slot drawn on top of its own CTA shape is intentional."""
    roles = {a.role, b.role}
    types = {a.layer_type, b.layer_type}
    return len(roles) == 1 and types == {"text", "shape"}


def validate_corpus(skeletons: list[TemplateSkeleton]) -> list[CorpusIssue]:
    issues: list[CorpusIssue] = []
    seen: set[str] = set()
    for skeleton in skeletons:
        if skeleton.id in seen:
            issues.append(CorpusIssue(skeleton.id, "duplicate-template-id",
                                      "two skeletons share an id"))
        seen.add(skeleton.id)
        issues.extend(validate_skeleton(skeleton))
    return issues
