"""Pydantic models for Lido.js's native JSON.

Two tiers, deliberately different in strictness:

- `Lido*` models mirror the editor's own shape. They use `extra="allow"` because `props`
  varies by `resolvedName` (TextLayer/FrameLayer/ShapeLayer/RootLayer all differ) and the
  editor may add fields we don't know about yet — the goal here is "parse without losing
  data on round-trip", not full validation.
- `LidoTemplateMeta` / `SlotInfo` are OUR addition: a `meta` block the loader injects
  into each template file so retrieval has something to search against. This is the part
  that "reaches for context" — description, tags, kind, and a manifest of fillable slots
  derived from each layer's semantic `type.type` tag.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------------------
# Raw Lido document (pass-through)
# --------------------------------------------------------------------------------------


class LidoBase(BaseModel):
    model_config = ConfigDict(extra="allow")


class LidoLayerType(LidoBase):
    """The `type` object on a layer.

    `type.type` is Lido's own semantic tag (`"bodyText"`, `"static"`, `"phoneNumber"`,
    `"address"`, `"website"`, `"logo"`, `"bgImage"`) — this is what tells a filler which
    layers are safe to rewrite and which (`"static"`, carrying `fixedText`) must not be
    touched. `resolvedName` is the component class: `TextLayer` / `FrameLayer` /
    `ShapeLayer` / `RootLayer`.
    """

    type: str | None = None
    resolvedName: str
    fixedText: str | None = None
    replacableText: str | None = None


class LidoLayer(LidoBase):
    type: LidoLayerType
    child: list[str] = Field(default_factory=list)
    props: dict[str, Any] = Field(default_factory=dict)
    locked: bool = False
    parent: str | None = None


class LidoDocument(LidoBase):
    """`layers["ROOT"]` is always the canvas/background; everything else hangs off it
    (possibly nested, via `parent`/`child`, though these 5 fixtures are all flat)."""

    layers: dict[str, LidoLayer]


# --------------------------------------------------------------------------------------
# Our enrichment — injected as a sibling `meta` key, not read by the Lido editor itself
# --------------------------------------------------------------------------------------

SlotRole = Literal[
    "background", "logo", "headline", "subhead", "body", "label",
    "phone", "email", "address", "website", "photo", "decoration",
]

ImageKind = Literal[
    "background_photo", "subject_cutout", "logo_static", "decorative_shape",
]


class ImageSpec(BaseModel):
    """How to source the image for an image-bearing layer (ROOT background, or a
    `photo`/`logo` slot). Human-authored — never recomputed from geometry, so it survives
    re-enrichment (`scripts/enrich_lido_templates.py`) the same way `name`/`kind`/`description` do.

    - `kind` distinguishes a full-bleed background photo from a foreground subject
      cutout from a static, never-regenerated logo from a decorative shape.
    - `transparent=True` means the asset must be an alpha-channel PNG containing only
      the subject (no backdrop) — as opposed to an ordinary rectangular photo that
      Lido's own `clipPath` crops into a shape. This matters because a generator that
      treats every `photo` slot as "cover-cropped opaque photography" (see
      `assets_ai.py`) will produce a rectangular photo with visible background inside
      the crop, not a clean cutout — the two only look the same when the subject
      happens to fill its mask exactly.
    - `prompt` is the exact, reusable image-generation instruction for this slot —
      specific enough that regenerating from it reproduces the same kind of asset.
    - `generate=False` marks an asset that must never be regenerated or re-styled
      (e.g. a brand logo) even though it lives in an image-bearing layer.
    """

    kind: ImageKind
    generate: bool = True
    transparent: bool = False
    prompt: str | None = None
    reference_url: str | None = None
    notes: str | None = None


class SlotInfo(BaseModel):
    layer_id: str
    resolved_name: str
    role: SlotRole
    editable: bool
    """True for any `TextLayer` carrying text (default-text or fixed label alike) — these
    templates are scratch layout material, not fixed branding, so a "static" label like
    "Contact:" is just as fair to rewrite as a headline. False only for layers with no
    text to rewrite at all: the background, logo/photo frames, and decorative shapes."""
    default_text: str | None = None
    max_chars: int | None = None
    max_lines: int | None = None
    """Human-authored line-count ceiling (e.g. a headline meant to stay one line even
    if `max_chars` alone would allow a wrap). `None` means no explicit limit was set."""
    locked: bool = False
    """True for a slot that must never be swapped, resized, or have its image/text
    regenerated (e.g. a brand logo). Distinct from `editable`, which is about text-fill
    behavior only."""
    font_size: float | None = None
    position: dict[str, float] | None = None
    box_size: dict[str, float] | None = None
    image: ImageSpec | None = None
    """Set only for image-bearing slots (`role in {"photo", "logo"}`). Human-authored,
    preserved across re-enrichment the same way `max_chars`/`notes`/`locked` are."""
    notes: str | None = None
    """Freeform human-authored guidance for this specific slot — preserved across
    re-enrichment. Use for anything an automated filler needs to know that doesn't fit
    a typed field (e.g. "keep to a single word", "ignore the source photo's centered
    subject — a separate cutout layer covers it")."""


class LidoTemplateMeta(BaseModel):
    id: str
    name: str = ""
    kind: str = "post"
    aspect: str = "1:1"
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    canvas_size: dict[str, float]
    background_image_url: str | None = None
    background: ImageSpec | None = None
    """Human-authored generation spec for the ROOT background image. `slots` never
    contains a ROOT entry, so this is where that guidance lives."""
    text_layer_count: int | None = None
    """Exact count of text layers this template ships with — a generator referencing
    this template as an exemplar should match this count, not add or drop layers."""
    reference_note: str | None = None
    """Freeform human-authored guidance for the template as a whole — preserved across
    re-enrichment. Use this for exemplar templates meant to guide future generation."""
    slots: list[SlotInfo] = Field(default_factory=list)


class LidoTemplateFile(BaseModel):
    """What `loader.load_enriched()` returns: the untouched Lido document plus our meta."""

    layers: dict[str, LidoLayer]
    meta: LidoTemplateMeta
