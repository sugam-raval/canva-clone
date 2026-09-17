"""Lido corpus generation endpoint — simpler, prompt-driven alternative to /v1/generate.

    POST /v1/lido/generate    brief (as a prompt) → filled Lido document

Unlike `/v1/generate` (which produces a complex DesignDoc with a full job graph), this
endpoint runs synchronously and returns the complete filled Lido JSON in one call, ready
to hand to the editor. No DB writes, no background tasks, just the pipeline.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.schemas import LidoGenerateRequest, LidoGenerateResponse, LidoAssetInfo, LidoSlotFillInfo
from app.lido_corpus.pipeline import generate_lido_design
from app.pipelines.part_one.brief import parse_brief
from app.util.safety import screen_prompt

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/lido", tags=["lido"])


@router.post("/generate", response_model=LidoGenerateResponse)
async def lido_generate(body: LidoGenerateRequest) -> LidoGenerateResponse:
    """Generate a Lido design from a text prompt.

    Returns a filled [{"layers": {...}}] document ready to open in the Lido editor.
    No background jobs, no DB writes — the full pipeline runs synchronously and
    returns the final result in one call.
    """
    verdict = screen_prompt(body.prompt)
    if not verdict.allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=verdict.reason)

    # Add kind as a hint to the prompt if provided
    prompt = body.prompt
    if body.kind:
        prompt = f"{prompt}\n(design kind: {body.kind})"

    try:
        brief, _cost = await parse_brief(prompt)
    except Exception as exc:
        log.error("lido.brief_parse_failed", error=str(exc), prompt=body.prompt[:100])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse design brief: {str(exc)}"
        ) from exc

    try:
        result = await generate_lido_design(brief, generate_assets=True)
    except Exception as exc:
        log.error("lido.generation_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Design generation failed: {str(exc)}"
        ) from exc

    return LidoGenerateResponse(
        document=result.document,
        template_id=result.template_id,
        template_score=result.template_score,
        text_fills=[
            LidoSlotFillInfo(layer_id=lid, role="text", text=text)
            for lid, text in result.text_fills.items()
        ],
        image_fills=[
            LidoAssetInfo(layer_id=lid, url=url)
            for lid, url in result.image_fills.items()
        ],
    )
