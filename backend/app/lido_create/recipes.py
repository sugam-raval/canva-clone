"""Layout recipes: each one is a proven post composition written against the `Canvas`
helpers, so it adapts to any palette, font pairing and copy theme. Positions that depend
on how the copy wraps (a 2-line vs 3-line headline) flow from the measured text above
them; `check.py` rejects any combination that still doesn't work.

Elements are appended back to front: the first one is drawn at the bottom.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.lido_create.kit import Canvas, Design, Element, Gradient, M, W
from app.lido_create.shapes import frames


def _bottom(e: Element) -> float:
    return e.y + e.h


def _badge(c: Canvas, text: str, cx: float, cy: float, d: float = 220) -> None:
    """Accent circle with a short offer (1–2 words) centred in it."""
    c.shape(cx - d / 2, cy - d / 2, d, d, "accent", circle=True)
    label = c.text(text, "badge", x=cx - d * 0.41, y=0, w=d * 0.82, font="display",
                   color="on_accent", align="center", max_lines=2, upper=True,
                   fit_from=60, smallest=34)
    label.y = round(cy - label.h / 2, 2)


def split_offer(c: Canvas) -> None:
    """Solid text panel on one half, full-height photo on the other, offer badge on the
    seam, button, website."""
    t = c.v.theme
    c.photo(540, 0, 540, 1080, focus=0.3)
    c.logo(M, 60)
    k = c.kicker(t.kicker, x=M, y=235, w=420, size=26)
    hl = c.headline(t.headline, x=M, y=_bottom(k) + 12, w=430, max_lines=3, start=112,
                    smallest=64)
    body = c.text(t.body, "body", x=M, y=_bottom(hl) + 34, w=350, max_lines=3, size=26,
                  lh=1.45, fit_from=26, smallest=22)
    c.button(t.cta, x=M, y=max(_bottom(body) + 50, 800))
    c.contact("website", x=M, y=990, w=420)
    _badge(c, t.badge, 540, min(_bottom(hl) + 130, 870))


def arch_showcase(c: Canvas) -> None:
    """Centred headline, arch-shaped photo, pill button overlapping the arch, soft circles
    peeking from behind it, phone + website footer."""
    t = c.v.theme
    c.logo(W / 2 - 55, 40)
    hl = c.headline(t.headline, x=90, y=140, w=900, max_lines=2, start=84, smallest=56,
                    align="center")
    top, bottom = _bottom(hl) + 30, 855
    c.shape(700, top - 25, 260, 260, "soft", circle=True)
    c.shape(150, bottom - 160, 140, 140, "soft", circle=True)
    c.photo(260, top, 560, bottom - top, clip="arch", focus=0.5)
    c.button(t.cta, x=0, y=bottom - 40, center_x=W / 2)
    c.text(t.body, "body", x=140, y=925, w=800, align="center", max_lines=1, size=26,
           lh=1.3, fit_from=26, smallest=20)
    c.contact("phone", x=M, y=1000, w=400, size=22)
    c.contact("website", x=610, y=1000, w=400, align="right", size=22)


def service_list(c: Canvas) -> None:
    """Headline column with a 3-item checklist, big circle photo, button, email."""
    t = c.v.theme
    c.photo(520, 440, 560, 560, clip="circle")
    c.shape(930, 395, 90, 90, "soft", circle=True)
    c.logo(M, 60)
    k = c.kicker(t.kicker, x=M, y=205, w=420)
    hl = c.headline(t.headline, x=M, y=_bottom(k) + 12, w=460, max_lines=3, start=72,
                    smallest=48)
    y = _bottom(hl) + 45
    for item in t.items:
        label = c.text(item, "item", x=118, y=y, w=330, size=28, fit_from=28, smallest=22)
        c.shape(M, y + (label.h - 28) / 2, 28, 28, "accent", circle=True)
        y += 66
    c.button(t.cta, x=M, y=y + 30)
    c.contact("email", x=M, y=975, w=400)


def photo_top_card(c: Canvas) -> None:
    """Photo band across the top, solid panel below with headline + body, offer badge on
    the seam, button, address and logo along the bottom."""
    t = c.v.theme
    c.photo(0, 0, 1080, 640, focus=0.55)
    _badge(c, t.badge, 910, 640)
    one_line = c.fits(t.headline, "display", 72, 700, 1, c.v.fonts.display_upper, 0)
    hl = c.headline(t.headline, x=M, y=680, w=700, max_lines=1 if one_line else 2,
                    start=96 if one_line else 72, smallest=72 if one_line else 52)
    c.text(t.body, "body", x=M, y=_bottom(hl) + 18, w=640, max_lines=2 if one_line else 1,
           size=26, lh=1.45, fit_from=26, smallest=20)
    pill, _ = c.button(t.cta, x=M, y=935, h=76)
    ax = pill.x + pill.w + 35
    address = c.contact("address", x=ax, y=0, w=870 - ax, size=22)
    address.y = round(pill.y + (pill.h - address.h) / 2, 2)
    c.logo(900, 928)


def event_invite(c: Canvas) -> None:
    """Centred type stack: script kicker, huge headline, date pill, wide rounded photo,
    address; corner circles as decoration."""
    t = c.v.theme
    c.shape(-90, -90, 280, 280, "accent", circle=True, bleed=True)
    c.shape(930, 900, 240, 240, "soft", circle=True, bleed=True)
    c.logo(W / 2 - 55, 50)
    s = c.text(t.script, "kicker", x=190, y=160, w=700, font="script", size=58,
               color="accent", align="center", fit_from=58, smallest=40)
    hl = c.headline(t.headline, x=90, y=_bottom(s) + 20, w=900, max_lines=2, start=118,
                    smallest=70, align="center")
    pill, _ = c.button(t.date, x=0, y=_bottom(hl) + 25, h=80, center_x=W / 2,
                       text_type="badge")
    top = pill.y + pill.h + 40
    c.photo(140, top, 800, 930 - top, clip="rounded", radius=36)
    c.contact("address", x=140, y=968, w=800, align="center", size=26)


def card_over_photo(c: Canvas) -> None:
    """Full-bleed photo with a solid rounded card over its lower half: kicker pill on
    the card's top edge, logo, headline, body, button."""
    t = c.v.theme
    c.photo(0, 0, 1080, 1080, focus=0.35)
    c.shape(60, 600, 960, 420, "bg", radius=28)
    c.logo(850, 635)
    c.button(t.kicker, x=110, y=570, h=60, text_type="kicker")
    hl = c.headline(t.headline, x=110, y=660, w=700, max_lines=2, start=80, smallest=52)
    c.text(t.body, "body", x=110, y=_bottom(hl) + 16, w=520, max_lines=2, size=24,
           lh=1.45, fit_from=24, smallest=20)
    pill, label = c.button(t.cta, x=0, y=899, h=76)
    shift = 970 - pill.w - pill.x
    pill.x += shift
    label.x += shift


