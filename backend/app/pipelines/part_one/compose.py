"""`compose.layout` — IMPLEMENTATION_PLAN §1.3.

The LLM does NOT invent coordinates. It picks a skeleton and variant, writes or places
copy, chooses a palette and font, fills image prompts, and may nudge a frame by at most
+/-8%. Everything geometric happens in `expand()`, which is deterministic code.

Output is constrained to `ComposerOutput`, which is small and hard to get wrong.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

import structlog

from app.adapters.base import AdapterError
from app.adapters.registry import llm as get_llm
from app.layout.fonts import get_registry
from app.schema.art import ArtDirection
from app.schema.brief import Contact, DesignBrief
from app.schema.composer import ComposerOutput, ComposerSlot, SlotImagePrompt, SlotText
from app.schema.doc import (
    AutoFit,
    Canvas,
    Constraints,
    DesignDoc,
    FontRef,
    Frame,
    GeneratedProvenance,
    GenerationParams,
    GradientStop,
    ImageLayer,
    Layer,
    LayerMeta,
    LinearGradient,
    OrnamentParams,
    ShadowEffect,
    ShapeLayer,
    ShapeStroke,
    TextLayer,
    TextStroke,
)
from app.schema.template import Slot, TemplateSkeleton
from app.templates_corpus.ornament import (
    MOTIF_FAMILIES,
    family_of,
    is_icon,
    is_stroked,
    render_motif,
)
from app.util.color import (
    adjust_lightness,
    contrast_ratio,
    ensure_distinct,
    harmonious_on,
    relative_luminance,
    saturation,
)
from app.util.palette import complete_palette, dedupe_palette, order_palette, resolve_palette_words

log = structlog.get_logger(__name__)

# §1.3: image prompts must ALWAYS append this block. The glyph gate (§1.4.6) is the
# actual enforcement — this only reduces how often the gate has to fire.
NEGATIVE_TEXT_BLOCK = (
    "text, letters, words, numbers, typography, watermark, logo, signature, "
    "caption, ui, frame, border"
)

# A transparent slot must not ask for anything that implies a ground plane, or the
# cutout arrives with a floor and shadow baked into its alpha.
NEGATIVE_TRANSPARENT_BLOCK = "background, floor, surface, ground, shadow, reflection, table"

DEFAULT_PALETTES: dict[str, list[str]] = {
    "minimal": ["#F8FAFC", "#0F172A", "#2563EB"],
    "premium": ["#111014", "#E8E2D9", "#C8A45C"],
    "bold": ["#0F172A", "#FFFFFF", "#F5B700"],
    "playful": ["#FFF4E6", "#1F2937", "#FF6B4A"],
    "dark": ["#08090C", "#F1F5F9", "#7C3AED"],
    "natural": ["#F3F1EA", "#24331F", "#8A9A5B"],
    "tech": ["#06080F", "#E2E8F0", "#22D3EE"],
    "retro": ["#F2E8D5", "#2B2118", "#D9531E"],
    "warm": ["#FFF7ED", "#2A1A12", "#EA7317"],
    "clean": ["#FFFFFF", "#111827", "#3B82F6"],
    # Deep ground, gold, cream — the ceremonial palette the festive mood expects, and
    # the one the reference work for this kind of design consistently lands on.
    "festive": ["#0E1A33", "#F5E6C8", "#C9A227", "#7A1F2B"],
}


def font_allow_list() -> dict[str, list[str]]:
    """§1.3 step 4: the composer chooses a family from an allow-list, not freely."""
    registry = get_registry()
    return {vibe: registry.families_for_vibe(vibe)
            for vibe in ("geometric", "humanist", "serif-editorial", "display-bold")}


# (display face, supporting face) per vibe, best first. The allow-list above answers
# "which families suit this vibe"; it cannot answer "which two work together", and a
# display face is unusable at body size — Archivo Black or Bebas Neue set as a caption
# is the single most reliable way to make a design look untyped.
# (display face, supporting face, script accent). The script is optional and is used
# only where a skeleton asks for it.
_PAIRINGS: dict[str, list[tuple[str, str, str | None]]] = {
    "serif-editorial": [
        ("Playfair Display", "Source Sans 3", "Great Vibes"),
        ("Abril Fatface", "Source Sans 3", "Great Vibes"),
        ("Playfair Display", "Montserrat", "Dancing Script"),
    ],
    "display-bold": [
        ("Anton", "Inter", "Pacifico"),
        ("Archivo Black", "Inter", "Dancing Script"),
        ("Alfa Slab One", "Source Sans 3", "Pacifico"),
        ("Bebas Neue", "Source Sans 3", "Dancing Script"),
    ],
    "geometric": [
        ("Montserrat", "Inter", "Dancing Script"),
        ("Space Grotesk", "Inter", None),
        ("Poppins", "DM Sans", "Dancing Script"),
    ],
    "humanist": [
        ("DM Sans", "Source Sans 3", "Caveat"),
        ("Source Sans 3", "Source Sans 3", "Dancing Script"),
        ("Playfair Display", "Source Sans 3", "Great Vibes"),
    ],
}


def font_pairings() -> dict[str, list[tuple[str, str, str | None]]]:
    """Pairings filtered to families actually present in the catalogue.

    A missing script degrades to no script rather than dropping the whole pairing — the
    accent is a flourish, the display and text faces are the design.
    """
    available = set(get_registry().families)
    out: dict[str, list[tuple[str, str, str | None]]] = {}
    for vibe, pairs in _PAIRINGS.items():
        usable = [(d, t, (c if c in available else None))
                  for d, t, c in pairs if d in available and t in available]
        if not usable:
            fallback = font_allow_list().get(vibe) or ["Inter"]
            usable = [(fallback[0], "Inter" if "Inter" in available else fallback[0], None)]
        out[vibe] = usable
    return out


def _pairing_for(vibe: str) -> tuple[str, str, str | None]:
    return font_pairings().get(vibe, font_pairings()["geometric"])[0]


COMPOSER_SYSTEM = """\
You are a layout composer. You are given a design brief and up to three candidate
layout skeletons. You choose one and fill it in. You do NOT invent coordinates — the
skeleton owns all geometry.

YOUR JOB
1. Pick the skeleton (and variant, if any) that best fits the brief. Give a one-line
   reason.
2. Write or place copy into each text slot, never exceeding that slot's maxChars.
   Count characters, not words.
