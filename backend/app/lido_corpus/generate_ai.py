"""One structured LLM call that fills a Lido template (plan.md §2.2).

The model receives the user's raw request plus the template's own per-layer metadata
(text limits, role notes, reference image prompts) and returns, keyed by `layer_id`,
the copy for every text layer and a brief-adapted prompt for every generated image.
No `DesignBrief` in between: the template already fixes canvas, kind and layer set.

Everything the model returns is re-checked mechanically afterwards — layer ids,
character and line limits, contact details — because "perfect" can't depend on the
model always obeying its instructions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import structlog
from pydantic import BaseModel

from app.adapters.base import AdapterError
from app.adapters.registry import llm as get_llm
from app.config import get_settings

from .model import ImageSpec, LidoTemplateFile, SlotInfo
from .textfit import TextMeasure, family_name, font_file, too_wide_words, wrap

log = structlog.get_logger(__name__)

BACKGROUND_LAYER_ID = "ROOT"
CONTACT_ROLES = frozenset({"website", "phone", "address"})

# High effort spends hidden reasoning tokens out of the same output budget.
_MAX_OUTPUT_TOKENS = 32000


class LidoLayerTextFill(BaseModel):
    layer_id: str
    text: str


class LidoLayerImagePrompt(BaseModel):
    layer_id: str
    prompt: str


class LidoTemplateFillOutput(BaseModel):
    text_fills: list[LidoLayerTextFill]
    image_prompts: list[LidoLayerImagePrompt]


class LidoTextRepairOutput(BaseModel):
    text_fills: list[LidoLayerTextFill]


@dataclass(frozen=True)
class TextTarget:
    slot: SlotInfo
    text_transform: str | None
    paragraphs: int
    measure: TextMeasure | None
    """None only when the layer has no box width or font size to measure against."""

    @property
    def layer_id(self) -> str:
        return self.slot.layer_id

    @property
    def box_width(self) -> float:
        return float((self.slot.box_size or {}).get("width") or 0)

    @property
    def chars_per_line(self) -> int | None:
        """A guide for the model only; limits are checked with `measure` itself."""
        if self.measure is None:
            return None
        return self.measure.average_chars_per_line(self.box_width)


@dataclass(frozen=True)
class ImageTarget:
    layer_id: str
    spec: ImageSpec
    width: float
    height: float


@dataclass
class TemplateFill:
    text: dict[str, str]
    image_prompts: dict[str, str]
    repaired: list[str] = field(default_factory=list)
    """Layers whose first answer broke a limit and were fixed by the repair call."""
    clamped: list[str] = field(default_factory=list)
    """Layers still over a limit after repair, trimmed mechanically."""
    llm_calls: int = 0
    cost_cents: int = 0


# --------------------------------------------------------------------------------------
# Targets: what the model is asked to fill, derived from the template's metadata
# --------------------------------------------------------------------------------------


def _font_urls(props: dict, css_family: str) -> tuple[str, ...]:
    for entry in props.get("fonts") or []:
        if entry.get("name") == css_family:
            return tuple(u for f in entry.get("fonts") or [] for u in f.get("urls") or [])
    return ()


def _text_target(slot: SlotInfo, props: dict) -> TextTarget:
    doc = props.get("doc")
    content = doc.get("content", []) if isinstance(doc, dict) else []
    attrs = (content[0].get("attrs") or {}) if content else {}
    transform = attrs.get("textTransform") or None
    measure = None
    width = (slot.box_size or {}).get("width")
    if width and slot.font_size:
        css_family = attrs.get("fontFamily") or ""
        path = font_file(family_name(css_family), _font_urls(props, css_family)) \
            if css_family else None
        measure = TextMeasure(path, slot.font_size, transform,
                              float(attrs.get("letterSpacing") or 0))
    return TextTarget(slot=slot, text_transform=transform, paragraphs=len(content),
                      measure=measure)


def text_targets(template: LidoTemplateFile) -> list[TextTarget]:
    return [
        _text_target(slot, template.layers[slot.layer_id].props)
        for slot in template.meta.slots
        if not slot.locked and slot.editable and slot.resolved_name == "TextLayer"
    ]


def _image_box(props: dict) -> tuple[float, float]:
    box = (props.get("image") or {}).get("boxSize") or props.get("boxSize") or {}
    return float(box.get("width") or 1024), float(box.get("height") or 1024)


def image_targets(template: LidoTemplateFile) -> list[ImageTarget]:
    """Every image the template wants generated: the background (if `meta.background`
    asks for one) and each image slot whose spec has `generate=True` and a reference
    prompt. Locked slots and `generate=False` specs (the logo) never appear here."""
    targets = []
    background = template.meta.background
    if background and background.generate and background.prompt:
        w, h = _image_box(template.layers[BACKGROUND_LAYER_ID].props)
        targets.append(ImageTarget(BACKGROUND_LAYER_ID, background, w, h))
    for slot in template.meta.slots:
        spec = slot.image
        if slot.locked or spec is None or not spec.generate or not spec.prompt:
            continue
        w, h = _image_box(template.layers[slot.layer_id].props)
        targets.append(ImageTarget(slot.layer_id, spec, w, h))
    return targets


# --------------------------------------------------------------------------------------
# Mechanical checks applied to whatever the model returns
# --------------------------------------------------------------------------------------


def check_text(text: str, target: TextTarget) -> list[str]:
    """Human-readable limit violations for `text` in `target`, empty when it fits.
    Phrased for the repair prompt, so each one says what to change."""
    if not text.strip():
        return ["text is empty"]
    slot = target.slot
    problems = []
    if slot.max_chars and len(text) > slot.max_chars:
        problems.append(f"{len(text)} characters, limit is {slot.max_chars}")
    measure, width = target.measure, target.box_width
    if measure is not None:
        wide = too_wide_words(text, measure, width)
        if wide:
            sizes = ", ".join(f"'{w}' is {measure.width(w):.0f}px" for w in wide)
            problems.append(f"too wide to fit on one line of this {width:.0f}px box in this "
                            f"font ({sizes}) — use shorter words")
        if slot.max_lines:
            lines = wrap(text, measure, width)
            if len(lines) > slot.max_lines:
                problems.append(f"wraps to {len(lines)} lines {lines}, "
                                f"limit is {slot.max_lines}")
    return problems


def normalize_text(text: str, target: TextTarget) -> str:
    # A single-paragraph layer renders "\n" as a space (see compose._set_doc_text), and
    # wrapping comes from the box width, so a manual break would only skew the counts.
    if target.paragraphs <= 1:
        return " ".join(text.split())
    return "\n".join(" ".join(line.split()) for line in text.strip().splitlines())


def clamp_text(text: str, target: TextTarget) -> str:
    """Last resort when repair didn't fix it: drop words that can't fit a line, then
    trailing words until the limits hold. Falls back to the template's own copy."""
    too_wide = set(too_wide_words(text, target.measure, target.box_width)) \
        if target.measure else set()
    words = [w for w in text.split() if w not in too_wide]
    while words and check_text(" ".join(words), target):
        words.pop()
    clamped = " ".join(words)
    return clamped if clamped else (target.slot.default_text or "")


