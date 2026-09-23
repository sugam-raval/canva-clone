"""Vector ornament, added after the layout is final.

A generated page can have a good palette, good type and a good photograph and still
read as a slide: what separates the reference posters from that is a layer of small
deliberate marks — a dot matrix in the corner, a short accent rule under the headline,
a filled pill behind the call to action, a band carrying the contact row, a circle
badge around the offer. None of it is content. All of it is what makes the page look
*made*.

It is built here rather than asked of the model for two reasons. It is pure geometry,
which is the thing an LLM is worst at and a repaired layout already knows exactly; and
every mark has to be placed against where the text actually ended up, which is only
known after `layout.repair` has wrapped, shrunk and de-overlapped everything. So the
model chooses *which* ornaments the design wears (`DesignSpec.decor`) and this module
works out where they go.

Only `rect` and `circle` are used — those are the shapes Lido actually has. A pill is a
rect with a circle welded on each end; a ring is a circle with the ground colour
punched through the middle. Nothing here needs a shape primitive that does not exist.
"""

from __future__ import annotations

from typing import Literal

from app.util.color import contrast_ratio, readable_on, relative_luminance

from . import palette as pal
from .layout import (
    BADGE_MAX_WIDTH,
    MARGIN,
    PILL_PAD_Y,
    element_height,
    font_px,
    text_ink_width,
    visual_bottom,
)
from .spec import DesignSpec, SpecElement

DecorKind = Literal[
    "dot-grid", "corner-brackets", "accent-underline", "side-rule",
    "badge-ring", "cta-pill", "contact-bar", "frame-outline", "edge-block",
]

#: Draw tiers, written straight onto the element as `z`, matching `builder._DRAW_ORDER`
#: (scrim 0, photo 1, shape 2, cutout 3, text 5). Ornament needs all three: a contact
#: band belongs under the imagery, a dot matrix above the photos but behind the hero
#: cutout, and a badge disc on top of everything except the type it carries.
Z_BACK = 0
Z_OVER_PHOTO = 2
Z_OVER_ALL = 4

DOT_ROWS = 5
DOT_RADIUS = 0.0045
"""Dot radius as a fraction of canvas width. Small on purpose — a dot matrix is a
texture you notice second, not a pattern of buttons."""
DOT_PITCH = 0.0235

RULE_THICKNESS = 0.009
"""Accent rule height as a fraction of canvas height."""
RULE_LENGTH = 0.16

BRACKET_ARM = 0.085
BRACKET_THICKNESS = 0.006

FRAME_INSET = 0.028
FRAME_THICKNESS = 0.0035

PILL_PAD_X = 0.035

BADGE_PAD = 0.045
BADGE_MAX = BADGE_MAX_WIDTH
"""Widest a roundel may get. An offer too long to fit a disc this size gets no disc: a
stamp that covers a third of the page is not a stamp. Shared with `layout`, which uses
it to decide whether that offer may overlap the hero image."""

PILL_MAX = 0.62
"""Widest a CTA pill may get. Past this it is a band, not a button."""
BAND_PAD_Y = 0.03

CHIP_GUTTER = 0.052
"""Space cleared at the left of each contact line for its icon chip."""

_CONTACT_ROLES = ("phone", "address", "website", "email")


# ----------------------------------------------------------------------------------
# geometry helpers
# ----------------------------------------------------------------------------------

def _rect(x: float, y: float, w: float, h: float, color: str, *,
          z: int = Z_BACK, opacity: float = 1.0) -> SpecElement:
    return SpecElement(kind="shape", shape="rect", color=color, opacity=opacity,
                       x=x, y=y, w=max(w, 0.001), h=max(h, 0.001), z=z,
                       behind=z <= Z_BACK)