def twin_photo(c: Canvas) -> None:
    """Two rounded photos side by side across the top, wide headline and body below,
    button and website on the bottom row."""
    t = c.v.theme
    c.shape(950, 470, 150, 150, "soft", circle=True, bleed=True)
    c.logo(M, 50)
    c.kicker(t.kicker, x=510, y=85, w=500, align="right")
    c.photo(M, 170, 460, 420, clip="rounded", radius=28)
    c.photo(550, 170, 460, 420, clip="rounded", radius=28)
    hl = c.headline(t.headline, x=M, y=630, w=940, max_lines=2, start=92, smallest=56)
    c.text(t.body, "body", x=M, y=_bottom(hl) + 14, w=640, max_lines=2, size=26,
           fit_from=26, smallest=20)
    pill, _ = c.button(t.cta, x=M, y=950)
    site = c.contact("website", x=540, y=0, w=470, align="right")
    site.y = round(pill.y + (pill.h - site.h) / 2, 2)


def offset_frame(c: Canvas) -> None:
    """Tall photo with a thick accent bar running down beside it, text column on the
    other side, phone line under the photo."""
    t = c.v.theme
    c.shape(M + 460, 110, 14, 740, "accent")
    c.photo(M, 110, 440, 740, focus=0.35)
    c.shape(960, 930, 200, 200, "soft", circle=True, bleed=True)
    c.logo(590, 60)
    k = c.kicker(t.kicker, x=590, y=220, w=420)
    hl = c.headline(t.headline, x=590, y=_bottom(k) + 12, w=420, max_lines=4, start=96,
                    smallest=52)
    body = c.text(t.body, "body", x=590, y=_bottom(hl) + 26, w=400, max_lines=4, size=26,
                  lh=1.45, fit_from=26, smallest=20)
    c.button(t.cta, x=590, y=_bottom(body) + 44)
    c.contact("phone", x=M, y=960, w=440)


