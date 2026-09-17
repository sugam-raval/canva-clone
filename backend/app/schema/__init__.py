"""Document schema — the source of truth (IMPLEMENTATION_PLAN §0.5)."""

from .doc import (
    SCHEMA_VERSION,
    Adjustments,
    AutoFit,
    Backdrop,
    Base,
    BlendMode,
    Canvas,
    Constraints,
    DesignDoc,
    DocId,
    Effect,
    FontRef,
    Frame,
    GenerationParams,
    GroupLayer,
    ImageLayer,
    Layer,
    LayerId,
    LayerMeta,
    LayerRole,
    ShapeLayer,
    SvgLayer,
    TextLayer,
    find_layer,
    replace_layer,
    walk,
)
from .migrate import UnknownSchemaVersion, migrate
from .validate import DocError, DocInvalid, ValidationResult, validate_doc

__all__ = [
    "SCHEMA_VERSION", "Adjustments", "AutoFit", "Backdrop", "Base", "BlendMode", "Canvas",
    "Constraints", "DesignDoc", "DocError", "DocId", "DocInvalid", "Effect", "FontRef",
    "Frame", "GenerationParams", "GroupLayer", "ImageLayer", "Layer", "LayerId", "LayerMeta",
    "LayerRole", "ShapeLayer", "SvgLayer", "TextLayer", "UnknownSchemaVersion",
    "ValidationResult", "find_layer", "migrate", "replace_layer", "validate_doc", "walk",
]