def _circle(cx: float, cy: float, diameter_x: float, diameter_y: float, color: str, *,
            z: int = Z_BACK, opacity: float = 1.0) -> SpecElement:
    return SpecElement(kind="shape", shape="circle", color=color, opacity=opacity,
                       x=cx - diameter_x / 2, y=cy - diameter_y / 2,
                       w=max(diameter_x, 0.001), h=max(diameter_y, 0.001), z=z,
                       behind=z <= Z_BACK)


def _pill(x: float, y: float, w: float, h: float, color: str, *,
          z: int, aspect: float) -> list[SpecElement]:
    """A rect with a semicircular cap welded on each end.

    `aspect` is width/height of the canvas: a circle element is an ellipse in canvas
    fractions, so a cap that is `h` tall must be `h / aspect` wide to come out round.
    """
    cap_w = h / max(aspect, 0.001)
    return [
        _rect(x, y, w, h, color, z=z),
        _circle(x, y + h / 2, cap_w, h, color, z=z),
        _circle(x + w, y + h / 2, cap_w, h, color, z=z),
    ]


def _box(element: SpecElement, spec: DesignSpec,
         scale: float) -> tuple[float, float, float, float]:
    """What ornament has to stay off — measured to the ink, not to the layout box."""
    return (element.x, element.y, element.x + element.w,
            visual_bottom(element, spec, scale))


