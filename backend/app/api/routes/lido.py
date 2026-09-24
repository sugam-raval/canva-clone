"""Lido.js (template) API.

    POST /v1/lido/generate            prompt → best template, filled; saved to lido_generations
    GET  /v1/lido/templates           every template in the catalog (lido_templates)
    POST /v1/lido/templates/sync      mirror lidojs_templates/*.json into lido_templates now
    GET  /v1/lido/generations         generation history, newest first
    GET  /v1/lido/generations/{id}    one saved design, to reopen it

Generation runs synchronously and returns the complete filled Lido JSON in one call.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError
from app.api.deps import db_session
from app.api.schemas import (
    LidoAssetInfo,
    LidoGenerateRequest,
    LidoGenerateResponse,
    LidoGenerationSummary,
    LidoImagePromptInfo,
    LidoMatchInfo,
    LidoSlotFillInfo,
    LidoTemplateSummary,
)
from app.db import repo
from app.lido_corpus.pipeline import generate_lido_design
from app.lido_corpus.retrieval import NoReadyTemplateError, TemplateNotFoundError
from app.lido_corpus.store import load_catalog, sync_templates
from app.util.safety import screen_prompt

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/lido", tags=["lido"])


async def _record_generation(session: AsyncSession, *, design_id: str,
                             document: list[dict], meta: dict) -> None:
    """The DB write IS the persistence for this design — unlike the old file-backed
    version, a failure here is not survivable by falling back to a file that was never
    written, so it is raised rather than swallowed."""
    await repo.upsert_lido_generation(session, design_id=design_id, document=document, meta=meta)


@router.post("/generate", response_model=LidoGenerateResponse)
async def lido_generate(body: LidoGenerateRequest,
                        session: AsyncSession = Depends(db_session)) -> LidoGenerateResponse:
    """Fill a Lido template from a text prompt.

    One LLM call writes every text layer and every image prompt from the template's own
    per-layer metadata; images are generated per layer spec (transparent cutout or
    opaque) and uploaded to the object store under a permanent public URL. The filled
    `[{"layers", "meta"}]` document is saved into `lido_generations` (reopen it with
    GET /v1/lido/generations/{id}) and returned in full.

    Which template gets filled: `template_id` picks one exactly; else `random_template`
    picks uniformly from the whole corpus; else the automatic match over every template
    (`app/lido_corpus/matcher.py`), reported back in `match`.
    """
    verdict = screen_prompt(body.prompt)
    if not verdict.allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=verdict.reason)

    try:
        result = await generate_lido_design(
            body.prompt, kind=body.kind, generate_images=body.generate_images,
            template_id=body.template_id, random_template=body.random_template,
        )
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NoReadyTemplateError as exc:
        log.error("lido.no_template", error=str(exc))
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

    try:
        await _record_generation(session, design_id=result.design_id,
                                 document=result.document, meta=result.document[0]["meta"])
    except Exception as exc:
        log.error("lido.generation_index_failed", design_id=result.design_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Design was generated but could not be saved; please retry",
        ) from exc

    roles = {slot.layer_id: slot.role for slot in result.template.meta.slots}
    return LidoGenerateResponse(
        document=result.document,
        template_id=result.template.meta.id,
        template_score=result.template_score,
        design_id=result.design_id,
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
        match=LidoMatchInfo.model_validate(result.match) if result.match else None,
    )


@router.get("/templates", response_model=list[LidoTemplateSummary])
async def lido_templates_list() -> list[LidoTemplateSummary]:
    """Every template in the catalog (`lido_templates`, synced from the files). `ready`
    means a human reviewed it (`meta.reference_note`); every template is a candidate for
    the automatic match either way."""
    catalog = await load_catalog()
    return [
        LidoTemplateSummary(
            id=t.meta.id, name=t.meta.name or t.meta.id, kind=t.meta.kind,
            aspect=t.meta.aspect, tags=t.meta.tags, description=t.meta.description,
            ready=bool(t.meta.reference_note),
        )
        for t in catalog.templates
    ]


@router.post("/templates/sync")
async def lido_templates_sync(force: bool = False) -> dict:
    """Mirror `lidojs_templates/*.json` into `lido_templates` right now, re-embedding
    only templates whose metadata changed (`force=true` re-embeds all). The API also
    does this by itself at startup and every LIDO_TEMPLATE_SYNC_SECONDS."""
    try:
        report = await sync_templates(force=force)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"template sync failed: {exc}") from exc
    return {"added": report.added, "reembedded": report.updated,
            "unchanged": report.unchanged, "deleted": report.deleted,
            "model": report.model}


@router.get("/generations", response_model=list[LidoGenerationSummary])
async def lido_generations_list(limit: int = 50, offset: int = 0,
                                session: AsyncSession = Depends(db_session)) -> list[dict]:
    """The generation history (`lido_generations`), newest first."""
    return await repo.list_lido_generations(
        session, limit=max(1, min(limit, 200)), offset=max(0, offset))


@router.get("/generations/{design_id}")
async def lido_generation_get(design_id: str,
                              session: AsyncSession = Depends(db_session)) -> dict:
    row = await repo.get_lido_generation(session, design_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="design not found")
    return {"designId": design_id, "document": row["document"]}
