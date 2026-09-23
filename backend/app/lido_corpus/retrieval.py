"""Template selection for the Lido.js (template) flow.

Only templates marked ready for generation are candidates: a `meta.reference_note` is
what a human adds once a template's per-layer metadata (limits, notes, image specs) has
been authored — see `lidojs_templates/TEMPLATE_METADATA_RULES.md`. A template without
it would be filled from auto-derived guesses, so it is never picked. Among ready
templates, keyword/tag overlap with the user's request breaks the tie.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import LidoTemplateFile

_WORD_RE = re.compile(r"[a-z0-9]+")


class NoReadyTemplateError(LookupError):
    """No template in the corpus has been marked ready (`meta.reference_note`)."""


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


@dataclass
class ScoredTemplate:
    template: LidoTemplateFile
    score: float


def score_template(template: LidoTemplateFile, query: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    meta = template.meta
    tag_hits = len(query_tokens & _tokens(" ".join(meta.tags)))
    desc_hits = len(query_tokens & _tokens(meta.description))
    kind_hits = len(query_tokens & _tokens(meta.kind))
    # Tags are hand-curated signal, worth more per hit than prose overlap.
    return 3.0 * tag_hits + 1.0 * desc_hits + 2.0 * kind_hits


def select_ready_template(templates: list[LidoTemplateFile], query: str) -> ScoredTemplate:
    ready = [t for t in templates if t.meta.reference_note]
    if not ready:
        raise NoReadyTemplateError(
            "no template is ready for generation — add per-layer metadata and a "
            "meta.reference_note to one (see lidojs_templates/TEMPLATE_METADATA_RULES.md)"
        )
    scored = [ScoredTemplate(t, score_template(t, query)) for t in ready]
    # Stable sort: equal scores keep corpus (filename) order, so selection is repeatable.
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[0]