def _overlaps(a: tuple[float, float, float, float],
              b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _content_boxes(spec: DesignSpec, scale: float) -> list[tuple[float, ...]]:
    """Everything ornament has to stay clear of: text, photos and cutouts."""
    return [_box(e, spec, scale) for e in spec.elements
            if e.kind in ("text", "photo") and (e.kind == "photo" or (e.text or "").strip())]


def _text_by_role(spec: DesignSpec, *roles: str) -> SpecElement | None:
    for element in spec.elements:
        if element.kind == "text" and element.role in roles and (element.text or "").strip():
            return element
    return None


def _headline(spec: DesignSpec) -> SpecElement | None:
    explicit = _text_by_role(spec, "headline")
    if explicit is not None:
        return explicit
    texts = [e for e in spec.elements if e.kind == "text" and (e.text or "").strip()]
    if not texts:
        return None
    order = ["display", "title", "heading", "body", "caption", "micro"]
    return min(texts, key=lambda e: order.index(e.size) if e.size in order else 99)


#: The ink estimator lives in `layout` because the collision pass needs it too — it
#: has to know whether an offer is short enough to earn a disc before ornament exists.
#: Two copies of this measurement drifting apart would put the disc and the line it is
#: drawn for in different places.
_text_width = text_ink_width


def _text_left(element: SpecElement, spec: DesignSpec, scale: float) -> float:
    """The left edge of the ink, honouring the element's own alignment."""
    width = _text_width(element, spec, scale)
    if element.align == "center":
        return element.x + (element.w - width) / 2
    if element.align == "end":
        return element.x + element.w - width
    return element.x


def _align_offset(element: SpecElement, width: float) -> float:
    """Where a mark `width` wide starts, so it sits under the text's own alignment."""
    if element.align == "center":
        return element.x + (element.w - width) / 2
    if element.align == "end":
        return element.x + element.w - width
    return element.x


# ----------------------------------------------------------------------------------
# the ornaments
# ----------------------------------------------------------------------------------

def _dot_grid(spec: DesignSpec, accent: str, scale: float) -> list[SpecElement]:
    """A small dot matrix in up to two corners the layout left empty."""
    aspect = spec.width / max(spec.height, 1)
    span_x = (DOT_ROWS - 1) * DOT_PITCH
    span_y = span_x * aspect
    inset = MARGIN * 0.6
    corners = [
        (inset, inset),
        (1 - inset - span_x, inset),
        (inset, 1 - inset - span_y),
        (1 - inset - span_x, 1 - inset - span_y),
    ]
    occupied = _content_boxes(spec, scale)
    dots: list[SpecElement] = []
    placed = 0
    for x0, y0 in corners:
        if placed >= 2:
            break
        patch = (x0 - 0.01, y0 - 0.01, x0 + span_x + 0.01, y0 + span_y + 0.01)
        if any(_overlaps(patch, box) for box in occupied):
            continue
        for row in range(DOT_ROWS):
            for col in range(DOT_ROWS):
                dots.append(_circle(
                    x0 + col * DOT_PITCH, y0 + row * DOT_PITCH * aspect,
                    DOT_RADIUS * 2, DOT_RADIUS * 2 * aspect,
                    accent, z=Z_OVER_PHOTO, opacity=0.85,
                ))
        placed += 1
    return dots


def _corner_brackets(spec: DesignSpec, accent: str) -> list[SpecElement]:
    """Two opposed L-brackets — a frame implied rather than drawn."""
    aspect = spec.width / max(spec.height, 1)
    inset = MARGIN * 0.75
    arm_y = BRACKET_ARM * aspect
    thick_y = BRACKET_THICKNESS * aspect
    far_x, far_y = 1 - inset, 1 - inset
    return [
        _rect(inset, inset, BRACKET_ARM, thick_y, accent, z=Z_OVER_PHOTO),
        _rect(inset, inset, BRACKET_THICKNESS, arm_y, accent, z=Z_OVER_PHOTO),
        _rect(far_x - BRACKET_ARM, far_y - thick_y, BRACKET_ARM, thick_y, accent,
              z=Z_OVER_PHOTO),
        _rect(far_x - BRACKET_THICKNESS, far_y - arm_y, BRACKET_THICKNESS, arm_y, accent,
              z=Z_OVER_PHOTO),
    ]


def _accent_underline(spec: DesignSpec, accent: str, scale: float) -> list[SpecElement]:
    """A short heavy rule directly under the headline — the cheapest mark there is for
    making a headline look set rather than typed.

    Skipped when the layout left no room for it. Ornament is added after collisions are
    resolved, so nothing will move out of its way: a rule drawn into an occupied gap
    strikes through the line below it instead of underlining the one above.
    """
    headline = _headline(spec)
    if headline is None:
        return []
    # `visual_bottom`, not the layout box: display type is set at 0.94 leading, so its
    # box ends above its own descenders and a rule hung off it is drawn through the
    # headline rather than under it.
    bottom = visual_bottom(headline, spec, scale)
    width = min(RULE_LENGTH, headline.w * 0.4)
    x = _align_offset(headline, width)
    y = bottom + 0.014
    if y + RULE_THICKNESS > 1 - MARGIN * 0.5:
        return []
    rule = (x, y, x + width, y + RULE_THICKNESS + 0.012)
    if any(_overlaps(rule, box) for box in _content_boxes(spec, scale)):
        return []
    return [_rect(x, y, width, RULE_THICKNESS, accent, z=Z_OVER_PHOTO)]


def _side_rule(spec: DesignSpec, accent: str, scale: float) -> list[SpecElement]:
    """A vertical bar down the left of the headline block, editorial-style."""
    headline = _headline(spec)
    if headline is None or headline.align != "start" or headline.x < MARGIN * 1.4:
        return []
    height = element_height(headline, spec, scale)
    return [_rect(headline.x - 0.028, headline.y, 0.007, max(height, 0.04), accent,
                  z=Z_OVER_PHOTO)]


def _badge_ring(spec: DesignSpec, colors: list[str],
                scale: float) -> list[SpecElement]:
    """A filled disc stamped behind the offer, with the offer's type recoloured to sit
    on it. The 'SAVE 50%' roundel: it only works because the disc is drawn above the
    photo it overlaps, which is what `Z_OVER_ALL` is for.

    The offer's text box is resized to the disc and centred on it, rather than the disc
    being fitted around wherever the text already was. Estimated ink is a few percent
    out at best, and any drift between the two leaves letters hanging off the white
    circle onto the dark ground, where they simply vanish.
    """
    offer = _text_by_role(spec, "offer", "label")
    if offer is None:
        return []
    aspect = spec.width / max(spec.height, 1)
    height = element_height(offer, spec, scale)
    text_w = _text_width(offer, spec, scale)
    diameter = max(text_w, height / aspect) + BADGE_PAD * 2
    if diameter > BADGE_MAX:
        return []

    cx = _text_left(offer, spec, scale) + text_w / 2
    cy = offer.y + height / 2
    # Hold the whole disc inside the trim; half a roundel bleeding off the edge is a
    # deliberate effect nobody asked for here.
    cx = min(max(cx, diameter / 2 + 0.01), 1 - diameter / 2 - 0.01)

    disc = (cx - diameter / 2, cy - diameter * aspect / 2,
            cx + diameter / 2, cy + diameter * aspect / 2)
    others = [_box(e, spec, scale) for e in spec.elements
              if e.kind == "text" and e is not offer and (e.text or "").strip()]
    if any(_overlaps(disc, box) for box in others):
        return []  # the disc would sit on another line; the offer stays plain text

    fill = pal.tint_of(colors)
    if contrast_ratio(fill, colors[0]) < 3.0:
        fill = pal.accent_of(colors)
    offer.color = readable_on(fill, colors, minimum=4.5)
    offer.align = "center"
    offer.w = diameter
    offer.x = disc[0]
    return [_circle(cx, cy, diameter, diameter * aspect, fill, z=Z_OVER_ALL)]


def _cta_pill(spec: DesignSpec, colors: list[str], scale: float) -> list[SpecElement]:
    """A filled pill behind the call to action — the one element on the page that
    should look pressable."""
    cta = _text_by_role(spec, "cta")
    if cta is None:
        return []
    aspect = spec.width / max(spec.height, 1)
    height = element_height(cta, spec, scale)
    ink = _text_width(cta, spec, scale)
    # The pill is the ink plus real padding, not the ink exactly. Sized flush to the
    # estimated width, a few percent of error in that estimate is enough to hang the
    # last word off the end cap onto the ground behind it.
    text_w = min(PILL_MAX, max(0.12, ink + PILL_PAD_X * 2))
    x = _text_left(cta, spec, scale) - (text_w - ink) / 2
    top = cta.y - PILL_PAD_Y
    cap_w = (height + PILL_PAD_Y * 2) / max(aspect, 0.001)

    # Nothing moves out of ornament's way, so a pill that would be drawn across a
    # neighbouring line is not drawn at all. The collision pass reserves `PILL_PAD_Y`
    # above and below the call to action for exactly this, but it can only reserve it
    # vertically — a line sitting beside the CTA is still caught here.
    bounds = (x - cap_w / 2, top, x + text_w + cap_w / 2,
              top + height + PILL_PAD_Y * 2)
    others = [_box(e, spec, scale) for e in spec.elements
              if e.kind == "text" and e is not cta and (e.text or "").strip()]
    if any(_overlaps(bounds, box) for box in others):
        return []

    fill = pal.accent_of(colors)
    cta.color = readable_on(fill, colors, minimum=4.5)
    return _pill(x, top, text_w, height + PILL_PAD_Y * 2, fill,
                 z=Z_OVER_ALL, aspect=aspect)


def _contact_bar(spec: DesignSpec, colors: list[str],
                 scale: float) -> list[SpecElement]:
    """A full-bleed band across the foot of the page carrying the contact lines, each
    with a small accent chip in front of it. Two contact lines floating loose at the
    bottom of a poster is the single clearest tell of a generated page."""
    rows = [e for e in spec.elements
            if e.kind == "text" and e.role in _CONTACT_ROLES and (e.text or "").strip()]
    if len(rows) < 2:
        return []
    aspect = spec.width / max(spec.height, 1)
    rows_top = min(e.y for e in rows)
    rows_bottom = max(e.y + element_height(e, spec, scale) for e in rows)
    top = rows_top - BAND_PAD_Y
    if top < 0.6:
        return []  # the contact lines are not at the foot; a band would cut the page

    # The band always runs to the trim — a strip with a sliver of ground under it reads
    # as a mistake — so the lines are re-centred inside it rather than left clinging to
    # its top edge, which is where laying the band under them leaves them.
    shift = (1.0 - top - (rows_bottom - rows_top)) / 2 - BAND_PAD_Y
    if shift > 0.001:
        for row in rows:
            row.y += shift

    # Contact lines stacked one above another are a block, and a block has one left
    # edge. Left where the model put them they arrive at three different indents with
    # their chips in three different places, which reads as carelessness more loudly
    # than anything else on the page.
    stacked = len({round(e.y, 2) for e in rows}) == len(rows)
    if stacked:
        left = min(e.x for e in rows)
        for row in rows:
            row.w = min(row.w + (row.x - left), 1 - MARGIN - left)
            row.x = left
            row.align = "start"

    band_color = pal.band_of(colors)
    marks: list[SpecElement] = [
        _rect(0.0, top, 1.0, 1.0 - top, band_color, z=Z_BACK, opacity=0.95)
    ]
    accent = pal.accent_of(colors)
    for row in rows:
        if row.align == "start":
            # Shift the line right to clear its own chip, exactly as a feature bullet
            # reserves its gutter — the chip must not sit on the text.
            row.x = max(CHIP_GUTTER, row.x)
            row.w = min(row.w, 1 - MARGIN - row.x)
        row.color = readable_on(band_color, colors, minimum=4.5)
        size_px = font_px(row, spec, scale)
        chip = size_px * 1.5 / spec.width
        left = _text_left(row, spec, scale)
        centre = left - CHIP_GUTTER / 2
        # The chip is *centred* on the gutter, so what has to clear the trim is its
        # left edge, not the whole gutter. Measuring the gutter instead suppressed the
        # chip on every row sitting at the page margin — which is every row — and the
        # contact band came back as two bare lines on a strip of colour.
        if centre - chip / 2 < 0.004:
            continue
        marks.append(_circle(
            centre, row.y + size_px * 0.6 / spec.height,
            chip, chip * aspect, accent, z=Z_OVER_ALL,
        ))
    return marks


def _frame_outline(spec: DesignSpec, accent: str) -> list[SpecElement]:
    """A hairline border inset from the trim — a certificate/invitation device."""
    aspect = spec.width / max(spec.height, 1)
    thick_y = FRAME_THICKNESS * aspect
    inner_w = 1 - FRAME_INSET * 2
    inner_h = 1 - FRAME_INSET * aspect * 2
    top = FRAME_INSET * aspect
    return [
        _rect(FRAME_INSET, top, inner_w, thick_y, accent, z=Z_OVER_PHOTO),
        _rect(FRAME_INSET, top + inner_h - thick_y, inner_w, thick_y, accent,
              z=Z_OVER_PHOTO),
        _rect(FRAME_INSET, top, FRAME_THICKNESS, inner_h, accent, z=Z_OVER_PHOTO),
        _rect(1 - FRAME_INSET - FRAME_THICKNESS, top, FRAME_THICKNESS, inner_h, accent,
              z=Z_OVER_PHOTO),
    ]


def _edge_block(spec: DesignSpec, colors: list[str], scale: float) -> list[SpecElement]:
    """A solid accent block bled off one edge, behind the text — the flat-colour panel
    that carries a split-panel or top-band composition."""
    texts = [e for e in spec.elements if e.kind == "text" and (e.text or "").strip()]
    if not texts:
        return []
    boxes = [_box(e, spec, scale) for e in texts]
    x0 = min(b[0] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y0 = min(b[1] for b in boxes)
    y1 = max(b[3] for b in boxes)
    color = colors[-1] if relative_luminance(colors[0]) > 0.3 else colors[0]
    if spec.layout_style == "top-band" or (y1 - y0) < 0.34:
        return [_rect(0.0, max(0.0, y0 - 0.05), 1.0,
                      min(1.0, y1 - y0 + 0.1), color, z=Z_BACK, opacity=0.92)]
    # A tall text column: bleed the panel off whichever side edge it already hugs.
    left = x0 < 0.5
    width = (x1 + 0.06) if left else (1 - x0 + 0.06)
    return [_rect(0.0 if left else max(0.0, x0 - 0.06), 0.0, min(1.0, width), 1.0,
                  color, z=Z_BACK, opacity=0.92)]


#: What a design wears when the model named no ornament. Each archetype gets the marks
#: that belong to it rather than a single house style stamped on everything.
DEFAULT_DECOR: dict[str, tuple[str, ...]] = {
    "hero-stack": ("accent-underline", "dot-grid", "contact-bar"),
    "split-panel": ("edge-block", "accent-underline", "contact-bar"),
    "badge-center": ("frame-outline", "badge-ring", "accent-underline"),
    "top-band": ("edge-block", "dot-grid", "contact-bar"),
    "corner-frame": ("corner-brackets", "accent-underline", "contact-bar"),
}

#: The order marks are built in, and so the order they end up in the layer list.
#: Iterating a set here instead made the layer order depend on string hash
#: randomisation — the same spec compiled to a different document on every process,
#: which is exactly the kind of thing that passes every test run but one.
#: `edge-block` leads because it is a ground the marks after it are measured against.
_DECOR_ORDER: tuple[str, ...] = (
    "edge-block", "contact-bar", "frame-outline", "corner-brackets", "side-rule",
    "accent-underline", "dot-grid", "badge-ring", "cta-pill",
)

#: Ornaments that are always considered, whatever the model asked for, because they are
#: responses to content being present rather than stylistic choices: an offer wants its
#: roundel and a call to action wants its pill in every layout there is.
_CONTENT_DRIVEN = ("badge-ring", "cta-pill")


def decorate(spec: DesignSpec, scale: float) -> None:
    """Add the spec's ornament to `spec.elements`, in place.

    Runs after `layout.repair`: every mark is positioned against final, wrapped,
    collision-resolved geometry, and the few that recolour the text they sit behind
    (the badge, the pill, the contact band) do so after `_assign_colors` has run, so
    their choice is the one that survives.
    """
    colors = spec.palette or ["#101418", "#FFFFFF"]
    accent = pal.accent_of(colors)

    asked = set(spec.decor) if spec.decor else set(
        DEFAULT_DECOR.get(spec.layout_style, DEFAULT_DECOR["hero-stack"]))
    asked.update(_CONTENT_DRIVEN)
    chosen = [kind for kind in _DECOR_ORDER if kind in asked]

    builders = {
        "dot-grid": lambda: _dot_grid(spec, accent, scale),
        "corner-brackets": lambda: _corner_brackets(spec, accent),
        "accent-underline": lambda: _accent_underline(spec, accent, scale),
        "side-rule": lambda: _side_rule(spec, accent, scale),
        "badge-ring": lambda: _badge_ring(spec, colors, scale),
        "cta-pill": lambda: _cta_pill(spec, colors, scale),
        "contact-bar": lambda: _contact_bar(spec, colors, scale),
        "frame-outline": lambda: _frame_outline(spec, accent),
        "edge-block": lambda: _edge_block(spec, colors, scale),
    }

    marks: list[SpecElement] = []
    drawn: list[str] = []
    for kind in chosen:
        build = builders.get(kind)
        if build is None:
            continue
        made = build()
        if made:
            marks.extend(made)
            drawn.append(kind)
    # Report what the page actually wears, not what was asked for: several ornaments
    # decline to draw when the layout left them no room, and a CTA pill is only real
    # if there was a CTA.
    spec.decor = drawn
    spec.elements.extend(marks)
