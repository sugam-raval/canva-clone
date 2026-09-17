"""Template retrieval for the Lido corpus.

Keyword/tag scoring, not embeddings — deliberately, so this has zero infra dependency
and stays swappable. Once `meta.description` is rich enough (loader.py grows it from the
slot manifest automatically), the same interface can call an embedder instead; nothing
upstream of `retrieve()` needs to change.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import structlog

from app.adapters.base import AdapterError
from app.adapters.registry import embedder as get_embedder
from app.schema.brief import DesignBrief

from .model import LidoTemplateFile

log = structlog.get_logger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


@dataclass
class ScoredTemplate:
    template: LidoTemplateFile
    score: float
    reason: str


def score_template(template: LidoTemplateFile, brief: str) -> float:
    brief_tokens = _tokens(brief)
    if not brief_tokens:
        return 0.0
    meta = template.meta
    tag_tokens = _tokens(" ".join(meta.tags))
    desc_tokens = _tokens(meta.description)
    kind_tokens = _tokens(meta.kind)

    tag_hits = len(brief_tokens & tag_tokens)
    desc_hits = len(brief_tokens & desc_tokens)
    kind_hits = len(brief_tokens & kind_tokens)

    # Tags are hand/heuristically curated signal, worth more per hit than prose overlap.
    return 3.0 * tag_hits + 1.0 * desc_hits + 2.0 * kind_hits


def retrieve(templates: list[LidoTemplateFile], brief: str, top_k: int = 3) -> list[ScoredTemplate]:
    scored = [
        ScoredTemplate(t, score_template(t, brief), reason=f"matched against: {t.meta.description}")
        for t in templates
    ]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top_k]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _brief_search_text(brief: DesignBrief) -> str:
    # Deferred import: `part_one.retrieve` pulls in the DB-backed DesignDoc retrieval
    # path, which this module has no other reason to depend on.
    from app.pipelines.part_one.retrieve import render_brief_as_search_text

    return render_brief_as_search_text(brief)


async def retrieve_for_brief(
    templates: list[LidoTemplateFile], brief: DesignBrief, top_k: int = 3,
) -> list[ScoredTemplate]:
    """Embedding-similarity retrieval against a `DesignBrief`, same query phrasing as
    the DesignDoc pipeline (§1.2) so both corpora respond to the same brief the same
    way. Falls back to keyword scoring against the brief's own text fields when no
    embedder is configured, so retrieval still returns something.
    """
    query = _brief_search_text(brief)
    try:
        embedder = get_embedder()
        vectors = await embedder.embed([query] + [t.meta.description for t in templates])
        query_vec, template_vecs = vectors[0], vectors[1:]
        scored = [
            ScoredTemplate(t, _cosine(query_vec, vec), reason=f"embedding match: {t.meta.description}")
            for t, vec in zip(templates, template_vecs)
        ]
    except AdapterError as exc:
        log.warning("lido.retrieve.embed_failed", error=str(exc))
        fallback_text = " ".join(filter(None, [
            brief.kind, brief.subject_description, " ".join(brief.mood),
            brief.copy_text.headline, brief.copy_text.body,
        ]))
        scored = [
            ScoredTemplate(t, score_template(t, fallback_text),
                          reason=f"keyword match: {t.meta.description}")
            for t in templates
        ]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top_k]
