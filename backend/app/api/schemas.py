"""Request and response bodies for §0.10. Validated with the same models the LLM is
constrained against, so the API and the pipeline can never disagree about shape."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schema.doc import Base


class GenerateRequest(Base):
    prompt: str = Field(min_length=1, max_length=4000)
    kind: str | None = None
    size: dict[str, int] | None = None
    brand_kit_id: str | None = None
    count: int = Field(default=1, ge=1, le=4)


class GenerateResponse(Base):
    request_id: str
    doc_ids: list[str] = Field(default_factory=list)


class RegenerateRequest(Base):
    prompt_override: str | None = None
    seed: int | None = None
    strength: float | None = Field(default=None, ge=0, le=1)


class ReshapeRequest(Base):
    """Rebuild a vector motif. Every field is optional; omitting `seed` re-rolls."""

    motif: str | None = None
    seed: int | None = Field(default=None, ge=0)
    density: int | None = Field(default=None, ge=1, le=5)


class ExpandRequest(Base):
    edges: dict[str, float] = Field(default_factory=dict, description="l, r, t, b in px")
    prompt: str | None = None


class EraseRequest(Base):
    mask_asset_id: str | None = None
    brush_path: list[list[float]] | None = None
    brush_width: float = 40.0


class RewriteRequest(Base):
    layer_ids: list[str] = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=1000)


class ResizeRequest(Base):
    width: int = Field(gt=0, le=20000)
    height: int = Field(gt=0, le=20000)


# Lido corpus endpoints

class LidoGenerateRequest(Base):
    """Generate a design from a Lido template — simpler prompt interface than DesignBrief."""
    prompt: str = Field(min_length=1, max_length=2000)
    kind: Literal["story", "post", "poster", "banner", "thumbnail", "ad", "flyer"] | None = None


class LidoSlotFillInfo(Base):
    layer_id: str
    role: str
    text: str


class LidoAssetInfo(Base):
    layer_id: str
    url: str


class LidoGenerateResponse(Base):
    """A filled Lido document ready to open in the editor."""
    document: list[dict[str, Any]]
    template_id: str
    template_score: float
    text_fills: list[LidoSlotFillInfo] = Field(default_factory=list)
    image_fills: list[LidoAssetInfo] = Field(default_factory=list)


class ExportRequest(Base):
    format: Literal["png", "jpeg", "webp", "pdf", "svg"] = "png"
    scale: float = Field(default=1.0, gt=0, le=4)


class ExportResponse(Base):
    export_id: str
    state: str
    url: str | None = None


class PatchRequest(Base):
    """JSON-merge patch for non-CRDT clients and server-side ops (§0.10)."""

    layers: list[dict[str, Any]] | None = None
    canvas: dict[str, Any] | None = None
    palette: list[str] | None = None
    title: str | None = None
