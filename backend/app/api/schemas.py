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


def checked_palette(value: list[str] | None) -> list[str] | None:
    """Up to 4 readable colours as #rrggbb (first = primary); empty means none."""
    if not value:
        return None
    return [to_hex(c) for c in parse_palette(value)]


def checked_logo_url(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        raise ValueError("logo_url must be an http(s) URL")
    return value


class LidoGenerateRequest(Base):
    """Generate a design from a Lido template — simpler prompt interface than DesignBrief.

    `template_id` picks an exact template from the corpus (by file stem), overriding
    retrieval entirely; `random_template` picks uniformly across the whole corpus
    instead. Giving both is treated as `template_id` winning; giving neither uses the
    automatic match (docs/new_match_plan.md): templates that can hold every detail the user
    gave come first, then the best topic + details match. The response's `match` says
    how it decided."""
    prompt: str = Field(min_length=1, max_length=2000)
    kind: Literal["story", "post", "poster", "banner", "thumbnail", "ad", "flyer",
                 "leaflet"] | None = None
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

    _valid_palette = field_validator("palette")(checked_palette)
    _valid_logo_url = field_validator("logo_url")(checked_logo_url)


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


class LidoDraftRequest(Base):
    """Design brand-new template(s) from a prompt (`POST /v1/lido/drafts`). Each variation
    is designed in a different creative direction and saved to lidojs_templates/drafts/."""
    prompt: str = Field(min_length=3, max_length=4000)
    variations: int = Field(default=1, ge=1, le=3)
    palette: list[str] | None = Field(default=None, max_length=4)
    """Optional brand colours, the same as `LidoGenerateRequest.palette`: up to 4
    (#rrggbb), the first primary. Every variation is drawn in exactly these instead of
    colours the designer picks. Omitted or empty: the designer chooses."""
    logo_url: str | None = None
    """Optional brand logo image URL (http/https). Every variation then gets a logo
    element showing it. Omitted: the stock placeholder logo, if the design has one."""

    _valid_palette = field_validator("palette")(checked_palette)
    _valid_logo_url = field_validator("logo_url")(checked_logo_url)


class LidoDraftInfo(Base):
    """One draft template awaiting review. `document` is only sent when a single draft
    is requested (or just created); the list omits it."""
    id: int
    """`lido_drafts.id`."""
    created_at: datetime
    source: str = "recipe"
    """"brief" (designed from a prompt), "ai" (CLI --ai), "recipe" (CLI) or "manual"."""
    prompt: str | None = None
    name: str | None = None
    idea: str | None = None
    direction: str | None = None
    layout: str | None = None
    theme: str | None = None
    palette: str | None = None
    fonts: str | None = None
    mirrored: bool = False
    colors: dict[str, str] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)
    """The feature families this design was asked to use (gradient, frame, draw…)."""
    plan: dict[str, Any] | None = None
    """The art director's plan: photos and their subjects, texts, moods, layout…"""
    plan_layout: str | None = None
    fingerprint: str | None = None
    text_count: int | None = None
    photo_subjects: list[str] = Field(default_factory=list)
    """What each photo should show — the prompts photo generation uses."""
    photo_source: str | None = None
    """corpus-cache (placeholder photos) or generated (rendered from photo_subjects)."""
    photo_fallbacks: int = 0
    """Photos that failed to generate and kept a cached placeholder instead."""
    attempts: int | None = None
    problems: list[str] = Field(default_factory=list)
    """Design checks still failing after the repair rounds; empty when it passes."""
    brand_palette: list[str] | None = None
    """The brand colours it was asked to use (LidoDraftRequest.palette), if any."""
    logo_url: str | None = None
    """The client logo it shows, if one was given."""
    generation_ms: int | None = None
    """How long designing it took, request start → this draft saved (null: unknown)."""
    timing: dict[str, int] = Field(default_factory=dict)
    """The same step by step, in ms: planMs, designMs, photosMs, saveMs, totalMs."""
    imported_from: str | None = None
    """The template_<n> file it was imported from (scripts/lido_drafts.py import)."""
    has_preview: bool = False
    preview_url: str | None = None
    document: list[dict[str, Any]] | None = None
