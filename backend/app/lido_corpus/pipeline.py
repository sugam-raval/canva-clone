"""End-to-end orchestrator for the Lido corpus — the same shape as
`app.pipelines.part_one.orchestrator`, retargeted at Lido's JSON:

    brief -> retrieve best-match template -> generate copy -> generate assets -> fill

One call, `generate_lido_design()`, does all four steps and returns the finished
`[{"layers": {...}}]` document plus which template was chosen and why — nothing here
touches the DesignDoc engine or a DB session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schema.brief import DesignBrief

from .assets_ai import generate_lido_assets
from .compose import fill_template
from .compose_ai import compose_lido_content
from .loader import DEFAULT_CORPUS_DIR, load_corpus
from .model import LidoTemplateFile
from .retrieval import ScoredTemplate, retrieve_for_brief


@dataclass
class LidoGenerationResult:
    document: list[dict]
    template_id: str
    template_score: float
    candidates: list[ScoredTemplate] = field(default_factory=list)
    text_fills: dict[str, str] = field(default_factory=dict)
    image_fills: dict[str, str] = field(default_factory=dict)


async def generate_lido_design(
    brief: DesignBrief,
    corpus_dir: str = DEFAULT_CORPUS_DIR,
    *,
    generate_assets: bool = True,
) -> LidoGenerationResult:
    templates: list[LidoTemplateFile] = load_corpus(corpus_dir)
    if not templates:
        raise ValueError(f"no Lido templates found in {corpus_dir}")

    candidates = await retrieve_for_brief(templates, brief, top_k=3)
    best = candidates[0]
    template = best.template

    text_fills = await compose_lido_content(brief, template)
    image_fills = await generate_lido_assets(brief, template) if generate_assets else {}

    document = fill_template(template, by_layer_id=text_fills, image_by_layer_id=image_fills)

    return LidoGenerationResult(
        document=document,
        template_id=template.meta.id,
        template_score=best.score,
        candidates=candidates,
        text_fills=text_fills,
        image_fills=image_fills,
    )
