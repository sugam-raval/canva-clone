"""Layout recipes: each one is a proven post composition written against the `Canvas`
helpers, so it adapts to any palette, font pairing and copy theme. Positions that depend
on how the copy wraps (a 2-line vs 3-line headline) flow from the measured text above
them; `check.py` rejects any combination that still doesn't work.

Elements are appended back to front: the first one is drawn at the bottom.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lido_layouts.kit import Canvas, Design, Element, M, W


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
    """Headline column with a 3-item checklist, big circle photo inside an accent ring,
    button, email."""
    t = c.v.theme
    c.shape(480, 400, 640, 640, "accent", circle=True, bleed=True)
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
    """Tall photo with an accent block offset behind it like a shadow, text column on the
    other side, phone line under the photo."""
    t = c.v.theme
    c.shape(100, 140, 440, 740, "accent")
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
]}


def mirror(design: Design) -> Design:
    """Left/right flip of the whole layout (text alignment flips with it)."""
    flipped = design.model_copy(deep=True)
    flipped.mirrored = not design.mirrored
    swap = {"left": "right", "right": "left", "center": "center"}
    for e in flipped.elements:
        e.x = round(W - e.x - e.w, 2)
        if e.kind == "text":
            e.align = swap[e.align or "left"]
    return flipped
