"""Design a brand-new template from a user's prompt.

One LLM call reads the brief and returns the whole design: the composition and its
decoration (the same element format the recipes use), the five colours, the font set,
the copy — written from the brief, using the user's own headline/price/contact when
given — and, for every photo, a `subject` saying what it should show. The result runs
through the same checks as every other generated layout (`check.py`); failures go back
to the model for repair, so only a passing design is returned unless repairs run out.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

import structlog
from pydantic import BaseModel

from app.adapters.base import AdapterError
from app.lido_corpus.palette import (
    BLACK,
    WHITE,
    contrast,
    luminance,
    parse_color,
    pick_readable,
    to_hex,
)
from app.lido_create.ai import EXAMPLE_RECIPES, SYSTEM, example, normalise
from app.lido_create.backdrops import brief_for, random_backdrop
from app.lido_create.backdrops import expand as expand_backdrop
from app.lido_create.check import FEATURE_FAMILIES, validate
from app.lido_create.kit import (
    FONT_SETS,
    FONT_SETS_BY_NAME,
    PALETTES,
    RGB,
    THEMES,
    THEMES_BY_NAME,
    Design,
    Element,
    ElementOut,
    Gradient,
    H,
    Palette,
    Photo,
    Variant,
    W,
    line_count,
    to_element,
)
from app.lido_create.models import describe, layout_call, repair_call
from app.lido_create.plan import DesignPlan, plan_brief

log = structlog.get_logger(__name__)

# Waits between tries when the API has a transient failure (5xx, 429, timeouts — what
# the adapter marks `recoverable`; it does no retrying itself). Short on purpose: the
# user is watching a spinner.
RETRY_DELAYS = (5.0, 20.0)

FontSetName = Literal[tuple(f.name for f in FONT_SETS)]  # type: ignore[valid-type]
ThemeName = Literal[tuple(t.name for t in THEMES)]  # type: ignore[valid-type]

FONT_CHARACTER = {
    "condensed-poster": "Anton — tall, bold, condensed capitals; loud promos and sales",
    "heavy-grotesk": "Archivo Black — wide, heavy sans; tech, modern, confident",
    "modern-serif": "DM Serif Display — elegant high-contrast serif; premium, lifestyle",
    "editorial-serif": "Playfair Display — classic refined serif; luxury, editorial, calm",
    "tall-caps": "Bebas Neue — clean narrow capitals; sporty, events, minimal",
}

# Rotated across variations of one brief so they come back as genuinely different
# compositions rather than three takes on the model's favourite layout.
DIRECTIONS = [
    "bold asymmetric split: the photo owns one side, the type the other",
    "centred and symmetrical, like a premium magazine cover",
    "photo-dominant: the photo fills most of the canvas, copy on a solid card or band",
    "typographic: a huge headline is the hero, the photo plays a supporting role",
    "layered and dynamic: overlapping circles, a badge breaking the photo's edge",
    "minimal and airy: lots of empty space, thin lines, small refined details",
    "structured grid: clear columns, a feature list, strong alignment",
    "framed: a border or frame around the composition, everything inside it",
]

BRIEF_RULES = """
YOU ARE DESIGNING FROM A CLIENT BRIEF
- Write every text from the brief. Use the client's own headline, offer, price, call to
  action and contact details exactly when they give them (shorten only if they cannot
  fit). Where the brief gives none, use a neutral placeholder (www.yourwebsite.com,
  +123-456-7890). Keep copy short: real templates hold short lines.
- Lists: put every item the brief (or the plan) lists into ONE list element — all of
  them, word for word, never dropped or merged. Up to 9 items; the list element picks
  the columns (1-4 → one column, 5-6 → 2 x 3, 7-9 → 3 x 3) and draws the bullets and
  dividers. Choose its bullet and divider style to suit the mood.
- When a DESIGN PLAN is given, it overrides everything else: its photo count, frames,
  text, logo choice, features and "do not add" list are fixed; your job is to build it
  beautifully.
- Use the brief's details the way pro templates do: an offer or discount as a
  multi-line badge ("UP TO" + "30% OFF"), a price as a price tag ("ONLY" + price),
  contacts as caption + value blocks with ring markers, a tagline as a reverse band.
- Plain text only: no emoji, icons or bullet symbols (✓ • 📞 🌐) — the fonts cannot draw
  them. Currency symbols, %, &, digits and punctuation are fine.
