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
from app.lido_corpus.palette import parse_color, to_hex
from app.lido_create.ai import EXAMPLE_RECIPES, SYSTEM, example, normalise
from app.lido_create.check import validate
from app.lido_create.kit import (
    FONT_SETS,
    FONT_SETS_BY_NAME,
    PALETTES,
    THEMES,
    THEMES_BY_NAME,
    Design,
    Element,
    Palette,
    Photo,
    Variant,
)

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
- At most 12 text boxes in total. When the brief lists many features, keep the 3-4
  most important as bulleted items and drop the rest.
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


def _palette(colors: BriefColors) -> Palette:
    """The model's colours; any value that isn't a colour falls back to a known-good one."""
    fallback = PALETTES[0]
    rgb = {role: parse_color(getattr(colors, role)) or fallback.color(role)
           for role in ("bg", "ink", "accent", "on_accent", "soft")}
    return Palette("custom", **rgb)


def _format_example(photos: list[Photo]) -> str:
    v = Variant(PALETTES[0], FONT_SETS[0], THEMES[0], random.Random(0), photos)
    return "\n".join(example(r, v) for r in EXAMPLE_RECIPES)


def _catalogue() -> str:
    fonts = "\n".join(f"- {name}: {desc}" for name, desc in FONT_CHARACTER.items())
    themes = ", ".join(f"{t.name} ({'/'.join(t.keywords[:3])})" for t in THEMES)
    return f"FONT SETS\n{fonts}\n\nPHOTO THEMES: {themes}"


async def design_from_brief(prompt: str, photos: list[Photo], *,
                            direction: str | None = None, repairs: int = 2,
                            rng: random.Random | None = None) -> BriefResult:
    from app.adapters.registry import llm as get_llm
    from app.config import get_settings

    if not get_settings().has_openai:
        raise RuntimeError("designing from a prompt needs OPENAI_API_KEY in backend/.env")

    rng = rng or random.Random()
    system = SYSTEM + BRIEF_RULES + "\n" + _catalogue()
    brief = f'CLIENT BRIEF:\n"""\n{prompt.strip()}\n"""'
    steer = (f"Creative direction for this version: {direction}." if direction
             else "Choose the composition that best serves this brief.")
    user = (f"{brief}\n\n{steer}\n\n"
            "Two existing pro layouts, to show the format and the level of detail "
            "expected — match their richness, do not copy their composition:\n"
            f"{_format_example(photos)}\n\n"
            "Design the template: name, idea, colours, font set, photo theme, elements.")

    llm = get_llm()
    result: BriefResult | None = None
    for attempt in range(1, repairs + 2):
        try:
            reply = await _ask(llm, system=system, user=user, schema=BriefDesign,
                               temperature=0.9, max_tokens=16000)
        except AdapterError:
            if result is None:
                raise
            # a repair round failed: keep the last design, its problems are reported
            log.warning("lido.brief.repair_unavailable", attempt=attempt)
            break
        ai: BriefDesign = reply.parsed
        v = Variant(_palette(ai.colors), FONT_SETS_BY_NAME[ai.fonts],
                    THEMES_BY_NAME[ai.photo_theme], rng, photos)
        ai.elements = normalise(ai.elements, v)
        design = Design(recipe=f"brief:{ai.name}", theme=ai.photo_theme, palette="custom",
                        fonts=ai.fonts, elements=ai.elements)
        errors = validate(design, v, creative=True)
        result = BriefResult(design, v, errors, ai.name, ai.idea, direction, attempt,
                             {r: to_hex(v.palette.color(r))
                              for r in ("bg", "ink", "accent", "on_accent", "soft")})
        if not errors:
            break
        user = (f"{brief}\n\nYour design:\n{ai.model_dump_json(exclude_none=True)}\n\n"
                "It fails these checks:\n- " + "\n- ".join(errors)
                + "\n\nReturn the corrected design: keep the idea and the brief's copy, fix "
                  "every problem (move or resize elements, shorten lines, reduce sizes).")
    assert result is not None
    return result
