"""Geometry and colour repair for a generated `DesignSpec`.

An LLM composes well and measures badly. It will place a headline at y=0.42 and a
subhead at y=0.45 without noticing the headline wraps to three lines and swallows it,
or run a caption off the bottom edge. None of that is a reasoning failure — the model
cannot know how the text wraps, because wrapping depends on metrics it never sees.

So the model's output is treated as *intent* and everything measurable is recomputed
here: clamp to the margin, estimate the wrapped height, push overlaps apart, shrink the
type until the page fits, and pick a legible colour against whatever ground each
element actually lands on. `repair()` is deterministic — the same spec in gives the
same layout out.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from itertools import pairwise

from app.util.color import (
    contrast_ratio,
    delta_e,
    harmonious_on,
    parse_hex,
    relative_luminance,
    saturation,
    to_hex,
)

from . import background, fonts
from . import palette as pal
from .spec import LINE_HEIGHT_FOR, ROLE_DEFAULTS, SIZE_RATIO, TRACKING_EM, DesignSpec, SpecElement

MARGIN = 0.055
"""Minimum clear edge, as a fraction. Generated pages crowd their edges otherwise."""

LINE_HEIGHT = 1.18
"""Fallback leading for a size class with no entry in `LINE_HEIGHT_FOR`."""
GAP = 0.018
"""Minimum clear space between two elements that would otherwise collide."""

PILL_PAD_Y = 0.022
"""Vertical padding a CTA pill puts above and below its text.

It lives here rather than in `decor` because the collision pass has to reserve the
room *before* the pill exists — ornament is placed against a finished layout and
nothing moves out of its way afterwards. `decor` imports it back.
"""

BADGE_CLEARANCE = 0.026
"""Room kept around a role='offer' line for the disc stamped behind it."""

#: Extra clear space a role needs beyond `GAP`, because something will later be drawn
#: around it. Without this the pill is built over whatever line happened to sit one
#: `GAP` below the call to action, and the page comes back with two sentences printed
#: across the button.
_ROLE_CLEARANCE: dict[str, float] = {"cta": PILL_PAD_Y, "offer": BADGE_CLEARANCE}


def _clearance(element: SpecElement) -> float:
    """Ornament padding to reserve above and below this element."""
    return _ROLE_CLEARANCE.get(element.role or "", 0.0)

MIN_FONT_PX = 9.0
SHRINK_FLOOR = 0.62
"""Never shrink type below this fraction of its spec size — past it the design is
overfull in a way scaling cannot fix, and clipping is the honest outcome."""

SCRIM_PAD_X = 0.035
SCRIM_PAD_Y = 0.025
"""Clear space the scrim keeps beyond the text it protects, as a fraction of canvas."""

SCRIM_CLUSTER_GAP = 0.05
"""Text elements closer than this (as a fraction of canvas height) are treated as one
reading group and share a single scrim, instead of one panel per line."""

SCRIM_OPACITY = 0.55

FEATURE_GUTTER = 0.032
"""Space reserved at the left of a 'feature' (bullet-list) text element for its dot,
as a fraction of canvas width."""

ACCENT_CLASH_DELTA_E = 12.0
"""How close a colour has to be to the accent to count as the accent.