- Every photo gets `subject`: one sentence saying exactly what the picture should show,
  taken from the brief (product, setting, lighting, mood). Visual effects the brief asks
  for (glow, reflections, lighting, realistic render) belong in the subject — the layout
  itself is flat shapes and text. The product or hero subject gets the most prominent
  photo.
- Colours: choose the five role colours (#rrggbb) to match the brief's mood and any
  colours it names. ink on bg and on_accent on accent must be strongly readable; soft is
  a quiet decoration colour.
- Fonts: choose the set whose character suits the brief.
- photo_theme: the nearest theme — it picks a placeholder photo until photos are
  generated.
- One text box = one paragraph. Never put line breaks in a text; each list item,
  price line or offer line is its own text element.
- The headline is the dominant element: big (typically 90-140px), set so it reads
  from across a room. Supporting copy stays small; contrast in size creates drama.
- Follow the creative direction when one is given — it is not optional, the
  composition must clearly show it. Avoid the default "headline on top, wide photo in
  the middle, list underneath" unless the direction asks for it.
- Make it feel custom-designed for this brief: decoration (lines, dots, rings, frames,
  bands, badges) should support the message and lead the eye to the headline, the
  product and the call to action. Do not overcrowd it.
"""


class BriefColors(BaseModel):
    bg: str
    ink: str
    accent: str
    on_accent: str
    soft: str


class BriefDesign(BaseModel):
    name: str  # short snake_case name for the layout idea
    idea: str  # the composition in one sentence
    colors: BriefColors
    fonts: FontSetName
    photo_theme: ThemeName
    background: Gradient | None  # a gradient canvas (with an end colour), or null
    elements: list[ElementOut]


class ElementEdit(BaseModel):
    action: Literal["replace", "delete", "insert"]
    # the element's number in the design as sent; insert: the new element goes before
    # it (the element count appends it in front of everything)
    index: int
    element: ElementOut | None  # replace / insert: the whole new element; delete: null


class BriefRepair(BaseModel):
    """A repair round's answer: only what changes, not the whole design again."""
    edits: list[ElementEdit]


async def _ask(llm, **kwargs):
    """One schema-constrained call, retried on transient API failures."""
    for delay in (*RETRY_DELAYS, None):
        try:
            return await llm.complete_json(**kwargs)
        except AdapterError as exc:
            if not exc.recoverable or delay is None:
                raise
            log.warning("lido.brief.llm_retry", error=str(exc)[:200], wait_s=delay)
            await asyncio.sleep(delay)


@dataclass
class BriefResult:
    design: Design
    variant: Variant
    errors: list[str]
    name: str
    idea: str
    direction: str | None
    attempts: int
    colors: dict[str, str] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    # what code added around the designer's work: the backdrop it was drawn on, the
    # contact lines that got an icon (camelCase: stored as is)
    extras: dict = field(default_factory=dict)


@dataclass
class _Draft:
    """One design as the model wrote it (what repairs edit) and as built and checked."""
    ai: BriefDesign
    written: list[Element]
    result: BriefResult


def _call_info(step: str, started: float, reply) -> dict:
    info = {"step": step, "ms": round((time.perf_counter() - started) * 1000),
            "outputTokens": getattr(reply, "completion_tokens", None)}
    log.info("lido.brief.llm_call", **info)
    return info


async def _first_passing(make: Callable[[], Awaitable[_Draft]], count: int) -> _Draft:
    """`count` drafts at once: the first that passes its checks (the others are
    cancelled), else the one with the fewest problems. Fails only if every one fails."""
    tasks = [asyncio.ensure_future(make()) for _ in range(count)]
    best: _Draft | None = None
    failure: BaseException | None = None
    try:
        for next_done in asyncio.as_completed(tasks):
            try:
                draft = await next_done
            except AdapterError as exc:
                failure = failure or exc
                continue
            if best is None or len(draft.result.errors) < len(best.result.errors):
                best = draft
            if not best.result.errors:
                break
    finally:
        for t in tasks:
            t.cancel()
    if best is None:
        assert failure is not None
        raise failure
    return best


# How to fix each kind of failed check — sent with the failures, so a repair round
# changes the right thing instead of nudging elements around.
FIX_HINTS = {
    "sits on a photo": "Text can't sit on a photo (nor on the fading part of a photo fade — "
                       "move it into the fade's solid part, or raise its start_at). Add a "
                       "solid card, band or panel shape "
                       "over that part of the photo (after the photo, before the text in "
                       "the list) and keep the text on it — or move the text or the photo "
                       "so they don't overlap.",
    "straddles the edge": "Put the text entirely on one shape (or entirely off it): move "
                          "it, or make the shape big enough to hold the whole text.",
    "overlaps": "Two texts collide. Use the measured boxes below: move one so they "
                "don't overlap, or shrink the size of the bigger one.",
    "drawn on top of it": "Order matters: shapes and photos must come BEFORE the text in "
                          "the elements list (earlier = further back).",
    "contrast": "Pick a text colour role that reads on what's behind it (ink on bg, "
                "on_accent on accent, bg on ink), or change the shape's colour.",
    "wraps to": "Shorten the line, widen its box, or lower its size.",
    "wider than": "A word doesn't fit: widen the box or lower the size.",
    "photos": "Use exactly the number of photos the plan lists, one per subject.",
    "missing": "Add the missing item to the list element's items, word for word.",
    "behind a photo": "Remove or move the shape under the photo; decorate around it.",
    "mostly hidden": "A shape covers the photo: put that shape earlier in the elements "
                     "list (behind the photo) or move it off the photo.",
    "items are too small": "Give the list element a bigger area (about 70px of height "
                           "per row) — move or shrink other elements to make room.",
    "px on each side)": "A photo too small: make it bigger (a framed photo keeps its "
                        "aspect, so widen it) — with several photos use a grid, stagger "
                        "or column so each fits, moving or shrinking other elements.",
    "crosses": "Move the line or drawing beside, under or around the text, not through it.",
}


def repair_notes(errors: list[str], design: Design) -> str:
    hints = [h for key, h in FIX_HINTS.items() if any(key in e for e in errors)]
    boxes = "\n".join(
        f"  {e.text_type} {(e.text or '')[:40]!r}: x {e.x:.0f}-{e.x + e.w:.0f}, "
        f"y {e.y:.0f}-{e.y + e.h:.0f}, size {e.size:g}"
        for e in design.elements if e.kind == "text")
    return (("How to fix:\n- " + "\n- ".join(hints) + "\n\n" if hints else "")
            + "Measured text boxes in your design (real heights — the list element is "
              f"already laid out here):\n{boxes}")


def back_text_on_photos(design: Design, v: Variant) -> Design:
    """Last resort for "text sits on a photo": slide a solid rounded card under it (in a
    colour the text reads on), one card per cluster of nearby texts — the classic "text
    card over a photo" look."""
    from app.lido_create.check import _samples, surface_at, text_extent

    els = design.elements
    hits = []
    for i, e in enumerate(els):
        if e.kind != "text":
            continue
        box = text_extent(e, v)
        if any(surface_at(els, i, px, py, v.palette, design.background)[1] == "photo"
               for px, py in _samples(box)):
            pad = max(16.0, (e.size or 20) * 0.45)
            hits.append([i, box[0] - pad, box[1] - pad * 0.6, box[2] + pad, box[3] + pad * 0.6,
                         e.color or "ink"])
    if not hits:
        return design
    clusters: list[list] = []
    for h in sorted(hits, key=lambda h: h[2]):
        for c in clusters:  # join a card that is close by and shares the same text colour
            if h[5] == c[5] and h[1] < c[3] + 40 and c[1] < h[3] + 40 and h[2] < c[4] + 40:
                c[0] = min(c[0], h[0])
                c[1:5] = [min(c[1], h[1]), min(c[2], h[2]), max(c[3], h[3]), max(c[4], h[4])]
                break
        else:
            clusters.append(list(h))
    out = list(els)
    for i, x0, y0, x1, y1, ink in sorted(clusters, key=lambda c: -c[0]):
        x0, y0 = max(x0, 0.0), max(y0, 0.0)
        x1, y1 = min(x1, float(W)), min(y1, float(H))
        if (x1 - x0) * (y1 - y0) > 0.15 * W * H:
            continue  # a card that big would bury the photo: leave it to the checks
        card = {"on_accent": "accent", "bg": "ink"}.get(ink, "bg")
        out.insert(i, Element(kind="shape", shape="rectangle", x=x0, y=y0, w=x1 - x0,
                              h=y1 - y0, color=card, radius=min(24.0, (y1 - y0) / 4)))
    return design.model_copy(update={"elements": out})


def relocate_logo(design: Design, v: Variant) -> Design:
    """Last resort for a logo that collides with text or sits on a photo/edge: try the
    four corners and keep the first spot that is free and on one flat colour."""
    from app.lido_create.check import _overlap, _samples, surface_at, text_extent

    els = list(design.elements)
    li = next((i for i, e in enumerate(els) if e.kind == "logo"), None)
    if li is None:
        return design
    logo = els[li]
    texts = [text_extent(e, v) for e in els if e.kind == "text"]
    for x, y in ((48, 48), (W - 48 - logo.w, 48), (48, H - 48 - logo.h),
                 (W - 48 - logo.w, H - 48 - logo.h)):
        box = (x, y, x + logo.w, y + logo.h)
        if any(_overlap(box, t, pad=-8) for t in texts):
            continue
        moved = logo.model_copy(update={"x": x, "y": y})
        trial = [*els[:li], moved, *els[li + 1:]]
        under = {surface_at(trial, li, px, py, v.palette, design.background)[0]
                 for px, py in _samples(box, 3, 3)}
        if len(under) == 1 and ("photo",) not in under:
            return design.model_copy(update={"elements": trial})
    return design


def _remeasure(e: Element, v: Variant) -> None:
    """A text's height again, after its copy or size changed."""
    lines, _ = line_count(v.fonts, e)
    e.h = round(len(lines) * (e.size or 26) * (e.line_height or 1.3), 2)


def clean_texts(design: Design, v: Variant) -> Design:
    """Line breaks, characters the fonts can't draw, and text in the decoration-only
    `soft` colour — the slips a repair round would otherwise be spent on."""
    from app.lido_create.check import UNDRAWABLE

    out = []
    for e in design.elements:
        if e.kind == "text" and ("\n" in (e.text or "") or UNDRAWABLE.search(e.text or "")
                                 or e.color == "soft"):
            e = e.model_copy()
            e.text = " ".join(UNDRAWABLE.sub("", e.text or "").split())
            e.color = "ink" if e.color == "soft" else e.color
            _remeasure(e, v)
        out.append(e)
    return design.model_copy(update={"elements": out})


def fit_texts(design: Design, v: Variant) -> Design:
    """Step a text that wraps past its line limit (or holds a word wider than its box)
    down in size, to 60% of what the model asked for at most."""
    out = []
    for e in design.elements:
        if e.kind == "text":
            lines, wide = line_count(v.fonts, e)
            if wide or (e.max_lines and len(lines) > e.max_lines):
                e = e.model_copy()
                floor = (e.size or 26) * 0.6
                while e.size > floor:
                    e.size = round(e.size - 2, 1)
                    lines, wide = line_count(v.fonts, e)
                    if not wide and (not e.max_lines or len(lines) <= e.max_lines):
                        break
                _remeasure(e, v)
        out.append(e)
    return design.model_copy(update={"elements": out})


def fix_contrast(design: Design, v: Variant, plan=None) -> Design:
    """For each text that fails the contrast check, the colour role that leaves the
    design with the fewest problems."""
    errors = validate(design, v, creative=True, plan=plan)
    els = list(design.elements)
    for i, e in enumerate(els):
        if e.kind != "text" or not any(err.startswith(f"{e.text_type} {e.text!r}: contrast")
                                       for err in errors):
            continue
        best = (len(errors), e)
        for role in ("ink", "bg", "accent", "on_accent"):
            if role == e.color:
                continue
            trial = [*els[:i], e.model_copy(update={"color": role}), *els[i + 1:]]
            n = len(validate(design.model_copy(update={"elements": trial}), v,
                             creative=True, plan=plan))
            if n < best[0]:
                best = (n, trial[i])
        els[i] = best[1]
    return design.model_copy(update={"elements": els})


def separate_texts(design: Design, v: Variant) -> Design:
    """Slide the lower of two colliding texts down below the upper one (or the upper one
    up, when there is no room below)."""
    from app.lido_create.check import _overlap, text_extent

    els = list(design.elements)
    texts = sorted((i for i, e in enumerate(els) if e.kind == "text"), key=lambda i: els[i].y)
    for a_pos, a in enumerate(texts):
        for b in texts[a_pos + 1:]:
            ta, tb = text_extent(els[a], v), text_extent(els[b], v)
            if not _overlap(ta, tb):
                continue
            gap = 12
            down = ta[3] + gap - els[b].y
            if els[b].y + down + els[b].h <= H - 32:
                els[b] = els[b].model_copy(update={"y": els[b].y + down})
            elif els[a].y - (tb[3] - ta[1] + gap) >= 32:
                els[a] = els[a].model_copy(update={"y": tb[1] - gap - els[a].h})
    return design.model_copy(update={"elements": els})


def _slide_inside(e: Element) -> Element:
    """`e` moved (and, if it is bigger than the canvas, shrunk) to lie on the canvas."""
    from app.lido_create.check import rotated_extent

    x0, y0, x1, y1 = rotated_extent(e)
    if x1 - x0 > W or y1 - y0 > H:
        scale = 0.95 * min(W / (x1 - x0), H / (y1 - y0))
        cx, cy = e.x + e.w / 2, e.y + e.h / 2
        e = e.model_copy(update={"w": e.w * scale, "h": e.h * scale})
        e.x, e.y = cx - e.w / 2, cy - e.h / 2
        x0, y0, x1, y1 = rotated_extent(e)
    dx = max(0.0, -x0) - max(0.0, x1 - W)
    dy = max(0.0, -y0) - max(0.0, y1 - H)
    return e.model_copy(update={"x": e.x + dx, "y": e.y + dy}) if dx or dy else e


def photos_inside(design: Design, v: Variant) -> Design:
    """Slide a photo or decoration that runs off the canvas without bleed back on."""
    from app.lido_create.check import STROKES, rotated_extent

    out = []
    for e in design.elements:
        if e.kind in ("shape", "photo", *STROKES) and not e.bleed:
            x0, y0, x1, y1 = rotated_extent(e)
            if x0 < -1 or y0 < -1 or x1 > W + 1 or y1 > H + 1:
                e = _slide_inside(e)
        out.append(e)
    return design.model_copy(update={"elements": out})


def grow_photos(design: Design, v: Variant) -> Design:
    """Scale a photo below the minimum size up to it, around its centre (its aspect,
    which a frame fixes, stays), and keep it on the canvas."""
    from app.lido_create.check import min_photo_side

    least = min_photo_side(sum(e.kind == "photo" for e in design.elements))
    out = []
    for e in design.elements:
        if e.kind == "photo" and min(e.w, e.h) < least:
            scale = least / min(e.w, e.h)
            cx, cy = e.x + e.w / 2, e.y + e.h / 2
            w, h = e.w * scale, e.h * scale
            e = _slide_inside(e.model_copy(update={"x": cx - w / 2, "y": cy - h / 2,
                                                   "w": w, "h": h}))
        out.append(e)
    return design.model_copy(update={"elements": out})


def clear_under_photos(design: Design, v: Variant) -> Design:
    """Drop the shapes drawn under a photo: photos sit directly on the background."""
    from app.lido_create.check import shapes_behind

    els = design.elements
    under = {i for p, e in enumerate(els) if e.kind == "photo" for i in shapes_behind(els, p)}
    return design.model_copy(update={"elements": [e for i, e in enumerate(els)
                                                  if i not in under]})


# Mechanical fixes, tried on every draft before any repair round: (what an error must
# contain for the fix to be worth trying, the fix). Each is kept only when it leaves
# fewer problems, so a fix can never make a design worse.
AUTO_FIXES = (
    (("line break", "emoji", "'soft'"), clean_texts),
    (("wraps to", "wider than"), fit_texts),
    (("contrast",), fix_contrast),
    (("sits on a photo",), back_text_on_photos),
    (("overlaps",), separate_texts),
    (("logo",), relocate_logo),
    (("runs off the canvas",), photos_inside),
    (("px on each side)",), grow_photos),
    (("behind a photo",), clear_under_photos),
)


def _kind(error: str) -> str:
    """An error without its numbers: the same problem, wherever it moved to."""
    return re.sub(r"-?\d+(\.\d+)?", "#", error)


def auto_fix(design: Design, v: Variant, errors: list[str], plan=None) -> tuple[Design, list[str]]:
    """Apply every mechanical fix that helps, a few passes over (one fix can unblock
    another); the design and its remaining problems."""
    for _ in range(3):
        improved = False
        for triggers, fix in AUTO_FIXES:
            if not any(t in e for t in triggers for e in errors):
                continue
            patched = fix(design, v, plan) if fix is fix_contrast else fix(design, v)
            after = validate(patched, v, creative=True, plan=plan)
            if len(after) < len(errors):
                log.info("lido.brief.auto_fixed", fix=fix.__name__,
                         before=len(errors), after=len(after))
                design, errors, improved = patched, after, True
        if not errors or not improved:
            break
    return design, errors


def apply_edits(elements: list[Element], edits: list[ElementEdit]) -> list[Element]:
    """A repair round's edits applied to the design as the model wrote it. Every index
    refers to the design as sent, so edits are applied from the back; ones that point
    nowhere are dropped."""
    out = list(elements)
    n = len(elements)
    order = {"insert": 0, "replace": 1, "delete": 1}  # at one index: change it, then insert
    for edit in sorted(edits, key=lambda d: (d.index, order[d.action]), reverse=True):
        in_range = 0 <= edit.index < n or (edit.action == "insert" and edit.index == n)
        if not in_range or (edit.action != "delete" and edit.element is None):
            log.warning("lido.brief.bad_edit", action=edit.action, index=edit.index, count=n)
            continue
        if edit.action == "delete":
            del out[edit.index]
        elif edit.action == "replace":
            out[edit.index] = to_element(edit.element)
        else:
            out.insert(edit.index, to_element(edit.element))
    return out


def _numbered(ai: BriefDesign, written: list[Element]) -> str:
    """The design as the model wrote it, its elements numbered for a repair's edits."""
    head = {"name": ai.name, "idea": ai.idea,
            "background": ai.background.model_dump(exclude_none=True) if ai.background
            else None}
    rows = "\n".join(f"{i}: {e.model_dump_json(exclude_none=True)}"
                     for i, e in enumerate(written))
    return (f"{json.dumps(head)}\nElements (drawn in this order: first = back, "
            f"last = front):\n{rows}")


ROLES = ("bg", "ink", "accent", "on_accent", "soft")
TEXT_CONTRAST = 4.5  # ink on bg and on_accent on accent: readable at any text size
LIGHT_PRIMARY = 0.45  # relative luminance above which a lone primary gets a dark canvas


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))  # type: ignore[return-value]