def _offer_badge(c: Canvas, lead: str, text: str, cx: float, cy: float,
                 d: float = 210) -> None:
    """A multi-line offer badge: a small caps lead ("UP TO") over a big offer."""
    c.shape(cx - d / 2, cy - d / 2, d, d, "accent", circle=True)
    cap = c.text(lead, "caption", x=cx - d * 0.35, y=0, w=d * 0.7, size=20,
                 color="on_accent", align="center", upper=True, ls=0.15, fit_from=20,
                 smallest=14)
    big = c.text(text, "badge", x=cx - d * 0.4, y=0, w=d * 0.8, font="display",
                 color="on_accent", align="center", max_lines=2, upper=True, fit_from=56,
                 smallest=32)
    top = cy - (cap.h + big.h) / 2
    cap.y, big.y = round(top, 2), round(top + cap.h, 2)


def fresh_promo(c: Canvas) -> None:
    """Pro product promo: script line over a huge caps headline, reverse-colour band,
    the subject straight on the background, multi-line offer badge, a dashed coupon
    price tag, dot-grid textures, a corner rhombus, label + value contacts with ring
    markers."""
    t = c.v.theme
    c.shape(822, -168, 396, 396, "accent", kind="rhombus", bleed=True)
    c.dots(70, 400, 4, 4, gap=22, dot=8)
    c.dots(930, 760, 4, 3, gap=22, dot=8)
    c.logo(M, 50)
    s = c.text(t.script, "kicker", x=190, y=55, w=700, font="script", size=76,
               color="accent", align="center", fit_from=76, smallest=48)
    hl = c.headline(t.headline, x=60, y=_bottom(s), w=960, max_lines=2, start=124,
                    smallest=84, align="center")
    band, _ = c.button(t.kicker, x=0, y=_bottom(hl) + 14, h=58, center_x=W / 2,
                       text_type="kicker", fill="ink", ink="bg")
    top = band.y + band.h + 50
    c.photo(250, top, 580, 945 - top, clip="cutout")
    _offer_badge(c, "Up to", t.badge, 925, 535)
    c.shape(M, 560, 200, 120, "bg", radius=18, stroke="accent", stroke_width=3,
            stroke_style="dashed")  # a coupon-style dashed tag
    only = c.text("Only", "caption", x=M, y=0, w=200, size=18, color="accent",
                  align="center", upper=True, ls=0.2)
    price = c.text(t.price, "badge", x=M + 10, y=0, w=180, font="display", color="ink",
                   align="center", fit_from=52, smallest=30)
    only.y = round(620 - (only.h + price.h) / 2, 2)
    price.y = round(only.y + only.h, 2)
    cap, _ = c.contact_block("phone", "Order now", x=118, y=950, w=300)
    c.bullet(M, cap.y + 6, "ring", 34)
    cap, _ = c.contact_block("website", "Visit us", x=560, y=950, w=362, align="right")
    c.bullet(976, cap.y + 6, "ring", 34)


def geo_agency(c: Canvas) -> None:
    """Pro service promo: script line + accent caps headline, an accent line under the
    intro, a corner disc holding the logo, a hexagon photo, an arrow-tag panel holding a
    bulleted list, dot grids, then label + value contacts either side of a button."""
    t = c.v.theme
    c.shape(760, -170, 500, 500, "accent", circle=True, bleed=True)
    c.dots(930, 420, 3, 3, gap=22, dot=9)  # in the corner the hexagon leaves free
    c.logo(880, 70)
    s = c.text(t.script, "kicker", x=M, y=80, w=600, font="script", size=72,
               color="ink", fit_from=72, smallest=48)
    hl = c.headline(t.headline, x=M, y=_bottom(s), w=600, max_lines=2, start=100,
                    smallest=76, color="accent")
    body = c.text(t.body, "body", x=M, y=_bottom(hl) + 16, w=420, max_lines=3, size=22,
                  fit_from=22, smallest=18)
    c.line(M, _bottom(body) + 26, 90, thickness=5)
    c.shape(0, 640, 470, 200, "accent", kind="arrowPentagon")
    c.photo(430, 400, 580, 520, clip="hexagon", focus=0.35)
    for i, item in enumerate(t.items):
        y = 668 + i * 50
        label = c.text(item, "item", x=104, y=y, w=260, size=24, color="on_accent",
                       fit_from=24, smallest=18)
        c.bullet(M, label.y + (label.h - 22) / 2, "bar", 22, color="on_accent")
    cap, _ = c.contact_block("phone", "Call us", x=118, y=950, w=280)
    c.bullet(M, cap.y + 6, "ring", 34)
    c.button(t.cta, x=0, y=958, h=70, center_x=W / 2)
    cap, _ = c.contact_block("website", "Visit our website", x=682, y=950, w=280,
                             align="right")
    c.bullet(976, cap.y + 6, "ring", 34)


