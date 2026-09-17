"""Export endpoints — IMPLEMENTATION_PLAN §4.1.

PNG/JPEG rasterise at scale; PDF stays vector with live, embedded-font text; SVG emits
shapes and text as elements. All four consume the same draw list the browser renders,
which is what makes an export match the canvas (INV-3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_id, db_session
from app.api.schemas import ExportRequest, ExportResponse
from app.db import repo
from app.renderer.core import to_draw_list
from app.renderer.skia_backend import render_jpeg, render_pdf, render_png, render_svg, render_webp
from app.schema.doc import DesignDoc
from app.schema.migrate import migrate
from app.schema.validate import validate_doc
from app.storage import assets as storage
from app.storage.resolver import resolve_for

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1", tags=["export"])

MIME_FOR_FORMAT = {
    "png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp",
    "pdf": "application/pdf", "svg": "image/svg+xml",
}


@router.post("/docs/{doc_id}/export", response_model=ExportResponse)
async def create_export(doc_id: str, body: ExportRequest,
                        session: AsyncSession = Depends(db_session),
                        user_id: str = Depends(current_user_id)) -> ExportResponse:
    row = await repo.get_document(session, doc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    result = validate_doc(migrate(row["doc"]))
    if not result.ok or result.doc is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="stored document is invalid")
    doc: DesignDoc = result.doc

    export_id = str(uuid.uuid4())
    await session.execute(
        sql_text("insert into exports (id, doc_id, format, scale, state) "
                 "values (:id, :doc, :fmt, :scale, 'running')"),
        {"id": export_id, "doc": doc_id, "fmt": body.format, "scale": body.scale},
    )

    try:
        data = await _render(session, doc, body.format, body.scale)
    except Exception as exc:
        log.exception("export.failed", doc_id=doc_id, format=body.format)
        await session.execute(
            sql_text("update exports set state='failed', error=:err, finished_at=now() "
                     "where id=:id"),
            {"id": export_id, "err": str(exc)[:500]})
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"export failed: {exc}") from exc

    key = f"exports/{doc_id}/{export_id}.{body.format}"
    storage.get_backend().put(key, data, MIME_FOR_FORMAT[body.format])
    stored = await repo.insert_asset(
        session, user_id=user_id, kind="export", storage_key=key,
        mime=MIME_FOR_FORMAT[body.format], width=None, height=None, has_alpha=False,
        size_bytes=len(data), gen_hash=None,
        gen_params={"docId": doc_id, "format": body.format, "scale": body.scale},
    )
    await session.execute(
        sql_text("update exports set state='done', asset_id=cast(:asset as uuid), "
                 "finished_at=now() where id=:id"),
        {"id": export_id, "asset": stored})

    return ExportResponse(exportId=export_id, state="done",
                          url=storage.url_for(key))


async def _render(session: AsyncSession, doc: DesignDoc, fmt: str,
                  scale: float) -> bytes:
    resolved = await resolve_for(session, doc)
    draw_list = to_draw_list(doc, scale=scale, resolve_asset=resolved.url_resolver())
    loader = resolved.image_loader()
    if fmt == "png":
        return render_png(draw_list, loader)
    if fmt == "jpeg":
        return render_jpeg(draw_list, loader)
    if fmt == "webp":
        return render_webp(draw_list, loader)
    if fmt == "pdf":
        return render_pdf(draw_list, loader, title=doc.title, dpi=doc.canvas.dpi)
    if fmt == "svg":
        return render_svg(draw_list, loader)
    raise ValueError(f"unsupported format {fmt}")


@router.get("/exports/{export_id}")
async def get_export(export_id: str,
                     session: AsyncSession = Depends(db_session)) -> ExportResponse:
    row = (await session.execute(
        sql_text("select e.id, e.state, e.error, a.storage_key from exports e "
                 "left join assets a on a.id = e.asset_id where e.id = :id"),
        {"id": export_id})).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="export not found")
    if row["state"] == "failed":
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=row["error"] or "export failed")
    return ExportResponse(
        exportId=export_id, state=row["state"],
        url=storage.url_for(row["storage_key"]) if row["storage_key"] else None)


@router.get("/docs/{doc_id}/preview.{fmt}")
async def preview(doc_id: str, fmt: str, scale: float = 0.5,
                  session: AsyncSession = Depends(db_session)) -> Response:
    """Render inline without persisting an export row — used by the editor's preview."""
    if fmt not in MIME_FOR_FORMAT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"unsupported format {fmt}")
    row = await repo.get_document(session, doc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    result = validate_doc(migrate(row["doc"]))
    if not result.ok or result.doc is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid document")
    data = await _render(session, result.doc, fmt, max(0.05, min(2.0, scale)))
    return Response(content=data, media_type=MIME_FOR_FORMAT[fmt])


def _now() -> str:
    return datetime.now(UTC).isoformat()