def brand_palette(colors: list[RGB]) -> Palette:
    """The user's brand colours (1–4, the first primary — the same palette "fill a
    template" takes) as the five roles a design is drawn in, readable by construction:

        accent     the primary colour (buttons, badges, highlights)
        bg         the other colour that sets the primary off most; with none, a pale
                   tint of it (a deep shade when the primary is itself light)
        ink        the palette colour most readable on bg, else made readable
        on_accent  text on the primary: bg when readable there, else black or white
        soft       an unused palette colour, else a quiet blend of primary and bg
    """
    accent, others = colors[0], colors[1:]
    if others:
        bg = max(others, key=lambda c: contrast(c, accent))
    else:
        # a pale canvas, unless the primary is itself pale (yellow, pastels)
        bg = _mix(accent, BLACK, 0.85) if luminance(accent) > LIGHT_PRIMARY \
            else _mix(accent, WHITE, 0.92)
    rest = [c for c in others if c != bg]
    preferred = max(rest or [accent], key=lambda c: contrast(c, bg))
    ink = pick_readable(preferred, bg, TEXT_CONTRAST, [*rest, accent])
    on_accent = pick_readable(bg, accent, TEXT_CONTRAST, [c for c in colors if c != accent])
    spare = [c for c in rest if c not in (ink, on_accent)]
    soft = spare[0] if spare else _mix(accent, bg, 0.6)
    return Palette("brand", bg=bg, ink=ink, accent=accent, on_accent=on_accent, soft=soft)