_URL_PREFIX_RE = re.compile(r"^(https?://)?(www\.)?")


def _contact_is_supported(text: str, role: str, user_prompt: str) -> bool:
    """True when a contact detail the model wrote actually comes from the user's
    request, so a website/phone/address is never invented."""
    prompt = user_prompt.lower()
    if role == "website":
        core = _URL_PREFIX_RE.sub("", text.strip().lower()).rstrip("/")
        return bool(core) and core in prompt
    if role == "phone":
        digits = re.sub(r"\D", "", text)
        return len(digits) >= 5 and digits in re.sub(r"\D", "", user_prompt)
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3]
    return bool(words) and all(w in prompt for w in words)


# --------------------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert brand designer, copywriter and photography art director filling in a
fixed template layout from a user's design request. The template's structure — which
layers exist, their size and their role — is FIXED: you never add, remove, merge or
reinterpret layers. Your job has two parts that must stay consistent with each other and
with the user's request: write the copy for every text layer, and rewrite every
reference image prompt so the generated images match the same request.

TEXT LAYERS
- Write copy for every text layer listed, in the voice implied by the user's request and
  in the language the request is written in.
- Obey max_chars and max_lines exactly. Each box wraps automatically at roughly
  approx_chars_per_line characters of average text in that layer's font. It is an
  average: wide letters (m, w, M, W, O) take more room, so in narrow boxes prefer short
  words well under that length. Every word must fit on one line, and the wrapped text
  must fit in max_lines lines. Your answer is measured with the real font afterwards.
