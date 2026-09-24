"""End-to-end Lido.js (template) generation (docs/plan.md §2.2):

    request -> best template (store.load_catalog + matcher: lido_templates / pgvector)
            -> ONE LLM call (all copy + image prompts, per layer)
            -> mechanical limit checks -> images (opaque / transparent per layer spec)
            -> fill -> returned to the route, which saves it into `lido_generations`

The finished `[{"layers": ..., "meta": ...}]` document is only persisted once the route
calls `app.db.repo.upsert_lido_generation`; nothing is written to disk.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog
from botocore.exceptions import BotoCoreError, ClientError

from .assets_ai import generate_template_images
from .compose import fill_template
from .generate_ai import BACKGROUND_LAYER_ID, TemplateFill, generate_template_fill, image_targets
from .generated import new_design_id, upload_asset
from .loader import DEFAULT_CORPUS_DIR, derive_meta
from .model import LidoDocument, LidoTemplateFile
from .retrieval import choose_template
from .store import load_catalog

log = structlog.get_logger(__name__)


@dataclass
class LidoGenerationResult:
    design_id: str
    document: list[dict]
    template: LidoTemplateFile
    template_score: float
    match: dict | None = None
    """Top-3 candidates and how the automatic match decided (None for explicit/random)."""
    text_fills: dict[str, str] = field(default_factory=dict)
    image_prompts: dict[str, str] = field(default_factory=dict)
    image_fills: dict[str, str] = field(default_factory=dict)
    image_failures: list[str] = field(default_factory=list)
    """Layers whose image generation failed and kept the template's original image."""
    repaired: list[str] = field(default_factory=list)
    clamped: list[str] = field(default_factory=list)


def _design_name(template: LidoTemplateFile, text: dict[str, str]) -> str:
    headline = next((text.get(s.layer_id) for s in template.meta.slots
                     if s.role == "headline" and text.get(s.layer_id)), None)
    return headline or template.meta.name or template.meta.id


def _asset_name(layer_id: str) -> str:
    return "background" if layer_id == BACKGROUND_LAYER_ID else layer_id


async def _upload(design_id: str, layer_id: str, data: bytes) -> str | None:
    try:
        return await asyncio.to_thread(upload_asset, design_id, _asset_name(layer_id), data)
    except (BotoCoreError, ClientError, OSError) as exc:
        log.warning("lido.template_image.upload_failed", layer_id=layer_id, error=str(exc))
        return None


async def _upload_all(design_id: str, rendered: dict[str, bytes]) -> dict[str, str]:
    urls = await asyncio.gather(*(_upload(design_id, lid, data) for lid, data in rendered.items()))
    return {lid: url for lid, url in zip(rendered, urls) if url}


def _build_meta(design_id: str, template: LidoTemplateFile, layers: dict, *, name: str,
                prompt: str, kind: str | None, fill: TemplateFill,
                image_fills: dict[str, str], image_failures: list[str]) -> dict:
    """The template's own metadata (limits, notes, image specs) carried onto the
    design, plus a record of what this run actually did. `reference_note` is dropped
    on purpose: a generated design is not a reviewed exemplar, so promoting it into
    the corpus must not make it selectable until a human says so."""
    existing = template.meta.model_dump(mode="json")
    existing.update(name=name, reference_note=None)
    document = LidoDocument.model_validate({"layers": layers})
    meta = derive_meta(design_id, document.layers, existing=existing).model_dump(mode="json")
    meta.update(
        template_id=template.meta.id,
        prompt=prompt,
        generated_at=datetime.now(UTC).isoformat(),
        generation={
            "requested_kind": kind,
            "text_fills": fill.text,
            "image_prompts": fill.image_prompts,
            "image_fills": image_fills,
            "image_failures": image_failures,
            "repaired_layers": fill.repaired,
            "clamped_layers": fill.clamped,
            "llm_calls": fill.llm_calls,
            "llm_cost_cents": fill.cost_cents,
        },
    )
    return meta


async def generate_lido_design(
    prompt: str,
    *,
    kind: str | None = None,
    generate_images: bool = True,
    template_id: str | None = None,
    random_template: bool = False,
    corpus_dir: Path | str = DEFAULT_CORPUS_DIR,
) -> LidoGenerationResult:
    catalog = await load_catalog(corpus_dir)      # lido_templates (DB), files as fallback
    templates = catalog.templates
    chosen = await choose_template(templates, prompt, template_id=template_id,
                                   random_pick=random_template, corpus_dir=corpus_dir,
                                   catalog=catalog)
    template = chosen.template

    fill = await generate_template_fill(prompt, template, kind=kind)
    name = _design_name(template, fill.text)
    design_id = new_design_id(name)

    image_fills: dict[str, str] = {}
    image_failures: list[str] = []
    if generate_images:
        targets = image_targets(template)
        rendered = await generate_template_images(targets, fill.image_prompts)
        image_fills = await _upload_all(design_id, rendered)
        image_failures = [t.layer_id for t in targets if t.layer_id not in image_fills]

    document = fill_template(template, by_layer_id=fill.text, image_by_layer_id=image_fills)
    document[0]["meta"] = _build_meta(
        design_id, template, document[0]["layers"], name=name,
        prompt=prompt, kind=kind, fill=fill, image_fills=image_fills,
        image_failures=image_failures,
    )

    return LidoGenerationResult(
        design_id=design_id,
        document=document,
        template=template,
        template_score=chosen.score,
        match=chosen.match.to_json() if chosen.match else None,
        text_fills=fill.text,
        image_prompts=fill.image_prompts,
        image_fills=image_fills,
        image_failures=image_failures,
        repaired=fill.repaired,
        clamped=fill.clamped,
    )
