"""`validateDoc` — IMPLEMENTATION_PLAN §0.5. Runs on every write.

Pydantic already enforces structure. This layer enforces the *semantic* invariants
that a type system cannot: unique ids, resolvable font references, palette sanity,
and INV-1 (text is text).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from .doc import DesignDoc, walk


@dataclass
class DocError:
    code: str
    message: str
    layer_id: str | None = None
    path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "layerId": self.layer_id, "path": self.path}


@dataclass
class ValidationResult:
    ok: bool
    doc: DesignDoc | None = None
    errors: list[DocError] = field(default_factory=list)

    def raise_for_errors(self) -> DesignDoc:
        if not self.ok or self.doc is None:
            raise DocInvalid(self.errors)
        return self.doc


class DocInvalid(Exception):
    def __init__(self, errors: list[DocError]):
        self.errors = errors
        super().__init__("; ".join(f"[{e.code}] {e.message}" for e in errors[:8]))


def validate_doc(raw: dict[str, Any] | DesignDoc) -> ValidationResult:
    """Parse + check semantic invariants. Never raises; returns a result."""
    errors: list[DocError] = []

    if isinstance(raw, DesignDoc):
        doc = raw
    else:
        try:
            doc = DesignDoc.model_validate(raw)
        except ValidationError as exc:
            for err in exc.errors():
                errors.append(
                    DocError(
                        code="schema",
                        message=err["msg"],
                        path=".".join(str(p) for p in err["loc"]),
                    )
                )
            return ValidationResult(ok=False, errors=errors)

    errors.extend(_check_unique_ids(doc))
    errors.extend(_check_fonts(doc))
    errors.extend(_check_palette(doc))
    errors.extend(_check_geometry(doc))
    errors.extend(_check_inv1(doc))

    return ValidationResult(ok=not errors, doc=doc if not errors else None, errors=errors)


def _check_unique_ids(doc: DesignDoc) -> list[DocError]:
    seen: set[str] = set()
    out = []
    for layer, _ in walk(doc.layers):
        if layer.id in seen:
            out.append(DocError("duplicate-layer-id", f"layer id {layer.id!r} appears twice",
                                layer.id))
        seen.add(layer.id)
        if not layer.id:
            out.append(DocError("empty-layer-id", "layer id must be non-empty"))
    return out


def _check_fonts(doc: DesignDoc) -> list[DocError]:
    """Every text layer's family must be declared in doc.fonts (§0.5 FontRef[])."""
    declared = {f.family for f in doc.fonts}
    out = []
    for layer, _ in walk(doc.layers):
        if layer.type == "text" and layer.font_family not in declared:
            out.append(
                DocError(
                    "undeclared-font",
                    f"text layer uses font {layer.font_family!r} not present in doc.fonts",
                    layer.id,
                )
            )
    return out


def _check_palette(doc: DesignDoc) -> list[DocError]:
    out = []
    for i, c in enumerate(doc.palette):
        if not (c.startswith("#") and len(c) in (7, 9)):
            out.append(DocError("bad-palette-color", f"palette[{i}] = {c!r} is not a hex colour"))
    return out


def _check_geometry(doc: DesignDoc) -> list[DocError]:
    out = []
    for layer, _ in walk(doc.layers):
        f = layer.frame
        for name, v in (("x", f.x), ("y", f.y), ("w", f.w), ("h", f.h), ("rotation", f.rotation)):
            if not math.isfinite(v):
                out.append(DocError("non-finite-frame", f"frame.{name} is not finite", layer.id))
        if layer.type in ("text", "shape") and (f.w <= 0 or f.h <= 0):
            out.append(DocError("degenerate-frame", "frame has zero width or height", layer.id))
    return out


def _check_inv1(doc: DesignDoc) -> list[DocError]:
    """INV-1: no text layer may carry raster generation params.

    A text layer whose meta.generation names an image adapter means something in the
    pipeline tried to rasterise copy. That is the failure mode Appendix A.1 describes,
    and it must fail the write rather than ship.
    """
    raster_adapters = {"TextToImage", "TransparentImage", "Inpainter", "Upscaler"}
    out = []
    for layer, _ in walk(doc.layers):
        if (
            layer.type == "text"
            and layer.meta.generation is not None
            and layer.meta.generation.adapter in raster_adapters
        ):
            out.append(
                DocError(
                    "inv1-text-rasterised",
                    f"text layer carries raster generation params "
                    f"({layer.meta.generation.adapter}); text must never be rasterised",
                    layer.id,
                )
            )
    return out
