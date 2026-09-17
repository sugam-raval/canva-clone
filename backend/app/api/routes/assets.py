"""Asset and font endpoints — IMPLEMENTATION_PLAN §0.8, §4.1."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_id, db_session
from app.db import repo
from app.layout.fonts import get_registry
from app.storage import assets as storage

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1", tags=["assets"])

MAX_UPLOAD_BYTES = 40 * 1024 * 1024
ALLOWED_UPLOAD_MIME = {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}


@router.post("/uploads")
async def upload(file: UploadFile = File(...),
                 session: AsyncSession = Depends(db_session),
                 user_id: str = Depends(current_user_id)) -> dict:
    """§1.4.5: a provided logo or product photo is a first-class path, not an add-on."""
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"upload exceeds {MAX_UPLOAD_BYTES // 1024 // 1024} MB")

    # Trust the bytes, not the declared content type.
    mime, width, height, has_alpha = storage.probe_image(data)
    if mime not in ALLOWED_UPLOAD_MIME:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail=f"unsupported image type: {mime}")

    asset_id = str(uuid.uuid4())
    blob = storage.store_bytes(user_id, asset_id, data, mime)
    stored = await repo.insert_asset(
        session, user_id=user_id, kind="upload", storage_key=blob.storage_key,
        mime=blob.mime, width=blob.width, height=blob.height,
        has_alpha=blob.has_alpha, size_bytes=blob.size_bytes,
        gen_hash=None, gen_params={"filename": file.filename},
    )
    return {"assetId": stored, "url": storage.url_for(blob.storage_key),
            "width": width, "height": height, "hasAlpha": has_alpha, "mime": mime}


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str, width: int | None = None,
                    session: AsyncSession = Depends(db_session)) -> dict:
    asset = await repo.get_asset(session, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="asset not found")
    key = asset["storage_key"]
    if width:
        derivative = storage.ensure_derivative(
            str(asset["user_id"]) if asset.get("user_id") else None,
            asset_id, key, width)
        key = derivative or key
    return {"assetId": asset_id, "url": storage.url_for(key), "mime": asset["mime"],
            "width": asset["width"], "height": asset["height"],
            "hasAlpha": asset["has_alpha"]}


@router.get("/assets/raw/{storage_key:path}")
async def get_raw(storage_key: str) -> Response:
    """Serves assets when the local filesystem backend is in use.

    With S3/MinIO the client gets a presigned URL and never touches this route.
    """
    data = storage.read_bytes(storage_key)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="asset not found")
    mime, _, _, _ = storage.probe_image(data)
    return Response(content=data, media_type=mime,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/fonts")
async def list_fonts() -> dict:
    """@font-face descriptors, so the editor previews the exact face the exporter draws."""
    registry = get_registry()
    return {
        "faces": registry.css_face_list(),
        "families": registry.families,
        "byVibe": {vibe: registry.families_for_vibe(vibe)
                   for vibe in ("geometric", "humanist", "serif-editorial",
                                "display-bold")},
    }


@router.get("/motifs")
async def list_motifs() -> dict:
    """The vector motifs a shape layer can be reshaped into.

    Split by family because the two behave differently under the inspector: decorative
    motifs frame a design, compositional ones are the design. Stroked motifs are open
    contours and take a stroke rather than a fill.
    """
    from app.templates_corpus.ornament import COMPOSITIONAL_MOTIFS, MOTIFS, STROKE_MOTIFS
    return {
        "motifs": sorted(MOTIFS),
        "compositional": sorted(COMPOSITIONAL_MOTIFS),
        "decorative": sorted(MOTIFS - COMPOSITIONAL_MOTIFS),
        "stroked": sorted(STROKE_MOTIFS),
    }


@router.get("/fonts/{font_key}.ttf")
async def get_font(font_key: str) -> Response:
    registry = get_registry()
    try:
        face = registry.face_by_key(font_key)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=f"unknown font {font_key}") from exc
    return Response(content=face.path.read_bytes(), media_type="font/ttf",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})
