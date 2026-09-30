"""Request and response bodies for the Lido.js (template) API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.lido_corpus.palette import parse_palette, to_hex


class Base(BaseModel):
    """Wire format is camelCase; Python is snake_case; both are accepted on input."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True,
                              extra="forbid")


class LidoGenerateRequest(Base):
    """Generate a design from a Lido template — simpler prompt interface than DesignBrief.

    `template_id` picks an exact template from the corpus (by file stem), overriding
    retrieval entirely; `random_template` picks uniformly across the whole corpus
    instead. Giving both is treated as `template_id` winning; giving neither uses the
    automatic match (docs/new_match_plan.md): templates that can hold every detail the user
    gave come first, then the best topic + details match. The response's `match` says
    how it decided."""
    prompt: str = Field(min_length=1, max_length=2000)
    kind: Literal["story", "post", "poster", "banner", "thumbnail", "ad", "flyer"] | None = None
    generate_images: bool = True
    template_id: str | None = None
    random_template: bool = False
    palette: list[str] | None = Field(default=None, max_length=4)
    """Optional colour theme: up to 4 colours (#rrggbb), the first one primary. Applied
    during generation to text, shapes and images (docs/palette_theme.md); template search
    ignores it. Omitted or empty: generation is unchanged."""
    logo_url: str | None = None
    """Optional brand logo image URL. When given, it replaces the chosen template's logo
    slot directly (a plain URL swap, no AI involved) — even though logo slots are
    normally `locked` against every other kind of write. Omitted: the template's own
    logo (if any) is left as-is. Ignored if the template has no logo slot."""

    @field_validator("palette")
    @classmethod
    def _valid_palette(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        return [to_hex(c) for c in parse_palette(value)]

    @field_validator("logo_url")
    @classmethod
    def _valid_logo_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not value.startswith(("http://", "https://")):
            raise ValueError("logo_url must be an http(s) URL")
        return value


class LidoSlotFillInfo(Base):
    layer_id: str
    role: str
    text: str


class LidoAssetInfo(Base):
    layer_id: str
    url: str


class LidoImagePromptInfo(Base):
    layer_id: str
    prompt: str


class LidoTemplateSummary(Base):
    """One entry in the corpus, for a template-picker UI. Every template is a
    candidate for the automatic match."""
    id: str
    name: str
    kind: str
    aspect: str
    tags: list[str] = Field(default_factory=list)
    description: str = ""


class LidoMatchCandidate(Base):
    template_id: str
    score: float
    topic: float
    details: float
    held: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    empty_contact_slots: list[str] = Field(default_factory=list)
    tier: Literal["A", "B", "C"] = "A"
    """A: places every line and detail; B: keeps every must-keep item (headline, offer,
    price, contact); C: the rest (docs/slot_fit_match_plan.md §7)."""
    coverage: float = 1.0
    placed_lines: list[str] = Field(default_factory=list)
    dropped_lines: list[str] = Field(default_factory=list)


class LidoMatchInfo(Base):
    """`path` is "holds_all" when the pick places every line and detail the user gave,
    else "best_match" (its `droppedLines` say what had no room)."""
    path: Literal["holds_all", "best_match"]
    tier: Literal["A", "B", "C"] = "A"
    topic_line: str
    request_details: list[str] = Field(default_factory=list)
    requested_lines: list[str] = Field(default_factory=list)
    used_llm: bool
    embedder: str
    candidates: list[LidoMatchCandidate] = Field(default_factory=list)


class LidoGenerateResponse(Base):
    """A filled Lido document ready to open in the editor, also saved to `lido_generations`."""
    document: list[dict[str, Any]]
    template_id: str
    template_score: float
    design_id: str
    text_fills: list[LidoSlotFillInfo] = Field(default_factory=list)
    image_fills: list[LidoAssetInfo] = Field(default_factory=list)
    image_prompts: list[LidoImagePromptInfo] = Field(default_factory=list)
    image_failures: list[str] = Field(default_factory=list)
    dropped_lines: list[str] = Field(default_factory=list)
    """Lines the user asked for that had no room in the template — never silently lost."""
    theme: dict[str, Any] | None = None
    """How the palette was applied (colour map, per-layer text colours, contrast fixes);
    null when no palette was chosen."""
    match: LidoMatchInfo | None = None
    """How the automatic match picked the template; None for an explicit or random pick."""


class LidoGenerationSummary(Base):
    """One row of `lido_generations` (infra/initdb/002_lido_generations.sql). Reopen
    the full document via `GET /v1/lido/generations/{id}`. `path` is legacy: only set on
    a design promoted in from the old file-based storage; new rows leave it null."""
    id: str
    template_id: str | None = None
    name: str = ""
    kind: str = "post"
    aspect: str = "1:1"
    prompt: str = ""
    canvas_size: dict[str, Any] = Field(default_factory=dict)
    thumbnail_url: str | None = None
    path: str | None = None
    created_at: datetime
