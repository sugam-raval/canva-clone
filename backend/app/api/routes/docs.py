"""Document endpoints — IMPLEMENTATION_PLAN §0.10, §3.3, §4.2."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_id, db_session
from app.api.schemas import (
    EraseRequest,
    ExpandRequest,
    PatchRequest,
    RegenerateRequest,
    ReshapeRequest,
    ResizeRequest,
    RewriteRequest,
)
from app.db import repo
from app.layout.solver import SolveOpts, solve
from app.pipelines.part_one.layer_ops import (
    erase_region,
    expand_layer,
    remove_layer_background,
    rewrite_copy,
)
from app.pipelines.part_one.orchestrator import regenerate_layer, reshape_layer
from app.pipelines.part_one.resize import resize_document
from app.renderer.core import to_draw_list
from app.schema.doc import DesignDoc, find_layer
from app.schema.migrate import migrate
from app.schema.validate import validate_doc
from app.storage import assets as storage
from app.storage.resolver import resolve_for

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/docs", tags=["documents"])


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


async def _load(session: AsyncSession, doc_id: str) -> tuple[DesignDoc, dict]:
    row = await repo.get_document(session, doc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    result = validate_doc(migrate(row["doc"]))
    if not result.ok or result.doc is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"stored document is invalid: "
                                   f"{[e.as_dict() for e in result.errors[:3]]}")
    return result.doc, row


async def _save(session: AsyncSession, doc: DesignDoc) -> None:
    doc.updated_at = _now()
    result = validate_doc(doc)
    if not result.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=[e.as_dict() for e in result.errors[:5]])
    await repo.update_document(session, doc)


@router.get("")
async def list_documents(session: AsyncSession = Depends(db_session),
                         user_id: str = Depends(current_user_id)) -> list[dict]:
    rows = await repo.list_documents(session, user_id)
    out = []
    for row in rows:
        thumb = None
        if row["thumb_asset_id"]:
            asset = await repo.get_asset(session, str(row["thumb_asset_id"]))
            if asset:
                thumb = storage.url_for(asset["storage_key"])
        out.append({
            "id": str(row["id"]), "title": row["title"],
            "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
            "provenance": row["provenance"], "thumbUrl": thumb,
        })
    return out


@router.get("/{doc_id}")
async def get_document(doc_id: str, session: AsyncSession = Depends(db_session)) -> dict:
    doc, row = await _load(session, doc_id)
    resolved = await resolve_for(session, doc)
    return {
        "doc": doc.model_dump(by_alias=True, exclude_none=True),
        "assets": {aid: resolved.url(aid) for aid in resolved.rows},
        "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.get("/{doc_id}/drawlist")
async def get_draw_list(doc_id: str, scale: float = 1.0,
                        session: AsyncSession = Depends(db_session)) -> dict:
    """The authoritative draw list (ADR 0001).

    The browser renders this rather than computing its own geometry and glyph positions,
    which is what upholds INV-3: there is exactly one implementation.
    """
    doc, _ = await _load(session, doc_id)
    resolved = await resolve_for(session, doc)
    scale = max(0.05, min(4.0, scale))
    draw_list = to_draw_list(doc, scale=scale, resolve_asset=resolved.url_resolver())
    return draw_list.model_dump(by_alias=True, exclude_none=True)


@router.patch("/{doc_id}")
async def patch_document(doc_id: str, body: PatchRequest,
                         session: AsyncSession = Depends(db_session)) -> dict:
    """Merge patch for non-CRDT clients and server ops (§0.10)."""
    doc, _ = await _load(session, doc_id)
    payload = doc.model_dump(by_alias=True, exclude_none=True)
    update = body.model_dump(by_alias=True, exclude_none=True)
    payload.update(update)

    result = validate_doc(payload)
    if not result.ok or result.doc is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=[e.as_dict() for e in result.errors[:5]])
    await _save(session, result.doc)
    return {"doc": result.doc.model_dump(by_alias=True, exclude_none=True)}


@router.post("/{doc_id}/solve")
async def solve_document(doc_id: str,
                         session: AsyncSession = Depends(db_session)) -> dict:
    """Re-run the layout solver — §3.3: after any operation that changes text or size."""
    doc, _ = await _load(session, doc_id)
    result = solve(doc, SolveOpts())
    await _save(session, result.doc)
    return {
        "doc": result.doc.model_dump(by_alias=True, exclude_none=True),
        "violations": [v.as_dict() for v in result.violations],
    }


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, session: AsyncSession = Depends(db_session),
                          user_id: str = Depends(current_user_id)) -> dict:
    if not await repo.delete_document(session, doc_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    return {"deleted": True}


@router.post("/{doc_id}/duplicate")
async def duplicate_document(doc_id: str, session: AsyncSession = Depends(db_session),
                             user_id: str = Depends(current_user_id)) -> dict:
    doc, _ = await _load(session, doc_id)
    from app.schema.doc import DuplicatedProvenance

    copy = doc.model_copy(deep=True)
    copy.id = str(uuid.uuid4())
    copy.title = f"{doc.title} copy"
    copy.provenance = DuplicatedProvenance(fromDocId=doc.id)
    copy.created_at = copy.updated_at = _now()
    await repo.insert_document(session, copy, user_id)
    return {"docId": copy.id}


# --------------------------------------------------------------------------------------
# Per-layer AI operations — §3.3
# --------------------------------------------------------------------------------------


@router.post("/{doc_id}/layers/{layer_id}/regenerate")
async def regenerate(doc_id: str, layer_id: str, body: RegenerateRequest,
                     session: AsyncSession = Depends(db_session),
                     user_id: str = Depends(current_user_id)) -> dict:
    doc, _ = await _load(session, doc_id)
    try:
        outcome = await regenerate_layer(session, doc, layer_id, user_id,
                                         prompt_override=body.prompt_override,
                                         seed=body.seed)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if outcome.error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=outcome.error)
    await _save(session, doc)
    return {"patch": outcome.patch, "costCents": outcome.cost_cents}


@router.post("/{doc_id}/layers/{layer_id}/reshape")
async def reshape(doc_id: str, layer_id: str, body: ReshapeRequest,
                  session: AsyncSession = Depends(db_session)) -> dict:
    """Re-roll, re-densify or swap a vector motif. No model call, so no cost."""
    doc, _ = await _load(session, doc_id)
    try:
        patch = reshape_layer(doc, layer_id, motif=body.motif, seed=body.seed,
                              density=body.density)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await _save(session, doc)
    return {"patch": patch, "costCents": 0}


@router.post("/{doc_id}/layers/{layer_id}/remove-bg")
async def remove_bg(doc_id: str, layer_id: str,
                    session: AsyncSession = Depends(db_session),
                    user_id: str = Depends(current_user_id)) -> dict:
    doc, _ = await _load(session, doc_id)
    patch = await remove_layer_background(session, doc, layer_id, user_id)
    await _save(session, doc)
    return {"patch": patch}


@router.post("/{doc_id}/layers/{layer_id}/expand")
async def expand(doc_id: str, layer_id: str, body: ExpandRequest,
                 session: AsyncSession = Depends(db_session),
                 user_id: str = Depends(current_user_id)) -> dict:
    doc, _ = await _load(session, doc_id)
    patch = await expand_layer(session, doc, layer_id, user_id, edges=body.edges,
                               prompt=body.prompt)
    await _save(session, doc)
    return {"patch": patch}


@router.post("/{doc_id}/layers/{layer_id}/erase")
async def erase(doc_id: str, layer_id: str, body: EraseRequest,
                session: AsyncSession = Depends(db_session),
                user_id: str = Depends(current_user_id)) -> dict:
    doc, _ = await _load(session, doc_id)
    patch = await erase_region(session, doc, layer_id, user_id,
                               mask_asset_id=body.mask_asset_id,
                               brush_path=body.brush_path, brush_width=body.brush_width)
    await _save(session, doc)
    return {"patch": patch}


@router.post("/{doc_id}/copy/rewrite")
async def rewrite(doc_id: str, body: RewriteRequest,
                  session: AsyncSession = Depends(db_session)) -> dict:
    doc, _ = await _load(session, doc_id)
    missing = [lid for lid in body.layer_ids if find_layer(doc, lid)[0] is None]
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=f"unknown layer ids: {missing}")
    patches, cost = await rewrite_copy(doc, body.layer_ids, body.instruction)
    result = solve(doc, SolveOpts())
    await _save(session, result.doc)
    return {
        "patches": patches,
        "doc": result.doc.model_dump(by_alias=True, exclude_none=True),
        "violations": [v.as_dict() for v in result.violations],
        "costCents": cost,
    }


# --------------------------------------------------------------------------------------
# Resize — §4.2
# --------------------------------------------------------------------------------------


@router.post("/{doc_id}/resize")
async def resize(doc_id: str, body: ResizeRequest,
                 session: AsyncSession = Depends(db_session),
                 user_id: str = Depends(current_user_id)) -> dict:
    doc, _ = await _load(session, doc_id)
    resized = await resize_document(session, doc, body.width, body.height, user_id)
    await repo.insert_document(session, resized, user_id)
    return {"docId": resized.id,
            "doc": resized.model_dump(by_alias=True, exclude_none=True)}
