"""--ai mode: the configured LLM invents a new layout in the same element format the
recipes produce. It runs through the same checks; any errors are sent back for repair
(up to `repairs` rounds), so a layout is only saved once it passes like a recipe does."""

from __future__ import annotations

import json

from pydantic import BaseModel

from app.lido_create.check import validate
from app.lido_create.kit import (
    FONT_SETS,
    PALETTES,
    THEMES,
    Canvas,
    Design,
    Element,
    Variant,
    line_count,
)
from app.lido_create.recipes import RECIPES


class AIDesign(BaseModel):
    name: str  # short snake_case name for the layout idea
    idea: str  # the composition in one sentence
    elements: list[Element]


SYSTEM = """You are a senior social-media designer. You lay out ONE square 1080x1080 post
template as a list of elements with pixel coordinates. The template will later be filled
automatically for any business, so it must be clean, generic and professional.

ELEMENTS (drawn in list order: first = back, last = front)
- shape: shape "rectangle" (radius = corner radius px, 0 for sharp) or "circle";
  color = a palette role; optional opacity 0-1; bleed=true if it may run off the canvas.
- photo: clip "rect" | "rounded" (radius px) | "circle" (w must equal h) | "arch";
  focus 0-1 (0.3 keeps faces, 0.5 centre); subject = one sentence on what it shows.
  The picture itself is supplied automatically.
- logo: exactly one, w 110, h 89. It must sit on one flat colour, never on a photo.
- text: text (placeholder copy), text_type, font role, size px, align, max_lines,
  uppercase, letter_spacing (em, 0-0.3), line_height. Set h to 0 — it is measured.
  text_type: headline (exactly one, the largest free text on the canvas), kicker, body,
  item (list lines), cta (button label), badge (offer/date label), website, phone,
  email, address (at most one of each contact type).
  font roles: display (headlines/badges), body (everything small), button (button
  labels, uppercase), script (short decorative phrase only).

COLOUR ROLES: bg (the canvas colour), ink (text on bg), accent (buttons, badges, big
shapes), on_accent (text ON accent), soft (decoration only — never text).
Text on bg uses ink or accent; text on an accent shape uses on_accent.

RULES THAT ARE CHECKED (your layout is rejected if any fails)
- every text fits its w within max_lines, measured with the real font
- no text overlaps other text or the logo; no shape/photo is drawn on top of text
- every text sits entirely on ONE flat colour: never on a photo, never across a
  shape's edge. Put a button label exactly on its pill (same x/w, vertically centred).
- text/logo at least 30px from the canvas edge; shapes/photos inside unless bleed
- 1 or 2 photos, each at least 200px on each side, given real prominence
  (roughly a third of the canvas or more); 3 to 9 text boxes

GOOD DESIGN
- 70px side margin grid; clear hierarchy (headline 3-4x body size, body ~24-28px)
- one element that breaks the grid (a badge on a seam, a pill overlapping a photo)
- decorations are simple shapes, nothing industry-specific; 1-2 photos max
- leave room: real copy may be 30-40% longer than the placeholder
"""


def _example(recipe: str, v: Variant) -> str:
    c = Canvas(v)
    RECIPES[recipe].build(c)
    return json.dumps({"name": recipe, "elements": [
        e.model_dump(exclude_none=True) for e in c.els]}, separators=(",", ":"))


def normalise(els: list[Element], v: Variant) -> None:
    """Fill what the model may leave loose: text heights are always measured."""
    for e in els:
        if e.kind == "text":
            e.font = e.font or "body"
            e.size = e.size or 26
            e.line_height = e.line_height or (v.fonts.display_lh if e.font == "display"
                                              else 1.3)
            e.align = e.align or "left"
            lines, _ = line_count(v.fonts, e)
            e.h = round(len(lines) * e.size * e.line_height, 2)
        elif e.kind == "logo":
            e.w, e.h = 110, 89


def _dress(v: Variant) -> str:
    """The palette, fonts and copy this layout is dressed in, spelled out for the model."""
    p, f, t = v.palette, v.fonts, v.theme
    colours = ", ".join(f"{role} rgb{p.color(role)}"
                        for role in ("bg", "ink", "accent", "on_accent", "soft"))
    return (f"Palette: {colours}.\n"
            f"Display font: {f.display} ("
            + ("set headlines uppercase" if f.display_upper else "not uppercase")
            + f", line height {f.display_lh}); body: {f.body}; button: {f.button}; "
              f"script: {f.script}.\n"
            f"Theme '{t.name}' — use this placeholder copy where it fits (you may shorten "
            f"it): kicker {t.kicker!r}, headline {t.headline!r}, body {t.body!r}, "
            f"cta {t.cta!r}, badge {t.badge!r}, items {list(t.items)}, script {t.script!r}, "
            f"date {t.date!r}, website {t.website!r}, phone {t.phone!r}, email {t.email!r}, "
            f"address {t.address!r}.")


async def invent(v: Variant, *, hint: str | None, avoid: list[str],
                 repairs: int = 2) -> tuple[Design, list[str], str]:
    """(design, remaining errors, the idea in one sentence) for the dress `v` gives."""
    from app.adapters.registry import llm as get_llm
    from app.config import get_settings

    if not get_settings().has_openai:
        raise SystemExit("--ai needs OPENAI_API_KEY in backend/.env")

    seed_v = Variant(PALETTES[0], FONT_SETS[0], THEMES[0], v.rng, v.photos)
    examples = "\n".join(_example(r, seed_v) for r in ("split_offer", "event_invite"))
    known = "\n".join(f"- {r.name}: {r.description}" for r in RECIPES.values())
    earlier = "".join(f"\n- {a}" for a in avoid)
    user = (f"Layouts that already exist — yours must look clearly different:\n{known}"
            + (f"\nAlso different from these layouts you already made:{earlier}" if avoid
               else "")
            + f"\n\nTwo existing layouts in the exact element format:\n{examples}\n\n"
            + f"Dress the new layout in:\n{_dress(v)}\n\n"
            + "Invent ONE new layout for it. "
            + (f"Brief for the idea: {hint}" if hint else "Surprise me with the idea."))

    llm = get_llm()
    errors: list[str] = []
    for attempt in range(repairs + 1):
        result = await llm.complete_json(system=SYSTEM, user=user, schema=AIDesign,
                                         temperature=0.9, max_tokens=16000)
        ai: AIDesign = result.parsed
        normalise(ai.elements, v)
        design = Design(recipe=f"ai:{ai.name}", theme=v.theme.name, palette=v.palette.name,
                        fonts=v.fonts.name, elements=ai.elements)
        errors = validate(design, v)
        print(f"    ai attempt {attempt + 1}: {ai.name!r} — "
              + ("passes" if not errors else f"{len(errors)} problem(s)"))
        if not errors:
            break
        user = (f"Dress:\n{_dress(v)}\n\nYour layout:\n"
                f"{ai.model_dump_json(exclude_none=True)}\n\n"
                "It fails these checks:\n- " + "\n- ".join(errors)
                + "\n\nReturn the corrected layout (same idea, fix every problem; move or "
                  "resize elements, shorten copy or reduce sizes as needed).")
    return design, errors, f"{ai.name}: {ai.idea}"