def spotlight_launch(c: Canvas) -> None:
    """Pro launch post: radial spotlight background, a hollow outline word over a solid
    headline with a marker underline, the photo in a brush-stroke frame, a price tag in
    an arrow-tag shape breaking the photo's edge, a hand-drawn arrow, slanted accent
    bands, dotted lines with circle ends either side of the button."""
    t = c.v.theme
    c.background = Gradient(style="radial", start="soft", end="bg", end_at=75)
    c.shape(800, 44, 230, 24, "accent", kind="parallelogram")
    c.shape(850, 82, 180, 24, "accent", kind="parallelogram", opacity=0.5)
    c.logo(M, 50)
    k = c.text(t.script, "kicker", x=140, y=165, w=800, font="display", size=64,
               color="accent", align="center", upper=True, effect="hollow", fit_from=64,
               smallest=56)
    hl = c.headline(t.headline, x=90, y=_bottom(k) + 4, w=900, max_lines=2, start=110,
                    smallest=72, align="center")
    c.draw("underline", 380, _bottom(hl) + 4, 320, 26, width=8)
    top = _bottom(hl) + 52
    aspect = frames()["brush_band"].aspect
    pw = min(600.0, (930 - top) * aspect)
    ph = pw / aspect
    c.photo((W - pw) / 2, top, pw, ph, frame="brush_band")
    tag = c.shape(690, top + ph - 100, 290, 84, "accent", kind="arrowPentagon")
    price = c.text(t.price, "badge", x=710, y=0, w=226, font="display", color="on_accent",
                   align="center", fit_from=50, smallest=30)
    price.y = round(tag.y + (tag.h - price.h) / 2, 2)
    c.draw("arrow", 110, top + ph - 200, 150, 120, width=6)
    c.dots(930, top + 20, 3, 4, gap=22, dot=8)
    pill, _ = c.button(t.cta, x=0, y=972, h=68, center_x=W / 2)
    mid = pill.y + pill.h / 2
    c.line(M, mid, pill.x - M - 30, thickness=3, style="dotted", end="circle")
    c.line(pill.x + pill.w + 30, mid, W - M - (pill.x + pill.w + 30), thickness=3,
           style="dotted", start="circle")


@dataclass(frozen=True)
class Recipe:
    name: str
    build: Callable[[Canvas], None]
    mirrorable: bool  # a left/right flip is a genuinely different-looking layout

    @property
    def description(self) -> str:
        return " ".join((self.build.__doc__ or "").split())


RECIPES = {r.name: r for r in [
    Recipe("split_offer", split_offer, True),
    Recipe("arch_showcase", arch_showcase, False),
    Recipe("service_list", service_list, True),
    Recipe("photo_top_card", photo_top_card, True),
    Recipe("event_invite", event_invite, False),
    Recipe("card_over_photo", card_over_photo, True),
    Recipe("twin_photo", twin_photo, True),
    Recipe("offset_frame", offset_frame, True),
    Recipe("fresh_promo", fresh_promo, False),
    Recipe("geo_agency", geo_agency, True),
    Recipe("spotlight_launch", spotlight_launch, False),
]}

# Asymmetric Lido shapes and what each becomes in a mirror image.
_MIRRORED_SHAPE = {"arrowRight": "arrowLeft", "arrowLeft": "arrowRight",
                   "parallelogram": "parallelogramUpsideDown",
                   "parallelogramUpsideDown": "parallelogram"}
_FLIP_BY_TURNING = {"chevron", "arrowPentagon"}  # symmetric top/bottom: turn 180 instead


def mirror(design: Design) -> Design:
    """Left/right flip of the whole layout (text alignment flips with it)."""
    flipped = design.model_copy(deep=True)
    flipped.mirrored = not design.mirrored
    if flipped.background is not None and flipped.background.style == "linear":
        a = flipped.background.angle
        flipped.background.angle = (360 - (180 if a is None else a)) % 360
    swap = {"left": "right", "right": "left", "center": "center"}
    for e in flipped.elements:
        e.x = round(W - e.x - e.w, 2)
        if e.rotate:
            e.rotate = -e.rotate
        if e.shape in _MIRRORED_SHAPE:
            e.shape = _MIRRORED_SHAPE[e.shape]  # type: ignore[assignment]
        elif e.shape in _FLIP_BY_TURNING:
            e.rotate = ((e.rotate or 0) + 180) % 360
        if e.kind == "line":
            e.line_start, e.line_end = e.line_end, e.line_start
        for g in (e.gradient,):
            if g is not None and g.style == "linear":
                g.angle = (360 - (180 if g.angle is None else g.angle)) % 360
        if e.kind == "text":
            e.align = swap[e.align or "left"]
    return flipped
