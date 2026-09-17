"""Asset service — IMPLEMENTATION_PLAN §0.8 and §6.1.

Layout on the object store:

    assets/{userId}/{assetId}/original.{ext}
    assets/{userId}/{assetId}/w{512|1024|2048}.webp
    assets/{userId}/{assetId}/mask.png
    docs/{docId}/thumb.webp

Rules enforced here:
  * layers reference an assetId, never a URL — resolution happens in `url_for`
  * alpha assets are never JPEG-encoded; that destroys the matte edge
  * derivatives are produced lazily on first request and cached
  * every generated asset carries `gen_hash`, and the unique index on it makes an
    identical generation request free (§6.1)
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
from PIL import Image

from app.config import get_settings

DERIVATIVE_WIDTHS = (512, 1024, 2048)

_EXT_FOR_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "application/pdf": "pdf",
}


@dataclass
class StoredBlob:
    storage_key: str
    mime: str
    width: int | None
    height: int | None
    has_alpha: bool
    size_bytes: int


def canonical_gen_hash(params: dict[str, Any]) -> str:
    """sha256 of canonicalised GenerationParams (§6.1).

    Key order is sorted and prompt whitespace collapsed — §6.1 warns that skipping this
    misses most cache hits, since two callers rarely build the dict the same way.
    """
    normalised: dict[str, Any] = {}
    for key in sorted(params):
        value = params[key]
        if isinstance(value, str):
            value = " ".join(value.split())
        elif isinstance(value, dict):
            value = {k: value[k] for k in sorted(value)}
        normalised[key] = value
    blob = json.dumps(normalised, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def probe_image(data: bytes) -> tuple[str, int | None, int | None, bool]:
    """(mime, width, height, has_alpha) without trusting the caller."""
    if data[:5] == b"<?xml" or data[:4] == b"<svg":
        return "image/svg+xml", None, None, True
    try:
        with Image.open(io.BytesIO(data)) as img:
            mime = Image.MIME.get(img.format or "", "application/octet-stream")
            has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
            return mime, img.width, img.height, has_alpha
    except Exception:  # noqa: BLE001
        return "application/octet-stream", None, None, False


class StorageBackend:
    def put(self, key: str, data: bytes, mime: str) -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes | None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> int:
        raise NotImplementedError

    def url(self, key: str, ttl: int) -> str:
        raise NotImplementedError


class S3Backend(StorageBackend):
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.public_base = settings.s3_public_base_url
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put(self, key: str, data: bytes, mime: str) -> None:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=mime)

    def get(self, key: str) -> bytes | None:
        try:
            return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError:
            return None

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete_prefix(self, prefix: str) -> int:
        paginator = self._client.get_paginator("list_objects_v2")
        removed = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objects:
                self._client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
                removed += len(objects)
        return removed

    def url(self, key: str, ttl: int) -> str:
        if self.public_base:
            return f"{self.public_base.rstrip('/')}/{key}"
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl
        )


class LocalBackend(StorageBackend):
    """Filesystem fallback so the stack runs with no object store at all."""

    def __init__(self) -> None:
        self.root = Path(get_settings().local_storage_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Prevent a crafted key from escaping the storage root.
        resolved = (self.root / key).resolve()
        if not str(resolved).startswith(str(self.root.resolve())):
            raise ValueError(f"storage key escapes the root: {key!r}")
        return resolved

    def put(self, key: str, data: bytes, mime: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.exists() else None

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete_prefix(self, prefix: str) -> int:
        base = self._path(prefix)
        if not base.exists():
            return 0
        removed = 0
        for path in sorted(base.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
                removed += 1
            else:
                path.rmdir()
        return removed

    def url(self, key: str, ttl: int) -> str:
        # Served by the API's /v1/assets/raw route.
        return f"/v1/assets/raw/{key}"


@lru_cache(maxsize=1)
def get_backend() -> StorageBackend:
    settings = get_settings()
    if settings.storage_backend == "local":
        return LocalBackend()
    try:
        backend = S3Backend()
        backend._client.head_bucket(Bucket=backend.bucket)
        return backend
    except Exception:  # noqa: BLE001 - object store down should not block local dev
        return LocalBackend()


# --------------------------------------------------------------------------------------
# Keys and derivatives
# --------------------------------------------------------------------------------------


def original_key(user_id: str | None, asset_id: str, mime: str) -> str:
    ext = _EXT_FOR_MIME.get(mime, "bin")
    return f"assets/{user_id or 'anon'}/{asset_id}/original.{ext}"


def derivative_key(user_id: str | None, asset_id: str, width: int) -> str:
    return f"assets/{user_id or 'anon'}/{asset_id}/w{width}.webp"


def mask_key(user_id: str | None, asset_id: str) -> str:
    return f"assets/{user_id or 'anon'}/{asset_id}/mask.png"


def doc_thumb_key(doc_id: str) -> str:
    return f"docs/{doc_id}/thumb.webp"


_derivative_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def ensure_derivative(user_id: str | None, asset_id: str, storage_key: str,
                      width: int) -> str | None:
    """Produce and cache a width-limited WebP. Returns the derivative key, or None if
    the source is not a raster (SVG needs no ladder)."""
    if width not in DERIVATIVE_WIDTHS:
        width = min(DERIVATIVE_WIDTHS, key=lambda w: abs(w - width))
    backend = get_backend()
    key = derivative_key(user_id, asset_id, width)
    if backend.exists(key):
        return key

    with _locks_guard:
        lock = _derivative_locks.setdefault(key, threading.Lock())
    with lock:
        if backend.exists(key):
            return key
        data = backend.get(storage_key)
        if not data:
            return None
        try:
            with Image.open(io.BytesIO(data)) as img:
                if img.width <= width:
                    return storage_key  # already small enough; do not upscale
                has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
                img = img.convert("RGBA" if has_alpha else "RGB")
                height = max(1, round(img.height * width / img.width))
                img = img.resize((width, height), Image.LANCZOS)
                buf = io.BytesIO()
                # Lossless for alpha: §0.8 forbids lossy-compressing a matte edge.
                img.save(buf, format="WEBP", quality=90, lossless=has_alpha, method=4)
                backend.put(key, buf.getvalue(), "image/webp")
                return key
        except Exception:  # noqa: BLE001
            return None


def store_bytes(user_id: str | None, asset_id: str, data: bytes,
                mime: str | None = None) -> StoredBlob:
    detected_mime, width, height, has_alpha = probe_image(data)
    mime = mime or detected_mime
    if has_alpha and mime == "image/jpeg":
        raise ValueError("refusing to store an alpha asset as JPEG (§0.8)")
    key = original_key(user_id, asset_id, mime)
    get_backend().put(key, data, mime)
    return StoredBlob(storage_key=key, mime=mime, width=width, height=height,
                      has_alpha=has_alpha, size_bytes=len(data))


def read_bytes(storage_key: str) -> bytes | None:
    return get_backend().get(storage_key)


def url_for(storage_key: str, ttl: int | None = None) -> str:
    settings = get_settings()
    return get_backend().url(storage_key, ttl or settings.signed_url_ttl_seconds)


def purge_asset(user_id: str | None, asset_id: str) -> int:
    """§7 data retention: delete every derivative of an asset, not just the original."""
    return get_backend().delete_prefix(f"assets/{user_id or 'anon'}/{asset_id}/")
