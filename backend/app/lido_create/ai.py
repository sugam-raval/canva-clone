"""--ai mode: the configured LLM invents a new layout in the same element format the
recipes produce. It runs through the same checks; any errors are sent back for repair
(up to `repairs` rounds), so a layout is only saved once it passes like a recipe does."""

from __future__ import annotations

import json

from pydantic import BaseModel

from app.lido_create.check import FEATURE_FAMILIES, validate
from app.lido_create.draw import DRAW_PRESETS
from app.lido_create.kit import (
    FONT_SETS,
    PALETTES,
    THEMES,
    Canvas,
    Design,
    Element,
    Gradient,
    Variant,
    line_count,
)
from app.lido_create.recipes import RECIPES
from app.lido_create.shapes import FRAME_HINTS, SHAPES, frames


class AIDesign(BaseModel):
    name: str  # short snake_case name for the layout idea
    idea: str  # the composition in one sentence
    background: Gradient | None  # a gradient canvas, or null for the flat bg colour
    elements: list[Element]


SYSTEM_TEMPLATE = """You are a senior social-media designer. You lay out ONE square 1080x1080 post
template as a list of elements with pixel coordinates. The template will later be filled
automatically for any business, so it must be generic in its decoration, but it must look
like a polished, professionally designed template — never a plain wireframe.

ELEMENTS (drawn in list order: first = back, last = front)
- shape: shape = one of the SHAPES below; color = a palette role; radius = corner
  radius px (rectangle only); opacity 0-1; rotate = degrees clockwise around its centre;
  gradient = a fill that changes across the shape (see GRADIENTS) instead of a flat
  colour; stroke + stroke_width + stroke_style (solid | dashed | dotted) = an outline
  (the fill is still drawn — fill with the colour behind it for an outline-only
  look); bleed=true if it may run off the canvas.
- line: a straight line — x/y = its left end, w = length, h = thickness (2-8px),
  rotate, color, stroke_style solid | dashed | dotted, line_start / line_end = none |
  arrow | triangle | bar | circle | square | diamond | outlineCircle | outlineSquare |
  outlineDiamond. For dividers, underlines, pointers, frames made of lines.
- draw: a hand-drawn marker stroke filling x/y/w/h — draw = one of DRAW below, color,
  stroke_width (4-14px), opacity. Casual, human accents: circle a price, underline a
  word, point an arrow at the product.
- dots: a dot-grid texture — x/y/w/h is the area, rows x cols dots (max 8 x 8) of
  diameter dot (6-12px), color, optional opacity. One element, not many circles.
- photo: frame = one of FRAMES below (the photo is cut to that outline and keeps its
  aspect ratio — h follows w), or clip "rect" | "rounded" (radius px) | "circle" (w = h)
  | "arch" | "hexagon" | "diamond" | "blob" | "leaf" | "cutout" (a transparent subject
  with no frame, floating directly on the background); focus 0-1 (0.3 keeps faces, 0.5
  centre); subject = one sentence on what it shows. The picture is supplied
  automatically.
- logo: exactly one, w 110, h 89. It must sit on one flat colour, never on a photo.
- text: text (placeholder copy), text_type, font role, size px, align, max_lines,
  uppercase, letter_spacing (em, 0-0.3), line_height, effect = shadow | lift (soft
  glow) | hollow (outline-only letters, display text of 56px or more) with
  effect_color for the shadow. Set h to 0 — it is measured.
  text_type: headline (exactly one, the largest free text on the canvas), kicker, body,
  item (list lines), cta (button label), badge (offer/price/date label), caption (small
  caps label like "CALL US", "UP TO", "ONLY"), website, phone, email, address (at most
  one of each contact type).
  font roles: display (headlines/badges/prices), body (everything small), button
  (button labels, uppercase), script (a short decorative phrase — always smaller in px
  than the headline).

SHAPES
{shapes}

FRAMES (photo outlines): {frames}; letter_A ... letter_Z (the photo fills one big
letter — for a bold initial or a one-letter word).

DRAW (hand-drawn strokes): {draws}

GRADIENTS: {{style: linear | radial, angle (linear, CSS degrees: 0 = towards the top,
90 = right, 180 = down, 45 = up-right), start (colour role, default the element's
color), end (colour role; leave empty to fade the start colour out to transparent),
start_at / end_at (0-100, where the fade begins and ends)}}. The whole canvas can have a
gradient too (background, with an end colour). Use them for depth: a spotlight
(radial) behind the headline, a panel that fades out, a dark-to-deep background.

COLOUR ROLES: bg (the canvas colour), ink (text on bg), accent (buttons, badges, big
shapes), on_accent (text ON accent), soft (decoration only — never text).
Text on bg uses ink or accent; text on an accent shape uses on_accent; text on an ink
shape uses bg.

RULES THAT ARE CHECKED (your layout is rejected if any fails)
- every text fits its w within max_lines, measured with the real font
- no text overlaps other text or the logo; no shape/photo is drawn on top of text
- every text sits entirely on ONE flat colour: never on a photo, never across a
  shape's edge, never over a dot grid. Put a label exactly on its pill/badge.
- text/logo at least 30px from the canvas edge; shapes/photos inside unless bleed
- 1 or 2 photos, each at least 200px on each side, given real prominence
  (roughly a third of the canvas or more); 3 to 12 text boxes
- at least 3 decorative elements that no text sits on
- lines and hand-drawn strokes never run through text (under, beside or around it)
- no shape behind a photo: photos sit directly on the background (no stage circle,
  blob, ring or offset block under them); decoration goes around photos, and badges
  may overlap a photo's edge only when drawn on top of it
- every list item has a bullet marker shape beside it, centred on its first line

PRO TEMPLATE TECHNIQUES — use several in every design
- Headline pairing: a script phrase (font script, accent) directly above or beside a
  huge uppercase display headline; or one headline word set on its own accent pill.
- Reverse band: a short line (offer, tagline) in bg-coloured text on an ink or accent
  pill/band right under the headline.
- Offer badge: an accent circle holding stacked texts — caption "UP TO", then the big
  offer ("30% OFF") in display — overlapping the photo's edge.
- Price tag: an outlined rounded rectangle (stroke accent) with caption "ONLY" above a
  display price.
- Geometric accents: a rotated square (diamond) or big circle bleeding off a corner;
  an accent panel with a diamond at its end as an arrow tip; thin 3-6px lines.
- Textures: 1-2 dot grids in empty corners or beside the photo.
- Bulleted features: each item with a ring (circle + smaller bg circle), dot or short
  bar marker, on a panel or on the bg.
- Contact blocks: a small caption label ("CALL US", "VISIT US") above the phone or
  website, with a small ring marker beside it, in a bottom row; often split left/right
  around a centred button.
- Framing: an outlined rounded rectangle inset 30-40px around the whole canvas, or a
  thick band along one edge; or thin lines forming corner brackets.
- Depth with gradients: a radial spotlight behind the headline or product, a panel
  fading out towards the photo, a background running from bg to a deeper tone.
- Shape language: parallelogram bands for energy, chevrons and arrows for flow and
  steps, a starburst look from rotated squares, hexagon/pentagon tiles, a cross or small
  triangles as sparkle accents.
- Hand-drawn accents: a marker underline under the key word, a loose circle around the
  price, a curved arrow pointing at the product, sparkle lines beside the offer.
- Type effects (use sparingly, one per design): a hollow outline word paired with a
  solid one, a soft lift under a big headline on a busy panel, a shadow on bold type.
- Frames: a brush-stroke or torn-paper frame for a casual, crafted look; a scallop
  badge or gem for a playful one; one big letter frame for a bold brand initial.

GOOD DESIGN
- 70px side margin grid; clear hierarchy (headline 3-4x body size, body ~22-28px)
- one element that breaks the grid (a badge overlapping the photo's edge)
- balance: fill the canvas with intent — no big dead gaps, no crowding; group related
  items (offer with price, contacts in one row)
- decorations are simple shapes, nothing industry-specific
- leave room: real copy may be 30-40% longer than the placeholder
"""


