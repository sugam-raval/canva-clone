"""`template.retrieve` — IMPLEMENTATION_PLAN §1.2.

Hard filters first (kind, aspect, text-only vs subject), then vector similarity blended
with `quality_score`. Returns 3 candidates for the composer to choose between.
"""

from __future__ import annotations

import math

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError
from app.adapters.registry import embedder as get_embedder
from app.db import repo
from app.schema.brief import DesignBrief
from app.schema.template import TemplateSkeleton

log = structlog.get_logger(__name__)

# Aspect families the corpus is authored against.
KNOWN_ASPECTS: dict[str, float] = {
    "9:16": 9 / 16,
    "4:5": 4 / 5,
    "1:1": 1.0,
    "1:1.414": 1 / 1.414,
    "1.91:1": 1.91,
    "16:9": 16 / 9,
    "3:1": 3.0,
}


def nearest_aspect(width: int, height: int) -> str:
    """Closest authored aspect family, compared in log space so 3:1 and 1:3 are equally
    far from 1:1."""
    target = width / max(1, height)
    return min(KNOWN_ASPECTS, key=lambda name: abs(math.log(KNOWN_ASPECTS[name] / target)))


def render_brief_as_search_text(brief: DesignBrief) -> str:
    """The query embedded against `templates.description`.

    Descriptions are written as design briefs (§1.2), so the query is phrased the same
    way rather than as a keyword bag.
    """
    parts = [f"A {' '.join(brief.mood) or 'clean'} {brief.kind}"]
    if brief.subject_description:
        parts.append(f"featuring {brief.subject_description}")
    else:
        parts.append("with no photographic subject, typography only")

    placement = brief.layout_hints.subject_placement
    if placement:
        parts.append(f"with the subject placed {placement}")
    parts.append(f"{brief.layout_hints.density} composition")
    parts.append(f"{brief.typography.vibe} typography")

    copy = brief.copy_text
    filled = [name for name, value in (
        ("headline", copy.headline), ("subhead", copy.subhead), ("body", copy.body),
        ("call to action", copy.cta), ("caption", copy.caption),
        ("an offer line", copy.offer), ("a price", copy.price),
        ("a discount badge", copy.badge), ("terms and fine print", copy.terms),
        ("event date and venue", copy.event_details)) if value]
    if copy.features:
        filled.append(f"a list of {len(copy.features)} short feature lines")
    if copy.tags:
        filled.append(f"a row of {len(copy.tags)} short keyword tags")
    if copy.contact.has_any():
        filled.append("a contact strip with phone, website and address")
    if filled:
        parts.append("needs slots for " + ", ".join(filled))

    # Descriptions in the corpus are written as design briefs, so the vocabulary a
    # promotional layout is described with has to appear in the query or the
    # information-dense skeletons never surface for the requests that need them.
    if copy.offer or copy.price or copy.badge:
        parts.append("a promotional discount layout with a price badge")
    if copy.features or copy.tags or copy.contact.has_any():
        parts.append("an information-dense business layout that carries a lot of copy")
    if copy.tags:
        parts.append("a tech stack or skill set shown as a row of keyword chips")
    if copy.body and len(copy.body) > 120:
        parts.append("room for a long paragraph of body copy")
    return ". ".join(parts) + "."


async def retrieve_templates(session: AsyncSession, brief: DesignBrief,
                             limit: int = 3) -> list[TemplateSkeleton]:
    query = render_brief_as_search_text(brief)
    embedding: list[float] | None = None
    try:
        vectors = await get_embedder().embed([query])
        embedding = vectors[0] if vectors else None
    except AdapterError as exc:
        # Retrieval must still return something; fall back to quality ranking.
        log.warning("template.retrieve.embed_failed", error=str(exc))

    rows = await repo.retrieve_templates(
        session,
        kind=brief.kind,
        aspect=nearest_aspect(brief.canvas.width, brief.canvas.height),
        text_only=brief.subject_description is None,
        dense=brief.layout_hints.density == "dense",
        embedding=embedding,
        limit=limit,
    )

    skeletons: list[TemplateSkeleton] = []
    for row in rows:
        try:
            skeletons.append(TemplateSkeleton.model_validate(row["skeleton"]))
        except Exception as exc:  # noqa: BLE001
            log.error("template.retrieve.invalid_skeleton", template_id=row.get("id"),
                      error=str(exc))
    return skeletons
