"""The draw list — IMPLEMENTATION_PLAN §0.11.

`toDrawList(doc, scale)` is the single implementation of scene-graph -> draw commands.
Per ADR 0001 the server owns it outright: the browser receives this list as JSON and
feeds it to a thin Konva backend, so there is exactly one implementation and INV-3
holds by construction rather than by convention.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .doc import Adjustments, Base, BlendMode


class Matrix2D(Base):
    """Column-major affine: [a c e / b d f / 0 0 1], same convention as canvas2d."""

    a: float = 1
    b: float = 0
    c: float = 0
    d: float = 1
    e: float = 0
    f: float = 0


class Rect(Base):
    x: float
    y: float
    w: float
    h: float


class PositionedGlyph(Base):
    """A shaped glyph. Positions come from HarfBuzz, never from a renderer."""

    gid: int = Field(description="glyph id in the font, not a codepoint")
    cluster: int = Field(default=0, description="byte offset into the source string")
    x: float
    y: float
    # The literal character(s) this glyph came from. The Konva backend draws text by
    # string (browsers will not accept glyph ids), so it needs this; the Skia backend
    # ignores it and draws `gid` directly.
    text: str = ""


class PositionedGlyphRun(Base):
    font_family: str
    font_weight: int = 400
    font_style: Literal["normal", "italic"] = "normal"
    font_size: float
    # Resolved font file this run was shaped with, so the server draws the same face.
    font_key: str = ""
    glyphs: list[PositionedGlyph] = Field(default_factory=list)
    # Baseline origin of the run, in the layer's local space.
    origin_x: float = 0
    origin_y: float = 0
    advance: float = 0
    direction: Literal["ltr", "rtl"] = "ltr"


class ClearCmd(Base):
    op: Literal["clear"] = "clear"
    color: str


class SaveTransformCmd(Base):
    op: Literal["saveTransform"] = "saveTransform"
    # The layer this command group belongs to. Each layer emits exactly one
    # saveTransform/restore pair, which is how the editor maps a canvas hit back to a
    # layer without reimplementing hit testing.
    layer_id: str = ""
    layer_type: str = ""
    role: str = ""
    locked: bool = False
    name: str = ""
    matrix: Matrix2D
    opacity: float = 1
    blend: BlendMode = "normal"
    clip: Rect | None = None
    # Size of the layer in its own local space, for drawing selection handles.
    size: Rect | None = None
    # Effects apply to everything drawn until the matching `restore`. See the note in
    # renderer/core.py on why this replaces §0.11's separate EffectCmd + index range.
    effects: list[dict] = Field(default_factory=list)


class RestoreCmd(Base):
    op: Literal["restore"] = "restore"


class ImageCmd(Base):
    op: Literal["image"] = "image"
    asset_url: str
    asset_id: str = ""
    dest: Rect
    crop: Rect | None = Field(default=None, description="source rect in natural px")
    opacity: float = 1
    blend: BlendMode = "normal"
    adjust: Adjustments | None = None
    radius: float = 0
    # Silhouette to cut the image to, in the layer's local space. Computed server-side so
    # both backends clip to the same geometry rather than each deriving it from `mask`.
    clip_path: str | None = None


class TextRunCmd(Base):
    op: Literal["textRun"] = "textRun"
    runs: list[PositionedGlyphRun] = Field(default_factory=list)
    color: str = "#000000"
    stroke_color: str | None = None
    stroke_width: float = 0
    layer_id: str = ""


class PathCmd(Base):
    op: Literal["path"] = "path"
    d: str = Field(description="SVG path data in the current transform space")
    fill: str | None = None
    stroke: str | None = None
    stroke_width: float = 0
    dash: list[float] | None = None
    gradient: dict | None = None
    # Butt caps and mitre joins are right for a rule and wrong for a pictogram: a tick
    # drawn with them ends in two chisels and spikes at the elbow.
    cap: Literal["butt", "round", "square"] = "butt"
    join: Literal["miter", "round", "bevel"] = "miter"


class PlaceholderCmd(Base):
    """A pending asset slot. Rendered as a flat palette-coloured rect (§1.3)."""

    op: Literal["placeholder"] = "placeholder"
    dest: Rect
    color: str
    layer_id: str = ""
    radius: float = 0
    clip_path: str | None = None


class EffectCmd(Base):
    op: Literal["effect"] = "effect"
    effect: dict
    target_index_range: tuple[int, int]


DrawCommand = Annotated[
    ClearCmd | SaveTransformCmd | RestoreCmd | ImageCmd | TextRunCmd | PathCmd | PlaceholderCmd | EffectCmd,
    Field(discriminator="op"),
]


class DrawList(Base):
    width: int
    height: int
    scale: float = 1
    commands: list[DrawCommand] = Field(default_factory=list)
