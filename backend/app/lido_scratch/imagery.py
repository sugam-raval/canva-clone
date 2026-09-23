"""Guaranteeing the design actually shows its subject.

A brief that names a subject ("the grand opening of a warm neighbourhood restaurant")
wants that subject on the page. The model decides whether to use a photo element, and
it decides inconsistently: the same brief produced a hero cutout on one run and a page
of pure type on the next. Type-only is a legitimate design, but it is not a *choice*
when it happens by omission, and a poster for a restaurant with nothing of the
restaurant on it is the plainest of the failures this pipeline exists to fix.

So a design that ended up with no imagery at all gets one subject, added *before*
`layout.repair` rather than after. Placing it afterwards — into whatever empty band the
finished layout happened to leave — sounds tidier and does not work: `repair` has by
then spread the copy to fill the frame, so there is no band left and the subject is
declined on every page that needed it most. Added first, it is laid out like any other
element, everything below it moves down to make room, and if the page then cannot hold
it `layout._reclaim_from_imagery` shrinks it back rather than dropping the copy.
"""

from __future__ import annotations

from app.schema.brief import DesignBrief

from .spec import DesignSpec, SpecElement

SUBJECT_HEIGHT = 0.30
"""Height as a fraction of canvas. Big enough to be the hero of the page, small enough
that `repair` can still fit the copy around it; it is shrunk from here if not."""

SUBJECT_WIDTH = 0.56
"""Width as a fraction of canvas. Narrower than the text measure on purpose — a cutout
spanning the full width reads as a banner, not as a subject standing on the page."""

SUBJECT_DROP = 0.06
"""Clear space left between the headline block and the subject below it."""

#: Roles that belong above the subject. Everything else is pushed below it, which is
#: what makes the cutout the hinge of the composition rather than a footnote under it.
_ABOVE = ("brand", "headline", "tagline", "subhead")


def ensure_subject(spec: DesignSpec, brief: DesignBrief) -> bool:
    """Add one cutout of the brief's subject if the design shows nothing at all.

    Returns whether anything was added. A design that already has a photo, or a brief
    with no subject to show, is left exactly as it is.
    """
    if any(element.kind == "photo" for element in spec.elements):
        return False
    subject = brief.subject_at(0)
    if not subject:
        return False

    texts = [e for e in spec.elements if e.kind == "text" and (e.text or "").strip()]
    if not texts:
        return False
    head = [e for e in texts if e.role in _ABOVE] or texts[:1]
    top = max(e.y for e in head) + SUBJECT_DROP

    mood = " ".join(brief.mood) or "clean, professional"
    spec.elements.append(SpecElement(
        kind="photo",
        cutout=True,
        image_prompt=f"{subject}, {mood}",
        x=(1 - SUBJECT_WIDTH) / 2,
        y=min(top, 1 - SUBJECT_HEIGHT),
        w=SUBJECT_WIDTH,
        h=SUBJECT_HEIGHT,
    ))
    return True
