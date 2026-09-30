"""Draft templates: design brand-new Lido templates from a prompt, for review.

    POST   /v1/lido/drafts                  prompt → 1–3 new templates, saved as drafts
    GET    /v1/lido/drafts                  every draft, newest first
    GET    /v1/lido/drafts/{id}             one draft with its Lido document
    GET    /v1/lido/drafts/{id}/preview.png its screenshot
    DELETE /v1/lido/drafts/{id}             remove it

Drafts live in lidojs_templates/drafts/ (see app/lido_create/drafts.py) and are never
match candidates: a reviewed draft is moved into lidojs_templates/ and onboarded with
`make lido-add`. Designing runs synchronously — one LLM call per variation, more if a
design needs repairing — so a request takes roughly 30–120 s.
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.adapters.base import AdapterError
from app.api.schemas import LidoDraftInfo, LidoDraftRequest
from app.lido_create import drafts
from app.lido_create.brief import RETRY_DELAYS
from app.util.safety import screen_prompt

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/lido/drafts", tags=["lido drafts"])


def _info(record: dict) -> LidoDraftInfo:
    info = LidoDraftInfo.model_validate(record)
    if info.has_preview:
        # the creation time busts the browser cache when an id is reused after a delete
        stamp = int(info.created_at.timestamp())
        info.preview_url = f"/v1/lido/drafts/{info.id}/preview.png?v={stamp}"
    return info


def _short(exc: Exception) -> str:
    """The first line of an API error, without the provider's JSON body."""
    return str(exc).split(":", 2)[0][:120] if "{" in str(exc) else str(exc)[:200]


def _draft_id(draft_id: str) -> str:
    try:
        drafts.draft_id(draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="draft not found") from exc
    return draft_id


@router.post("", response_model=list[LidoDraftInfo])
async def create_drafts(body: LidoDraftRequest) -> list[LidoDraftInfo]:
    """Design `variations` new templates from the prompt: layout, decoration, colours,
    fonts and copy all come from the prompt; photos are placeholders from the corpus
    for now. Each is checked (text fit, overlaps, contrast…) and repaired by the model
    until it passes; anything still failing is reported in `problems`."""
    verdict = screen_prompt(body.prompt)
    if not verdict.allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=verdict.reason)
    try:
        records = await drafts.create_from_prompt(body.prompt, variations=body.variations)
    except AdapterError as exc:
        log.error("lido.drafts.llm_unavailable", error=str(exc))
        detail = (f"The AI service is temporarily unavailable ({_short(exc)}); tried "
                  f"{len(RETRY_DELAYS) + 1} times. Please try again in a minute."
                  if exc.recoverable else f"The AI service refused the request: {_short(exc)}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(exc)) from exc
    except Exception as exc:
        log.error("lido.drafts.failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Designing the template failed: {exc}") from exc
    log.info("lido.drafts.created", ids=[r["id"] for r in records])
    return [_info(r) for r in records]


@router.get("", response_model=list[LidoDraftInfo])
async def list_drafts(limit: int = 60) -> list[LidoDraftInfo]:
    records = await asyncio.to_thread(drafts.list_drafts)
    return [_info(r) for r in records[:max(1, min(limit, 500))]]


@router.get("/{draft_id}", response_model=LidoDraftInfo)
async def get_draft(draft_id: str) -> LidoDraftInfo:
    record = await asyncio.to_thread(drafts.get_draft, _draft_id(draft_id))
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft not found")
    return _info(record)


@router.get("/{draft_id}/preview.png", include_in_schema=False)
async def draft_preview(draft_id: str) -> FileResponse:
    path = drafts.preview_path(_draft_id(draft_id))
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no preview")
    return FileResponse(path, media_type="image/png")


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(draft_id: str) -> None:
    if not drafts.delete_draft(_draft_id(draft_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft not found")