The reserved accent is also the colour the background is painted with — the brush
sweep, the halftone block, the glow. Text set in it disappears the moment it crosses
that mark, which no contrast check against the flat ground can see: a real page came
back with the offer at 6.05 against the ground and invisible on the stroke behind it.
"""

ULTRA_TRACKING_MAX_CHARS = 24
"""Longest line that may be set at 'ultra' tracking. Past this the spaced-out sub-line
wraps, which is neither the effect nor a layout that fits."""

FEATURE_BULLET_RATIO = 0.30
"""Bullet diameter as a fraction of that feature line's own font size — a dot sized
to the text it marks, not a fixed pixel size that reads wrong at any other scale."""


def _curate_palette(spec: DesignSpec) -> None:
    """Replace the model's colour list with a structured one.

    `palette.refine` keeps whatever the model already got right and manufactures the
    rest — a deep ground, one reserved accent, a support colour and two tinted
    neutrals. `_assign_colors` below can only pick from this list, so this is where a
    design's whole colour quality is decided; the previous step only pushed
    near-duplicates apart, which left a flat palette flat.
    """
    subject = " ".join(filter(None, [
        spec.name, spec.kind, spec.background.motif or "",
        *(e.text or "" for e in spec.elements if e.kind == "text"),
    ]))
    spec.palette = pal.refine(spec.palette, subject)
    if not spec.background.color or spec.background.color == "#101418":
        # The ground the page is actually drawn on has to be the palette's ground, or
        # the background colour and the colour every element was contrasted against
        # are two different colours and the type resolves against a fiction.
        spec.background.color = spec.palette[0]


def _apply_role_defaults(spec: DesignSpec) -> None:
    """Fill in each text element's typographic conventions where it stated none.

    The model is good at deciding that a line is a tagline and bad at remembering that
    a tagline is set uppercase and tracked out. Anything it set explicitly is left
    alone — these are defaults, not corrections.
    """
    for element in spec.elements:
        if element.kind != "text":
            continue
        if element.role == "offer" and element.size in ("display", "title", "heading"):
            # A roundel is a stamp, not a headline. At 'heading' or above the disc
            # `decor` fits around it swallows half the canvas, and the offer starts
            # competing with the thing it is supposed to be a footnote to.
            element.size = "body"
        defaults = ROLE_DEFAULTS.get(element.role or "", {})
        if element.tracking is None:
            element.tracking = defaults.get("tracking", "normal")
        if element.tracking == "ultra" and (
                element.size in ("display", "title")
                or len((element.text or "").strip()) > ULTRA_TRACKING_MAX_CHARS):
            # Extreme tracking is a device for one short line. On display type it is
            # not a style but a headline broken into scattered letters, and on a long
            # line it simply wraps — which drags the whole page past the bottom margin
            # and loses the effect anyway.
            element.tracking = "wide"
        if element.transform == "none" and "transform" in defaults:
            element.transform = defaults["transform"]


BADGE_MAX_WIDTH = 0.32
"""Widest a roundel may get, as a fraction of canvas width — the same cap `decor`
applies. Layout needs it to know, before ornament exists, whether an offer is going to
earn a disc, because that is what decides whether it may sit on the hero image."""

INK_SAFETY = 1.08
"""Margin on the estimated text width. The mean-advance heuristic is a few percent
either way, and the two directions are not symmetric: over-estimating gives a slightly
roomy disc, under-estimating hangs the last character off it onto the dark ground."""


def text_ink_width(element: SpecElement, spec: DesignSpec, scale: float) -> float:
    """Roughly how wide the words actually are, as a canvas fraction.

    A text layer's `w` is its wrap limit, not its ink: a right-aligned caption in a
    0.37-wide box may only set 0.18 of the canvas. Anything hung off the *text* — a
    chip, a disc, a rule — has to measure the ink, or it lands in the empty half of
    the box.
    """
    size_px = font_px(element, spec, scale)
    longest = max((len(line) for line in (element.text or "").split("\n")), default=0)
    advance = fonts.advance_ratio(fonts.face_for(
        element.font, spec.vibe, display=element.size in ("display", "title")))
    ink = longest * size_px * (advance + tracking_em(element)) / spec.width
    return min(element.w, ink * INK_SAFETY)


def wants_badge(element: SpecElement, spec: DesignSpec, scale: float) -> bool:
    """Whether `decor` will actually stamp a disc behind this offer.

    'SAVE 50%' gets one; 'Free for the first 100 customers' is far too long for a disc
    that is not a third of the page, so it gets none — and an offer with no disc is
    ordinary text with no business sitting on top of the hero image.
    """
    if element.role != "offer":
        return False
    aspect = spec.width / max(spec.height, 1)
    height = element_height(element, spec, scale)
    diameter = max(text_ink_width(element, spec, scale), height / aspect) + 0.09
    return diameter <= BADGE_MAX_WIDTH


def tracking_em(element: SpecElement) -> float:
    """Letter spacing as a fraction of font size."""
    return TRACKING_EM.get(element.tracking or "normal", 0.0)


def line_height(element: SpecElement) -> float:
    """Leading as a multiple of font size, by size class."""
    return LINE_HEIGHT_FOR.get(element.size, LINE_HEIGHT)


def font_px(element: SpecElement, spec: DesignSpec, scale: float = 1.0) -> float:
    short_edge = min(spec.width, spec.height)
    return max(MIN_FONT_PX, SIZE_RATIO.get(element.size, SIZE_RATIO["body"])
               * short_edge * scale)


def _line_count(element: SpecElement, spec: DesignSpec, size_px: float) -> int:
    """Wrapped line count. Calls the exact same `fonts.wrap_text` the compiler
    uses to split this element's actual paragraphs, so a block is never taller
    on the page than layout reserved room for, or shorter than what gets built."""
    text = (element.text or "").strip()
    if not text:
        return 0
    family = fonts.face_for(element.font, spec.vibe,
                            display=element.size in ("display", "title"))
    width_px = max(1.0, element.w * spec.width)
    return len(fonts.wrap_text(text, family, size_px, width_px, tracking_em(element)))


def element_height(element: SpecElement, spec: DesignSpec, scale: float = 1.0) -> float:
    """Height as a fraction of canvas height — the *layout* box.

    This is leading, which is what stacking cares about. It is not where the ink ends:
    display type is set at 0.94 leading, so the box is shorter than the glyphs in it.
    Anything drawn *against* the type wants `visual_bottom` instead.
    """
    if element.kind != "text":
        return element.h if element.h is not None else 0.25
    size_px = font_px(element, spec, scale)
    return (_line_count(element, spec, size_px) * size_px
            * line_height(element)) / spec.height


INK_LEADING_FLOOR = 1.06
"""Leading to assume when measuring where the ink actually ends, including descenders.

