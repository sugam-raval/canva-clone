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
    "phone", "address", "website", "photo", "decoration",
]


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
    font_size: float | None = None
    position: dict[str, float] | None = None
    box_size: dict[str, float] | None = None


class LidoTemplateMeta(BaseModel):
    id: str
    name: str = ""
    kind: str = "post"
    aspect: str = "1:1"
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    canvas_size: dict[str, float]
    background_image_url: str | None = None
    slots: list[SlotInfo] = Field(default_factory=list)


class LidoTemplateFile(BaseModel):
    """What `loader.load_enriched()` returns: the untouched Lido document plus our meta."""

    layers: dict[str, LidoLayer]
    meta: LidoTemplateMeta