- Do not insert line breaks; the layout wraps the text for you.
- "renders_as" tells you how the layer displays the text (for example uppercase) — write
  normally cased text and let the layer transform it.
- Follow each layer's "notes": they describe what kind of phrase belongs there (kicker,
  script accent, headline, offer, label), not just a length.
- CONTACT LAYERS (role website, phone or address): only replace the text if the user's
  request explicitly contains that exact detail. Otherwise return current_text
  unchanged, verbatim. Never invent a website, phone number or address.
- All text layers must read as one coherent piece of marketing copy for the same
  product or offer — not unrelated sentences.

IMAGE PROMPTS
- Each reference_prompt encodes a composition that makes this template work: layout,
  camera angle, lighting and style. Preserve that structure.
- Change only what the request implies should change: the subject matter, the colour
  palette and the mood/style words. Do not restate the reference verbatim, and do not
  drop its structural instructions (panel layout, camera angle, "leave the centre
  empty", "transparent background, no backdrop", and so on) — they are load-bearing.
- Follow each image's "notes"; they explain how that image is layered in the design.
- The background and the subject must describe one coherent scene: same product
  category, same palette, same mood — even though they are generated separately.
- Keep each rewritten prompt about as long and detailed as its reference.
- Image prompts must never ask for text, lettering, logos or watermarks in the image.

Return exactly one text_fills entry per text layer listed (same layer_id set, no more,
no fewer) and exactly one image_prompts entry per image listed (same layer_id set).
"""

REPAIR_SYSTEM_PROMPT = """\
You are fixing copy for a fixed design template. Some text layers broke their size
limits when measured in its real font. Rewrite ONLY the layers listed as needing a fix
so they fit — shorter words, fewer words — while keeping the same meaning and tone as
the rest of the copy. Each layer's "problems" say exactly what didn't fit. Every word
must fit on one line of the box, the wrapped text must fit in max_lines lines, and the
text must stay within max_chars. Do not insert line breaks. Return one text_fills entry
for each layer that needed a fix, and nothing else.
"""


def _text_payload(target: TextTarget) -> dict:
    slot = target.slot
    return {
        "layer_id": slot.layer_id,
        "role": slot.role,
        "current_text": slot.default_text,
        "max_chars": slot.max_chars,
        "max_lines": slot.max_lines,
        "approx_chars_per_line": target.chars_per_line,
        "renders_as": target.text_transform,
        "notes": slot.notes,
    }


def build_user_message(user_prompt: str, template: LidoTemplateFile,
                       texts: list[TextTarget], images: list[ImageTarget],
                       kind: str | None = None) -> str:
    meta = template.meta
    width, height = (int(meta.canvas_size.get(k, 0)) for k in ("width", "height"))
    image_payload = [
        {
            "layer_id": t.layer_id,
            "purpose": t.spec.kind,
            "transparent": t.spec.transparent,
            "reference_prompt": t.spec.prompt,
            "notes": t.spec.notes,
        }
        for t in images
    ]
    parts = [
        "User's design request:",
        f'"""{user_prompt.strip()}"""',
    ]
    if kind:
        parts.append(f"(requested design kind: {kind})")
    parts += [
        "",
        f"Template: {meta.name or meta.id} — {meta.description}",
        f"Canvas: {width}x{height} ({meta.aspect})",
        "",
        "TEXT LAYERS — fill every one, exactly this set (do not add, remove or merge):",
        json.dumps([_text_payload(t) for t in texts], indent=2, ensure_ascii=False),
        "(Locked layers such as the logo are intentionally omitted; they never change.)",
    ]
    if image_payload:
        parts += [
            "",
            "IMAGE PROMPTS — rewrite each reference prompt for this request:",
            json.dumps(image_payload, indent=2, ensure_ascii=False),
        ]
    return "\n".join(parts)


def _repair_message(user_prompt: str, texts: list[TextTarget], current: dict[str, str],
                    problems: dict[str, list[str]]) -> str:
    needs_fix = [
        {**_text_payload(t), "your_text": current[t.layer_id], "problems": problems[t.layer_id]}
        for t in texts if t.layer_id in problems
    ]
    context = {t.layer_id: current[t.layer_id] for t in texts if t.layer_id not in problems}
    return "\n".join([
        "User's design request:",
        f'"""{user_prompt.strip()}"""',
        "",
        "Copy already accepted for the other layers (for tone; do not return these):",
        json.dumps(context, indent=2, ensure_ascii=False),
        "",
        "Layers that need a fix:",
        json.dumps(needs_fix, indent=2, ensure_ascii=False),
    ])


# --------------------------------------------------------------------------------------
# The call
# --------------------------------------------------------------------------------------


async def _complete(system: str, user: str, schema: type[BaseModel]):
    """One schema-constrained call; a recoverable failure (truncation, 5xx, rate
    limit) gets exactly one retry, anything else propagates to the caller."""
    kwargs = {
        "system": system, "user": user, "schema": schema, "max_tokens": _MAX_OUTPUT_TOKENS,
        "reasoning_effort": get_settings().lido_template_reasoning_effort,
    }
    llm = get_llm()
    try:
        return await llm.complete_json(**kwargs), 1
    except AdapterError as exc:
        if not exc.recoverable:
            raise
        log.warning("lido.template_fill.retry", error=str(exc))
        return await llm.complete_json(**kwargs), 2


def _accept_text(raw: str, target: TextTarget, user_prompt: str) -> str:
    text = normalize_text(raw, target)
    default = target.slot.default_text or ""
    if not text:
        return default
    if (target.slot.role in CONTACT_ROLES and text != default
            and not _contact_is_supported(text, target.slot.role, user_prompt)):
        log.info("lido.template_fill.contact_reverted", layer_id=target.layer_id, text=text)
        return default
    return text


async def generate_template_fill(user_prompt: str, template: LidoTemplateFile,
                                 *, kind: str | None = None) -> TemplateFill:
    """Fill every non-locked text layer and write every image prompt in one call.

    A second, text-only call happens only when the first answer broke a size limit;
    anything still over after that is trimmed by `clamp_text`. Raises `AdapterError`
    when no LLM is available — a template echoed back unchanged would look like a
    successful generation when nothing was generated.
    """
    texts = text_targets(template)
    images = image_targets(template)
    by_text_id = {t.layer_id: t for t in texts}
    image_ids = {t.layer_id for t in images}

    result, calls = await _complete(
        SYSTEM_PROMPT, build_user_message(user_prompt, template, texts, images, kind),
        LidoTemplateFillOutput,
    )
    parsed: LidoTemplateFillOutput = result.parsed
    cost = result.cost_cents

    returned_text = {f.layer_id: f.text for f in parsed.text_fills if f.layer_id in by_text_id}
    missing = [lid for lid in by_text_id if lid not in returned_text]
    if missing:
        log.warning("lido.template_fill.missing_text", layer_ids=missing)
    text = {
        lid: _accept_text(returned_text.get(lid, ""), target, user_prompt)
        for lid, target in by_text_id.items()
    }

    prompts = {p.layer_id: p.prompt.strip() for p in parsed.image_prompts
               if p.layer_id in image_ids and p.prompt.strip()}
    for target in images:
        if target.layer_id not in prompts:
            log.warning("lido.template_fill.missing_image_prompt", layer_id=target.layer_id)
            prompts[target.layer_id] = target.spec.prompt or ""

    problems = {lid: p for lid, t in by_text_id.items() if (p := check_text(text[lid], t))}
    repaired: list[str] = []
    if problems:
        log.info("lido.template_fill.repairing", problems=problems)
        try:
            fix, fix_calls = await _complete(
                REPAIR_SYSTEM_PROMPT, _repair_message(user_prompt, texts, text, problems),
                LidoTextRepairOutput,
            )
            calls += fix_calls
            cost += fix.cost_cents
            for item in fix.parsed.text_fills:
                target = by_text_id.get(item.layer_id)
                if target is None or item.layer_id not in problems:
                    continue
                candidate = _accept_text(item.text, target, user_prompt)
                if not check_text(candidate, target):
                    text[item.layer_id] = candidate
                    repaired.append(item.layer_id)
        except AdapterError as exc:
            log.warning("lido.template_fill.repair_failed", error=str(exc))

    clamped: list[str] = []
    for lid, target in by_text_id.items():
        if check_text(text[lid], target):
            text[lid] = clamp_text(text[lid], target)
            clamped.append(lid)

    return TemplateFill(text=text, image_prompts=prompts, repaired=repaired,
                        clamped=clamped, llm_calls=calls, cost_cents=cost)