Display type is set at 0.94 leading, so its layout box finishes *above* the bottom of
its own glyphs. An accent rule positioned off that box lands inside the headline and
strikes through it — which is exactly what a real page came back with.
"""


def visual_bottom(element: SpecElement, spec: DesignSpec, scale: float = 1.0) -> float:
    """Where this element's ink actually ends, as a fraction of canvas height."""
    if element.kind != "text":
        return element.y + (element.h if element.h is not None else 0.25)
    size_px = font_px(element, spec, scale)
    lines = _line_count(element, spec, size_px)
    leading = max(line_height(element), INK_LEADING_FLOOR)
    return element.y + (lines * size_px * leading) / spec.height


def _clamp_horizontal(element: SpecElement) -> None:
    element.w = min(element.w, 1 - 2 * MARGIN)
    element.x = min(max(element.x, MARGIN), 1 - MARGIN - element.w)


def _overlaps_horizontally(a: SpecElement, b: SpecElement) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w


def _resolve_collisions(elements: list[SpecElement], spec: DesignSpec, scale: float,
                        slack: float = 1.0) -> float:
    """Push overlapping elements down the page. Returns the lowest bottom edge.

    Only elements that actually collide are moved, so the spec's own spacing — which
    carries the model's grouping intent — survives wherever it was already valid.

    `slack` below 1.0 additionally squeezes the empty space each element left above
    itself, by that factor. At 1.0 (the normal pass) nothing is squeezed and the
    model's spacing is untouched; `repair` lowers it only when the page would
    otherwise run off the bottom edge, because losing some air is a far smaller
    failure than losing the contact line off the trim.
    """
    ordered = sorted(elements, key=lambda e: e.y)
    placed: list[tuple[SpecElement, float]] = []
    lowest = 0.0
    for element in ordered:
        height = element_height(element, spec, scale)
        floor = MARGIN
        for other, other_bottom in placed:
            if not _overlaps_horizontally(element, other):
                continue
            if (other.kind == "photo"
                    and wants_badge(element, spec, scale)):
                # A roundel is *meant* to sit on the hero image — that overlap is the
                # design, not a collision, and pushing it clear of the photo is what
                # lands it in the middle of the headline. It still gives way to text,
                # because a disc stamped over the headline is not a design either.
                #
                # Only an offer that will actually *get* a disc, though. A long offer
                # gets none, and then this exemption is just a line of type printed
                # across the hero subject's face.
                continue
            floor = max(floor, other_bottom + GAP
                        + _clearance(element) + _clearance(other))
        top = max(element.y, floor)
        if slack < 1.0:
            top = floor + (top - floor) * slack
        element.y = top
        bottom = top + height
        placed.append((element, bottom))
        # The lowest *drawn* edge, not the lowest text edge: a pill hanging its bottom
        # cap over the trim is the same overflow as a caption doing it.
        lowest = max(lowest, bottom + _clearance(element))
    return lowest


