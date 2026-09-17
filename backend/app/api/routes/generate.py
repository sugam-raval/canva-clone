"""Generation endpoints — IMPLEMENTATION_PLAN §0.10.

    POST /v1/generate          -> { requestId, docIds[] }
    GET  /v1/requests/:id      -> state + job graph
    WS   /v1/progress?requestId -> ProgressEvent stream
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_budget, current_user_id, db_session, rate_limit_generation
from app.api.schemas import GenerateRequest, GenerateResponse
from app.db import repo
from app.db.session import get_sessionmaker
from app.jobs.progress import emitter, get_bus
from app.pipelines.part_one.orchestrator import generate as run_generation
from app.schema.events import RequestFailed
from app.util.safety import screen_prompt

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1", tags=["generate"])

# Requests are executed as background tasks in this process. The orchestrator is a plain
# async function taking a session and an emitter, so moving it onto the arq worker
# (app/jobs/worker.py) is a call-site change, not a rewrite.
_running: dict[str, asyncio.Task] = {}


@router.post("/generate", response_model=GenerateResponse,
             dependencies=[Depends(rate_limit_generation)])
async def create_generation(
    body: GenerateRequest,
    session: AsyncSession = Depends(db_session),
    user_id: str = Depends(current_user_id),
) -> GenerateResponse:
    verdict = screen_prompt(body.prompt)
    if not verdict.allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=verdict.reason)
    await check_budget(session, user_id)

    prompt = body.prompt.strip()
    if body.kind:
        prompt = f"{prompt}\n(design kind: {body.kind})"
    if body.size and body.size.get("width") and body.size.get("height"):
        prompt = f"{prompt}\n(canvas: {body.size['width']}x{body.size['height']})"

    request_id = await repo.create_generation_request(session, user_id=user_id,
                                                      prompt=prompt)
    await session.commit()

    brand_kit = None
    if body.brand_kit_id:
        brand_kit = await _load_brand_kit(session, body.brand_kit_id, user_id)

    task = asyncio.create_task(
        _run(request_id, prompt, user_id, body.count, brand_kit),
        name=f"generate:{request_id}",
    )
    _running[request_id] = task
    task.add_done_callback(lambda _t: _running.pop(request_id, None))

    # docIds are not known until the composer runs; the client learns them from the
    # `doc.skeleton` events on the WebSocket.
    return GenerateResponse(requestId=request_id, docIds=[])


async def _run(request_id: str, prompt: str, user_id: str, count: int,
               brand_kit: dict | None) -> None:
    emit = emitter(request_id)
    try:
        async with get_sessionmaker()() as session:
            try:
                await run_generation(session, prompt=prompt, user_id=user_id,
                                     request_id=request_id, count=count,
                                     brand_kit=brand_kit, emit=emit)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except asyncio.CancelledError:
        await emit(RequestFailed(reason="cancelled"))
        raise
    except Exception as exc:
        log.exception("generate.failed", request_id=request_id)
        await emit(RequestFailed(reason=str(exc)))
        async with get_sessionmaker()() as session:
            await repo.update_generation_request(session, request_id, state="failed",
                                                 error=str(exc)[:500])
            await session.commit()


async def _load_brand_kit(session: AsyncSession, brand_kit_id: str,
                          user_id: str) -> dict | None:
    from sqlalchemy import text

    row = (await session.execute(
        text("select palette, fonts, tone from brand_kits where id = :id "
             "and user_id = :uid"),
        {"id": brand_kit_id, "uid": user_id},
    )).mappings().first()
    return dict(row) if row else None


@router.get("/requests/{request_id}")
async def get_request(request_id: str,
                      session: AsyncSession = Depends(db_session)) -> dict:
    row = await repo.get_generation_request(session, request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="request not found")
    return {
        "requestId": str(row["id"]),
        "prompt": row["prompt"],
        "brief": row["brief"],
        "state": row["state"],
        "docId": str(row["doc_id"]) if row["doc_id"] else None,
        "templateId": row["chosen_template_id"],
        "costCents": row["cost_cents"],
        "error": row["error"],
        "jobs": [
            {"id": str(j["id"]), "type": j["type"], "state": j["state"],
             "layerId": j["layer_id"], "error": j["error"], "costCents": j["cost_cents"]}
            for j in row["jobs"]
        ],
        "running": request_id in _running,
    }


@router.post("/requests/{request_id}/cancel")
async def cancel_request(request_id: str) -> dict:
    task = _running.get(request_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="request is not running")
    task.cancel()
    return {"cancelled": True}


@router.websocket("/progress")
async def progress_socket(websocket: WebSocket, requestId: str = "") -> None:
    """Streams `ProgressEvent`s for one request.

    Replays buffered events on connect, so a client that attaches a beat late still
    receives `doc.skeleton` instead of hanging.
    """
    await websocket.accept()
    if not requestId:
        await websocket.close(code=4400, reason="requestId is required")
        return
    try:
        async for text in get_bus().subscribe(requestId):
            await websocket.send_text(text)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("progress.socket_failed", request_id=requestId)
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass
