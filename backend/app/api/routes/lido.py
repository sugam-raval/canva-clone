"""Lido corpus generation endpoint — simpler, prompt-driven alternative to /v1/generate.

    POST /v1/lido/generate        prompt → filled Lido template, saved to disk
    POST /v1/lido/scratch        brief → a design composed from scratch, saved to disk
    GET  /v1/lido/scratch         everything generated so far, newest first
    GET  /v1/lido/scratch/{id}    one saved design (scratch or template)

Unlike `/v1/generate` (which produces a complex DesignDoc with a full job graph), this
endpoint runs synchronously and returns the complete filled Lido JSON in one call, ready
to hand to the editor. No DB writes, no background tasks, just the pipeline.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, status

from app.adapters.base import AdapterError
from app.api.schemas import (
    LidoAssetInfo,
    LidoGenerateRequest,
    LidoGenerateResponse,
    LidoImagePromptInfo,
    LidoScratchElement,
    LidoScratchRequest,
    LidoScratchResponse,
    LidoScratchSummary,
    LidoSlotFillInfo,
)
from app.lido_corpus.pipeline import generate_lido_design
from app.lido_corpus.retrieval import NoReadyTemplateError
from app.lido_scratch import generate_scratch_design
from app.lido_scratch.store import listing, load
from app.pipelines.part_one.brief import parse_brief
from app.schema.brief import KIND_DEFAULT_SIZE
from app.util.safety import screen_prompt

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/lido", tags=["lido"])


@router.post("/generate", response_model=LidoGenerateResponse)
async def lido_generate(body: LidoGenerateRequest) -> LidoGenerateResponse:
    """Fill a ready Lido template from a text prompt.

    One LLM call writes every text layer and every image prompt from the template's own
    per-layer metadata; images are generated per layer spec (transparent cutout or
    opaque) and uploaded to the object store under a permanent public URL. The filled
    `[{"layers", "meta"}]` document is saved under `lido_generated/` and returned in
    full — no background jobs, no DB writes.
    """
    verdict = screen_prompt(body.prompt)
    if not verdict.allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=verdict.reason)

    try:
        result = await generate_lido_design(
            body.prompt, kind=body.kind, generate_images=body.generate_images
        )
    except NoReadyTemplateError as exc:
        log.error("lido.no_ready_template", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=str(exc)) from exc
    except AdapterError as exc:
        log.error("lido.llm_unavailable", error=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"The language model is unavailable: {exc}") from exc
    except Exception as exc:
        log.error("lido.generation_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Design generation failed: {exc}") from exc

    roles = {slot.layer_id: slot.role for slot in result.template.meta.slots}
    return LidoGenerateResponse(
        document=result.document,
        template_id=result.template.meta.id,
        template_score=result.template_score,
        design_id=result.design_id,
        path=result.path,
        text_fills=[
            LidoSlotFillInfo(layer_id=lid, role=roles.get(lid, "text"), text=text)
            for lid, text in result.text_fills.items()
        ],
        image_fills=[
            LidoAssetInfo(layer_id=lid, url=url)
            for lid, url in result.image_fills.items()
        ],
        image_prompts=[
            LidoImagePromptInfo(layer_id=lid, prompt=prompt)
            for lid, prompt in result.image_prompts.items()
        ],
        image_failures=result.image_failures,
    )


@router.post("/scratch", response_model=LidoScratchResponse)
async def lido_scratch(body: LidoScratchRequest) -> LidoScratchResponse:
    """Design a Lido document from scratch — no template is retrieved or referenced.

    The model composes the whole page (canvas, palette, type scale, placement, copy),
    the layout engine repairs its geometry, images are generated for whatever the design
    asked for, and the result is saved under `lido_generated/`.
    """
    verdict = screen_prompt(body.prompt)
    if not verdict.allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=verdict.reason)

    prompt = body.prompt
    if body.kind:
        prompt = f"{prompt}\n(design kind: {body.kind})"

    try:
        brief, _cost = await parse_brief(prompt)
    except Exception as exc:
        log.error("lido.scratch.brief_parse_failed", error=str(exc), prompt=body.prompt[:100])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse design brief: {exc}",
        ) from exc

    # An explicit size wins over the brief; an explicit kind only sets the size when the
    # caller did not give one, so "make it a story" still resizes the canvas.
    if body.size and body.size.get("width") and body.size.get("height"):
        brief.canvas.width = max(64, min(8000, int(body.size["width"])))
        brief.canvas.height = max(64, min(8000, int(body.size["height"])))
    elif body.kind and body.kind in KIND_DEFAULT_SIZE:
        width, height, _dpi = KIND_DEFAULT_SIZE[body.kind]
        brief.canvas.width, brief.canvas.height = width, height

    try:
        result = await generate_scratch_design(
            brief, body.prompt, generate_images=body.generate_images
        )
    except Exception as exc:
        log.error("lido.scratch.failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scratch generation failed: {exc}",
        ) from exc

    spec = result.spec
    return LidoScratchResponse(
        design_id=result.design_id,
        document=result.document,
        name=spec.name,
        kind=spec.kind,
        width=spec.width,
        height=spec.height,
        vibe=spec.vibe,
        layout_style=spec.layout_style,
        background_style=spec.background.style,
        decor=list(spec.decor),
        palette=spec.palette,
        elements=[
            LidoScratchElement(
                kind=e.kind, role=e.role, text=e.text, size=e.size,
                x=round(e.x, 4), y=round(e.y, 4), w=round(e.w, 4),
                color=e.color, image_prompt=e.image_prompt,
                cutout=e.cutout, behind=e.behind,
                font=e.font, tracking=e.tracking,
            )
            for e in spec.elements
        ],
        llm_designed=result.llm_designed,
        font_scale=round(result.font_scale, 3),
        background_url=result.background_url,
        path=result.path,
    )


@router.get("/scratch", response_model=list[LidoScratchSummary])
async def lido_scratch_list() -> list[LidoScratchSummary]:
    """Every design saved under `lido_generated/`, newest first."""
    return [
        LidoScratchSummary(
            id=meta.get("id", ""),
            name=meta.get("name", ""),
            kind=meta.get("kind", "post"),
            aspect=meta.get("aspect", "1:1"),
            description=meta.get("description", ""),
            prompt=meta.get("prompt", ""),
            generated_at=meta.get("generated_at", ""),
            canvas_size=meta.get("canvas_size", {}),
        )
        for meta in listing()
    ]


@router.get("/scratch/{design_id}")
async def lido_scratch_get(design_id: str) -> dict:
    document = load(design_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="design not found")
    return {"designId": design_id, "document": document}
