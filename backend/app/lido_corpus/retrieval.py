"""Template selection for the Lido.js (template) flow.

Precedence: an explicit `template_id` wins, then `random_pick`, then the automatic match
in `matcher.py` (docs/new_match_plan.md): templates that can hold every detail the user gave
come first, ranked by topic; otherwise the best topic + details match wins. Every
template in the corpus is a candidate — the old "must have a reference_note" gate is gone.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from .loader import DEFAULT_CORPUS_DIR
from .matcher import MatchResult, match_templates
from .model import LidoTemplateFile


class NoReadyTemplateError(LookupError):
    """The corpus is empty — there is nothing to pick from."""


class TemplateNotFoundError(LookupError):
    """An explicitly requested `template_id` isn't in the corpus."""


@dataclass
class ScoredTemplate:
    template: LidoTemplateFile
    score: float
    match: MatchResult | None = None
    """How the automatic match decided; None for an explicit or random pick."""


def get_template(templates: list[LidoTemplateFile], template_id: str) -> ScoredTemplate:
    """An explicit pick, by `meta.id` (the file stem)."""
    for template in templates:
        if template.meta.id == template_id:
            return ScoredTemplate(template, 1.0)
    raise TemplateNotFoundError(f"no template {template_id!r} in the corpus")


def random_template(templates: list[LidoTemplateFile]) -> ScoredTemplate:
    """Uniform pick across every template in the corpus."""
    if not templates:
        raise NoReadyTemplateError("the corpus is empty")
    return ScoredTemplate(random.choice(templates), 0.0)


async def select_best_template(templates: list[LidoTemplateFile], query: str, *,
                               corpus_dir: Path | str = DEFAULT_CORPUS_DIR,
                               use_llm: bool = True, catalog=None) -> ScoredTemplate:
    if not templates:
        raise NoReadyTemplateError("the corpus is empty — add a template to lidojs_templates/")
    result = await match_templates(templates, query, corpus_dir=corpus_dir,
                                   use_llm=use_llm, catalog=catalog)
    by_id = {t.meta.id: t for t in templates}
    return ScoredTemplate(by_id[result.best.template_id], result.best.score, result)


async def choose_template(templates: list[LidoTemplateFile], query: str, *,
                          template_id: str | None = None, random_pick: bool = False,
                          corpus_dir: Path | str = DEFAULT_CORPUS_DIR,
                          catalog=None) -> ScoredTemplate:
    """The one place `/v1/lido/generate` decides which template to fill: an explicit
    `template_id` wins outright, then `random_pick`, then the automatic match."""
    if template_id:
        return get_template(templates, template_id)
    if random_pick:
        return random_template(templates)
    return await select_best_template(templates, query, corpus_dir=corpus_dir,
                                      catalog=catalog)
