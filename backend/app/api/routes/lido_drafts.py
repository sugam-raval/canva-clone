"""Draft templates: design brand-new Lido templates from a prompt, for review.

    POST   /v1/lido/drafts                  prompt → 1–3 new templates, saved as drafts
    POST   /v1/lido/drafts/stream           the same, streamed: progress, then each draft
    GET    /v1/lido/drafts                  every draft, newest first
    GET    /v1/lido/drafts/{id}             one draft with its Lido document
    DELETE /v1/lido/drafts/{id}             remove it

Drafts live in the `lido_drafts` table (see app/lido_create/drafts.py), their preview
screenshots in the object store (`previewUrl`), and are never match candidates: a
reviewed draft is exported into lidojs_templates/ (`make lido-draft-export ID=<id>`)
and onboarded with `make lido-add`. Designing takes a minute or two — a plan and a
layout call per variation, a patch call if a design still needs repairing, with the
photo renders (LIDO_DRAFT_PHOTOS=generate) running alongside — so the UI uses the
streamed route to show progress and each draft as soon as it is ready.
"""

from __future__ import annotations

import asyncio
import json
import time

import structlog
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.adapters.base import AdapterError
from app.api.schemas import LidoDraftInfo, LidoDraftRequest
from app.lido_create import drafts
from app.lido_create.brief import RETRY_DELAYS
from app.util.safety import screen_prompt

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/lido/drafts", tags=["lido drafts"])


def _info(record: dict) -> LidoDraftInfo:
    return LidoDraftInfo.model_validate(record)


def _short(exc: Exception) -> str:
    """The first line of an API error, without the provider's JSON body."""
    return str(exc).split(":", 2)[0][:120] if "{" in str(exc) else str(exc)[:200]


def _draft_id(draft_id: str) -> int:
    """The path's draft id (`lido_drafts.id`); anything that isn't one is simply not found."""
    if not draft_id.isdigit():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft not found")
    return int(draft_id)


def _check(body: LidoDraftRequest) -> None:
    verdict = screen_prompt(body.prompt)
    if not verdict.allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=verdict.reason)


async def _create(body: LidoDraftRequest, on_progress=None) -> list[dict]:
    """`drafts.create_from_prompt`, its failures turned into readable HTTP errors."""
    try:
        return await drafts.create_from_prompt(body.prompt, variations=body.variations,
                                               palette=body.palette,
                                               logo_url=body.logo_url,
                                               on_progress=on_progress)
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


@router.post("", response_model=list[LidoDraftInfo])
async def create_drafts(body: LidoDraftRequest) -> list[LidoDraftInfo]:
    """Design `variations` new templates from the prompt: layout, decoration, colours,
    fonts and copy all come from the prompt — colours from `palette` and the logo from
    `logoUrl` when given, as in "fill a template"; photos are generated from each photo's
    subject or taken from the corpus cache, as LIDO_DRAFT_PHOTOS says. Each is checked (text fit, overlaps, contrast…) and repaired by the model
    until it passes; anything still failing is reported in `problems`."""
    _check(body)
    records = await _create(body)
    log.info("lido.drafts.created", ids=[r["id"] for r in records])
    return [_info(r) for r in records]


@router.post("/stream")
async def create_drafts_stream(body: LidoDraftRequest) -> StreamingResponse:
    """`POST /v1/lido/drafts`, streamed as newline-delimited JSON so the page can show
    what is happening during the minute or two it takes, and each draft the moment it is
    saved:

        {"stage": "planning" | "designing" | "repairing" | "photos" | "saving",
         "variation": i, "elapsedMs": …}
        {"stage": "draft", "variation": i, "draft": LidoDraftInfo, "elapsedMs": …}
        {"stage": "error", "status": 503, "detail": "…"}     (instead of an HTTP error)
        {"stage": "done", "elapsedMs": …}

    The prompt is screened first; a rejected one is a plain 400 like the other route."""
    _check(body)
    events: asyncio.Queue[dict | None] = asyncio.Queue()
    started = time.perf_counter()

    def emit(event: dict) -> None:
        event = {**event, "elapsedMs": round((time.perf_counter() - started) * 1000)}
        if "draft" in event:
            event["draft"] = _info(event["draft"]).model_dump(by_alias=True, mode="json")
        events.put_nowait(event)

    async def run() -> None:
        try:
            records = await _create(body, on_progress=emit)
            log.info("lido.drafts.created", ids=[r["id"] for r in records])
            emit({"stage": "done"})
        except HTTPException as exc:
            emit({"stage": "error", "status": exc.status_code, "detail": exc.detail})
        finally:
            events.put_nowait(None)

    async def lines():
        task = asyncio.create_task(run())
        try:
            while (event := await events.get()) is not None:
                yield json.dumps(event) + "\n"
        finally:
            task.cancel()  # the client went away: stop designing

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("", response_model=list[LidoDraftInfo])
async def list_drafts(limit: int = 60) -> list[LidoDraftInfo]:
    records = await drafts.list_drafts(max(1, min(limit, 500)))
    return [_info(r) for r in records]


@router.get("/{draft_id}", response_model=LidoDraftInfo)
async def get_draft(draft_id: str) -> LidoDraftInfo:
    record = await drafts.get_draft(_draft_id(draft_id))
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft not found")
    return _info(record)


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(draft_id: str) -> None:
    if not await drafts.delete_draft(_draft_id(draft_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft not found")
