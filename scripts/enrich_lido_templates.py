#!/usr/bin/env python3
"""Enrich Lido.js templates with intelligent `meta` — companion to `app.lido_corpus`.

Every template in `lidojs_templates/` is loaded fresh at request time (see
`app/lido_corpus/loader.py`), so this script is never required for the pipeline to work.
It exists purely as a convenience: drop a raw Lido export (just `{"layers": {...}}`, no
`meta` block) into the directory, run this script, and get a human-readable `meta` block
written back into the file — so you can inspect slots/roles/description without starting
the API.

By default, uses an LLM (if available via OPENAI_API_KEY) to generate intelligent metadata:
smart template names, inferred kinds (poster/story/banner), and descriptions that understand
the design's purpose. Falls back to rule-based generation if the LLM is unavailable.

Default behavior only touches templates that have NO `meta` block yet. A template that
already has one (even a partial, human-edited one) is left alone, because `name`, `kind`,
`tags` and `description` are treated as human-authored. Pass --force to recompute for
all templates (still preserves non-empty existing name/kind/tags/description values).

    python scripts/enrich_lido_templates.py              # only templates missing meta, uses LLM
    python scripts/enrich_lido_templates.py --force       # recompute for all templates
    python scripts/enrich_lido_templates.py --no-llm      # use rule-based enrichment instead
    python scripts/enrich_lido_templates.py --dir path/to/templates
    python scripts/enrich_lido_templates.py --check       # exit 1 if missing meta, don't write

    # Only touch specific template(s) (by file stem, e.g. template_300.json -> template_300).
    # Composes with --force: without it, a named template missing meta still gets a
    # first pass, but one that already has meta is left alone unless --force is added too.
    python scripts/enrich_lido_templates.py --template template_300
    python scripts/enrich_lido_templates.py --template template_300 --force
    python scripts/enrich_lido_templates.py --template template_300 --template template_301

    # AI-drafted per-slot notes/image specs (background prompt via vision, logo locked
    # deterministically, text slot notes+max_lines via one batched call) — still a draft,
    # not a substitute for reading docs/TEMPLATE_METADATA_RULES.md and reviewing it yourself.
    # Only fills fields that are currently empty; never overwrites a hand-authored one.
    python scripts/enrich_lido_templates.py --template template_300 --draft-slots
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.adapters.registry import llm as get_llm
from app.config import get_settings
from app.lido_corpus.generate_ai import _text_target
from app.lido_corpus.loader import (
    DEFAULT_CORPUS_DIR,
    _aspect,
    _describe,
    _extract_slots,
    _read_root_object,
    derive_meta,
    discover_templates,
)
from app.lido_corpus.model import ImageSpec, LidoDocument, LidoTemplateMeta, SlotInfo
from app.lido_corpus.textfit import wrap


class TemplateMetadataSchema(BaseModel):
    """Schema for LLM to generate intelligent template metadata."""
    name: str = Field(description="A short, descriptive name for the template (2-4 words)")
    kind: str = Field(
        description="The most suitable design kind: post, story, poster, banner, thumbnail, ad, or flyer"
    )
    description: str = Field(description="A one-sentence description of what this template is for")
    tags: list[str] = Field(description="2-3 relevant tags for the template")


class BackgroundDraft(BaseModel):
    prompt: str = Field(description=(
        "Reusable image-generation prompt describing ONLY the background composition — "
        "panel layout with approximate proportions, colors, where accent elements sit "
        "(corners/edges), lighting/style. Mark every brief-specific element with "
        "'(this template: ...)' so a generator knows what to swap. No text, and none of "
        "the foreground subject that a separate layer supplies."
    ))
    notes: str = Field(description=(
        "Constraints a generator must keep that aren't style: the contrast the region "
        "behind the fixed-color text must keep, and — only if the layout facts say a "
        "foreground cutout exists — the area that must stay empty for it."
    ))


class SubjectDraft(BaseModel):
    prompt: str = Field(description=(
        "Reusable image-generation prompt for this foreground subject: subject category "
        "(with '(this template: ...)' marking the swappable specific subject), camera "
        "angle, lighting, styling and framing. Generic enough to be re-themed to any "
        "brief's own subject."
    ))
    notes: str = Field(description=(
        "How this subject sits in the composition (e.g. floats over the background, "
        "cropped by a circular mask) and what that demands of the image."
    ))


class SlotDraft(BaseModel):
    layer_id: str
    notes: str = Field(description=(
        "This slot's function for a copywriter, not its current text: what kind of "
        "phrase goes here (kicker, script accent, headline, offer block, CTA, contact), "
        "roughly how many words, and whether it's a peer in a parallel list with sibling "
        "slots. Written for a designer: no field names or code."
    ))
    max_chars: int = Field(description=(
        "Character ceiling for this slot's role — never below the current text's length."
    ))
    max_lines: int | None = Field(description=(
        "Line-count ceiling if this slot's visual role depends on staying short; never "
        "below the number of lines the current text already sets in. Null if wrapping to "
        "any number of lines is genuinely fine."
    ))


class SlotDraftBatch(BaseModel):
    slots: list[SlotDraft]


def _download_image(url: str) -> bytes | None:
    """Some template asset hosts (quickhub, etc.) 403 a bare urllib request; a normal
    browser UA is enough to pass. Returns None rather than raising — a failed fetch
    should skip the vision draft, not abort the whole enrichment run."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001
        print(f"    (could not fetch image {url} for drafting: {exc})")
        return None


