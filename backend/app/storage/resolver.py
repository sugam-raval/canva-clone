"""Asset resolution — IMPLEMENTATION_PLAN §0.8.

"Layers reference an assetId, never a URL. The asset service resolves to a signed URL
plus a size ladder; this keeps documents portable and CDN-swappable."

Two resolvers, both built from one prefetched batch so a render costs a single query:
  * `url_resolver`   — assetId -> signed URL, for the browser
  * `image_loader`   — assetId -> encoded bytes, for the Skia exporter
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.schema.doc import DesignDoc, walk
from app.storage import assets as storage

log = structlog.get_logger(__name__)


def asset_ids_in(doc: DesignDoc) -> list[str]:
    out: list[str] = []
    for layer, _ in walk(doc.layers):
        for attr in ("asset_id", "back_plate_asset_id"):
            value = getattr(layer, attr, None)
            if value:
                out.append(value)
    return sorted(set(out))


class ResolvedAssets:
    def __init__(self, rows: dict[str, dict]):
        self.rows = rows

    def url(self, asset_id: str) -> str:
        row = self.rows.get(asset_id)
        if not row:
            return ""
        return storage.url_for(row["storage_key"])

    def url_at_width(self, asset_id: str, width: float) -> str:
        """Smallest derivative that still covers `width` (§0.8 size ladder)."""
        row = self.rows.get(asset_id)
        if not row:
            return ""
        natural = row.get("width") or 0
        if not natural or width <= 0 or natural <= width * 1.1:
            return storage.url_for(row["storage_key"])
        target = next((w for w in storage.DERIVATIVE_WIDTHS if w >= width), None)
        if target is None:
            return storage.url_for(row["storage_key"])
        key = storage.ensure_derivative(row.get("user_id"), asset_id,
                                        row["storage_key"], target)
        return storage.url_for(key or row["storage_key"])

    def bytes(self, asset_id: str) -> bytes | None:
        row = self.rows.get(asset_id)
        return storage.read_bytes(row["storage_key"]) if row else None

    def url_resolver(self):
        return lambda asset_id: self.url(asset_id)

    def image_loader(self):
        def load(asset_id: str, _asset_url: str) -> bytes | None:
            data = self.bytes(asset_id)
            if data is None and asset_id:
                log.warning("asset.missing", asset_id=asset_id)
            return data

        return load


async def resolve_for(session: AsyncSession, doc: DesignDoc) -> ResolvedAssets:
    ids = asset_ids_in(doc)
    rows = await repo.get_assets(session, ids) if ids else {}
    return ResolvedAssets(rows)
