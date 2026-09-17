"""The document schema. IMPLEMENTATION_PLAN §0.5.

This module is the SOURCE OF TRUTH for the entire system. The JSON Schema emitted
from these models is what the LLM composer is constrained against (§1.3), what the
HTTP layer validates against (§0.10), and what the renderer consumes (§0.11).

Do not change `schemaVersion` semantics without adding a migration in `migrate.py`
and a fixture in `fixtures/`.

Field names are camelCase on the wire (matching the plan's TypeScript verbatim) and
snake_case in Python, bridged by `alias_generator`. Always dump with `by_alias=True`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

DocId = str
LayerId = str

SCHEMA_VERSION = 3


class Base(BaseModel):
    """Wire format is camelCase; Python is snake_case; both are accepted on input."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        validate_assignment=False,
    )


# --------------------------------------------------------------------------------------
# Canvas, fonts, provenance
# --------------------------------------------------------------------------------------

HEX = r"^(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|transparent|none)$"


class Canvas(Base):
    width: int = Field(gt=0, le=20000, description="px at scale 1")
    height: int = Field(gt=0, le=20000)
    background: str = Field(default="#FFFFFF", pattern=HEX)
    safe_margin: float = Field(default=0, ge=0, description="px; solver keeps content inside")
    dpi: int = Field(default=72, ge=36, le=1200, description="72 screen, 300 print")


class FontRef(Base):
    family: str
    weights: list[int] = Field(default_factory=lambda: [400])
    source: Literal["google", "system", "hosted"] = "google"
    url: str | None = None


class GeneratedProvenance(Base):
    kind: Literal["generated"] = "generated"
    brief: dict[str, Any]
    template_id: str
    request_id: str
    # What `art.direct` decided this design's imagery and ornament would be. Recorded
    # because the layout no longer determines the picture: without it, a document says
    # which skeleton it used and nothing about why its background is a marble vanity.
    art_direction: dict[str, Any] | None = None


class DecomposedProvenance(Base):
    # Part Two is not built yet (deferred). The variant stays in the schema so
    # documents written by a future decomposer validate against version 3.
    kind: Literal["decomposed"] = "decomposed"
    source_asset_id: str
    pipeline_version: str
    confidence: float = Field(ge=0, le=1)


class BlankProvenance(Base):
    kind: Literal["blank"] = "blank"


class DuplicatedProvenance(Base):
    kind: Literal["duplicated"] = "duplicated"
    from_doc_id: DocId