def _brand_rules(palette: Palette) -> str:
    roles = ", ".join(f"{r} {to_hex(palette.color(r))}" for r in ROLES)
    return (f"BRAND COLOURS — fixed by the client, use exactly these and no others: {roles}. "
            "Set `colors` to them as given; choose fills, text colours and gradients from "
            "these roles only.")


def _palette(colors: BriefColors) -> Palette:
    """The model's colours; any value that isn't a colour falls back to a known-good one."""
    fallback = PALETTES[0]
    rgb = {role: parse_color(getattr(colors, role)) or fallback.color(role) for role in ROLES}
    return Palette("custom", **rgb)


def _format_example(photos: list[Photo], rng: random.Random) -> str:
    """Two of the pro example layouts, a different pair each time, so the designer
    doesn't keep imitating the same one."""
    v = Variant(PALETTES[0], FONT_SETS[0], THEMES[0], random.Random(0), photos)
    return "\n".join(example(r, v) for r in rng.sample(EXAMPLE_RECIPES, 2))


def _catalogue() -> str:
    fonts = "\n".join(f"- {name}: {desc}" for name, desc in FONT_CHARACTER.items())
    themes = ", ".join(f"{t.name} ({'/'.join(t.keywords[:3])})" for t in THEMES)
    return f"FONT SETS\n{fonts}\n\nPHOTO THEMES: {themes}"


