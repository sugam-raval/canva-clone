"""TemplateSkeleton — IMPLEMENTATION_PLAN §1.2.

A skeleton is a DesignDoc with slots instead of content, in normalised coordinates
so one skeleton serves any canvas size within its aspect family.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .brief import DesignKind
from .doc import Base, Constraints, LayerRole, MaskShape

PaletteRole = Literal["primary", "accent", "neutral", "on-primary", "on-accent"]


class FrameN(Base):
    """Normalised 0..1 of canvas w/h."""

    x: float
    y: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)
    rotation: float = 0


class AutoFitN(Base):
    min: float = Field(gt=0, description="normalised to canvas height")
    max: float = Field(gt=0)


class TextSlotSpec(Base):
    max_chars: int = Field(gt=0)
    size_n: float = Field(gt=0, description="font size normalised to canvas height")
    weight: int = 400
    align: Literal["left", "center", "right"] = "left"
    vertical_align: Literal["top", "middle", "bottom"] = "top"
    transform: Literal["none", "uppercase", "capitalize"] = "none"
    line_height: float = 1.15
    letter_spacing_n: float = 0
    auto_fit_n: AutoFitN
    auto_height: bool = False
    # Which of the pairing's faces this slot is set in. Left unset, a headline takes the
    # display face and everything else the supporting face.
    face: Literal["display", "text", "script"] | None = None
    # Outlined type. `TextLayer.stroke` and both renderers have always supported this;
    # without a field here a skeleton had no way to ask for it.
    stroke_width_n: float = Field(default=0, ge=0)
    stroke_palette_role: PaletteRole | None = None


class ImageSlotSpec(Base):
    prompt_template: str = Field(
        description="uses {{subjectDescription}}, {{mood}}, {{palette}} placeholders"
    )
    transparent: bool = False
    aspect_preference: str | None = None
    fit: Literal["fill", "cover", "contain"] = "cover"
    # Which of the brief's subjects this slot shows. A multi-subject skeleton whose
    # slots all leave this at 0 renders the same object several times over, which reads
    # as a bug rather than as a range.
    subject_index: int = Field(default=0, ge=0, le=7)
    # Silhouette the photograph is cut to. A corpus where every picture is a rectangle
    # produces designs where every picture is a rectangle.
    mask: MaskShape | None = None
    mask_radius_n: float = Field(
        default=0, ge=0, le=0.5,
        description="corner radius for mask='rounded', as a fraction of the slot's "
                    "shorter side; 0 uses the renderer's default")


class ShapeSlotSpec(Base):
    shape: Literal["rect", "ellipse", "line", "polygon", "path"] = "rect"
    radius_n: float = 0
    fill_from_palette: bool = True
    gradient_scrim: bool = Field(
        default=False, description="render as a transparent->colour ramp, for legibility scrims"
    )
    gradient_angle: float = 90
    # Procedural ornament. When set, the slot materialises as a `path` shape whose
    # geometry comes from `app.templates_corpus.ornament`, seeded per document so the
    # same design regenerates identically (INV-2).
    motif: str | None = None
    stroke_width_n: float = Field(
        default=0, ge=0, description="stroke weight normalised to canvas height; "
                                     "ignored for motifs built from closed shapes")
    density: int = Field(default=3, ge=1, le=5, description="how much motif appears")


class Slot(Base):
    slot_id: str
    role: LayerRole
    layer_type: Literal["image", "text", "shape", "svg", "group"]
    frame_n: FrameN
    required: bool = True
    constraints: Constraints
    text: TextSlotSpec | None = None
    image: ImageSlotSpec | None = None
    shape: ShapeSlotSpec | None = None
    palette_role: PaletteRole | None = None
    z_index: int = 0
    opacity: float = Field(default=1, ge=0, le=1)
    effects: list[dict[str, Any]] = Field(default_factory=list)
    # This slot only makes sense next to another one. A tick beside a service line, a
    # keyline around a photograph, a rule under a price: if the partner is dropped
    # because the brief carried nothing for it, this goes with it.
    #
    # Role-level pairing already exists in `_included_slots`, and it is too coarse here:
    # six checklist rows all carry role `feature`, so dropping the fourth line leaves its
    # tick floating beside nothing.
    pairs_with: str | None = None


class SkeletonVariant(Base):
    id: str
    name: str = ""
    # Sparse per-slot overrides, keyed by slotId. Merged over the base slot.
    patch: dict[str, dict[str, Any]] = Field(default_factory=dict)


class TemplateSkeleton(Base):
    id: str
    name: str = ""
    kind: DesignKind
    aspect: str = Field(description="'9:16'")
    tags: list[str] = Field(default_factory=list)
    description: str = Field(description="embedded for retrieval; reads like a design brief")
    grid_baseline: int = Field(default=8, gt=0, description="solver snaps to this")
    slots: list[Slot]
    variants: list[SkeletonVariant] = Field(default_factory=list)