GROUP_GAP = 0.045
"""A vertical gap at least this big separates two groups rather than spacing lines
within one. Only these gaps are opened up when the page has room to spare, so a
headline and the subhead tucked under it stay tucked."""

BALANCE_MIN_SLACK = 0.07
"""Leftover space below which the page is close enough to full to leave alone."""

BALANCE_MAX_STRETCH = 2.2
"""How far a separating gap may be opened, as a multiple of itself. Uncapped, a page
with one gap dumps all of its leftover space into it and the design comes apart."""

BACKDROP_MIN_HEIGHT = 0.85
"""A photo at least this tall is a backdrop, not a block in the stack — it is held
still while everything else is redistributed over it."""


def _balance_vertical(elements: list[SpecElement], spec: DesignSpec, scale: float,
                      lowest: float) -> None:
    """Spread leftover vertical space so the composition fills its frame.

    `_resolve_collisions` only ever pushes elements *down* far enough to stop them
    overlapping, which means a model that placed everything in the top half gets a page
    with everything in the top half and a third of the canvas empty below it. That dead
    band is one of the loudest tells of a generated layout: a designed poster either
    fills the frame or leaves its empty space deliberately, in the middle of the
    composition, not all of it pooled at the bottom.

    Space goes into the gaps *between groups*, never into the gaps within one, because
    proximity is what tells the reader which lines belong together — that is the one
    piece of the model's spacing intent worth protecting. Whatever the capped gaps
    cannot absorb re-centres the block instead.
    """
    limit = 1 - MARGIN
    slack = limit - lowest
    if slack < BALANCE_MIN_SLACK:
        return
    ordered = sorted(
        (e for e in elements
         if e.kind in ("text", "photo")
         and not (e.kind == "photo" and (e.h or 0.25) >= BACKDROP_MIN_HEIGHT)),
        key=lambda e: e.y,
    )
    if not ordered:
        return

    gaps = [
        nxt.y - (prev.y + element_height(prev, spec, scale) + _clearance(prev))
        for prev, nxt in pairwise(ordered)
    ]
    separators = [i for i, gap in enumerate(gaps) if gap >= GROUP_GAP]
    extra = [0.0] * len(gaps)
    if separators:
        share = slack / len(separators)
        for index in separators:
            extra[index] = min(share, gaps[index] * (BALANCE_MAX_STRETCH - 1))

    # Anything the gaps could not take drops the whole block toward the optical centre
    # rather than leaving it pinned to the top margin.
    shift = (slack - sum(extra)) / 2
    for index, element in enumerate(ordered):
        if index:
            shift += extra[index - 1]
        element.y += shift


def _ground_behind(element: SpecElement, spec: DesignSpec) -> str:
    """The colour an element is read against.

    A shape drawn behind the text is the ground for anything sitting on it, which is
    the whole point of a scrim — so a headline over a dark panel on a white page has to
    resolve against the panel, not the page.
    """
    for other in spec.elements:
        if other.kind != "shape" or not other.behind or not other.color:
            continue
        height = other.h if other.h is not None else 0.25
        if (_overlaps_horizontally(element, other)
                and other.y <= element.y + 0.02
                and element.y <= other.y + height):
            return other.color
    return spec.background.color


def _photo_bbox(element: SpecElement) -> tuple[float, float, float, float]:
    height = element.h if element.h is not None else 0.25
    return element.x, element.y, element.x + element.w, element.y + height


def _bbox_overlaps(a: tuple[float, float, float, float],
                   b: tuple[float, float, float, float]) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _busy_regions(spec: DesignSpec) -> list[tuple[float, float, float, float]]:
    """Bounding boxes of whatever might make text hard to read: the full canvas when
    the background is a photo, plus every non-cutout photo element. A cutout is left
    out on purpose — it is placed as a deliberate foreground subject, usually clear of
    the text precisely because the model chose where it sits, and papering a scrim
    behind it would hide the transparency that makes it worth generating."""
    regions = []
    if background.is_photographic(spec.background.style):
        # Only a *photographic* ground is unpredictable. A graphic treatment is drawn
        # from this design's own palette with a calm safe zone held for the type, so
        # veiling the whole page behind a grey panel there would throw away the
        # background the design just commissioned — that blanket scrim is a large part
        # of why generated pages came out looking muddy.
        regions.append((0.0, 0.0, 1.0, 1.0))
    for element in spec.elements:
        if element.kind == "photo" and not element.cutout:
            regions.append(_photo_bbox(element))
    return regions


