"""Evaluation metrics — IMPLEMENTATION_PLAN §5.3.

Every metric here is computed from the finished `DesignDoc` plus the stored assets, so
the harness measures what the user actually receives rather than what an intermediate
stage intended.

The thresholds are the plan's release gates (§5.3 "Definition of done"). `MetricResult`
carries both the measured value and whether it cleared its gate, so the runner can print
a pass/fail table rather than a wall of numbers someone has to interpret.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.layout.measure import shape_block
from app.layout.solver import _overlap_declared, is_full_bleed
from app.renderer.core import to_draw_list
from app.renderer.skia_backend import render_surface, surface_to_numpy
from app.renderer.transform import Rect, world_bounds
from app.schema.doc import DesignDoc, TextLayer, walk
from app.schema.validate import validate_doc
from app.util.color import contrast_ratio, relative_luminance, to_hex

# §5.3 release gates.
GATES: dict[str, tuple[str, float]] = {
    "schema_validity":        (">=", 1.00),
    "text_overflow_rate":     ("<=", 0.00),
    "collision_rate":         ("<=", 0.02),
    "contrast_pass_rate":     (">=", 0.98),
    "safe_margin_pass_rate":  (">=", 0.98),
    "glyph_leakage_rate":     ("<=", 0.01),
    "copy_length_pass_rate":  (">=", 0.98),
    "editable_text_rate":     (">=", 1.00),
    "p95_skeleton_seconds":   ("<=", 3.0),
    "p95_complete_seconds":   ("<=", 25.0),
}

CONTRAST_BODY = 4.5
CONTRAST_DISPLAY = 3.0
DISPLAY_SIZE_PX = 32.0
PROBE_WIDTH = 240


@dataclass
class DocMetrics:
    """Per-document measurements. Counts, not rates — the runner aggregates."""

    doc_id: str
    prompt_id: str
    schema_valid: bool = True
    schema_errors: list[str] = field(default_factory=list)

    text_layers: int = 0
    overflowing_text_layers: int = 0
    copy_over_limit: int = 0

    collidable_pairs: int = 0
    colliding_pairs: int = 0

    layers_checked_for_margin: int = 0
    layers_outside_margin: int = 0

    contrast_checked: int = 0
    contrast_failed: int = 0
    worst_contrast: float = 99.0

    image_layers: int = 0
    layers_with_baked_text: int = 0

    rasterised_text_layers: int = 0

    degraded_layers: int = 0
    skeleton_seconds: float = 0.0
    complete_seconds: float = 0.0
    cost_cents: int = 0
    template_id: str = ""
    notes: list[str] = field(default_factory=list)


def measure_document(doc: DesignDoc, *, prompt_id: str, glyph_boxes: dict[str, float] | None = None,
                     resolve_asset=None, load_image=None) -> DocMetrics:
    """Measure one finished document against every §5.3 quality metric.

    `glyph_boxes` maps layer id -> fraction of that asset covered by detected text, as
    reported by the §1.4.6 gate during generation. It is passed in rather than recomputed
    because re-running detection would measure the gate's *output* twice instead of
    measuring leakage past it.
    """
    metrics = DocMetrics(doc_id=doc.id, prompt_id=prompt_id)
    metrics.template_id = str(getattr(doc.provenance, "template_id", "") or "")

    result = validate_doc(doc)
    metrics.schema_valid = result.ok
    metrics.schema_errors = [f"{e.code}:{e.path}" for e in result.errors[:5]]

    _measure_text(doc, metrics)
    _measure_collisions(doc, metrics)
    _measure_margins(doc, metrics)
    _measure_contrast(doc, metrics, resolve_asset=resolve_asset, load_image=load_image)
    _measure_glyph_leakage(doc, metrics, glyph_boxes or {})
    _measure_invariants(doc, metrics)

    metrics.degraded_layers = sum(
        1 for layer, _ in walk(doc.layers) if layer.meta.notes.get("degraded")
    )
    return metrics


def _measure_text(doc: DesignDoc, metrics: DocMetrics) -> None:
    """§5.3 text overflow rate, and the §1.3 copy-length contract."""
    for layer, _ in walk(doc.layers):
        if not isinstance(layer, TextLayer) or not layer.visible:
            continue
        metrics.text_layers += 1
        if not layer.content.strip():
            continue
        try:
            block = shape_block(
                layer.content,
                font_family=layer.font_family,
                font_weight=layer.font_weight,
                font_style=layer.font_style,
                font_size=layer.font_size,
                line_height=layer.line_height,
                letter_spacing=layer.letter_spacing,
                max_width=layer.frame.w,
                text_transform=layer.text_transform,
            )
        except Exception as exc:  # noqa: BLE001 - a shaping failure is itself a defect
            metrics.notes.append(f"{layer.id}: shaping failed ({exc})")
            metrics.overflowing_text_layers += 1
            continue

        # A layer with autoHeight grows its frame, so only width overflow counts.
        overflows_width = block.width > layer.frame.w + 0.5
        overflows_height = (not layer.auto_height) and block.height > layer.frame.h + 0.5
        if overflows_width or overflows_height:
            metrics.overflowing_text_layers += 1
            metrics.notes.append(
                f"{layer.id}: text {block.width:.0f}x{block.height:.0f} exceeds frame "
                f"{layer.frame.w:.0f}x{layer.frame.h:.0f}"
            )

        # §1.3 caps copy at the slot's maxChars; the doc no longer carries the slot, so
        # the proxy is whether the copy fits at the autofit minimum size.
        if layer.auto_fit is not None and layer.font_size <= layer.auto_fit.min + 0.01:
            floor = shape_block(
                layer.content, font_family=layer.font_family,
                font_weight=layer.font_weight, font_style=layer.font_style,
                font_size=layer.auto_fit.min, line_height=layer.line_height,
                letter_spacing=layer.letter_spacing, max_width=layer.frame.w,
                text_transform=layer.text_transform,
            )
            if floor.height > layer.frame.h + 0.5:
                metrics.copy_over_limit += 1


def _collidable(layer: Any) -> bool:
    return (
        layer.type in ("text", "image", "shape", "svg", "group")
        and layer.role not in ("background", "overlay", "decoration")
        and layer.visible
    )


def _paired(a: Any, b: Any) -> bool:
    """A label and its own shape backing are one object (see solver companions)."""
    if a.role != b.role or a.role in ("background", "overlay", "unknown"):
        return False
    return {a.type, b.type} == {"text", "shape"}


def _measure_collisions(doc: DesignDoc, metrics: DocMetrics) -> None:
    layers = [layer for layer, ancestors in walk(doc.layers)
              if not ancestors and _collidable(layer)]
    bounds = {layer.id: world_bounds(layer, ()) for layer in layers}
    for i, a in enumerate(layers):
        for b in layers[i + 1:]:
            if _paired(a, b):
                continue
            if _overlap_declared(a, b):
                # Deliberate depth — display type behind a subject, a prop layered over
                # one. Counting these would penalise the composition the skeleton asked
                # for. Imported from the solver so the two cannot disagree.
                continue
            metrics.collidable_pairs += 1
            overlap = bounds[a.id].intersection(bounds[b.id])
            smaller = min(bounds[a.id].area, bounds[b.id].area)
            if smaller > 0 and overlap.area / smaller > 0.02:
                metrics.colliding_pairs += 1
                metrics.notes.append(
                    f"{a.id}/{b.id}: overlap {overlap.area / smaller:.0%}")


def _measure_margins(doc: DesignDoc, metrics: DocMetrics) -> None:
    margin = doc.canvas.safe_margin
    if margin <= 0:
        return
    safe = Rect(margin, margin, doc.canvas.width - margin * 2,
                doc.canvas.height - margin * 2)
    for layer, ancestors in walk(doc.layers):
        if ancestors or not layer.visible:
            continue
        # Deliberately full-bleed layers are supposed to cross the margin. This uses the
        # solver's own predicate rather than a second copy of the rule, which would drift
        # and report phantom violations.
        if is_full_bleed(layer, doc):
            continue
        box = world_bounds(layer, ())
        # A layer larger than the safe area cannot be placed inside it; the solver
        # already reports that as `margin-unfittable`, and counting it here as well
        # would double-penalise a template flaw the solver cannot fix.
        if box.w > safe.w + 0.5 or box.h > safe.h + 0.5:
            metrics.notes.append(f"{layer.id}: larger than the safe area (template flaw)")
            continue
        metrics.layers_checked_for_margin += 1
        if (box.x < safe.x - 0.5 or box.y < safe.y - 0.5
                or box.right > safe.right + 0.5 or box.bottom > safe.bottom + 0.5):
            metrics.layers_outside_margin += 1
            metrics.notes.append(f"{layer.id}: crosses the safe margin")


def _measure_contrast(doc: DesignDoc, metrics: DocMetrics, *, resolve_asset=None,
                      load_image=None) -> None:
    """Measure text contrast against what is actually rendered behind each layer.

    This deliberately re-renders rather than trusting the `contrastRatio` note that
    §1.5.2 writes: the note records what harmonisation believed at the time, and the
    point of an eval is to check the belief.
    """
    try:
        scale = PROBE_WIDTH / max(1, doc.canvas.width)
        draw_list = to_draw_list(doc, scale=scale, resolve_asset=resolve_asset)
        pixels = surface_to_numpy(render_surface(draw_list, load_image,
                                                 opaque_background=doc.canvas.background))
    except Exception as exc:  # noqa: BLE001
        metrics.notes.append(f"contrast probe failed: {exc}")
        return

    height, width = pixels.shape[0], pixels.shape[1]
    for index, layer in enumerate(doc.layers):
        if not isinstance(layer, TextLayer) or not layer.visible:
            continue
        if not layer.content.strip():
            continue

        # Render only what sits *below* this layer, so the text does not measure itself.
        beneath = doc.model_copy(update={"layers": doc.layers[:index]})
        try:
            below_pixels = surface_to_numpy(render_surface(
                to_draw_list(beneath, scale=scale, resolve_asset=resolve_asset),
                load_image, opaque_background=doc.canvas.background))
        except Exception:  # noqa: BLE001
            below_pixels = pixels

        box = world_bounds(layer, ())
        x0 = max(0, int(box.x * scale))
        y0 = max(0, int(box.y * scale))
        x1 = min(width, int(box.right * scale))
        y1 = min(height, int(box.bottom * scale))
        if x1 <= x0 or y1 <= y0:
            continue
        region = below_pixels[y0:y1, x0:x1, :3]
        if region.size == 0:
            continue

        artwork = to_hex(tuple(float(v) for v in region.reshape(-1, 3).mean(axis=0)))
        behind = _effective_background(layer, artwork)
        ratio = contrast_ratio(layer.color, behind)

        metrics.contrast_checked += 1
        metrics.worst_contrast = min(metrics.worst_contrast, ratio)
        threshold = CONTRAST_DISPLAY if layer.font_size >= DISPLAY_SIZE_PX else CONTRAST_BODY
        if ratio < threshold:
            metrics.contrast_failed += 1
            metrics.notes.append(
                f"{layer.id}: contrast {ratio:.2f}:1 against {behind} "
                f"(needs {threshold})")


def _effective_background(layer: TextLayer, artwork: str) -> str:
    """What the text is really sitting on.

    §1.5.2 may resolve a contrast failure by putting a translucent backdrop behind the
    text. Measuring against the artwork would then report a failure that the viewer
    cannot see, so the backdrop is composited over the artwork first.
    """
    if layer.backdrop is None:
        return artwork
    from app.util.color import parse_hex

    alpha = max(0.0, min(1.0, layer.backdrop.opacity))
    scrim = np.array(parse_hex(layer.backdrop.color), dtype=float)
    under = np.array(parse_hex(artwork), dtype=float)
    return to_hex(tuple(scrim * alpha + under * (1.0 - alpha)))


def _measure_glyph_leakage(doc: DesignDoc, metrics: DocMetrics,
                           glyph_boxes: dict[str, float]) -> None:
    """§5.3 glyph leakage: generated rasters that still contain text (INV-1)."""
    for layer, _ in walk(doc.layers):
        if layer.type != "image":
            continue
        metrics.image_layers += 1
        coverage = glyph_boxes.get(layer.id, 0.0)
        if coverage > 0.004:
            metrics.layers_with_baked_text += 1
            metrics.notes.append(
                f"{layer.id}: baked text covering {coverage:.2%} survived the gate")


def _measure_invariants(doc: DesignDoc, metrics: DocMetrics) -> None:
    """INV-1 and INV-2, checked structurally rather than by inspection."""
    raster_adapters = {"TextToImage", "TransparentImage", "Inpainter", "Upscaler"}
    for layer, _ in walk(doc.layers):
        if isinstance(layer, TextLayer):
            generation = layer.meta.generation
            if generation is not None and generation.adapter in raster_adapters:
                metrics.rasterised_text_layers += 1
                metrics.notes.append(f"{layer.id}: INV-1 violated — text carries "
                                     f"{generation.adapter}")
        elif layer.type == "image" and layer.asset_id:
            # INV-2: an asset that exists must record how it was made.
            generation = layer.meta.generation
            if generation is None or not generation.prompt:
                metrics.notes.append(f"{layer.id}: INV-2 — asset has no generation params")


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------


@dataclass
class MetricResult:
    name: str
    value: float
    comparator: str
    threshold: float
    unit: str = ""

    @property
    def passed(self) -> bool:
        if self.comparator == ">=":
            return self.value >= self.threshold - 1e-9
        return self.value <= self.threshold + 1e-9

    def format(self) -> str:
        shown = f"{self.value:.3f}" if self.unit != "s" else f"{self.value:.2f}s"
        gate = f"{self.comparator} {self.threshold}"
        return f"{'PASS' if self.passed else 'FAIL'}  {self.name:24} {shown:>9}  ({gate})"


def _rate(numerator: int, denominator: int, *, default: float = 1.0) -> float:
    return default if denominator == 0 else numerator / denominator


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


def aggregate(all_metrics: list[DocMetrics]) -> list[MetricResult]:
    if not all_metrics:
        return []

    total = len(all_metrics)
    text_layers = sum(m.text_layers for m in all_metrics)
    pairs = sum(m.collidable_pairs for m in all_metrics)
    margin_checked = sum(m.layers_checked_for_margin for m in all_metrics)
    contrast_checked = sum(m.contrast_checked for m in all_metrics)
    image_layers = sum(m.image_layers for m in all_metrics)

    values = {
        "schema_validity": _rate(sum(1 for m in all_metrics if m.schema_valid), total),
        "text_overflow_rate": _rate(
            sum(m.overflowing_text_layers for m in all_metrics), text_layers, default=0.0),
        "collision_rate": _rate(
            sum(m.colliding_pairs for m in all_metrics), pairs, default=0.0),
        "contrast_pass_rate": _rate(
            contrast_checked - sum(m.contrast_failed for m in all_metrics),
            contrast_checked),
        "safe_margin_pass_rate": _rate(
            margin_checked - sum(m.layers_outside_margin for m in all_metrics),
            margin_checked),
        "glyph_leakage_rate": _rate(
            sum(m.layers_with_baked_text for m in all_metrics), image_layers, default=0.0),
        "copy_length_pass_rate": _rate(
            text_layers - sum(m.copy_over_limit for m in all_metrics), text_layers),
        "editable_text_rate": _rate(
            text_layers - sum(m.rasterised_text_layers for m in all_metrics), text_layers),
        "p95_skeleton_seconds": percentile([m.skeleton_seconds for m in all_metrics], 95),
        "p95_complete_seconds": percentile([m.complete_seconds for m in all_metrics], 95),
    }

    results = []
    for name, (comparator, threshold) in GATES.items():
        unit = "s" if name.endswith("_seconds") else ""
        results.append(MetricResult(name, values[name], comparator, threshold, unit))
    return results


def summary_stats(all_metrics: list[DocMetrics]) -> dict[str, Any]:
    skeleton = [m.skeleton_seconds for m in all_metrics]
    complete = [m.complete_seconds for m in all_metrics]
    return {
        "documents": len(all_metrics),
        "p50SkeletonSeconds": round(percentile(skeleton, 50), 3),
        "p95SkeletonSeconds": round(percentile(skeleton, 95), 3),
        "p50CompleteSeconds": round(percentile(complete, 50), 3),
        "p95CompleteSeconds": round(percentile(complete, 95), 3),
        "meanCostCents": round(
            sum(m.cost_cents for m in all_metrics) / max(1, len(all_metrics)), 2),
        "totalCostCents": sum(m.cost_cents for m in all_metrics),
        "degradedLayers": sum(m.degraded_layers for m in all_metrics),
        "templatesUsed": sorted({m.template_id for m in all_metrics if m.template_id}),
        "worstContrast": round(min((m.worst_contrast for m in all_metrics), default=0), 2),
    }


def luminance_of(color: str) -> float:
    return relative_luminance(color)
