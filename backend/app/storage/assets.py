"""Object storage for generated images (MinIO/S3, or a local folder fallback).

The Lido.js (template) flow uploads each generated image to
`public/lido-generated/<design_id>/` (see `app/lido_corpus/generated.py`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import get_settings


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