Provenance = Annotated[
    GeneratedProvenance | DecomposedProvenance | BlankProvenance | DuplicatedProvenance,
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------------------
# Geometry and shared layer parts
# --------------------------------------------------------------------------------------

LayerRole = Literal[
    "background", "subject", "object", "decoration",
    "headline", "subhead", "body", "cta", "caption",
    # Promotional and contact roles. These are text like any other — they exist as
    # distinct roles because the solver, the harmoniser and the composer all need to
    # tell "the phone number" apart from "a caption" to place and size it correctly.
    "offer", "price", "terms", "feature", "event", "contact",
    "logo", "badge", "overlay", "unknown",
]

BlendMode = Literal[
    "normal", "multiply", "screen", "overlay", "soft-light", "darken",
    "lighten", "color-dodge", "difference",
]


class Frame(Base):
    x: float
    y: float
    w: float = Field(ge=0)
    h: float = Field(ge=0)
    rotation: float = Field(default=0, description="degrees clockwise about the frame centre")
    flip_x: bool = False
    flip_y: bool = False


class ShadowEffect(Base):
    kind: Literal["shadow"] = "shadow"
    dx: float = 0
    dy: float = 0
    blur: float = Field(default=0, ge=0)
    color: str = Field(default="#000000", pattern=HEX)
    opacity: float = Field(default=0.3, ge=0, le=1)
    spread: float = 0


class BlurEffect(Base):
    kind: Literal["blur"] = "blur"
    radius: float = Field(ge=0)


class StrokeEffect(Base):
    kind: Literal["stroke"] = "stroke"
    color: str = Field(pattern=HEX)
    width: float = Field(ge=0)


class GlowEffect(Base):
    kind: Literal["glow"] = "glow"
    color: str = Field(pattern=HEX)
    radius: float = Field(ge=0)
    opacity: float = Field(default=1, ge=0, le=1)


Effect = Annotated[
    ShadowEffect | BlurEffect | StrokeEffect | GlowEffect,
    Field(discriminator="kind"),
]


class Constraints(Base):
    """Drives resize-to-other-format (§4.2)."""

    horizontal: Literal["left", "right", "center", "scale", "stretch"] = "left"
    vertical: Literal["top", "bottom", "middle", "scale", "stretch"] = "top"
    lock_aspect: bool = False
    optional: bool = False
    priority: int = Field(default=50, ge=0, le=100, description="0 drop first .. 100 never drop")
    # The layer this one is part of: a tick beside its service line, a keyline around
    # its photograph, a rule under its quote. The solver moves the pair as one unit and
    # never resolves them against each other — without it, packing a six-row checklist
    # lifts the copy and leaves the ticks where they were.
    pairs_with: LayerId | None = None
    allow_overlap: bool = Field(
        default=False,
        description="this layer is meant to overlap its neighbours — display type set "
                    "behind a subject, a prop layered over one. The solver leaves such "
                    "pairs alone instead of separating them, and they are not reported "
                    "as collisions.")


class GenerationParams(Base):
    """Everything needed to regenerate this layer's pixels. Enforces INV-2."""

    adapter: str
    model: str
    prompt: str
    negative_prompt: str | None = None
    seed: int = 0
    params: dict[str, Any] = Field(default_factory=dict)
    produced_at: str | None = None


class ExtractionInfo(Base):
    """Populated only by Part Two. Kept for schema-version compatibility."""

    method: Literal["sam-box", "sam-auto", "ocr", "vectorize", "background"]
    detection_label: str | None = None
    detection_score: float | None = None
    mask_area: float = 0
    matte_confidence: float = 0
    was_occluded: bool = False
    back_plate_inpainted: bool = False


class OrnamentParams(Base):
    """How a vector motif was built.

    The imagery analogue is `GenerationParams`, and the reason to keep this is the same:
    without it the document holds only the resulting path, which can be recoloured but
    never re-rolled, re-densified or swapped for another motif — and cannot be rebuilt
    from the document alone, which is what INV-2 asks of every generated artefact.
    """

    motif: str
    seed: int = 0
    density: int = Field(default=3, ge=1, le=5)


class LayerMeta(Base):
    generation: GenerationParams | None = None
    ornament: OrnamentParams | None = None
    extraction: ExtractionInfo | None = None
    notes: dict[str, Any] = Field(default_factory=dict)


class BaseLayer(Base):
    id: LayerId
    name: str = ""
    role: LayerRole = "unknown"
    frame: Frame
    opacity: float = Field(default=1, ge=0, le=1)
    blend_mode: BlendMode = "normal"
    visible: bool = True
    locked: bool = False
    clip_to_parent: bool = False
    effects: list[Effect] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    meta: LayerMeta = Field(default_factory=LayerMeta)


# --------------------------------------------------------------------------------------
# Layer variants
# --------------------------------------------------------------------------------------


class Adjustments(Base):
    brightness: float = Field(default=0, ge=-1, le=1)
    contrast: float = Field(default=0, ge=-1, le=1)
    saturation: float = Field(default=0, ge=-1, le=1)
    temperature: float = Field(default=0, ge=-1, le=1, description="-1 cool .. 1 warm")
    hue_rotate: float = Field(default=0, ge=-360, le=360)


class Crop(Base):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class Size(Base):
    w: float = Field(ge=0)
    h: float = Field(ge=0)


# The silhouette a photograph is cut to. Rectangles are the default and always will be,
# but a design where every picture is a rectangle is the plainest design there is: the
# reference work this corpus chases puts portraits in arches, product shots in circles
# and offers in diamonds. The path is built once, server-side, in `renderer.core`, so
# Konva and Skia cut identical shapes (INV-3).
MaskShape = Literal[
    "rounded", "circle", "ellipse", "diamond", "arch", "arch-down", "hexagon",
    "leaf", "squircle", "pill",
]


class ImageLayer(BaseLayer):
    type: Literal["image"] = "image"
    asset_id: str = Field(default="", description="empty string = placeholder, asset pending")
    has_alpha: bool = False
    natural_size: Size = Field(default_factory=lambda: Size(w=0, h=0))
    fit: Literal["fill", "cover", "contain"] = "cover"
    crop: Crop | None = None
    adjust: Adjustments | None = None
    # Part Two fields, unused for now.
    back_plate_asset_id: str | None = None
    occlusion_group: str | None = None
    # Placeholder colour shown while `asset_id` is empty (§1.3 progressive delivery).
    placeholder_color: str | None = Field(default=None, pattern=HEX)
    mask: MaskShape | None = None
    mask_radius: float = Field(
        default=0, ge=0, description="px corner radius, for mask='rounded'")


class Backdrop(Base):
    color: str = Field(pattern=HEX)
    opacity: float = Field(default=1, ge=0, le=1)
    padding: float = Field(default=0, ge=0)
    radius: float = Field(default=0, ge=0)


class AutoFit(Base):
    min: float = Field(gt=0)
    max: float = Field(gt=0)
    mode: Literal["shrink", "shrink-grow"] = "shrink"


class TextStroke(Base):
    color: str = Field(pattern=HEX)
    width: float = Field(ge=0)


class TextLayer(BaseLayer):
    """INV-1: a text layer must never be replaced by a raster."""

    type: Literal["text"] = "text"
    content: str = ""
    font_family: str = "Inter"
    font_weight: int = Field(default=400, ge=100, le=1000)
    font_style: Literal["normal", "italic"] = "normal"
    font_size: float = Field(default=16, gt=0)
    line_height: float = Field(default=1.2, gt=0, le=10)
    letter_spacing: float = 0
    align: Literal["left", "center", "right"] = "left"
    vertical_align: Literal["top", "middle", "bottom"] = "top"
    color: str = Field(default="#000000", pattern=HEX)
    text_transform: Literal["none", "uppercase", "capitalize"] = "none"
    auto_fit: AutoFit | None = None
    auto_height: bool = False
    stroke: TextStroke | None = None
    backdrop: Backdrop | None = None


class ShapeStroke(Base):
    color: str = Field(pattern=HEX)
    width: float = Field(ge=0)
    dash: list[float] | None = None
    cap: Literal["butt", "round", "square"] = "butt"
    join: Literal["miter", "round", "bevel"] = "miter"


class ShapeLayer(BaseLayer):
    type: Literal["shape"] = "shape"
    shape: Literal["rect", "ellipse", "line", "polygon", "path"] = "rect"
    fill: str | None = Field(default=None, pattern=HEX)
    stroke: ShapeStroke | None = None
    radius: float = Field(default=0, ge=0, description="rect corner radius; 999 => pill")
    points: list[float] | None = None
    path_data: str | None = None
    # Linear gradient fill, used by the contrast scrim escalation in §1.5.2.
    gradient: LinearGradient | None = None


class GradientStop(Base):
    offset: float = Field(ge=0, le=1)
    color: str = Field(pattern=HEX)
    opacity: float = Field(default=1, ge=0, le=1)


class LinearGradient(Base):
    kind: Literal["linear"] = "linear"
    angle: float = Field(default=90, description="degrees; 90 = top to bottom")
    stops: list[GradientStop] = Field(min_length=2)


class SvgLayer(BaseLayer):
    type: Literal["svg"] = "svg"
    asset_id: str = ""
    color_map: dict[str, str] = Field(default_factory=dict)
    preserve_aspect: bool = True


class GroupLayer(BaseLayer):
    type: Literal["group"] = "group"
    children: list[Layer] = Field(default_factory=list)


Layer = Annotated[
    ImageLayer | TextLayer | ShapeLayer | SvgLayer | GroupLayer,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------------------


class DesignDoc(Base):
    id: DocId
    schema_version: Literal[3] = 3
    title: str = "Untitled"
    canvas: Canvas
    layers: list[Layer] = Field(default_factory=list, description="paint order: index 0 = bottom")
    palette: list[str] = Field(default_factory=list)
    fonts: list[FontRef] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=BlankProvenance)
    created_at: str = ""
    updated_at: str = ""


ShapeLayer.model_rebuild()
GroupLayer.model_rebuild()
DesignDoc.model_rebuild()


# --------------------------------------------------------------------------------------
# Traversal helpers — used everywhere, defined once.
# --------------------------------------------------------------------------------------


def walk(layers: list[Any], _ancestors: tuple[Any, ...] = ()):
    """Depth-first over the layer tree, yielding (layer, ancestors) bottom-up in paint order."""
    for layer in layers:
        yield layer, _ancestors
        if getattr(layer, "type", None) == "group":
            yield from walk(layer.children, _ancestors + (layer,))


def find_layer(doc: DesignDoc, layer_id: str):
    """Return (layer, ancestors) or (None, ())."""
    for layer, ancestors in walk(doc.layers):
        if layer.id == layer_id:
            return layer, ancestors
    return None, ()


def replace_layer(layers: list[Any], layer_id: str, new_layer: Any) -> bool:
    """In-place replace by id, recursing into groups. Returns True if replaced."""
    for i, layer in enumerate(layers):
        if layer.id == layer_id:
            layers[i] = new_layer
            return True
        if getattr(layer, "type", None) == "group" and replace_layer(
            layer.children, layer_id, new_layer
        ):
            return True
    return False