def _has_alpha(data: bytes | None) -> bool:
    """True when the image actually uses transparency (not merely has an alpha band)."""
    if not data:
        return False
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        if img.mode in ("P", "LA", "PA") or "transparency" in img.info:
            img = img.convert("RGBA")
        if img.mode != "RGBA":
            return False
        return img.getchannel("A").getextrema()[0] < 250
    except Exception:  # noqa: BLE001
        return False


def _data_url(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()


async def _vision_json(instruction: str, data: bytes, schema, system: str):
    """Chat-completions content-part format (`type: "text"/"image_url"`) is not the
    Responses API's `input` shape — an explicit model forces the chat path regardless
    of LLM_REASONING_EFFORT, same as OpenAIVisionGlyphDetector (see
    app/adapters/openai_adapters.py)."""
    llm = get_llm()
    settings = get_settings()
    # The fast model misread layouts (a full-width band as "60% wide", an invented
    # shadowed circle), so drafting defaults to a stronger vision model and only falls
    # back to the fast one if that call fails.
    models = [m for m in dict.fromkeys([settings.lido_enrich_vision_model,
                                        settings.llm_model_fast]) if m]
    last_exc: Exception | None = None
    for model in models:
        try:
            result = await llm.complete_json(
                system=system,
                user=[  # type: ignore[arg-type]
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": _data_url(data)}},
                ],
                schema=schema,
                model=model,
            )
            return result.parsed
        except Exception as exc:  # noqa: BLE001
            print(f"    (vision draft with {model} failed: {exc})")
            last_exc = exc
    raise last_exc or RuntimeError("no vision model configured")


# --------------------------------------------------------------------------------------
# Layout facts the drafts are grounded in. The model only ever sees one image at a time,
# so everything it can't see there (where the text sits, its fixed color, which areas a
# separate foreground layer covers) is computed from the layers and spelled out.
# --------------------------------------------------------------------------------------


def _parse_rgb(color: str | None) -> tuple[int, int, int] | None:
    if not color:
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", color)
    if color.startswith("#"):
        h = color.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            return None
    if len(nums) >= 3:
        return int(float(nums[0])), int(float(nums[1])), int(float(nums[2]))
    return None


def _color_words(color: str | None) -> str:
    rgb = _parse_rgb(color)
    if rgb is None:
        return color or "unknown"
    r, g, b = rgb
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if lum > 235:
        return "white"
    if lum < 25:
        return "black"
    return f"{'light' if lum > 150 else 'dark'} ({color})"


def _is_light(color: str | None) -> bool | None:
    rgb = _parse_rgb(color)
    if rgb is None:
        return None
    r, g, b = rgb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 150


def _text_attrs(layer) -> dict:
    doc = layer.props.get("doc") or {}
    content = doc.get("content", []) if isinstance(doc, dict) else []
    return (content[0].get("attrs") or {}) if content else {}


def _clip_shape(props: dict) -> str | None:
    """'circle' / 'shape' for a non-rectangular clipPath, None when there is none (or
    it is a plain rectangle, which crops exactly like having no mask)."""
    path = props.get("clipPath")
    if not path:
        return None
    if re.search(r"[CcSsQqTtAa]", path):
        box = props.get("boxSize") or {}
        w, h = box.get("width") or 0, box.get("height") or 0
        return "circle" if w and h and abs(w - h) / max(w, h) < 0.05 else "shape"
    return None


def _region(x: float, y: float, w: float, h: float, cw: float, ch: float) -> str:
    """Human wording for where a box sits, plus percentages a generator can use."""
    cx, cy = (x + w / 2) / cw, (y + h / 2) / ch
    horiz = "left" if cx < 0.38 else "right" if cx > 0.62 else "center"
    vert = "upper" if cy < 0.38 else "lower" if cy > 0.62 else "middle"
    name = "center" if (horiz, vert) == ("center", "middle") else f"{vert}-{horiz}"
    pct = lambda v, t: max(0, min(100, round(100 * v / t)))
    return (f"the {name} of the frame (about {pct(x, cw)}–{pct(x + w, cw)}% across, "
            f"{pct(y, ch)}–{pct(y + h, ch)}% down)")


def _canvas(layers: dict) -> tuple[float, float]:
    box = layers["ROOT"].props.get("boxSize") or {}
    return float(box.get("width") or 1), float(box.get("height") or 1)


def _box(props: dict) -> tuple[float, float, float, float] | None:
    pos, box = props.get("position") or {}, props.get("boxSize") or {}
    w, h = box.get("width"), box.get("height")
    if not w or not h:
        return None
    return float(pos.get("x", 0)), float(pos.get("y", 0)), float(w), float(h)


def _text_groups(layers: dict) -> list[tuple[bool, str, str, int]]:
    """(is_light, color, band, count) for the text that sits directly on the background,
    one entry per light/dark group. Text whose center falls on a ShapeLayer (a label on
    a colored ribbon or button) is skipped: its contrast is with that shape, which the
    template fixes, not with the generated background."""
    cw, ch = _canvas(layers)
    shapes = [bx for l in layers.values()
              if l.type.resolvedName == "ShapeLayer" and (bx := _box(l.props))]
    groups: dict[bool, list[tuple[str, tuple[float, float, float, float]]]] = {}
    for lid, layer in layers.items():
        if lid == "ROOT" or layer.type.resolvedName != "TextLayer":
            continue
        bx, color = _box(layer.props), _text_attrs(layer).get("color")
        light = _is_light(color)
        if bx is None or light is None:
            continue
        cx, cy = bx[0] + bx[2] / 2, bx[1] + bx[3] / 2
        if any(sx <= cx <= sx + sw and sy <= cy <= sy + sh for sx, sy, sw, sh in shapes):
            continue
        groups.setdefault(light, []).append((color, bx))
    out = []
    for light, items in groups.items():
        pct = lambda v, t: max(0, min(100, round(100 * v / t)))
        x0 = pct(min(b[0] for _, b in items), cw)
        x1 = pct(max(b[0] + b[2] for _, b in items), cw)
        y0 = pct(min(b[1] for _, b in items), ch)
        y1 = pct(max(b[1] + b[3] for _, b in items), ch)
        color = Counter(c for c, _ in items).most_common(1)[0][0]
        out.append((light, color, f"the area about {x0}–{x1}% across, {y0}–{y1}% down",
                    len(items)))
    return sorted(out, key=lambda g: -g[3])


def _is_subject_slot(slot: SlotInfo) -> bool:
    return slot.role == "photo" and slot.resolved_name == "FrameLayer"


def _subject_is_cutout(slot: SlotInfo, layers: dict, data: bytes | None) -> bool:
    """A real alpha cutout only when the template's own sample image is transparent.
    A round mask alone does not mean cutout: most round frames in the corpus hold an
    ordinary opaque photo that fills the circle (template_10091, 1825, 831), and
    calling those cutouts produced an isolated sofa floating in an empty circle."""
    return _has_alpha(data)


# --------------------------------------------------------------------------------------
# Drafts
# --------------------------------------------------------------------------------------

_NO_TEXT_CLAUSE = "No text, lettering, logos or watermarks anywhere in the image."


def _append(text: str, sentence: str) -> str:
    """Join a deterministic clause onto a model-written prompt as its own sentence."""
    text = text.rstrip()
    if text and text[-1] not in ".!?":
        text += "."
    return f"{text} {sentence.strip()}" if text else sentence.strip()


async def _draft_background(meta: LidoTemplateMeta, layers: dict,
                            cutout_slots: list[SlotInfo],
                            photo_slots: list[SlotInfo] | None = None) -> ImageSpec | None:
    root = layers["ROOT"]
    url = (root.props.get("image") or {}).get("url")
    if not url:
        return None
    cw, ch = _canvas(layers)
    text_groups = _text_groups(layers)
    empty_areas = [
        _region(s.position.get("x", 0), s.position.get("y", 0),
                s.box_size.get("width", 0), s.box_size.get("height", 0), cw, ch)
        for s in cutout_slots if s.position and s.box_size
    ]
    cutout_ids = {s.layer_id for s in cutout_slots}
    covered_areas = [
        (_region(s.position.get("x", 0), s.position.get("y", 0),
                 s.box_size.get("width", 0), s.box_size.get("height", 0), cw, ch),
         _clip_shape(layers[s.layer_id].props))
        for s in (photo_slots or []) if s.layer_id not in cutout_ids
        and s.position and s.box_size
    ]

    facts = [f"Canvas: {int(cw)}x{int(ch)}. Text is added later as separate editable layers."]
    for _, color, band, n in text_groups:
        facts.append(f"{n} text layer(s) fixed in {_color_words(color)} sit directly on "
                     f"the background in {band}.")
    for area in empty_areas:
        facts.append(f"A separate transparent foreground subject is composited over {area}. "
                     "Anything in that area of this photo (a dish, product, person...) "
                     "belongs to that foreground layer, not to the background.")
    for area, shape in covered_areas:
        facts.append(f"A separate {'round ' if shape else ''}photo layer covers {area}. "
                     "Whatever this image shows there (a photo in a circle, a ring) is a "
                     "leftover under that layer: do not describe it.")
    if not empty_areas and not covered_areas:
        facts.append("No foreground subject or photo layer sits on this background: do not "
                     "mention any cutout or reserved area; describe the whole image.")

    instruction = (
        "This is a design template's current background image. Draft the reusable "
        "generation prompt that recreates this KIND of background for any brief, plus "
        "the notes a generator must obey.\n\nLayout facts (from the template layers, "
        "not visible in the image):\n- " + "\n- ".join(facts) + "\n\n"
        "Rules for the prompt: describe the panel layout with approximate proportions and "
        "the shape/angle of any seam. Then list EVERY other distinct element outside the "
        "photo-layer areas, each with its position (percent across/down) and size: "
        "photographs that are part of the background itself, badges, icons, small "
        "repeated shapes, lines, stripes, dots. Small repeated badges or tabs usually "
        "hold text, so give their exact positions. Give lighting and style. Mark every brief-specific element (colors, props, subject "
        "matter) with '(this template: ...)'. Do NOT describe any foreground subject — say "
        "instead that its area must be left empty. Never ask for text."
    )
    data = _download_image(url)
    draft = None
    if data is not None:
        try:
            draft = await _vision_json(
                instruction, data, BackgroundDraft,
                system="You are an art director writing reusable image-generation "
                       "prompts for design-template backgrounds.")
        except Exception as exc:  # noqa: BLE001
            print(f"    (background draft failed: {exc})")
    prompt = (draft.prompt.strip() if draft else
              "Full-bleed background matching the brief's palette and theme, with the "
              "same panel layout, accent placement and lighting as the reference image.")
    notes = draft.notes.strip() if draft else ""

    # Load-bearing constraints are appended deterministically: the drafter has dropped
    # them before (a background with its own subject baked into the center, under the
    # real cutout), and the fill model is told to preserve them verbatim.
    for area in empty_areas:
        prompt = _append(prompt, f" IMPORTANT: leave {area} empty of any dish, product, person or "
                   "other subject — that area is reserved for a separate transparent "
                   "cutout composited on top; keep only background surface there.")
    for area, shape in covered_areas:
        prompt = _append(prompt, f" A separate {'round ' if shape else ''}photo layer covers {area}: draw "
                   "no circle, ring, frame, shadow or photo there — keep plain background "
                   "surface.")
    if "no text" not in prompt.lower():
        prompt = _append(prompt, _NO_TEXT_CLAUSE)

    for light, color, band, _ in text_groups:
        tone = ("saturated, medium-to-dark tone that it reads clearly on — never pastel, "
                "pale, cream or near-white, even when a brief asks for soft or light tones "
                "(put those elsewhere and in the accents instead)") if light else (
               "light, calm tone that it reads clearly on — never dark or busy, even when "
               "a brief asks for a moody palette")
        notes = _append(notes, f" Text fixed in {_color_words(color)} sits in {band}, so that part of "
                  f"the background must stay a {tone}.")
    if covered_areas:
        notes = _append(notes, " The photo frames are separate layers; a regenerated background must "
                  "not contain its own circles, rings or photos under them.")
    if empty_areas:
        notes = _append(notes, " The reference photo may have a subject baked in; a fresh background "
                  "must leave it out, because the separate cutout layer supplies it and it "
                  "must not be duplicated.")
    return ImageSpec(kind="background_photo", generate=True, transparent=False,
                     prompt=prompt, reference_url=url, notes=notes.strip() or None)


async def _draft_subject(slot: SlotInfo, layers: dict) -> tuple[ImageSpec, str | None]:
    """A photo frame with no `image` spec is never regenerated at fill time (see
    `image_targets`), so the template's own sample photo would ship unchanged in every
    design — this always returns a spec, with a generic prompt if vision fails."""
    props = layers[slot.layer_id].props
    url = (props.get("image") or {}).get("url")
    data = _download_image(url) if url else None
    cutout = _subject_is_cutout(slot, layers, data)
    shape = _clip_shape(props)
    cw, ch = _canvas(layers)
    area = _region(slot.position.get("x", 0), slot.position.get("y", 0),
                   slot.box_size.get("width", 0), slot.box_size.get("height", 0), cw, ch) \
        if slot.position and slot.box_size else "the frame"

    mask = f"a {shape} mask" if shape == "circle" else "a shaped mask" if shape else "its frame"
    draft = None
    if data is not None:
        instruction = (
            f"This is the foreground subject image of a design template. It sits in {area}, "
            f"cropped by {mask}" + (", floating over the background as a transparent cutout"
                                    if cutout else "") + ". Draft a reusable generation "
            "prompt for this KIND of subject: open with the generic category (e.g. 'a "
            "single hero dish in a bowl') and put the specific subject only in "
            "'(this template: ...)'; then camera angle, lighting, styling and framing so "
            "it fills the mask well. Never ask for text."
            + (" Describe the subject ONLY: no background, backdrop, surface, blur or "
               "bokeh — the subject is isolated on transparency." if cutout else ""))
        try:
            draft = await _vision_json(
                instruction, data, SubjectDraft,
                system="You are a photography art director writing reusable "
                       "image-generation prompts for design-template subjects.")
        except Exception as exc:  # noqa: BLE001
            print(f"    (subject draft failed: {exc})")

    prompt = (draft.prompt.strip() if draft else
              "The brief's hero subject, photographed in the same camera angle, lighting "
              "and styling as the reference image, framed to fill the mask.")
    notes = draft.notes.strip() if draft else ""
    if cutout:
        if "transparent" not in prompt.lower():
            prompt = _append(prompt, " Subject only, isolated on a fully transparent background: an "
                       "alpha-channel PNG with no backdrop, table surface or baked-in shadow.")
        notes = _append(notes, f" This subject floats over the background in {area}, cropped by {mask}. "
                  "It must be a genuine alpha-transparent cutout — only the subject has "
                  "pixels, never a rectangular photo backdrop, or that backdrop would show "
                  "inside the mask wherever the subject doesn't reach its edge.")
    else:
        notes = _append(notes, " Opaque photo, cover-cropped to the frame — it must fill the frame "
                  "completely with no empty corners.")
    if "no text" not in prompt.lower():
        prompt = _append(prompt, _NO_TEXT_CLAUSE)
    slot_note = ("The mask on this layer crops the image at render time — keep the source "
                 "image a full rectangle (not pre-cropped), so the mask can be moved or "
                 "resized later without exposing hard edges.") if shape else None
    spec = ImageSpec(kind="subject_cutout" if cutout else "background_photo",
                     generate=True, transparent=cutout, prompt=prompt,
                     reference_url=url, notes=notes.strip())
    return spec, slot_note


def _is_logo_slot(slot: SlotInfo) -> bool:
    return slot.role == "logo"


def _draft_logo(slot: SlotInfo, layers: dict) -> tuple[bool, ImageSpec]:
    """Deterministic, not LLM-drafted: docs/TEMPLATE_METADATA_RULES.md is explicit that a
    logo is a brand asset, never regenerated — there is no judgment call here."""
    url = (layers[slot.layer_id].props.get("image") or {}).get("url")
    transparent = _has_alpha(_download_image(url)) if url else False
    return True, ImageSpec(kind="logo_static", generate=False, transparent=transparent,
                           reference_url=url,
                           notes="Brand logo — reuse the asset exactly as supplied. Never "
                                 "regenerate, recolor, re-crop, or let a filler touch this "
                                 "layer; only ever swap in a different brand's own logo file.")


def _default_lines(slot: SlotInfo, layers: dict) -> list[str] | None:
    """How the template's own copy actually sets, measured with the layer's real font.
    Lido text boxes grow downward to fit, so box height is not a line limit — this is."""
    if not slot.default_text:
        return None
    try:
        target = _text_target(slot, layers[slot.layer_id].props)
        if target.measure is None:
            return None
        return wrap(slot.default_text, target.measure, target.box_width)
    except Exception:  # noqa: BLE001
        return None


def _auto_max_chars(slot: SlotInfo) -> int | None:
    return int(len(slot.default_text) * 1.4) + 8 if slot.default_text else None


async def _draft_text_slots(slots: list[SlotInfo], layers: dict) -> dict[str, SlotDraft]:
    """One batched call so the model can see every slot at once — the only way it can
    recognize a parallel-list pattern (several slots that are peers, not a hierarchy)
    and write consistent notes across them, per docs/TEMPLATE_METADATA_RULES.md."""
    if not slots:
        return {}
    lines = []
    for s in sorted(slots, key=lambda s: (s.position or {}).get("y", 0)):
        box = s.box_size or {}
        pos = s.position or {}
        attrs = _text_attrs(layers[s.layer_id])
        wrapped = _default_lines(s, layers)
        sets_as = (" / ".join(repr(line) for line in wrapped) + f" ({len(wrapped)} line"
                   f"{'s' if len(wrapped) != 1 else ''})") if wrapped else "unknown"
        lines.append(
            f"- {s.layer_id} | role={s.role} | text={s.default_text!r} | "
            f"font={attrs.get('fontFamily', '?')} {s.font_size}px"
            + (f" {attrs['textTransform']}" if attrs.get("textTransform") else "")
            + f" | box width={int(box.get('width', 0))} at x={int(pos.get('x', 0))}, "
              f"y={int(pos.get('y', 0))} | current text sets as: {sets_as}"
        )
    try:
        llm = get_llm()
        result = await llm.complete_json(
            system="You write per-slot authoring notes and length limits for a design "
                   "template's text layers, for the copywriter who will refill them.",
            user="Draft notes, max_chars and max_lines for each text slot below (listed "
                 "top to bottom). Facts:\n"
                 "- Text boxes grow downward automatically, so box height is NOT a line "
                 "limit. 'sets as' is how the current copy really wraps in its real font.\n"
                 "- The current copy is the template's own design and must pass its own "
                 "limits: max_lines >= its line count, max_chars >= its length. Choose "
                 "limits that fit this slot's role (a script accent stays one line; a "
                 "stacked narrow offer block may take several one-word lines).\n"
                 "- A script font (e.g. Allura, Great Vibes) marks an accent phrase; an "
                 "uppercase narrow box marks a stacked offer/CTA block.\n"
                 "- Consider slots together: if several are peers in a list rather than a "
                 "headline/subhead/body hierarchy, say so consistently. If the inferred "
                 "role looks wrong, say what the slot really is.\n\n"
                 + "\n".join(lines),
            schema=SlotDraftBatch,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"    (text slot draft failed: {exc})")
        return {}
    return {d.layer_id: d for d in result.parsed.slots}


async def _draft_slot_metadata(meta: LidoTemplateMeta, layers: dict) -> None:
    """Fills empty `background`/per-slot `image`/`notes`/`max_chars`/`max_lines`/`locked`
    fields in place from AI drafts — never overwrites a field that already has a value,
    so this is safe to re-run after a human has started hand-editing."""
    subject_slots = [s for s in meta.slots if _is_subject_slot(s)]
    for slot in subject_slots:
        if slot.image is None:
            slot.image, slot_note = await _draft_subject(slot, layers)
            if not slot.notes:
                slot.notes = slot_note
    cutouts = [s for s in subject_slots if s.image and s.image.transparent]

    if meta.background is None:
        meta.background = await _draft_background(meta, layers, cutouts, subject_slots)

    to_draft: list[SlotInfo] = []
    for slot in meta.slots:
        if _is_logo_slot(slot) and slot.image is None:
            slot.locked, slot.image = _draft_logo(slot, layers)
        elif slot.resolved_name == "TextLayer" and not slot.notes:
            to_draft.append(slot)

    drafts = await _draft_text_slots(to_draft, layers)
    for slot in to_draft:
        draft = drafts.get(slot.layer_id)
        if draft is None:
            continue
        slot.notes = draft.notes
        # Floors: the template's own copy must pass its own limits, whatever the model said.
        text_len = len(slot.default_text or "")
        if slot.max_chars is None or slot.max_chars == _auto_max_chars(slot):
            slot.max_chars = max(draft.max_chars or 0, text_len) or slot.max_chars
        if slot.max_lines is None and draft.max_lines is not None:
            wrapped = _default_lines(slot, layers)
            slot.max_lines = max(draft.max_lines, len(wrapped) if wrapped else 1)


def _slot_summary(slots) -> str:
    """Describe slots for LLM prompting."""
    by_role = {}
    for s in slots:
        role = s.role
        if role not in by_role:
            by_role[role] = []
        by_role[role].append(s.default_text[:30] if s.default_text else "(empty)")

    parts = []
    for role in ["headline", "subhead", "body", "phone", "address", "website", "logo", "photo"]:
        if role in by_role:
            texts = ", ".join(f'"{t}"' for t in by_role[role])
            parts.append(f"- {role}: {texts}")
    return "\n".join(parts) if parts else "(no editable slots)"


async def _enrich_with_llm(template_id: str, layers: dict, existing: dict | None = None) -> LidoTemplateMeta:
    """Use LLM to generate intelligent template metadata."""
    existing = existing or {}
    root = layers["ROOT"]
    box = root.props.get("boxSize", {"width": 0, "height": 0})
    w, h = box.get("width", 0), box.get("height", 0)
    existing_slots_by_id = {
        s["layer_id"]: s for s in existing.get("slots", []) if s.get("layer_id")
    }
    slots = _extract_slots(layers, existing_slots_by_id)
    existing_background = existing.get("background")

    # If human already set these, keep them
    existing_name = existing.get("name", "").strip()
    existing_kind = existing.get("kind", "").strip()
    existing_desc = existing.get("description", "").strip()
    existing_tags = existing.get("tags", [])

    slot_summary = _slot_summary(slots)
    system_prompt = """You are an expert at analyzing design templates and generating descriptive metadata."""
    user_prompt = f"""Analyze this Lido.js template and generate metadata for it.

Template ID: {template_id}
Canvas size: {int(w)}x{int(h)} ({_aspect(w, h)})

Editable slots in the design:
{slot_summary}

Generate appropriate metadata:
- name: A short, descriptive name (2-4 words, e.g. "Product Showcase", "Restaurant Menu")
- kind: The most suitable design kind: post, story, poster, banner, thumbnail, ad, or flyer
- description: A one-sentence description of what this template is for
- tags: 2-3 relevant tags (e.g. business, contact, modern)"""

    try:
        llm = get_llm()
        llm_result = await llm.complete_json(
            system=system_prompt,
            user=user_prompt,
            schema=TemplateMetadataSchema,
        )
        result = llm_result.parsed
        llm_name = (result.name or "").strip()
        llm_kind = (result.kind or "post").strip()
        llm_desc = (result.description or "").strip()
        llm_tags = result.tags or []
    except Exception as exc:  # noqa: BLE001
        print(f"    (LLM unavailable: {exc}; falling back to rule-based)")
        llm_name = llm_kind = llm_desc = ""
        llm_tags = []

    # Use LLM if available, otherwise fall back to rule-based; preserve existing if non-empty
    name = existing_name or llm_name or ""
    kind = existing_kind or llm_kind or "post"
    description = existing_desc or llm_desc or _describe(slots)
    tags = existing_tags or llm_tags or []

    return LidoTemplateMeta(
        id=template_id,
        name=name,
        kind=kind,
        aspect=_aspect(w, h) if w and h else "1:1",
        tags=tags,
        description=description,
        canvas_size={"width": w, "height": h},
        background_image_url=(root.props.get("image") or {}).get("url"),
        background=ImageSpec.model_validate(existing_background) if existing_background else None,
        text_layer_count=sum(1 for s in slots if s.resolved_name == "TextLayer"),
        reference_note=existing.get("reference_note"),
        slots=slots,
    )


def _enrich_file_in_place(path: Path, use_llm: bool = True,
                          draft_slots: bool = False) -> LidoTemplateMeta:
    """Recompute metadata and write it back, preserving human-authored fields."""
    obj = _read_root_object(path)
    doc = LidoDocument.model_validate({"layers": obj["layers"]})

    async def _run() -> LidoTemplateMeta:
        if use_llm:
            meta = await _enrich_with_llm(path.stem, doc.layers, existing=obj.get("meta"))
        else:
            # Fallback: rule-based (same merge behavior as the API's own loader)
            meta = derive_meta(path.stem, doc.layers, existing=obj.get("meta"))
        if draft_slots and use_llm:
            await _draft_slot_metadata(meta, doc.layers)
        return meta

    meta = asyncio.run(_run())

    out = [{
        "layers": json.loads(json.dumps(
            {lid: layer.model_dump(mode="json", by_alias=False) for lid, layer in doc.layers.items()}
        )),
        "meta": meta.model_dump(mode="json"),
    }]
    with path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return meta


def _has_meta(path: Path) -> bool:
    try:
        obj = _read_root_object(path)
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        raise ValueError(f"could not read {path.name}: {exc}") from exc
    return bool(obj.get("meta"))


def _verify(path: Path) -> tuple[list[str], list[str]]:
    """Every rule of docs/TEMPLATE_METADATA_RULES.md that can be checked mechanically.
    Returns (errors, warnings). Errors block `make lido-add` from syncing the template;
    warnings are things a human should still look at."""
    from app.lido_corpus.generate_ai import check_text, text_targets
    from app.lido_corpus.loader import load_enriched

    errors: list[str] = []
    warnings: list[str] = []
    try:
        if not _has_meta(path):
            return ["no meta block yet — run `make lido-meta`"], []
        t = load_enriched(path)
    except (ValueError, OSError, KeyError) as exc:
        return [f"cannot read: {exc}"], []
    m = t.meta

    if not m.name.strip():
        errors.append("meta.name is empty")
    if not m.description.strip():
        errors.append("meta.description is empty")
    if not m.tags:
        warnings.append("meta.tags is empty (matching reads tags)")

    root_image = (t.layers["ROOT"].props.get("image") or {}).get("url")
    if root_image and (m.background is None or not (m.background.prompt or "").strip()):
        errors.append("background has an image but no meta.background prompt")
    elif m.background and m.background.prompt and "no text" not in m.background.prompt.lower():
        warnings.append("background prompt does not forbid text in the image")

    for s in m.slots:
        label = f"{s.role} slot {s.layer_id[:8]}"
        if s.role == "logo":
            if not s.locked or s.image is None or s.image.generate:
                errors.append(f"{label}: logo must be locked with a non-generated logo_static image")
        elif s.role == "photo" and s.resolved_name in ("FrameLayer", "ImageLayer"):
            if s.image is None:
                errors.append(f"{label}: no image spec — its sample photo would never be replaced")
            elif s.image.generate and not (s.image.prompt or "").strip():
                errors.append(f"{label}: image spec has no prompt")
        elif s.resolved_name == "TextLayer" and s.editable:
            if not s.max_chars:
                errors.append(f"{label}: no max_chars")
            if not (s.notes or "").strip():
                warnings.append(f"{label}: no notes (what kind of copy goes here)")

    for target in text_targets(t):
        problems = check_text(target.slot.default_text or "", target)
        if problems:
            errors.append(f"{target.slot.role} slot {target.slot.layer_id[:8]}: the template's "
                          f"own text breaks its limits — {'; '.join(problems)}")

    if not m.reference_note:
        warnings.append("no meta.reference_note yet (add it after your review)")
    return errors, warnings


def _run_verify(paths: list[Path]) -> int:
    failed = 0
    for path in paths:
        errors, warnings = _verify(path)
        status = "FAIL" if errors else ("OK*" if warnings else "OK")
        print(f"  {status:<5} {path.name}")
        for e in errors:
            print(f"        error:   {e}")
        for w in warnings:
            print(f"        warning: {w}")
        failed += bool(errors)
    print(f"\nverify: {len(paths) - failed} passed, {failed} failed "
          f"(errors block the database sync; warnings are for your review)")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_CORPUS_DIR,
                        help=f"template directory (default: {DEFAULT_CORPUS_DIR})")
    parser.add_argument("--force", action="store_true",
                        help="recompute meta for every template, not just ones missing it")
    parser.add_argument("--check", action="store_true",
                        help="don't write anything; exit 1 if any template is missing meta")
    parser.add_argument("--no-llm", action="store_true",
                        help="use rule-based enrichment instead of LLM")
    parser.add_argument("--verify", action="store_true",
                        help="don't write anything; check every mechanical metadata rule "
                             "and exit 1 if any template has an error")
    parser.add_argument("--template", action="append", default=None, metavar="NAME",
                        help="only process this template, by file stem (e.g. template_300 "
                             "for template_300.json); repeat to name several")
    parser.add_argument("--draft-slots", action="store_true",
                        help="also AI-draft empty background/notes/max_lines/logo-lock "
                             "fields — a starting point to review against "
                             "docs/TEMPLATE_METADATA_RULES.md, never a substitute for it; "
                             "only fills fields that are currently empty")
    args = parser.parse_args()

    if args.draft_slots and args.no_llm:
        print("--draft-slots has no effect with --no-llm (drafting requires the LLM)",
             file=sys.stderr)

    paths = discover_templates(args.dir)
    if not paths:
        print(f"no templates found in {args.dir}")
        return 0

    if args.template:
        wanted = set(args.template)
        paths = [p for p in paths if p.stem in wanted]
        unmatched = wanted - {p.stem for p in paths}
        if unmatched:
            print(f"template(s) not found in {args.dir}: {', '.join(sorted(unmatched))}",
                 file=sys.stderr)
            return 1

    if args.verify:
        return _run_verify(paths)

    missing: list[Path] = []
    errors: list[tuple[Path, str]] = []
    for path in paths:
        try:
            if not _has_meta(path):
                missing.append(path)
        except ValueError as exc:
            errors.append((path, str(exc)))

    if errors:
        for path, message in errors:
            print(f"  ERROR    {path.name}: {message}", file=sys.stderr)

    if args.check:
        if missing:
            print(f"{len(missing)} template(s) missing meta: " + ", ".join(p.name for p in missing))
            return 1
        print(f"all {len(paths)} template(s) have meta")
        return 1 if errors else 0

    targets = paths if args.force else missing
    enriched: list[Path] = []
    for path in targets:
        try:
            meta = _enrich_file_in_place(path, use_llm=not args.no_llm,
                                         draft_slots=args.draft_slots)
            enriched.append(path)
            status = f"name={meta.name!r}, kind={meta.kind}" if meta.name else f"kind={meta.kind}"
            print(f"  enriched {path.name:<25} {status}")
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            errors.append((path, str(exc)))
            print(f"  ERROR    {path.name}: {exc}", file=sys.stderr)

    skipped = [p for p in paths if p not in targets]
    for path in skipped:
        print(f"  skipped  {path.name} (already has meta)")

    print(f"\n{len(enriched)} enriched, {len(skipped)} skipped, {len(errors)} error(s) "
          f"— {len(paths)} template(s) total in {args.dir}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
