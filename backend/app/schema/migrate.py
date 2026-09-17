"""Schema migrations — IMPLEMENTATION_PLAN §0.5.

Migrations are pure functions `dict -> dict`, chained by version. Keep them pure and
covered by a fixture in `fixtures/`. `SCHEMA_VERSION` lives in `doc.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .doc import SCHEMA_VERSION


def _v1_to_v2(d: dict[str, Any]) -> dict[str, Any]:
    """v1 had `layers[].z` instead of array order, and no `constraints`."""
    layers = sorted(d.get("layers", []), key=lambda layer: layer.pop("z", 0))
    for layer in layers:
        layer.setdefault(
            "constraints",
            {"horizontal": "left", "vertical": "top", "lockAspect": False, "priority": 50},
        )
    d["layers"] = layers
    d["schemaVersion"] = 2
    return d


def _v2_to_v3(d: dict[str, Any]) -> dict[str, Any]:
    """v3 introduced `meta.generation` (INV-2) and `canvas.safeMargin`."""
    d.setdefault("canvas", {}).setdefault("safeMargin", 0)
    d.setdefault("canvas", {}).setdefault("dpi", 72)

    def fix(layer: dict[str, Any]) -> None:
        meta = layer.setdefault("meta", {})
        # v2 stored the prompt loose on the layer; v3 nests it under meta.generation.
        if "prompt" in layer:
            meta["generation"] = {
                "adapter": "TextToImage",
                "model": layer.pop("model", "unknown"),
                "prompt": layer.pop("prompt"),
                "negativePrompt": layer.pop("negativePrompt", None),
                "seed": layer.pop("seed", 0),
                "params": {},
            }
        for child in layer.get("children", []):
            fix(child)

    for layer in d.get("layers", []):
        fix(layer)
    d["schemaVersion"] = 3
    return d


MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
}


class UnknownSchemaVersion(Exception):
    pass


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a raw document dict to `SCHEMA_VERSION`. Idempotent."""
    d = dict(raw)
    version = int(d.get("schemaVersion", 1))
    if version > SCHEMA_VERSION:
        raise UnknownSchemaVersion(
            f"document is schemaVersion {version}, newer than supported {SCHEMA_VERSION}"
        )
    while version < SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise UnknownSchemaVersion(f"no migration registered from version {version}")
        d = step(d)
        new_version = int(d["schemaVersion"])
        if new_version <= version:
            raise UnknownSchemaVersion(f"migration from {version} did not advance the version")
        version = new_version
    return d
