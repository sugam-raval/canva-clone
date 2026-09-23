"""Persist Lido.js (template) generations.

The design JSON goes to `lido_generated/`, same directory and `[{"layers", "meta"}]`
shape as scratch designs, so both appear in one gallery and `GET /v1/lido/scratch/{id}`
loads either. Generated images go to the object store (MinIO) under `public/`, which
the bucket policy makes anonymously readable: a saved design must keep working long
after it was made, and the store's default presigned URLs expire within the hour.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from app.config import get_settings
from app.storage.assets import S3Backend, get_backend

from .loader import DEFAULT_CORPUS_DIR

GENERATED_DIR = DEFAULT_CORPUS_DIR.parent / "lido_generated"
ASSET_PREFIX = "public/lido-generated"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def new_design_id(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")[:40] or "design"
    return f"tpl-{slug}-{uuid.uuid4().hex[:8]}"


def asset_key(design_id: str, name: str) -> str:
    return f"{ASSET_PREFIX}/{design_id}/{name}.png"


def public_url(backend, key: str) -> str:
    """A URL for `key` that never expires. On S3/MinIO that's the object's direct path
    (or `S3_PUBLIC_BASE_URL` when the store sits behind another host); the local
    fallback backend already serves keys through a permanent API route."""
    if isinstance(backend, S3Backend):
        settings = get_settings()
        base = settings.s3_public_base_url or f"{settings.s3_endpoint_url}/{backend.bucket}"
        return f"{base.rstrip('/')}/{key}"
    return backend.url(key, get_settings().signed_url_ttl_seconds)


def upload_asset(design_id: str, name: str, data: bytes) -> str:
    """Upload one generated PNG and return the URL the document should reference.
    Blocking (boto3); call it off the event loop."""
    backend = get_backend()
    key = asset_key(design_id, name)
    backend.put(key, data, "image/png")
    return public_url(backend, key)


def save_design(design_id: str, document: list[dict], directory: Path | None = None) -> Path:
    directory = directory or GENERATED_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{design_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)
    return path