3. Choose a palette of 3 to 5 hex colours. The first is the dominant/background colour,
   the last is the accent. If the brief supplies a brand palette, use it unchanged.
   Choose designed colours, not primaries: a metallic is a muted mid-tone (#C9A227, not
   #FFD700) and is never the background. Where the brief names colours, those colours
   are the palette.
4. Choose ONE font pairing from the allowed list: `family` is the display face used
   for the headline, `textFamily` is the supporting face used for every other text
   layer. Take a pairing as given — do not mix a display face from one with a
   supporting face from another, and never set body copy in a display face.
5. Write a prompt and a negativePrompt for every image slot.
6. Set include=false ONLY for a slot the design is genuinely better without, and never
   for one marked required. Default to filling the skeleton: it was designed as a whole,
   and a layout built for a headline, a subhead, a CTA and a product that ships with only
   the headline reads as a broken design, not a minimal one. If a slot has no obvious
   content, write content for it rather than dropping it. Decoration slots cost nothing
   and should be kept unless the brief asks for a sparse layout.

PROMOTIONAL AND CONTACT SLOTS
- A slot with role `offer`, `price`, `badge`, `terms`, `event`, `contact` or `logo` is
  filled from the matching brief field, not written fresh. These carry the user's own
  facts. A `logo` slot holds `brandName` exactly as the user wrote it — it is the
  business's name, not a tagline, and a design that renames the business is unusable.
- `contact` and `phone` content is TRANSCRIBED CHARACTER FOR CHARACTER. Never reformat a
  number, never shorten a URL, never invent either. A design whose phone number does not
  work is worse than one with no phone number on it.
- `feature` slots take the brief's `features` list in order, one entry per slot. Keep
  them short and parallel in construction — they are read as a list, not as sentences.
- A slot whose id starts with `tag_` is also role `feature` but takes the brief's
  SEPARATE `tags` list instead, in order, one entry per slot — a row of short keyword
  chips (a tech stack, a skill set), never the same content as the `feature_N` slots
  beside it. When the brief has both `features` and `tags`, fill both lists into their
  own slots rather than merging them or choosing one.
- A `badge` slot holds a handful of characters ("50% OFF"). If the offer will not fit,
  shorten it to the number; do not overflow the seal.
- Where the brief has an offer, a price or contact details and the chosen skeleton has
  slots for them, those slots are the point of the design. Fill them before you decide
  any optional slot is not worth including.

COPY RULES
- If the brief already contains copy, use it VERBATIM. Do not rewrite the user's words.
- Where the brief has no copy for a slot, write it: concrete, specific, in the brief's
  language. Never emit placeholder text like "Your headline here" or lorem ipsum.
- Do NOT pre-uppercase copy. Case transforms are applied at render time; baking them in
  breaks non-Latin text and makes the text awkward for the user to edit.
- If good copy would exceed maxChars, write shorter copy. Do not overflow the slot.

IMAGE PROMPT RULES
- Every image prompt must describe an EMPTY scene with room where the subject and the
  headline will sit. Say so in words, e.g. "leave the upper-left third uncluttered".
- A transparent slot's prompt must NOT mention background, floor, surface, shadow or
  any ground plane — it is a cutout.
- Never ask for text, lettering, logos or watermarks in an image. Text is a separate
  editable layer and must never be part of a raster.
- Describe lighting and camera, not brand names or real people.
- Describe how the mood should LOOK, never the mood word itself. An image model reads a
  mood word as a stock genre and answers with that genre's iconography — "festive"
  returns snowflakes, baubles and fir, so a Diwali greeting comes back decorated for
  Christmas. Write "ornamental, warm glowing light, marigold and brass" instead.
- Where the design is for a specific occasion, culture or cuisine, say which one. An
  unqualified celebration prompt defaults to a Western Christmas.

FRAME NUDGES
- frameNudge is optional and limited to +/-0.08 of the canvas. Use it only to improve
  balance for this specific copy length, never to restructure the layout.
"""


def _render_candidates(candidates: list[TemplateSkeleton]) -> str:
    lines = []
    for skeleton in candidates:
        lines.append(f"\n### {skeleton.id} — {skeleton.name}")
        lines.append(f"{skeleton.description}")
        if skeleton.variants:
            lines.append("variants: " + ", ".join(
                f"{v.id} ({v.name})" for v in skeleton.variants))
        lines.append("slots:")
        for slot in skeleton.slots:
            bits = [f"  - {slot.slot_id}: {slot.layer_type} / role={slot.role}",
                    "required" if slot.required else "optional"]
            if slot.text:
                bits.append(f"maxChars={slot.text.max_chars}")
                if slot.text.transform != "none":
                    bits.append(f"rendered {slot.text.transform}")
            if slot.image:
                bits.append("TRANSPARENT CUTOUT" if slot.image.transparent else "photo")
                bits.append(f"template={slot.image.prompt_template!r}")
            if slot.palette_role:
                bits.append(f"colour={slot.palette_role}")
            lines.append(", ".join(bits))
    return "\n".join(lines)


def _render_brief(brief: DesignBrief) -> str:
    copy = brief.copy_text
    supplied = {k: v for k, v in (
        ("headline", copy.headline), ("subhead", copy.subhead), ("body", copy.body),
        ("cta", copy.cta), ("caption", copy.caption), ("offer", copy.offer),
        ("price", copy.price), ("badge", copy.badge), ("terms", copy.terms),
        ("event", copy.event_details)) if v}
    if copy.features:
        supplied["features"] = copy.features
    if copy.tags:
        supplied["tags"] = copy.tags
    pairs = font_pairings().get(brief.typography.vibe, [])
    return (
        f"kind: {brief.kind}\n"
        f"canvas: {brief.canvas.width}x{brief.canvas.height}\n"
        f"language: {brief.language}\n"
        f"subject: {brief.subject_description or 'NONE — this is a text-only design'}\n"
        + (f"further subjects (one per extra subject slot, in order): "
           f"{brief.subjects}\n" if brief.subjects else "")
        + (f"contact details (TRANSCRIBE VERBATIM): "
           f"{copy.contact.model_dump(exclude_none=True)}\n"
           if copy.contact.has_any() else "")
        +
        f"mood: {', '.join(brief.mood) or 'clean'}\n"
        f"density: {brief.layout_hints.density}\n"
        f"subject placement hint: {brief.layout_hints.subject_placement or 'none'}\n"
        f"typography vibe: {brief.typography.vibe}\n"
        "allowed font pairings (display face + supporting face): "
        + "; ".join(f"{d} + {t}" + (f" + {c} (script)" if c else "")
                    for d, t, c in pairs) + "\n"
        f"colour direction: {brief.color_direction.mode}"
        + (f" palette={brief.color_direction.palette}"
           if brief.color_direction.palette else "")
        + f"\nsupplied copy (USE VERBATIM): {supplied or 'none — write it yourself'}"
    )


async def compose(brief: DesignBrief, candidates: list[TemplateSkeleton],
                  direction: ArtDirection | None = None) -> tuple[ComposerOutput, int]:
    """Return (composer output, cost_cents). Never raises: §1.3 says never fail here."""
    if not candidates:
        raise ValueError("compose() requires at least one candidate skeleton")

    user = (f"BRIEF\n{_render_brief(brief)}\n\nCANDIDATE SKELETONS"
            f"\n{_render_candidates(candidates)}")
    try:
        result = await get_llm().complete_json(
            system=COMPOSER_SYSTEM, user=user, schema=ComposerOutput, temperature=0.4,
        )
        output = _sanitise_output(result.parsed, brief, candidates, direction)
        return output, result.cost_cents
    except AdapterError as exc:
        log.warning("compose.layout.llm_failed", error=str(exc))

    log.info("compose.layout.mechanical_fallback", template_id=candidates[0].id)
    return mechanical_compose(brief, candidates[0], direction), 0


# --------------------------------------------------------------------------------------
# Fallback composer (§1.3 "Never fail the request at this stage")
# --------------------------------------------------------------------------------------


def _palette_for(brief: DesignBrief) -> list[str]:
    if brief.color_direction.palette:
        # `ComposerOutput` requires at least three colours; a user who named two still
        # has to end up with a usable palette rather than a validation error.
        return complete_palette(list(brief.color_direction.palette),
                                moods=brief.mood)[:5]
    for mood in brief.mood:
        if mood in DEFAULT_PALETTES:
            return list(DEFAULT_PALETTES[mood])
    return list(DEFAULT_PALETTES["clean"])


def _fonts_for(brief: DesignBrief) -> tuple[str, str, str | None]:
    """(display face, supporting face, script accent). A family hint replaces the display
    face only — the brief is naming the voice of the headline, not the body copy."""
    display, text, script = _pairing_for(brief.typography.vibe)
    hint = brief.typography.family_hint
    if hint:
        for family in get_registry().families:
            if family.lower() == hint.lower():
                return family, text, script
    return display, text, script


_TRAILING_INDEX_RE = re.compile(r"(\d+)$")


def _slot_index(slot_id: str) -> int:
    """0-based position of a repeated slot, read off its id (`feature_2` -> 1).

    Repeated slots are how a skeleton holds a list, and the only thing distinguishing
    one from the next is its id. Ids are authored 1-based because that is how a designer
    numbers them.
    """
    match = _TRAILING_INDEX_RE.search(slot_id)
    if not match:
        return 0
    return max(0, int(match.group(1)) - 1)



# Which field a named contact slot wants. A layout that puts a handset beside one line
# and a globe beside another is making a promise about what each line holds, and the
# slot id is where the author states it — without this, every contact slot in a design
# resolves to the same value and the globe sits beside the phone number.
_CONTACT_BY_NAME: tuple[tuple[tuple[str, ...], str], ...] = (
    (("phone", "call", "tel", "mobile"), "phone"),
    (("web", "site", "url", "domain"), "website"),
    (("mail", "email"), "email"),
    (("address", "map", "pin", "location", "visit"), "address"),
    (("social", "handle", "insta", "follow"), "social"),
)


def _contact_for_slot(slot: Slot, contact: Contact) -> str | None:
    """The part of the contact block this slot holds.

    Preference order: what the slot's id asks for, then the whole strip if it fits, then
    whatever single field does. A slot that names a field it does not have falls back to
    the general rule rather than rendering empty — a design missing its website still
    wants a phone number under the globe.
    """
    name = slot.slot_id.lower()
    limit = slot.text.max_chars if slot.text else 80
    for needles, field in _CONTACT_BY_NAME:
        if any(needle in name for needle in needles):
            value = getattr(contact, field)
            if value and value.strip():
                return value
            break

    # Unnamed: how much room the slot has decides. A narrow slot beside a CTA holds the
    # phone number, a full-width footer holds everything. Both beat truncating mid-URL.
    line = contact.strip_line()
    if line and len(line) <= limit:
        return line
    for candidate in (contact.phone, contact.website, contact.email,
                      contact.social, contact.address):
        if candidate and len(candidate) <= limit:
            return candidate
    return line


def copy_for_slot(slot: Slot, brief: DesignBrief) -> str | None:
    """The brief's copy for one slot, by role. Never invents prose.

    This is the single mapping from brief fields to layer roles. It is used both to fill
    slots the composer wrote nothing for and to decide whether an optional slot has
    earned its place, and those two answers have to agree — when they drift, a slot is
    judged worth keeping and then materialised empty.
    """
    copy = brief.copy_text
    role = slot.role
    if role == "feature":
        # Two distinct lists share this role: `checklist()` rows ("feature_N") pull full
        # bullet lines, `chip_row()` rows ("tag_N") pull the short keyword chips. The id
        # prefix is the only thing that tells them apart once both are just text slots.
        index = _slot_index(slot.slot_id)
        pool = copy.tags if slot.slot_id.startswith("tag_") else copy.features
        return pool[index] if index < len(pool) else None
    if role == "contact":
        return _contact_for_slot(slot, copy.contact)

    value = {
        "headline": copy.headline, "subhead": copy.subhead, "body": copy.body,
        "cta": copy.cta, "caption": copy.caption, "offer": copy.offer,
        "price": copy.price, "badge": copy.badge, "terms": copy.terms,
        "event": copy.event_details, "logo": copy.brand_name,
    }.get(role)

    # Fallbacks between neighbouring roles. A skeleton built around an offer still has to
    # say something when the brief carried the discount in the headline instead, and an
    # empty slot in the middle of a promotional layout is a hole, not restraint.
    if value is None:
        if role == "offer":
            value = copy.price or copy.badge
        elif role == "badge":
            value = copy.price if copy.price and len(copy.price) <= 12 else None
        elif role == "price":
            value = copy.offer
    return value


def _fallback_copy_for(slot: Slot, brief: DesignBrief) -> str | None:
    """`copy_for_slot`, plus the one slot that may never ship empty."""
    value = copy_for_slot(slot, brief)
    if value is None and slot.role == "headline":
        # A headline slot is required; derive one rather than shipping an empty frame.
        # The offer first: on a promotional brief the discount IS the headline, and
        # falling straight through to the subject description gives a sale poster whose
        # biggest words are a description of a photograph.
        copy = brief.copy_text
        value = (copy.offer or copy.badge or brief.subject_description
                 or brief.kind).strip()
        value = value[:1].upper() + value[1:] if value else "Untitled"
    if value is None:
        return None
    return fit_to_slot(value, slot)


# Roles whose content is a FACT, not prose. Shortening prose loses nuance; shortening one
# of these changes what it says. "+91 98765 4…" is not a phone number, "BIKE SHED M…" is
# not a business, "FLAT 50…" is not an offer and "23 Septem…" is not a date — each ships
# a design that looks finished and cannot be acted on, which is the failure mode the
# contact rule already existed to prevent. The rest of them were missing it.
_VERBATIM_ROLES = frozenset({"contact", "logo", "price", "badge", "event", "terms"})


def fit_to_slot(value: str, slot: Slot) -> str | None:
    """`value` cut to the slot's budget, or None when cutting it would make it wrong."""
    limit = slot.text.max_chars if slot.text else 80
    if len(value) <= limit:
        return value
    if slot.role in _VERBATIM_ROLES:
        log.info("compose.layout.verbatim_too_long", slot_id=slot.slot_id,
                 role=slot.role, length=len(value), limit=limit)
        return None
    # Prose may be shortened, but never mid-word: "BIKE SHED M…" reads as a rendering
    # fault, "BIKE SHED…" reads as an abbreviation.
    head = value[:max(1, limit - 1)].rstrip()
    spaced = head.rsplit(" ", 1)[0] if " " in head else head
    return (spaced if len(spaced) >= limit * 0.6 else head).rstrip(" ,;:-") + "…"


# The order a reader's eye assigns importance, so that when the same words land in two
# slots the copy stays in the more prominent one and is dropped from the lesser.
_ROLE_PROMINENCE = ["headline", "offer", "price", "badge", "subhead", "cta", "event",
                    "body", "feature", "caption", "contact", "terms"]


def _drop_duplicate_copy(entries: list[ComposerSlot],
                         slots_by_id: dict[str, Slot]) -> list[ComposerSlot]:
    """Stop the same sentence being set twice in one design.

    Both composers produce this. The LLM writes the discount into the headline and then
    dutifully fills the offer slot with it again; the mechanical path derives a headline
    from the offer when the brief carried no headline, and the offer slot still holds the
    original. Either way the design ships saying "FLAT 50% OFF" twice, which reads as a
    bug — and it is invisible to every other check, because both slots are correctly
    filled with correct copy.

    The more prominent slot keeps the words. A required slot always keeps them: it has no
    other content to fall back on and may not ship empty.
    """
    ordered = sorted(
        entries,
        key=lambda e: _ROLE_PROMINENCE.index(slots_by_id[e.slot_id].role)
        if e.slot_id in slots_by_id
        and slots_by_id[e.slot_id].role in _ROLE_PROMINENCE else len(_ROLE_PROMINENCE))

    seen: set[str] = set()
    dropped: set[str] = set()
    for entry in ordered:
        slot = slots_by_id.get(entry.slot_id)
        if slot is None or not entry.include or not (entry.text and entry.text.content):
            continue
        key = " ".join(entry.text.content.lower().split()).strip(" .!:—-")
        if len(key) < 3:
            continue
        if key in seen and not slot.required:
            log.info("compose.layout.dropped_duplicate_copy", slot_id=entry.slot_id,
                     role=slot.role)
            dropped.add(entry.slot_id)
            continue
        seen.add(key)

    return [e for e in entries if e.slot_id not in dropped]



def normalise_case(content: str, slot: Slot, *, undo_baked_transform: bool = False) -> str:
    """Shouting copy, put back into the case the slot actually wants.

    A slot set in a SCRIPT face never takes all caps, whoever produced them: script
    capitals are unjoined display swashes, so a line set in caps renders as disconnected
    letters with holes punched between them — "RIDE IN. DINE OUT." came back as
    "R IDE IN. D INE OUT." — and title case sets 20 percent narrower besides, so it stops
    overrunning its box as well.

    `undo_baked_transform` additionally un-shouts copy bound for a slot that will
    uppercase it anyway (§1.3: case is applied at render time, never baked in, or
    non-Latin text breaks and the layer is awkward to edit). That one is aimed at the
    model, which shouts unprompted; it is off for `mechanical_compose`, whose input comes
    from the deterministic extractor that uppercases a badge on purpose.
    """
    if slot.text is None or not content.isupper() or not any(c.isalpha() for c in content):
        return content
    if undo_baked_transform and slot.text.transform == "uppercase":
        return content.capitalize()
    if slot.text.face == "script":
        return " ".join(word[:1].upper() + word[1:].lower() for word in content.split())
    return content


def mechanical_compose(brief: DesignBrief, skeleton: TemplateSkeleton,
                       direction: ArtDirection | None = None) -> ComposerOutput:
    palette = _palette_for(brief)
    display_family, text_family, script_family = _fonts_for(brief)
    slots: list[ComposerSlot] = []

    for slot in skeleton.slots:
        entry = ComposerSlot(slotId=slot.slot_id, include=True)
        if slot.layer_type == "text":
            content = _fallback_copy_for(slot, brief)
            if content is None:
                if slot.required:
                    continue
                entry.include = False
            else:
                entry.text = SlotText(content=normalise_case(content, slot))
        elif slot.layer_type == "image" and slot.image:
            prompt, negative = build_image_prompt(slot, brief, palette, direction)
            entry.image_prompt = SlotImagePrompt(prompt=prompt, negativePrompt=negative)
        slots.append(entry)

    slots = _drop_duplicate_copy(slots, {s.slot_id: s for s in skeleton.slots})

    registry = get_registry()
    display_weights = registry.weights_for(display_family) or [400, 700]
    text_weights = registry.weights_for(text_family) or [400, 700]
    return ComposerOutput(
        templateId=skeleton.id,
        reason="mechanical fallback: highest-ranked candidate, copy mapped by slot role",
        palette=palette,
        font={"family": display_family,
              "textFamily": text_family,
              "scriptFamily": script_family,
              "headlineWeight": max(display_weights),
              "bodyWeight": min(w for w in text_weights if w >= 400)},
        slots=slots,
    )


# Mood words are written for a *designer* — they name a tone. Handed to an image model
# they name a stock genre instead, and the model answers with that genre's iconography.
# "festive" is the worst offender: it returns snowflakes, baubles and fir, so a Diwali
# greeting comes back decorated for Christmas. These expansions say what the mood should
# look like rather than what it is called, which is the only way to get the tone without
# the imagery that happens to dominate the training data for the word.
_MOOD_FOR_IMAGE: dict[str, str] = {
    "festive": "ornamental, celebratory, warm glowing light",
    "festival": "ornamental, celebratory, warm glowing light",
    "celebration": "ornamental, celebratory, warm glowing light",
    "greeting": "ornamental, warm, generous",
    "premium": "refined, restrained, softly lit",
    "luxury": "refined, restrained, softly lit",
    "elegant": "refined, restrained, softly lit",
    "bold": "high-contrast, graphic, strongly lit",
    "playful": "bright, informal, softly rounded forms",
    "retro": "period-correct mid-century styling, faded film colour",
    "tech": "cool, precise, clean specular highlights",
    "natural": "organic, matte, daylight",
    "minimal": "spare, uncluttered, even light",
    "dark": "low-key, deep shadow, single light source",
    "warm": "warm-toned, soft golden light",
    "clean": "clean, uncluttered, even light",
}


def mood_for_image(moods: list[str]) -> str:
    """Mood words rewritten as visual direction, for substitution into an image prompt."""
    seen: list[str] = []
    for mood in moods:
        expanded = _MOOD_FOR_IMAGE.get(mood.strip().lower(), mood.strip())
        for part in expanded.split(", "):
            if part and part not in seen:
                seen.append(part)
    return ", ".join(seen) or "clean, uncluttered, even light"



# Ground-plane words. A transparent slot that mentions any of these comes back as a
# product photographed on something, and the alpha channel then traces that something —
# a tray, a plinth, a table edge — so the "cutout" is a hard-edged rectangle of wood.
_GROUND_PLANE_RE = re.compile(
    r"\b(?:background|backdrop|floor|ground|surface|table|tabletop|desk|counter|tray|"
    r"platter|plinth|pedestal|podium|stand|shelf|mat|cloth|fabric|velvet|marble|wood|"
    r"wooden|shadow|reflection|placed on|resting on|sitting on|arranged on|laid on|"
    r"set on|on a)\b", re.IGNORECASE)

# Only the words that hijack the *genre* are rewritten inside a prose prompt. Most mood
# words ("clean", "warm", "bold") are ordinary adjectives an image model handles fine,
# and substituting those produces mangled grammar for no gain. These few do not name a
# tone to an image model, they name Christmas — so a Diwali greeting, a Ramadan post and
# an Onam sale all come back with snowflakes, baubles and fir. A user who actually asks
# for Christmas says "Christmas", and that word is deliberately left alone.
_GENRE_HIJACKING: dict[str, str] = {
    "festive": "ornamental and celebratory",
    "festival": "ornamental and celebratory",
    "holiday": "ornamental and celebratory",
    "seasonal": "ornamental and celebratory",
}

_MOOD_WORD_RE = re.compile(
    r"\b(" + "|".join(sorted(_GENRE_HIJACKING, key=len, reverse=True)) + r")\b",
    re.IGNORECASE)


def scrub_image_prompt(prompt: str, *, transparent: bool) -> str:
    """Repair an LLM-written image prompt in the two ways it reliably goes wrong.

    §1.3 tells the composer both of these rules and the composer breaks both of them, so
    they are enforced here rather than trusted. Neither can be left to the negative
    prompt: a negative cannot undo a positive instruction to photograph something on a
    surface, and it cannot stop a mood word from selecting a genre.

    1. Genre-hijacking mood words are rewritten as visual direction. "subtle festive
       texture" returns snowflakes and fir, which is how a Diwali greeting arrives
       decorated for Christmas.
    2. For a transparent slot, clauses naming a ground plane are dropped entirely.
    """
    prompt = _MOOD_WORD_RE.sub(
        lambda m: _GENRE_HIJACKING.get(m.group(1).lower(), m.group(1)), prompt)

    if transparent:
        clauses = [c.strip() for c in prompt.split(",")]
        # The first clause IS the subject; dropping it because it happens to name a
        # surface leaves a prompt describing lighting and nothing to light. A brief that
        # says "a manicure set on a marble tray" has to become "a manicure set", not
        # "side profile view, crisp detail". Later clauses are the template's own
        # scene-setting and are dropped whole, as before.
        head = _trim_ground_plane(clauses[0]) if clauses else ""
        tail = [c for c in clauses[1:] if c and not _GROUND_PLANE_RE.search(c)]
        kept = ([head] if head else []) + tail
        prompt = ", ".join(kept) if kept else (clauses[0] if clauses else prompt)
        if "transparent background" not in prompt.lower():
            prompt = f"{prompt}, isolated on a plain transparent background"

    return " ".join(prompt.split())

# Where a ground plane is introduced *inside* the subject clause it arrives as a
# trailing prepositional phrase — "on dark velvet", "arranged on a slate board". Cutting
# at the preposition keeps the object and loses the furniture.
_GROUND_PHRASE_RE = re.compile(
    r"\s+(?:on|upon|atop|against|over)\s+(?:a|an|the)?\s*\S+.*$", re.IGNORECASE)

# Below this a cut has eaten the subject rather than its surroundings, and the whole
# clause is better than a fragment.
_MIN_SUBJECT_WORDS = 2


def _trim_ground_plane(clause: str) -> str:
    """Drop a trailing 'on <surface>' phrase from the subject clause, keeping the subject."""
    if not _GROUND_PLANE_RE.search(clause):
        return clause
    trimmed = _GROUND_PHRASE_RE.sub("", clause).strip(" ,")
    if len(trimmed.split()) >= _MIN_SUBJECT_WORDS:
        return trimmed
    # Nothing safe to cut: the surface word is load-bearing ("a marble sculpture").
    return clause


# Collapses the gaps a dropped placeholder leaves behind: an empty {{lighting}} turns
# "a marble top, , empty scene" into something an image model reads as a typo.
_EMPTY_CLAUSE_RE = re.compile(r"(?:,\s*)+,")


def _substitutions(brief: DesignBrief, palette: list[str], subject: str | None,
                   direction: ArtDirection | None) -> dict[str, str]:
    """What each placeholder resolves to.

    Without a direction these fall back to what the templates used to say inline, so the
    pipeline still produces a sane prompt when `art.direct` is unavailable — one generic
    backdrop is worse than a directed one and far better than a blank.
    """
    mood = mood_for_image(brief.mood)
    colours = ", ".join(palette[:3])
    if direction is None:
        return {
            "{{subjectDescription}}": subject or "abstract form",
            "{{scene}}": f"{mood} backdrop",
            "{{texture}}": f"subtle {mood} texture",
            "{{lighting}}": "soft directional light",
            "{{treatment}}": f"{mood}, crisp detail",
            "{{prop}}": f"a small decorative prop related to {subject or 'the subject'}",
            "{{mood}}": mood,
            "{{palette}}": colours,
        }
    return {
        "{{subjectDescription}}": subject or "abstract form",
        "{{scene}}": direction.scene,
        "{{texture}}": direction.texture,
        "{{lighting}}": direction.lighting,
        "{{treatment}}": direction.subject_treatment,
        "{{prop}}": direction.prop or f"a small prop related to {subject or 'the subject'}",
        "{{mood}}": mood,
        "{{palette}}": colours,
    }


def build_image_prompt(slot: Slot, brief: DesignBrief, palette: list[str],
                       direction: ArtDirection | None = None) -> tuple[str, str]:
    """Fill a slot's promptTemplate and attach the mandatory negative blocks (§1.3).

    The template supplies composition — which region stays empty, which angle, whether
    this is a cutout — and `direction` supplies subject matter. Neither is useful alone:
    a direction with no template forgets to leave room for the headline, and a template
    with no direction is the generic studio sweep every design used to be shot on.
    """
    spec = slot.image
    template = spec.prompt_template if spec else ""
    # A skeleton's second and third subject slots ask for the brief's second and third
    # subjects. Where the brief names only one, `subject_at` cycles back to it and the
    # slot's own prompt template supplies a different angle, so a trio is three views of
    # one product rather than three identical cutouts.
    subject = brief.subject_at(spec.subject_index) if spec else brief.subject_description

    prompt = template
    for placeholder, value in _substitutions(brief, palette, subject, direction).items():
        prompt = prompt.replace(placeholder, value.strip())
    prompt = _EMPTY_CLAUSE_RE.sub(",", prompt).strip(" ,")

    transparent = bool(spec and spec.transparent)
    prompt = scrub_image_prompt(prompt, transparent=transparent)
    negative = NEGATIVE_TEXT_BLOCK
    if transparent:
        negative = f"{negative}, {NEGATIVE_TRANSPARENT_BLOCK}"
    return prompt, negative


# --------------------------------------------------------------------------------------
# Sanitising LLM output
# --------------------------------------------------------------------------------------


def _sanitise_output(output: ComposerOutput, brief: DesignBrief,
                     candidates: list[TemplateSkeleton],
                     direction: ArtDirection | None = None) -> ComposerOutput:
    """Repair anything the model got wrong rather than failing the request (§1.3)."""
    valid_ids = {s.id for s in candidates}
    if output.template_id not in valid_ids:
        log.info("compose.layout.unknown_template", got=output.template_id)
        output.template_id = candidates[0].id
    skeleton = next(s for s in candidates if s.id == output.template_id)

    variant_ids = {v.id for v in skeleton.variants}
    if output.variant_id and output.variant_id not in variant_ids:
        output.variant_id = None

    known_slots = {s.slot_id: s for s in skeleton.slots}
    cleaned: list[ComposerSlot] = []
    seen: set[str] = set()
    for entry in output.slots:
        slot = known_slots.get(entry.slot_id)
        if slot is None:
            # §1.3: "Composer picks a slotId that does not exist -> ignore that entry,
            # log it as an eval signal."
            log.info("compose.layout.unknown_slot", slot_id=entry.slot_id,
                     template_id=skeleton.id)
            continue
        if entry.slot_id in seen:
            continue
        seen.add(entry.slot_id)

        if slot.required:
            entry.include = True

        if entry.text is not None and slot.text is not None:
            content = entry.text.content.strip()
            if len(content) > slot.text.max_chars:
                log.info("compose.layout.copy_truncated", slot_id=slot.slot_id,
                         length=len(content), limit=slot.text.max_chars)
                trimmed = fit_to_slot(content, slot)
                if trimmed is None:
                    # A fact that will not fit is dropped, not mangled.
                    entry.include = False
                    continue
                content = trimmed
            content = normalise_case(content, slot, undo_baked_transform=True)
            entry.text = SlotText(content=content)

        if entry.image_prompt is not None and slot.image is not None:
            prompt = scrub_image_prompt(entry.image_prompt.prompt,
                                        transparent=slot.image.transparent)
            negative = entry.image_prompt.negative_prompt or ""
            # The negative-text block is mandatory; append it if the model dropped it.
            if "text" not in negative.lower():
                negative = f"{negative}, {NEGATIVE_TEXT_BLOCK}".strip(", ")
            if slot.image.transparent and "background" not in negative.lower():
                negative = f"{negative}, {NEGATIVE_TRANSPARENT_BLOCK}"
            entry.image_prompt.prompt = prompt
            entry.image_prompt.negative_prompt = negative
        cleaned.append(entry)

    # Any slot the model forgot entirely still has to be materialised if the skeleton
    # requires it — or if the brief plainly has something to put in it. The second half
    # matters more than the first: the composer drops optional slots freely, and a
    # skeleton designed for headline + subhead + CTA + product that ships with only the
    # headline is not a sparser version of that design, it is a third of it over an
    # expanse of flat colour.
    for slot_id, slot in known_slots.items():
        if slot_id in seen:
            continue
        wanted = slot.required or _slot_is_earned(slot, brief)
        if not wanted:
            continue
        entry = ComposerSlot(slotId=slot_id, include=True)
        if slot.layer_type == "text":
            content = _fallback_copy_for(slot, brief)
            if not content:
                continue
            entry.text = SlotText(content=content)
        elif slot.layer_type == "image":
            prompt, negative = build_image_prompt(slot, brief, output.palette,
                                                  direction)
            entry.image_prompt = SlotImagePrompt(prompt=prompt,
                                                 negativePrompt=negative)
        cleaned.append(entry)
    output.slots = _drop_duplicate_copy(cleaned, known_slots)

    if brief.color_direction.mode == "brand" and brief.color_direction.palette:
        # A brand palette is used unchanged, including its order: the brand decided which
        # colour is the ground.
        output.palette = list(brief.color_direction.palette)[:5]
    else:
        if brief.color_direction.palette:
            # The user named colours. They are the palette; the composer's contribution
            # is whatever it added beyond them.
            named = list(brief.color_direction.palette)
            extra = [c for c in output.palette if c not in named]
            output.palette = (named + extra)[:5]
        # Colour words the model emitted instead of hex ("gold", "navy") resolve through
        # a designer's vocabulary rather than the CSS keyword table.
        resolved: list[str] = []
        for entry_color in output.palette:
            word = resolve_palette_words([entry_color])
            resolved.extend(word or [])
        output.palette = resolved
        output.palette = [c for c in output.palette if len(c) in (7, 9)] or _palette_for(brief)
        while len(output.palette) < 3:
            output.palette.append("#FFFFFF" if len(output.palette) % 2 else "#111111")
        # Ground first, accent last — the order `expand()` reads, which is never the
        # order colours are thought of in.
        output.palette = complete_palette(
            order_palette(dedupe_palette(output.palette), moods=brief.mood),
            moods=brief.mood)
    output.palette = [c if c.startswith("#") else f"#{c}" for c in output.palette]
    output.palette = [c for c in output.palette if len(c) in (7, 9)] or _palette_for(brief)
    while len(output.palette) < 3:
        output.palette.append("#FFFFFF" if len(output.palette) % 2 else "#111111")

    available = set(get_registry().families)
    default_display, default_text, default_script = _fonts_for(brief)
    if output.font.family not in available:
        log.info("compose.layout.font_not_available", got=output.font.family)
        output.font.family = default_display
    if output.font.text_family not in available:
        if output.font.text_family:
            log.info("compose.layout.text_font_not_available",
                     got=output.font.text_family)
        # Pair the supporting face to whatever display face survived, so a repaired
        # display face does not leave a mismatched partner behind.
        allowed = {d: t for d, t, _ in font_pairings().get(brief.typography.vibe, [])}
        output.font.text_family = allowed.get(output.font.family, default_text)
    if output.font.script_family not in available:
        scripts = {d: c for d, _, c in font_pairings().get(brief.typography.vibe, [])}
        output.font.script_family = scripts.get(output.font.family, default_script)
    return output


def _slot_is_earned(slot: Slot, brief: DesignBrief) -> bool:
    """Should an optional slot the composer never mentioned be materialised anyway?

    Yes when the brief already contains what it holds. A subhead slot is earned by the
    brief having a subhead, a contact strip by the brief carrying a phone number, the
    third feature line by there being a third feature; a second or third subject slot is
    earned by the brief asking for a range rather than one item; decoration is earned
    unless the design is deliberately spare, because ornament is procedural and free and
    a skeleton author placed it on purpose.
    """
    if slot.layer_type == "text":
        value = copy_for_slot(slot, brief)
        return bool(value and value.strip())
    if slot.layer_type == "shape":
        if slot.pairs_with:
            # Earned by its partner, never by the density dial: an icon is part of the
            # line it sits beside, not decoration the design can afford or skip.
            return True
        if slot.role == "decoration":
            return brief.layout_hints.density != "sparse"
        # A CTA pill, a contact bar or a scrim is earned by whatever sits on top of it.
        return bool(_text_for_role(slot.role, brief))
    if slot.layer_type == "image":
        if slot.role in ("background", "subject"):
            return bool(brief.subject_description) or slot.role == "background"
        if slot.role == "object":
            return bool(brief.subject_description)
    return False


def _text_for_role(role: str, brief: DesignBrief) -> str | None:
    """Is there copy for this role anywhere in the brief?

    Asked of a shape rather than a text slot, so there is no slot to size against — a
    panel behind a contact strip only needs to know the strip exists.
    """
    copy = brief.copy_text
    if role == "feature":
        return copy.features[0] if copy.features else None
    if role == "contact":
        return copy.contact.strip_line()
    return {
        "headline": copy.headline, "subhead": copy.subhead, "body": copy.body,
        "cta": copy.cta, "caption": copy.caption, "offer": copy.offer,
        "price": copy.price, "badge": copy.badge, "terms": copy.terms,
        "event": copy.event_details, "logo": copy.brand_name,
    }.get(role)


# --------------------------------------------------------------------------------------
# expand() — deterministic. §1.3: "Then, in deterministic code, expand ComposerOutput +
# skeleton into a DesignDoc."
# --------------------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def apply_variant(skeleton: TemplateSkeleton, variant_id: str | None) -> list[Slot]:
    """Merge a variant's sparse per-slot overrides over the base slots."""
    slots = [s.model_copy(deep=True) for s in skeleton.slots]
    if not variant_id:
        return slots
    variant = next((v for v in skeleton.variants if v.id == variant_id), None)
    if variant is None:
        return slots
    by_id = {s.slot_id: s for s in slots}
    for slot_id, patch in variant.patch.items():
        slot = by_id.get(slot_id)
        if slot is None:
            continue
        merged = slot.model_dump(by_alias=True, exclude_none=True)
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        by_id[slot_id] = Slot.model_validate(merged)
    return [by_id[s.slot_id] for s in slots]


def _resolve_palette_roles(palette: list[str]) -> dict[str, str]:
    """Map the composer's flat palette onto the named roles skeletons refer to."""
    primary = palette[0]
    rest = palette[1:] or [primary]
    # The accent is the most saturated colour that is not the primary.
    accent = max(rest, key=saturation) if rest else primary
    accent = ensure_distinct(accent, primary)
    neutral = min(palette, key=lambda c: saturation(c))
    return {
        "primary": primary,
        "accent": accent,
        "neutral": neutral,
        # Harmony-aware, not contrast-maximising: on a saturated ground the highest
        # contrast ratio is frequently a colour that clashes with it.
        "on-primary": harmonious_on(primary, palette, minimum=4.5),
        "on-accent": harmonious_on(accent, palette, minimum=4.5, allow_chroma=True),
    }


def _seed_for(doc_id: str, slot_id: str, prompt: str) -> int:
    """Deterministic per-slot seed, so regenerating a document reproduces it (INV-2)."""
    digest = hashlib.sha256(f"{doc_id}|{slot_id}|{prompt}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def expand(skeleton: TemplateSkeleton, output: ComposerOutput, brief: DesignBrief,
           *, doc_id: str, request_id: str = "", title: str | None = None,
           direction: ArtDirection | None = None) -> DesignDoc:
    """Skeleton + composer output -> a complete DesignDoc with empty asset slots.

    Steps follow §1.3 exactly: denormalise, nudge, clamp, snap, materialise in zIndex
    order, attach generation stubs, copy constraints, validate.
    """
    width, height = brief.canvas.width, brief.canvas.height
    baseline = max(1, skeleton.grid_baseline)
    palette = list(output.palette)
    roles = _resolve_palette_roles(palette)
    slots = apply_variant(skeleton, output.variant_id)
    entries = {e.slot_id: e for e in output.slots}

    def snap(value: float) -> float:
        return round(value / baseline) * baseline

    included = _included_slots(slots, entries)
    motifs = motif_assignment(included, direction)

    layers: list[Layer] = []
    for slot in sorted(included, key=lambda s: s.z_index):
        entry = entries.get(slot.slot_id)

        frame = _build_frame(slot, entry, width, height, baseline, snap)
        common = {
            "id": f"l_{slot.slot_id}",
            "name": slot.slot_id.replace("_", " ").title(),
            "role": slot.role,
            "frame": frame,
            "opacity": slot.opacity,
            "constraints": Constraints.model_validate(
                slot.constraints.model_dump(by_alias=True)
                | ({"pairsWith": f"l_{slot.pairs_with}"} if slot.pairs_with else {})),
            "effects": _denormalise_effects(slot.effects, height),
        }

        if slot.layer_type == "text":
            layer = _build_text_layer(slot, entry, common, output, roles, height)
        elif slot.layer_type == "image":
            layer = _build_image_layer(slot, entry, common, brief, palette, roles,
                                       doc_id, direction)
        elif slot.layer_type == "shape":
            layer = _build_shape_layer(slot, common, roles, doc_id=doc_id,
                                       canvas_height=height,
                                       motif=motifs.get(slot.slot_id),
                                       density=_motif_density(slot, direction))
        else:
            continue
        if layer is not None:
            layers.append(layer)

    # Every family used by a text layer must be declared, or validate_doc rejects the
    # document. `url` is deliberately omitted: faces are served per weight and style from
    # /v1/fonts/{fontKey}.ttf, which a single family-level URL cannot address.
    families = {layer.font_family for layer in layers if layer.type == "text"}
    registry = get_registry()
    weights = registry.weights_for(output.font.family) or [400, 700]
    fonts = [FontRef(family=family, weights=registry.weights_for(family) or weights,
                     source="hosted")
             for family in sorted(families)] or [
        FontRef(family=output.font.family, weights=weights, source="hosted")]

    doc = DesignDoc(
        id=doc_id,
        title=title or _title_from(output, brief),
        canvas=Canvas(width=width, height=height, background=roles["primary"],
                      safeMargin=round(min(width, height) * 0.0667 / baseline) * baseline,
                      dpi=300 if brief.kind in ("poster", "flyer") else 72),
        layers=layers,
        palette=palette,
        fonts=fonts,
        provenance=GeneratedProvenance(
            brief=brief.model_dump(by_alias=True, exclude_none=True),
            artDirection=(direction.model_dump(by_alias=True, exclude_none=True)
                          if direction else None),
            templateId=skeleton.id + (f"#{output.variant_id}" if output.variant_id else ""),
            requestId=request_id,
        ),
        createdAt=_now(),
        updatedAt=_now(),
    )
    return doc


def _included_slots(slots: list[Slot],
                    entries: dict[str, ComposerSlot]) -> list[Slot]:
    """Decide which slots survive, then drop orphaned paired backgrounds.

    A CTA pill and its label are one visual unit. If the label is dropped — because the
    brief carried no CTA copy — the pill must go too, or the design ships an empty
    coloured lozenge.
    """
    kept: list[Slot] = []
    for slot in slots:
        entry = entries.get(slot.slot_id)
        if slot.required:
            kept.append(slot)
            continue
        if entry is not None and not entry.include:
            continue
        if slot.layer_type == "text":
            # Text needs words. Silence from the composer means no copy was written.
            if not (entry and entry.text and entry.text.content.strip()):
                continue
        elif entry is None and slot.layer_type != "shape":
            # An image slot with no entry has no prompt, so it cannot be generated.
            # `_sanitise_output` has already written prompts for the optional image slots
            # the brief earns, so anything still silent here is one it did not.
            continue
        # Silence about a shape is not a decision to drop it. The skeleton author placed
        # that garland, that scrim, that divider; the composer omitting the slot from its
        # reply means it had nothing to say about it, and reading that as "delete" is
        # what strips the ornament out of designs that were built around it. Shapes are
        # procedural vector drawn from the palette, so keeping them costs nothing.
        kept.append(slot)

    text_roles = {s.role for s in kept if s.layer_type == "text"}
    all_text_roles = {s.role for s in slots if s.layer_type == "text"}
    orphaned = all_text_roles - text_roles
    kept = [s for s in kept
            if not (s.layer_type == "shape" and s.role in orphaned and not s.required)]

    # Then the per-slot pairings. Role-level orphaning cannot see these: six checklist
    # rows share the role `feature`, so a tick beside the fourth line survives on the
    # strength of the first line existing and renders as a bullet pointing at nothing.
    # Iterated to a fixed point so a chain (icon -> line -> panel) unwinds in one pass.
    kept_ids = {s.slot_id for s in kept}
    while True:
        survivors = [s for s in kept
                     if s.required or not s.pairs_with or s.pairs_with in kept_ids]
        if len(survivors) == len(kept):
            return survivors
        kept = survivors
        kept_ids = {s.slot_id for s in kept}


def _title_from(output: ComposerOutput, brief: DesignBrief) -> str:
    headline = next((e.text.content for e in output.slots
                     if e.text and e.text.content), None)
    base = headline or brief.subject_description or brief.kind
    base = " ".join(base.split())
    return (base[:57] + "…") if len(base) > 58 else base


def _build_frame(slot: Slot, entry: ComposerSlot | None, width: int, height: int,
                 baseline: int, snap) -> Frame:
    frame_n = slot.frame_n
    x, y = frame_n.x, frame_n.y
    w, h = frame_n.w, frame_n.h

    if entry is not None and entry.frame_nudge is not None:
        nudge = entry.frame_nudge
        # §1.3 limits nudges to +/-8%; the schema enforces it, this clamps defensively.
        x += max(-0.08, min(0.08, nudge.dx))
        y += max(-0.08, min(0.08, nudge.dy))
        w += max(-0.08, min(0.08, nudge.dw))
        h += max(-0.08, min(0.08, nudge.dh))

    px, py = x * width, y * height
    pw, ph = max(1.0, w * width), max(1.0, h * height)

    # A frame the skeleton authored partly off-canvas is asking to bleed: a colour field
    # anchored past the corner, a subject running off the bottom edge. Clamping those
    # back on-canvas does not just lose the effect, it relocates the slot — a blob
    # authored off the left edge slides right and lands under the copy it was placed to
    # avoid. `validate_skeleton` already caps authored bleed at MAX_BLEED, so anything
    # negative here is a decision rather than a typo.
    authored_bleed = (frame_n.x < 0 or frame_n.y < 0
                      or frame_n.x + frame_n.w > 1 or frame_n.y + frame_n.h > 1)
    full_bleed = (slot.role in ("background", "overlay", "decoration")
                  or frame_n.w >= 0.999 or authored_bleed)
    if not full_bleed:
        # Keep the slot on the canvas; deliberate bleed is expressed by the skeleton.
        pw = min(pw, width)
        ph = min(ph, height)
        px = max(0.0, min(px, width - pw))
        py = max(0.0, min(py, height - ph))
        px, py, pw, ph = snap(px), snap(py), max(baseline, snap(pw)), max(baseline, snap(ph))

    return Frame(x=px, y=py, w=pw, h=ph, rotation=frame_n.rotation)


def _denormalise_effects(effects: list[dict], height: int) -> list:
    """Skeleton effect values are normalised to canvas height."""
    out = []
    for effect in effects:
        data = dict(effect)
        if data.get("kind") == "shadow":
            out.append(ShadowEffect(
                dx=float(data.get("dx", 0)) * height,
                dy=float(data.get("dy", 0)) * height,
                blur=float(data.get("blur", 0)) * height,
                color=data.get("color", "#000000"),
                opacity=float(data.get("opacity", 0.3)),
            ))
    return out


def _build_text_layer(slot: Slot, entry: ComposerSlot | None, common: dict,
                      output: ComposerOutput, roles: dict[str, str],
                      height: int) -> TextLayer | None:
    spec = slot.text
    content = entry.text.content if (entry and entry.text) else ""
    if not content.strip():
        if slot.required:
            content = " "
        else:
            return None

    colour = (entry.color if entry and entry.color and entry.color.startswith("#")
              else roles.get(slot.palette_role or "on-primary", "#FFFFFF"))
    # The offer and the price are the headline of a promotional design and are set like
    # one; the fine print, the feature list and the contact strip are read, not seen, and
    # take the supporting face at body weight.
    display_roles = ("headline", "offer", "price", "badge")
    face = spec.face if spec and spec.face else (
        "display" if slot.role in display_roles else "text")
    family = output.font.for_face(face)
    weight = spec.weight if spec else 400
    if slot.role in display_roles:
        weight = max(weight, output.font.headline_weight)
    elif slot.role in ("body", "caption", "terms"):
        # Running copy and fine print take the pairing's body weight. A feature list, an
        # event line and a contact strip do not: they are scanned rather than read, and
        # the skeleton author already chose a weight that holds them apart from prose.
        weight = output.font.body_weight
    # A display face usually ships one weight; asking it for 900 resolves to that single
    # face anyway, but clamping here keeps the document honest about what it uses.
    available_weights = get_registry().weights_for(family)
    if available_weights:
        weight = min(available_weights, key=lambda w: (abs(w - weight), -w))

    size = (spec.size_n if spec else 0.03) * height
    fit = spec.auto_fit_n if spec else None

    stroke = None
    if spec and spec.stroke_width_n > 0:
        stroke = TextStroke(
            color=roles.get(spec.stroke_palette_role or "on-primary", "#FFFFFF"),
            width=spec.stroke_width_n * height,
        )

    return TextLayer(
        **common,
        content=content,
        fontFamily=family,
        fontWeight=weight,
        fontSize=size,
        lineHeight=spec.line_height if spec else 1.2,
        letterSpacing=(spec.letter_spacing_n if spec else 0.0) * height,
        align=spec.align if spec else "left",
        verticalAlign=spec.vertical_align if spec else "top",
        color=colour,
        textTransform=spec.transform if spec else "none",
        autoFit=AutoFit(min=fit.min * height, max=fit.max * height, mode="shrink")
        if fit else None,
        autoHeight=spec.auto_height if spec else False,
        stroke=stroke,
    )


def _build_image_layer(slot: Slot, entry: ComposerSlot | None, common: dict,
                       brief: DesignBrief, palette: list[str], roles: dict[str, str],
                       doc_id: str,
                       direction: ArtDirection | None = None) -> ImageLayer:
    spec = slot.image
    if entry is not None and entry.image_prompt is not None:
        prompt = entry.image_prompt.prompt
        negative = entry.image_prompt.negative_prompt
    else:
        prompt, negative = build_image_prompt(slot, brief, palette, direction)

    transparent = bool(spec and spec.transparent)
    adapter = "TransparentImage" if transparent else "TextToImage"
    seed = _seed_for(doc_id, slot.slot_id, prompt)

    # Placeholder colour while the asset job runs (§1.3 progressive delivery). A slightly
    # lightened primary reads as "pending" rather than as a deliberate solid block.
    placeholder = adjust_lightness(roles["primary"], 1.35 if
                                   relative_luminance(roles["primary"]) < 0.5 else 0.85)

    mask = spec.mask if spec else None
    frame = common["frame"]
    mask_radius = (spec.mask_radius_n * min(frame.w, frame.h)
                   if spec and spec.mask_radius_n else 0.0)

    return ImageLayer(
        **common,
        assetId="",
        hasAlpha=transparent,
        fit=spec.fit if spec else "cover",
        mask=mask,
        maskRadius=mask_radius,
        placeholderColor=placeholder,
        meta=LayerMeta(generation=GenerationParams(
            adapter=adapter,
            model="pending",
            prompt=prompt,
            negativePrompt=negative,
            seed=seed,
            params={"transparent": transparent,
                    "aspectPreference": (spec.aspect_preference if spec else None) or ""},
        )),
    )


def motif_assignment(slots: list[Slot],
                     direction: ArtDirection | None) -> dict[str, str]:
    """Which motif each ornament slot actually draws, decided for the whole document.

    The skeleton author places *a frame* around the canvas or *a band* along the top
    edge; which frame, which band, is a question about this design rather than about the
    layout, and a corpus that answers it once at authoring time gives every request the
    same decoration. So the authored motif names the family and the direction chooses the
    member — a garland for a wedding, bunting for a school fete, in the same slot.

    It has to be decided for the document rather than slot by slot, because a family
    choice applied independently to every slot collapses ornament the author deliberately
    varied: a layout carrying a scalloped skirt AND a divider comes back with two
    dividers. So distinct authored motifs are mapped to distinct substitutes, and slots
    the author gave the same motif keep sharing one. The direction's own choice is placed
    first, so it lands on the slot that already wanted it where there is one.

    A family is homogeneous in stroke-versus-fill, so no substitution can invalidate a
    slot's authored stroke width. A test enforces that.
    """
    authored = {slot.slot_id: slot.shape.motif for slot in slots
                if slot.shape is not None and slot.shape.motif}
    if direction is None:
        return authored

    remap: dict[str, str] = {}
    for family, members in MOTIF_FAMILIES.items():
        chosen = direction.motifs.for_family(family)
        if not chosen or chosen not in members:
            continue
        # Distinct authored motifs in this family, in the order the slots appear.
        distinct: list[str] = []
        for motif in authored.values():
            if family_of(motif) == family and motif not in distinct:
                distinct.append(motif)
        if not distinct:
            continue
        # If the direction asked for something a slot already uses, that slot keeps it
        # and the others move around it.
        if chosen in distinct:
            pivot = distinct.index(chosen)
            distinct = distinct[pivot:] + distinct[:pivot]
        start = members.index(chosen)
        for offset, motif in enumerate(distinct):
            remap[motif] = members[(start + offset) % len(members)]

    return {slot_id: remap.get(motif, motif) for slot_id, motif in authored.items()}


def _motif_density(slot: Slot, direction: ArtDirection | None) -> int:
    """The direction's density is a whole-design dial; the slot's is what its author
    thought this particular ornament could carry. Averaging keeps both honest — a heavily
    decorated brief cannot flood a slot authored to be restrained, and a restrained one
    cannot strip a slot that exists to be ornate."""
    authored = slot.shape.density if slot.shape else 3
    if direction is None:
        return authored
    return max(1, min(5, round((authored + direction.density) / 2)))


def _build_shape_layer(slot: Slot, common: dict, roles: dict[str, str], *,
                       doc_id: str, canvas_height: int, motif: str | None = None,
                       density: int = 3) -> ShapeLayer | None:
    spec = slot.shape
    colour = roles.get(slot.palette_role or "accent", "#FFFFFF")
    frame: Frame = common["frame"]
    radius = (spec.radius_n if spec else 0.0) * min(frame.w, frame.h)

    gradient = None
    fill: str | None = colour
    stroke = None
    path_data = None

    ornament_params = None
    if motif:
        # Seeded from the document and slot, like image generation, so regenerating a
        # design reproduces the same scatter rather than reshuffling the confetti.
        motif_seed = _seed_for(doc_id, slot.slot_id, motif)
        path_data = render_motif(motif, frame.w, frame.h,
                                 seed=motif_seed, density=density)
        if not path_data:
            return None
        # Kept so the motif can be re-rolled or swapped after the fact. The path alone
        # is a dead end: you can recolour it, but you cannot ask for another one.
        ornament_params = OrnamentParams(motif=motif, seed=motif_seed, density=density)
        if is_stroked(motif):
            # Open contours: filling them would flood the shape they outline.
            # Pictograms are drawn round: butt caps and mitre joins leave a tick ending
            # in two chisels with a spike at the elbow, which reads as a broken glyph.
            round_ends = is_icon(motif)
            stroke = ShapeStroke(color=colour,
                                 width=max(1.0, spec.stroke_width_n * canvas_height),
                                 cap="round" if round_ends else "butt",
                                 join="round" if round_ends else "miter")
            fill = None
    if spec and spec.gradient_scrim:
        # A legibility scrim: the palette colour fading in, not a flat block.
        gradient = LinearGradient(
            angle=spec.gradient_angle,
            stops=[GradientStop(offset=0.0, color=colour, opacity=0.0),
                   GradientStop(offset=0.55, color=colour, opacity=0.55),
                   GradientStop(offset=1.0, color=colour, opacity=0.92)],
        )
        fill = None

    if ornament_params is not None:
        common["meta"] = common.get("meta") or LayerMeta()
        common["meta"].ornament = ornament_params

    return ShapeLayer(
        **common,
        shape=spec.shape if spec else "rect",
        fill=fill,
        stroke=stroke,
        pathData=path_data,
        radius=radius,
        gradient=gradient,
    )


def contrast_of(text_color: str, background: str) -> float:
    return contrast_ratio(text_color, background)