def _cluster_text(elements: list[SpecElement], spec: DesignSpec,
                  scale: float) -> list[list[SpecElement]]:
    """Group text elements into reading blocks by vertical proximity, so a headline
    and its subhead share one scrim panel instead of each getting a separate box."""
    texts = sorted(
        (e for e in elements if e.kind == "text" and (e.text or "").strip()),
        key=lambda e: e.y,
    )
    clusters: list[list[SpecElement]] = []
    cursor_bottom = None
    for element in texts:
        if cursor_bottom is not None and element.y - cursor_bottom <= SCRIM_CLUSTER_GAP:
            clusters[-1].append(element)
        else:
            clusters.append([element])
        cursor_bottom = element.y + element_height(element, spec, scale)
    return clusters


def _at_lightness(color: str, lightness: float) -> str:
    """`color`'s hue and saturation at an absolute HLS lightness.

    Not `adjust_lightness`: that scales the existing lightness by a factor, which
    cannot pull an already near-black colour up to near-white — 0.05 lightened by
    1.8x is still 0.09. A scrim needs a specific target, not a relative nudge.
    """
    r, g, b = parse_hex(color)
    h, _l, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return to_hex(tuple(c * 255 for c in colorsys.hls_to_rgb(h, lightness, sat * 0.7)))


def _scrim_color(spec: DesignSpec) -> str:
    """A dark panel by default — the standard, reliable veil for text over a photo of
    unknown content — tinted with the design's own hue rather than flat black, so it
    reads as part of the palette. Flips to a light panel only when the ground is
    already so dark that a further-darkened scrim would barely register against it.
    """
    ground = spec.palette[0] if spec.palette else spec.background.color
    return _at_lightness(ground, 0.92 if relative_luminance(ground) < 0.12 else 0.10)


def _inject_scrims(spec: DesignSpec, scale: float) -> None:
    """Add a translucent panel behind any text block sitting over a photo or an image
    background, so legibility never depends on what the generated image turns out to
    contain. This is the one correction that cannot be delegated to colour choice
    alone — `harmonious_on` can pick a colour that is legible against a flat ground,
    but a photo has no single ground colour, and a warm portrait under bold red text
    is exactly the failure this exists to prevent.
    """
    busy = _busy_regions(spec)
    if not busy:
        return
    color = _scrim_color(spec)
    scrims: list[SpecElement] = []
    for cluster in _cluster_text(spec.elements, spec, scale):
        x0 = min(e.x for e in cluster) - SCRIM_PAD_X
        x1 = max(e.x + e.w for e in cluster) + SCRIM_PAD_X
        y0 = min(e.y for e in cluster) - SCRIM_PAD_Y
        y1 = max(e.y + element_height(e, spec, scale) for e in cluster) + SCRIM_PAD_Y
        bbox = (max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1))
        if not any(_bbox_overlaps(bbox, region) for region in busy):
            continue
        scrims.append(SpecElement(
            kind="shape", shape="rect", behind=True, color=color, opacity=SCRIM_OPACITY,
            x=bbox[0], y=bbox[1], w=bbox[2] - bbox[0], h=bbox[3] - bbox[1],
        ))
    spec.elements = scrims + spec.elements


def _inject_feature_bullets(spec: DesignSpec, scale: float) -> None:
    """A small filled circle to the left of every 'feature' text line — the bullet
    dot in front of each row of a job listing, menu, or amenities list. The model is
    told to write one text element per bullet point (`design_ai._system_prompt`,
    FEATURES section) rather than one paragraph with line breaks, precisely so this
    can attach real per-row markers instead of a plain wall of text.
    """
    bullets: list[SpecElement] = []
    for element in spec.elements:
        if element.kind != "text" or element.role != "feature":
            continue
        size_px = font_px(element, spec, scale)
        diameter_px = size_px * FEATURE_BULLET_RATIO
        cx = element.x - FEATURE_GUTTER / 2
        # Vertically centred on the first line's cap-height, not the whole (possibly
        # multi-line) block — a bullet belongs beside the first line, like a list
        # marker, not floating in the middle of a wrapped row.
        cy = element.y + (size_px * line_height(element) * 0.42) / spec.height
        bullets.append(SpecElement(
            kind="shape", shape="circle", behind=False,
            color=element.color, opacity=1.0,
            x=max(0.0, cx - diameter_px / spec.width / 2),
            y=max(0.0, cy - diameter_px / spec.height / 2),
            w=diameter_px / spec.width, h=diameter_px / spec.height,
        ))
    spec.elements = spec.elements + bullets


