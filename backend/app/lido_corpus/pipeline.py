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

import httpx
import structlog
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings

from .assets_ai import generate_template_images, mask_reserved_areas
from .compose import fill_template
from .generate_ai import (
    BACKGROUND_LAYER_ID,
    TemplateFill,
    background_mirror_ids,
    generate_template_fill,
    image_targets,
    reserved_overlay_areas,
)
from .generated import new_design_id, upload_asset
from .loader import DEFAULT_CORPUS_DIR, derive_meta
from .model import LidoDocument, LidoTemplateFile
from .palette import ThemePlan, apply_theme, check_contrast, parse_palette, plan_theme
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
    dropped_lines: list[str] = field(default_factory=list)
    """Lines the user asked for that had no room in the chosen template."""
    theme: dict | None = None
    """The palette and how it was applied; None when the user chose no palette."""


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


async def _fetch_image(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        # The asset CDN answers 403 to clients without a browser user agent.
        async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0"}) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as exc:
        log.warning("lido.palette.background_fetch_failed", url=url, error=str(exc))
        return None


async def _upload_all(design_id: str, rendered: dict[str, bytes]) -> dict[str, str]:
    urls = await asyncio.gather(*(_upload(design_id, lid, data) for lid, data in rendered.items()))
    return {lid: url for lid, url in zip(rendered, urls) if url}


def _build_meta(design_id: str, template: LidoTemplateFile, layers: dict, *, name: str,
                prompt: str, kind: str | None, fill: TemplateFill,
                image_fills: dict[str, str], image_failures: list[str],
                theme: ThemePlan | None = None) -> dict:
    """The template's own metadata (limits, notes, image specs) carried onto the
    design, plus a record of what this run actually did."""
    existing = template.meta.model_dump(mode="json")
    existing.update(name=name)
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
            "placed_lines": fill.placed,
            "hidden_layers": fill.hidden,
            "dropped_lines": fill.dropped,
            "llm_calls": fill.llm_calls,
            "llm_cost_cents": fill.cost_cents,
        },
    )
    if theme is not None:
        meta["generation"]["theme"] = theme.to_json()
    return meta


async def generate_lido_design(
    prompt: str,
    *,
    kind: str | None = None,
    generate_images: bool = True,
    template_id: str | None = None,
    random_template: bool = False,
    palette: list[str] | None = None,
    logo_url: str | None = None,
    corpus_dir: Path | str = DEFAULT_CORPUS_DIR,
) -> LidoGenerationResult:
    """`palette`: up to 4 colours (#rrggbb, first = primary) applied to the chosen
    template's text, shapes and generated images (docs/palette_theme.md). Template
    search ignores it. None or empty: generation is exactly as without the feature.

    `logo_url`: a plain URL swap into the chosen template's logo slot (if it has one) —
    a code-level replacement, never AI-generated or re-cropped. Applied after image
    generation so it always wins over whatever the logo slot originally held."""
    colors = parse_palette(palette)
    catalog = await load_catalog(corpus_dir)      # lido_templates (DB), files as fallback
    templates = catalog.templates
    chosen = await choose_template(templates, prompt, template_id=template_id,
                                   random_pick=random_template, corpus_dir=corpus_dir,
                                   catalog=catalog)
    template = chosen.template

    theme = plan_theme(template, colors) if colors else None
    fill = await generate_template_fill(prompt, template, kind=kind, plan=chosen.fit,
                                        theme=theme)
    if theme is not None:
        fill.image_prompts = theme.finalize_prompts(fill.image_prompts,
                                                    image_targets(template))
    name = _design_name(template, fill.text)
    design_id = new_design_id(name)

    image_fills: dict[str, str] = {}
    image_failures: list[str] = []
    rendered: dict[str, bytes] = {}
    if generate_images:
        targets = image_targets(template)
        rendered = await generate_template_images(targets, fill.image_prompts)
        if get_settings().lido_mask_reserved_areas and BACKGROUND_LAYER_ID in rendered:
            canvas = template.meta.canvas_size
            rendered[BACKGROUND_LAYER_ID] = mask_reserved_areas(
                rendered[BACKGROUND_LAYER_ID], canvas.get("width", 0), canvas.get("height", 0),
                reserved_overlay_areas(template),
            )
        image_fills = await _upload_all(design_id, rendered)
        image_failures = [t.layer_id for t in targets if t.layer_id not in image_fills]
        if (bg_url := image_fills.get(BACKGROUND_LAYER_ID)) is not None:
            for mirror_id in background_mirror_ids(template):
                image_fills.setdefault(mirror_id, bg_url)

    if theme is not None:
        # Measure against the background the design actually ships with: the new one if
        # it was generated and uploaded, otherwise the template's own picture.
        if BACKGROUND_LAYER_ID in image_fills:
            background = rendered.get(BACKGROUND_LAYER_ID)
        else:
            background = await _fetch_image(template.meta.background_image_url)
        canvas = template.meta.canvas_size
        check_contrast(theme, background, canvas.get("width", 0), canvas.get("height", 0))

    unlock_layer_ids: set[str] = set()
    if logo_url:
        logo_slot = next((s for s in template.meta.slots if s.role == "logo"), None)
        if logo_slot is not None:
            image_fills[logo_slot.layer_id] = logo_url
            unlock_layer_ids.add(logo_slot.layer_id)
        else:
            log.info("lido.logo_url_ignored", reason="template has no logo slot",
                     template_id=template.meta.id)

    document = fill_template(template, by_layer_id=fill.text, image_by_layer_id=image_fills,
                             unlock_layer_ids=unlock_layer_ids)
    if theme is not None:
        apply_theme(document[0]["layers"], theme)
    document[0]["meta"] = _build_meta(
        design_id, template, document[0]["layers"], name=name,
        prompt=prompt, kind=kind, fill=fill, image_fills=image_fills,
        image_failures=image_failures, theme=theme,
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
        dropped_lines=fill.dropped,
        theme=theme.to_json() if theme is not None else None,
    )