SYSTEM = SYSTEM_TEMPLATE.format(
    shapes="\n".join(f"- {s.name}: {s.hint}" for s in SHAPES.values()),
    frames=", ".join(f"{name} ({hint})" for name, hint in FRAME_HINTS.items()),
    draws="; ".join(f"{name} = {hint}" for name, hint in DRAW_PRESETS.items()),
)


def compact(els: list[Element]) -> list[dict]:
    """Elements as the model writes them: a run of small same-colour circles (how a
    recipe draws a dot grid) is written back as one `dots` element."""
    out: list[dict] = []
    run: list[Element] = []

    def flush() -> None:
        if len(run) >= 4:
            xs, ys = sorted({e.x for e in run}), sorted({e.y for e in run})
            dot = run[0].w
            out.append(Element(kind="dots", x=xs[0], y=ys[0], w=xs[-1] - xs[0] + dot,
                               h=ys[-1] - ys[0] + dot, rows=len(ys), cols=len(xs), dot=dot,
                               color=run[0].color, opacity=run[0].opacity)
                       .model_dump(exclude_none=True))
        else:
            out.extend(e.model_dump(exclude_none=True) for e in run)
        run.clear()

    for e in els:
        small_dot = e.kind == "shape" and e.shape == "circle" and e.w < 16
        if small_dot and (not run or (e.color == run[0].color and e.w == run[0].w)):
            run.append(e)
            continue
        flush()
        if small_dot:
            run.append(e)
        else:
            out.append(e.model_dump(exclude_none=True))
    flush()
    return out