#: Which text gets the one reserved accent when no element dominates on size alone.
_ACCENT_PRIORITY = ("headline", "offer", "cta", "brand", "subhead")

_SIZE_RANK = ("display", "title", "heading", "body", "caption", "micro")


def _accent_holder(spec: DesignSpec) -> SpecElement | None:
    """The single element allowed to wear the palette's accent.

    Without this, `harmonious_on` hands every line the same passing palette colour and
    the page comes back set entirely in lime — which is not a legibility failure, it is
    the failure of the one rule that makes an accent an accent. The dominant element
    takes it; everything else is set in a neutral.
    """
    texts = [e for e in spec.elements
             if e.kind == "text" and (e.text or "").strip() and not e.color]
    if not texts:
        return None

    def rank(element: SpecElement) -> tuple[int, int]:
        size = _SIZE_RANK.index(element.size) if element.size in _SIZE_RANK else 99
        role = (_ACCENT_PRIORITY.index(element.role)
                if element.role in _ACCENT_PRIORITY else 99)
        return (size, role)

    return min(texts, key=rank)


def _assign_colors(spec: DesignSpec) -> None:
    palette = [c for c in spec.palette if c]
    accent = pal.accent_of(palette) if palette else ""
    # Everything that is not the accent, for the rest of the page to be set in — and
    # only the genuinely neutral part of it. A palette that kept a second high-chroma
    # colour hands it straight to the next line otherwise, and the page ends up with
    # a gold headline, a lime sub-line and no reserved accent at all.
    neutrals = [c for c in palette if c != accent and saturation(c) < 0.35] or \
        [c for c in palette if c != accent] or palette
    holder = _accent_holder(spec)

    for element in spec.elements:
        if element.kind == "photo":
            continue
        ground = _ground_behind(element, spec)
        if element.kind == "shape":
            if not element.color:
                element.color = accent or (palette[-1] if palette else "#FFFFFF")
            continue
        # Large type carries a lower bar, per WCAG — and it is also where a designer's
        # deliberately low-contrast choice is most often the right one. The same
        # threshold decides whether to keep the model's colour and what to replace it
        # with, so a colour that would be rejected is never one we could have picked.
        # Two thresholds, deliberately different. Large type *keeps* a colour at the
        # WCAG large-text bar of 3.0, because that is usually a designer's considered
        # low-contrast choice. But a colour we pick ourselves is held to 4.5 whatever
        # its size: at 3.0 the chooser settles for the palette's mid-tone support
        # green on a near-black ground, which passes and still reads as dim and
        # muddy — the exact quality problem, arriving through the accessibility door.
        keep_minimum = 3.0 if element.size in ("display", "title") else 4.5
        # One element wears the accent — including when the model chose the colour
        # itself. This was only ever enforced on colours we picked, so a spec that
        # named the accent outright walked straight past it, and the page came back
        # with the accent on two lines and one of them sitting on the accent-coloured
        # background it was drawn from.
        wears_accent = bool(
            element.color and accent and element is not holder
            and delta_e(element.color, accent) < ACCENT_CLASH_DELTA_E
        )
        if (element.color and not wears_accent
                and contrast_ratio(ground, element.color) >= keep_minimum):
            continue
        if element is holder and accent and contrast_ratio(ground, accent) >= 4.5:
            element.color = accent
            continue
        element.color = harmonious_on(ground, neutrals, minimum=4.5)


IMAGE_MIN_HEIGHT = 0.18
"""Shortest a photo may be squeezed to when the copy needs its room. Past this the
picture has stopped being a picture and the page should clip instead."""


