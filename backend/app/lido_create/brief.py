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
import random
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
    Gradient,
    H,
    Palette,
    Photo,
    Variant,
    W,
)
from app.lido_create.models import describe, layout_call
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
    elements: list[Element]


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


# How to fix each kind of failed check — sent with the failures, so a repair round
# changes the right thing instead of nudging elements around.
FIX_HINTS = {
    "sits on a photo": "Text can't sit on a photo. Add a solid card, band or panel shape "
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
    "too small to read": "Give the list element a bigger area (about 70px of height per "
                         "row) — move or shrink other elements to make room.",
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
                            logo: bool = False) -> BriefResult:
    """Step 2 — the DESIGNER. With a `plan` (step 1, `plan.make_plan`) it builds exactly
    that plan; without one it designs freely with a creative direction and three random
    feature families. `palette` (the client's brand colours, `brand_palette`) replaces
    the colours the model would pick; `logo` asks for a logo even without a plan (the
    client gave one)."""
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
        features = rng.sample(sorted(FEATURE_FAMILIES), 3)
        steer = (f"Creative direction for this version: {direction}." if direction
                 else "Choose the composition that best serves this brief.")
        steer += ("\nSignature elements for this version — work all three into the design: "
                  + "; ".join(FEATURE_FAMILIES[f] for f in features) + ".")
    # what every repair round must still respect, with or without a plan
    fixed = _brand_rules(palette) if palette is not None else ""
    if fixed:
        steer += "\n" + fixed
    if logo and plan is None:
        steer += "\nInclude exactly one logo element: the client supplied their logo."
    user = (f"{brief}\n\n{steer}\n\n"
            "Two existing pro layouts, to show the format and the level of detail "
            "expected — match their richness, do not copy their composition:\n"
            f"{_format_example(photos, rng)}\n\n"
            "Design the template: name, idea, colours, font set, photo theme, elements.")

    llm = get_llm()
    options = layout_call()  # LIDO_LAYOUT_MODEL / LIDO_LAYOUT_REASONING_EFFORT
    log.info("lido.brief.model", layout=describe(options))
    result: BriefResult | None = None
    for attempt in range(1, repairs + 2):
        try:
            reply = await _ask(llm, system=system, user=user, schema=BriefDesign,
                               temperature=0.9, max_tokens=16000, **options)
        except AdapterError:
            if result is None:
                raise
            # a repair round failed: keep the last design, its problems are reported
            log.warning("lido.brief.repair_unavailable", attempt=attempt)
            break
        ai: BriefDesign = reply.parsed
        if plan is not None:
            ai.photo_theme = plan.photo_theme  # the art director chose the photos' theme
        if palette is not None:  # the client's colours, whatever the model wrote
            ai.colors = BriefColors(**{r: to_hex(palette.color(r)) for r in ROLES})
        v = Variant(palette or _palette(ai.colors), FONT_SETS_BY_NAME[ai.fonts],
                    THEMES_BY_NAME[ai.photo_theme], rng, photos)
        # the design as the model wrote it (a list is still ONE element): repairs work
        # on this, so "move the list" is one change, not twenty
        as_written = ai.model_dump_json(exclude_none=True)
        ai.elements = normalise(ai.elements, v)
        design = Design(recipe=f"brief:{ai.name}", theme=ai.photo_theme,
                        palette=palette.name if palette else "custom",
                        fonts=ai.fonts, background=ai.background, elements=ai.elements)
        errors = validate(design, v, creative=True, plan=plan)
        result = BriefResult(design, v, errors, ai.name, ai.idea, direction, attempt,
                             {r: to_hex(v.palette.color(r)) for r in ROLES},
                             features)
        if not errors:
            break
        user = (f"{brief}\n\n{steer if plan is not None else fixed}\n\n"
                f"Your design:\n{as_written}\n\n"
                "It fails these checks:\n- " + "\n- ".join(errors)
                + "\n\n" + repair_notes(errors, design)
                + "\n\nReturn the full corrected design: keep the idea and the brief's copy, "
                  "fix every problem.")
    assert result is not None
    # mechanical last resorts, each kept only if it leaves fewer problems
    for trigger, fix in (("sits on a photo", back_text_on_photos), ("logo", relocate_logo)):
        if any(trigger in e for e in result.errors):
            patched = fix(result.design, result.variant)
            errors = validate(patched, result.variant, creative=True, plan=plan)
            if len(errors) < len(result.errors):
                log.info("lido.brief.auto_fixed", fix=fix.__name__,
                         before=len(result.errors), after=len(errors))
                result.design, result.errors = patched, errors
    return result