def example(recipe: str, v: Variant) -> str:
    c = Canvas(v)
    RECIPES[recipe].build(c)
    background = c.background.model_dump(exclude_none=True) if c.background else None
    return json.dumps({"name": recipe, "background": background, "elements": compact(c.els)},
                      separators=(",", ":"))


EXAMPLE_RECIPES = ("fresh_promo", "geo_agency", "spotlight_launch")


def expand_dots(e: Element) -> list[Element]:
    """A `dots` element is shorthand for a grid of small circles filling its box."""
    rows, cols = max(1, min(e.rows or 3, 8)), max(1, min(e.cols or 3, 8))
    dot = e.dot or 10
    gx = (e.w - dot) / (cols - 1) if cols > 1 else 0
    gy = (e.h - dot) / (rows - 1) if rows > 1 else 0
    return [Element(kind="shape", shape="circle", x=round(e.x + c * gx, 2),
                    y=round(e.y + r * gy, 2), w=dot, h=dot, color=e.color or "accent",
                    opacity=e.opacity, bleed=e.bleed)
            for r in range(rows) for c in range(cols)]


def normalise(els: list[Element], v: Variant) -> list[Element]:
    """Fill what the model may leave loose (text heights are always measured) and
    expand shorthand elements. Returns the element list to use."""
    out: list[Element] = []
    for e in els:
        if e.kind == "dots":
            out += expand_dots(e)
            continue
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
        elif e.kind == "photo" and e.frame:
            e.h = round(e.w / frames()[e.frame].aspect, 2)  # a frame keeps its outline
            e.clip = None
        elif e.kind == "photo" and e.clip == "circle":
            e.h = e.w  # the circle crop is always round
        elif e.kind == "draw":
            e.draw = e.draw or "underline"
            e.stroke_width = e.stroke_width or 6
        out.append(e)
    return out


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
    examples = "\n".join(example(r, seed_v) for r in EXAMPLE_RECIPES)
    known = "\n".join(f"- {r.name}: {r.description}" for r in RECIPES.values())
    earlier = "".join(f"\n- {a}" for a in avoid)
    user = (f"Layouts that already exist — yours must look clearly different:\n{known}"
            + (f"\nAlso different from these layouts you already made:{earlier}" if avoid
               else "")
            + f"\n\nTwo existing layouts in the exact element format:\n{examples}\n\n"
            + f"Dress the new layout in:\n{_dress(v)}\n\n"
            + "Signature elements for this version — work all three into the design: "
            + "; ".join(FEATURE_FAMILIES[f] for f in v.rng.sample(sorted(FEATURE_FAMILIES), 3))
            + ".\n\nInvent ONE new layout for it. "
            + (f"Brief for the idea: {hint}" if hint else "Surprise me with the idea."))

    llm = get_llm()
    errors: list[str] = []
    for attempt in range(repairs + 1):
        result = await llm.complete_json(system=SYSTEM, user=user, schema=AIDesign,
                                         temperature=0.9, max_tokens=16000)
        ai: AIDesign = result.parsed
        ai.elements = normalise(ai.elements, v)
        design = Design(recipe=f"ai:{ai.name}", theme=v.theme.name, palette=v.palette.name,
                        fonts=v.fonts.name, background=ai.background, elements=ai.elements)
        errors = validate(design, v, creative=True)
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