def _compact(spec: DesignSpec, scale: float, limit: float) -> float:
    """Squeeze the air out in increasingly hard steps; return the lowest bottom edge."""
    lowest = _resolve_collisions(spec.elements, spec, scale)
    for slack in (0.7, 0.45, 0.2, 0.0):
        if lowest <= limit:
            break
        lowest = _resolve_collisions(spec.elements, spec, scale, slack)
    return lowest


def _reclaim_from_imagery(spec: DesignSpec, overflow: float) -> bool:
    """Take `overflow` back off the photos, tallest first. Returns whether any gave."""
    photos = sorted((e for e in spec.elements if e.kind == "photo"),
                    key=lambda e: -(e.h or 0.0))
    reclaimed = False
    for photo in photos:
        if overflow <= 0:
            break
        height = photo.h if photo.h is not None else 0.25
        give = min(overflow, max(0.0, height - IMAGE_MIN_HEIGHT))
        if give <= 0:
            continue
        photo.h = height - give
        overflow -= give
        reclaimed = True
    return reclaimed


@dataclass
class LayoutResult:
    spec: DesignSpec
    font_scale: float
    """What the type had to be scaled by to fit. 1.0 means the spec fit as designed."""


def repair(spec: DesignSpec) -> LayoutResult:
    """Clamp, de-overlap, shrink-to-fit and recolour. Mutates `spec` in place."""
    _curate_palette(spec)
    _apply_role_defaults(spec)
    for element in spec.elements:
        if element.kind == "text" and element.role == "feature":
            # Reserve room for the bullet dot `_inject_feature_bullets` adds later,
            # by narrowing the text block rather than the bullet overlapping it.
            element.x += FEATURE_GUTTER
            element.w = max(0.1, element.w - FEATURE_GUTTER)
        _clamp_horizontal(element)
        element.y = min(max(element.y, MARGIN), 1 - MARGIN)
        if element.kind != "text" and element.h is None:
            element.h = 0.25

    # Two passes: lay out, and if the page overflows, scale the type down by exactly
    # the overflow and lay out again. One correction converges because height is linear
    # in font size; the second pass only exists to catch rewrap at the smaller size.
    scale = 1.0
    limit = 1 - MARGIN
    lowest = 0.0
    for _ in range(5):
        lowest = _resolve_collisions(spec.elements, spec, scale)
        if lowest <= limit:
            break
        usable = limit - MARGIN
        new_scale = max(SHRINK_FLOOR, scale * (usable / max(lowest - MARGIN, 1e-6)))
        if new_scale >= scale:
            break  # already at the shrink floor; further passes would not help
        scale = new_scale
        # No ceiling clamp here on purpose: `_resolve_collisions` already floors each
        # element at MARGIN internally, and clamping the *ceiling* mid-loop used to
        # cap several already-spaced elements to the same y=1-MARGIN at once, which
        # collided them right back together — the exact "stacked on top of each
        # other" failure this loop exists to prevent.

    # Shrinking type alone cannot save a page whose elements were simply placed too
    # far down — a caption the model put at y=0.97 is still at y=0.97 however small it
    # is set. So if the page is still overfull, the air between blocks is squeezed in
    # increasingly hard steps, each starting from where the last left off, and the
    # first that brings the page inside the margin wins. Squeezing only ever moves an
    # element up toward its floor, so the sequence converges and never re-overlaps.
    if lowest > limit:
        lowest = _compact(spec, scale, limit)

    # Type at the shrink floor, no air left, and still overfull means the imagery is
    # simply taking room the copy needs. A real run put a 0.6-tall photo at the top of
    # a poster carrying eight text elements and pushed the last three clean off the
    # bottom of the canvas — so the picture gives the space back, and only then does
    # clipping become the honest outcome.
    if lowest > limit and _reclaim_from_imagery(spec, lowest - limit):
        lowest = _compact(spec, scale, limit)

    # The mirror of the squeeze above: a page that came out short is spread back out to
    # fill the frame. Both run after the type has settled, so neither is fighting a
    # font scale that is still moving.
    _balance_vertical(spec.elements, spec, scale, lowest)

    _inject_scrims(spec, scale)
    _assign_colors(spec)
    _inject_feature_bullets(spec, scale)
    return LayoutResult(spec=spec, font_scale=scale)