async def design_from_brief(prompt: str, photos: list[Photo], *,
                            direction: str | None = None, repairs: int = 2,
                            rng: random.Random | None = None,
                            plan: DesignPlan | None = None,
                            palette: Palette | None = None,
                            logo: bool = False,
                            on_draft: Callable[[Design, Variant], None] | None = None,
                            on_repair: Callable[[int, int], None] | None = None,
                            ) -> BriefResult:
    """Step 2 — the DESIGNER. With a `plan` (step 1, `plan.make_plan`) it builds exactly
    that plan; without one it designs freely with a creative direction and three random
    feature families. `palette` (the client's brand colours, `brand_palette`) replaces
    the colours the model would pick; `logo` asks for a logo even without a plan (the
    client gave one).

    LIDO_LAYOUT_CANDIDATES first drafts are requested at once (the first to pass wins);
    each draft gets the mechanical fixes, and what they leave goes back to the model as
    a patch (LIDO_REPAIR_MODEL), up to `repairs` rounds. `on_draft` is told about every
    better design as soon as there is one, so its photos can start rendering while
    repairs run; `on_repair(attempt, problems)` as each repair round starts."""
    from app.adapters.registry import llm as get_llm
    from app.config import get_settings

    if not get_settings().has_openai:
        raise RuntimeError("designing from a prompt needs OPENAI_API_KEY in backend/.env")

    rng = rng or random.Random()
    system = SYSTEM + BRIEF_RULES + "\n" + _catalogue()
    brief = f'CLIENT BRIEF:\n"""\n{prompt.strip()}\n"""'
    if plan is not None:
        features: list[str] = []
        steer = plan_brief(plan)
    else:
        # a different trio of feature families per design, so results spread across
        # Lido's whole vocabulary instead of settling on circles and rectangles
        features = rng.sample(sorted(FEATURE_FAMILIES), min(3, len(FEATURE_FAMILIES)))
        steer = (f"Creative direction for this version: {direction}." if direction
                 else "Choose the composition that best serves this brief.")
        steer += ("\nSignature elements for this version — work all three into the design: "
                  + "; ".join(FEATURE_FAMILIES[f] for f in features) + ".")
    # what every repair round must still respect, with or without a plan
    # the backdrop: the plan's, or (designing without a plan) often a random one
    backdrop = plan.backdrop if plan is not None else random_backdrop(rng)
    expanded = expand_backdrop(backdrop) if backdrop is not None else None
    fixed = "\n".join(part for part in (
        _brand_rules(palette) if palette is not None else "",
        brief_for(expanded, palette) if expanded is not None else "") if part)
    if fixed:
        steer += "\n" + fixed
    if logo and plan is None:
        steer += "\nInclude exactly one logo element: the client supplied their logo."

    def draft_prompt() -> str:  # a different pair of examples for every draft
        return (f"{brief}\n\n{steer}\n\n"
                "Two existing pro layouts, to show the format and the level of detail "
                "expected — match their richness, do not copy their composition:\n"
                f"{_format_example(photos, rng)}\n\n"
                "Design the template: name, idea, colours, font set, photo theme, elements.")

    def build(ai: BriefDesign, written: list[Element], attempt: int) -> _Draft:
        """The design as written → normalised, on its backdrop, checked, auto-fixed."""
        if plan is not None:
            ai.photo_theme = plan.photo_theme  # the art director chose the photos' theme
        if palette is not None:  # the client's colours, whatever the model wrote
            ai.colors = BriefColors(**{r: to_hex(palette.color(r)) for r in ROLES})
        v = Variant(palette or _palette(ai.colors), FONT_SETS_BY_NAME[ai.fonts],
                    THEMES_BY_NAME[ai.photo_theme], rng, photos)
        # normalise a copy: repairs edit the design as written (a list is still ONE
        # element there, so "move the list" is one edit, not twenty)
        elements = normalise([e.model_copy(deep=True) for e in written], v)
        for e in elements:  # only code marks backdrop layers and draws icons
            e.backdrop, e.doodle = None, None
        background = ai.background
        if expanded is not None:
            background = expanded.base
            elements = [*(e.model_copy() for e in expanded.layers), *elements]
        design = Design(recipe=f"brief:{ai.name}", theme=ai.photo_theme,
                        palette=palette.name if palette else "custom",
                        fonts=ai.fonts, background=background, elements=elements)
        design, errors = auto_fix(design, v, validate(design, v, creative=True, plan=plan),
                                  plan)
        return _Draft(ai, written, BriefResult(
            design, v, errors, ai.name, ai.idea, direction, attempt,
            {r: to_hex(v.palette.color(r)) for r in ROLES}, features))

    llm = get_llm()
    options, fix_options = layout_call(), repair_call()
    log.info("lido.brief.model", layout=describe(options), repair=describe(fix_options))
    calls: list[dict] = []  # how long each LLM call took, for the timing log

    async def first_draft() -> _Draft:
        t0 = time.perf_counter()
        reply = await _ask(llm, system=system, user=draft_prompt(), schema=BriefDesign,
                           temperature=0.9, max_tokens=16000, **options)
        calls.append(_call_info("draft", t0, reply))
        ai: BriefDesign = reply.parsed
        return build(ai, [to_element(e) for e in ai.elements], 1)

    best = await _first_passing(first_draft, max(1, get_settings().lido_layout_candidates))
    if on_draft is not None:
        on_draft(best.result.design, best.result.variant)
    sent: set[str] = set()  # the problems the last repair round was asked to fix
    for attempt in range(2, repairs + 2):
        if not best.result.errors:
            break
        errors = best.result.errors
        if sent and all(_kind(e) in sent for e in errors):
            # the model already had these and couldn't fix them: another round would
            # spend the same seconds for the same answer
            log.info("lido.brief.repairs_stalled", attempt=attempt, problems=len(errors))
            break
        sent = {_kind(e) for e in errors}
        if on_repair is not None:
            on_repair(attempt, len(errors))
        user = (f"{brief}\n\n{steer if plan is not None else fixed}\n\n"
                f"Your design:\n{_numbered(best.ai, best.written)}\n\n"
                "It fails these checks:\n- " + "\n- ".join(errors)
                + "\n\n" + repair_notes(errors, best.result.design)
                + "\n\nReturn ONLY the edits that fix every problem: replace an element "
                  "(its number and the whole corrected element), delete one, or insert a "
                  "new one before a number (the element count adds it in front). Keep the "
                  "idea and the brief's copy; leave every element that is fine alone.")
        t0 = time.perf_counter()
        try:
            reply = await _ask(llm, system=system, user=user, schema=BriefRepair,
                               temperature=0.4, max_tokens=8000, **fix_options)
        except AdapterError:
            # a repair round failed: keep the best design, its problems are reported
            log.warning("lido.brief.repair_unavailable", attempt=attempt)
            break
        calls.append(_call_info("repair", t0, reply))
        repaired = build(best.ai.model_copy(), apply_edits(best.written, reply.parsed.edits),
                         attempt)
        log.info("lido.brief.repaired", attempt=attempt, edits=len(reply.parsed.edits),
                 before=len(errors), after=len(repaired.result.errors))
        if len(repaired.result.errors) <= len(errors):  # never trade down
            best = repaired
            if on_draft is not None:
                on_draft(best.result.design, best.result.variant)
        best.result.attempts = attempt
    result = _decorate(best.result, plan, rng, backdrop)
    result.extras["llmCalls"] = calls
    return result


def _decorate(result: BriefResult, plan: DesignPlan | None, rng: random.Random,
              backdrop) -> BriefResult:
    """Contact icons, placed by code once the design is built (each kept only if it
    adds no problem)."""
    from app.lido_create.decorate import add_contact_icons

    extras: dict = {"backdrop": backdrop.model_dump() if backdrop is not None else None}
    if plan is None or (plan.contact_icons and "contact" not in plan.exclude):
        result.design, extras["contactIcons"] = add_contact_icons(
            result.design, result.variant, plan)
    result.errors = validate(result.design, result.variant, creative=True, plan=plan)
    result.extras = extras
    log.info("lido.brief.decorated", backdrop=backdrop.style if backdrop else None,
             icons=extras.get("contactIcons"))
    return result
