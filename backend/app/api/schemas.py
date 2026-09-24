"""Request and response bodies for the Lido.js (template) API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


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
    """One entry in the corpus, for a template-picker UI. `ready` is true when a human
    has reviewed the template's metadata (`meta.reference_note`). It no longer limits
    the automatic match — every template is a candidate — it is shown for information."""
    id: str
    name: str
    kind: str
    aspect: str
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    ready: bool


class LidoMatchCandidate(Base):
    template_id: str
    score: float
    topic: float
    details: float
    held: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    empty_contact_slots: list[str] = Field(default_factory=list)


class LidoMatchInfo(Base):
    """`path` is "holds_all" when at least one template can hold every detail the user
    gave (the pick came from those), else "best_match"."""
    path: Literal["holds_all", "best_match"]
    topic_line: str
    request_details: list[str] = Field(default_factory=list)
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
