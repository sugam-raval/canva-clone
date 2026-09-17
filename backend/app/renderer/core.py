"""Scene graph -> draw command list. IMPLEMENTATION_PLAN §0.11.

Pure: no I/O, no DOM, no Skia. Asset URLs arrive through a resolver callback so the
same function serves the browser (signed CDN URLs) and the exporter (local paths).

Per ADR 0001 this runs on the server only and the browser consumes its JSON output, so
there is exactly one implementation of compositing order, text placement and geometry.

Deviation from §0.11 worth noting: effects are carried on the enclosing
`saveTransform` command rather than as a separate `EffectCmd` with a
`targetIndexRange`. Both backends apply effects to a *group* natively (Konva via shape
properties, Skia via `saveLayer` with a paint filter); index ranges would have to be
translated into exactly that on both sides, so the range form buys nothing and is
easier to get wrong.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from app.layout.measure import ShapedBlock, shape_block
from app.renderer.transform import Mat, frame_matrix
from app.schema.doc import DesignDoc, ImageLayer, ShapeLayer, TextLayer
from app.schema.draw import (
    ClearCmd,
    DrawList,
    ImageCmd,
    Matrix2D,
    PathCmd,
    PlaceholderCmd,
    PositionedGlyphRun,
    RestoreCmd,
    SaveTransformCmd,
    TextRunCmd,
)
from app.schema.draw import Rect as DrawRect

AssetResolver = Callable[[str], str]

# Placeholder fill while an asset job is still running (§1.3 progressive delivery).
DEFAULT_PLACEHOLDER = "#E2E8F0"


def _noop_resolver(asset_id: str) -> str:
    return f"asset:{asset_id}"


def to_draw_list(
    doc: DesignDoc,
    *,
    scale: float = 1.0,
    resolve_asset: AssetResolver | None = None,
    shaped: dict[str, ShapedBlock] | None = None,
    language: str = "en",
    include_hidden: bool = False,
) -> DrawList:
    """Flatten `doc` into an ordered command list at `scale`."""
    resolve = resolve_asset or _noop_resolver
    shaped = shaped if shaped is not None else {}
    commands: list[Any] = [ClearCmd(color=doc.canvas.background)]

    root = Mat(a=scale, d=scale)
    _emit_layers(doc, doc.layers, root, commands, resolve, shaped, language, include_hidden)

    return DrawList(
        width=round(doc.canvas.width * scale),
        height=round(doc.canvas.height * scale),
        scale=scale,
        commands=commands,
    )


def _emit_layers(
    doc: DesignDoc, layers: list[Any], parent: Mat, out: list[Any],
    resolve: AssetResolver, shaped: dict[str, ShapedBlock], language: str,
    include_hidden: bool,
) -> None:
    for layer in layers:
        if not layer.visible and not include_hidden:
            continue
        if layer.frame.w <= 0 or layer.frame.h <= 0:
            continue

        matrix = parent.mul(frame_matrix(layer.frame))
        out.append(
            SaveTransformCmd(
                layerId=layer.id,
                layerType=layer.type,
                role=layer.role,
                locked=layer.locked,
                name=layer.name,
                size=DrawRect(x=0, y=0, w=layer.frame.w, h=layer.frame.h),
                matrix=Matrix2D(**matrix.as_dict()),
                opacity=layer.opacity,
                blend=layer.blend_mode,
                clip=(
                    DrawRect(x=0, y=0, w=layer.frame.w, h=layer.frame.h)
                    if layer.clip_to_parent else None
                ),
                # Effects ride on the enclosing transform; see the module docstring.
                effects=[e.model_dump(by_alias=True) for e in layer.effects],
            )
        )
        _emit_one(doc, layer, matrix, out, resolve, shaped, language, include_hidden)
        out.append(RestoreCmd())


def _emit_one(
    doc: DesignDoc, layer: Any, matrix: Mat, out: list[Any], resolve: AssetResolver,
    shaped: dict[str, ShapedBlock], language: str, include_hidden: bool,
) -> None:
    if layer.type == "group":
        _emit_layers(doc, layer.children, matrix, out, resolve, shaped, language,
                     include_hidden)
    elif layer.type == "image":
        _emit_image(doc, layer, out, resolve)
    elif layer.type == "text":
        _emit_text(layer, out, shaped, language)
    elif layer.type == "shape":
        _emit_shape(layer, out)
    elif layer.type == "svg" and layer.asset_id:
        out.append(ImageCmd(
            assetUrl=resolve(layer.asset_id), assetId=layer.asset_id,
            dest=DrawRect(x=0, y=0, w=layer.frame.w, h=layer.frame.h),
            opacity=1.0,
        ))


# --------------------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------------------


def _emit_image(doc: DesignDoc, layer: ImageLayer, out: list[Any],
                resolve: AssetResolver) -> None:
    if not layer.asset_id:
        colour = layer.placeholder_color or (doc.palette[0] if doc.palette
                                             else DEFAULT_PLACEHOLDER)
        out.append(PlaceholderCmd(
            dest=DrawRect(x=0, y=0, w=layer.frame.w, h=layer.frame.h),
            color=colour, layerId=layer.id, clipPath=mask_path(layer),
        ))
        return

    nat_w = layer.natural_size.w or layer.frame.w
    nat_h = layer.natural_size.h or layer.frame.h
    src = _source_rect(layer, nat_w, nat_h)

    out.append(ImageCmd(
        assetUrl=resolve(layer.asset_id),
        assetId=layer.asset_id,
        dest=DrawRect(x=0, y=0, w=layer.frame.w, h=layer.frame.h),
        crop=src,
        opacity=1.0,
        blend="normal",
        adjust=layer.adjust,
        clipPath=mask_path(layer),
    ))



def mask_path(layer: ImageLayer) -> str | None:
    """The silhouette `layer.mask` names, as SVG path data in the layer's local space.

    Built here rather than in either backend for the same reason `fit` is resolved here:
    two implementations of "what shape is an arch" is two designs, and INV-3 asks for one.
    A placeholder is cut to the same shape as the image that will replace it, so the
    progressive render does not change silhouette when the asset lands.
    """
    mask = getattr(layer, "mask", None)
    if not mask:
        return None
    w, h = layer.frame.w, layer.frame.h
    if w <= 0 or h <= 0:
        return None

    if mask == "rounded":
        return _rounded_rect_path(0, 0, w, h, layer.mask_radius or min(w, h) * 0.08)
    if mask == "pill":
        return _rounded_rect_path(0, 0, w, h, min(w, h) / 2)
    if mask == "ellipse":
        return _ellipse_path(0, 0, w, h)
    if mask == "circle":
        # A true circle, centred — not an ellipse squashed into a non-square frame.
        d = min(w, h)
        return _ellipse_path((w - d) / 2, (h - d) / 2, d, d)
    if mask == "diamond":
        return f"M {w / 2} 0 L {w} {h / 2} L {w / 2} {h} L 0 {h / 2} Z"
    if mask == "hexagon":
        return (f"M {w * 0.25} 0 L {w * 0.75} 0 L {w} {h / 2} "
                f"L {w * 0.75} {h} L {w * 0.25} {h} L 0 {h / 2} Z")
    if mask == "arch":
        r = min(w / 2, h)
        return (f"M 0 {h} L 0 {r} A {w / 2} {r} 0 0 1 {w} {r} L {w} {h} Z")
    if mask == "arch-down":
        r = min(w / 2, h)
        return (f"M 0 0 L {w} 0 L {w} {h - r} A {w / 2} {r} 0 0 1 0 {h - r} Z")
    if mask == "leaf":
        # Two opposite corners rounded hard, two left square — the "petal" crop.
        r = min(w, h) * 0.5
        return (f"M {r} 0 L {w} 0 L {w} {h - r} "
                f"A {r} {r} 0 0 1 {w - r} {h} L 0 {h} L 0 {r} "
                f"A {r} {r} 0 0 1 {r} 0 Z")
    if mask == "squircle":
        # A superellipse approximated with cubics: rounder than a rounded rect at the
        # corners and flatter along the edges, which is what reads as "soft" at size.
        kx, ky = w * 0.28, h * 0.28
        return (f"M {w / 2} 0 C {w / 2 + kx} 0 {w} {h / 2 - ky} {w} {h / 2} "
                f"C {w} {h / 2 + ky} {w / 2 + kx} {h} {w / 2} {h} "
                f"C {w / 2 - kx} {h} 0 {h / 2 + ky} 0 {h / 2} "
                f"C 0 {h / 2 - ky} {w / 2 - kx} 0 {w / 2} 0 Z")
    return None


def _source_rect(layer: ImageLayer, nat_w: float, nat_h: float) -> DrawRect:
    """Source rectangle in natural pixels, honouring `crop` then `fit`.

    `fit` is resolved here rather than in the backends so Konva and Skia cannot disagree
    about which pixels of a 'cover' image are visible.
    """
    if layer.crop is not None:
        cx, cy = layer.crop.x * nat_w, layer.crop.y * nat_h
        cw, ch = layer.crop.w * nat_w, layer.crop.h * nat_h
    else:
        cx, cy, cw, ch = 0.0, 0.0, nat_w, nat_h

    if layer.fit == "fill" or cw <= 0 or ch <= 0 or layer.frame.h <= 0:
        return DrawRect(x=cx, y=cy, w=cw, h=ch)

    target_ratio = layer.frame.w / layer.frame.h
    source_ratio = cw / ch

    if layer.fit == "cover":
        # Take the largest centred sub-rect of the source matching the frame's ratio.
        if source_ratio > target_ratio:
            new_w = ch * target_ratio
            return DrawRect(x=cx + (cw - new_w) / 2, y=cy, w=new_w, h=ch)
        new_h = cw / target_ratio
        return DrawRect(x=cx, y=cy + (ch - new_h) / 2, w=cw, h=new_h)

    # contain: use the whole source; the backend letterboxes inside `dest`.
    return DrawRect(x=cx, y=cy, w=cw, h=ch)


def contain_dest(frame_w: float, frame_h: float, src_w: float, src_h: float) -> DrawRect:
    """Letterboxed destination rect for `fit: contain`. Shared by both backends."""
    if src_w <= 0 or src_h <= 0:
        return DrawRect(x=0, y=0, w=frame_w, h=frame_h)
    k = min(frame_w / src_w, frame_h / src_h)
    w, h = src_w * k, src_h * k
    return DrawRect(x=(frame_w - w) / 2, y=(frame_h - h) / 2, w=w, h=h)


# --------------------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------------------


def _emit_text(layer: TextLayer, out: list[Any], shaped: dict[str, ShapedBlock],
               language: str) -> None:
    block = shaped.get(layer.id)
    if block is None:
        block = shape_block(
            layer.content,
            font_family=layer.font_family,
            font_weight=layer.font_weight,
            font_style=layer.font_style,
            font_size=layer.font_size,
            line_height=layer.line_height,
            letter_spacing=layer.letter_spacing,
            max_width=max(1.0, layer.frame.w),
            language=language,
            text_transform=layer.text_transform,
        )

    y_offset = _vertical_offset(layer, block)

    if layer.backdrop is not None:
        pad = layer.backdrop.padding
        ink_x = min((line.ink_left for line in block.lines if line.text.strip()), default=0.0)
        ink_w = max((line.advance for line in block.lines), default=0.0)
        out.append(PathCmd(
            d=_rounded_rect_path(
                ink_x - pad + _horizontal_offset(layer, block, 0.0),
                y_offset - pad,
                ink_w + 2 * pad,
                block.height + 2 * pad,
                layer.backdrop.radius,
            ),
            fill=layer.backdrop.color,
        ))

    runs: list[PositionedGlyphRun] = []
    for line in block.lines:
        if not line.runs:
            continue
        x_offset = _horizontal_offset(layer, block, line.advance)
        for run in line.runs:
            runs.append(run.model_copy(update={
                "origin_x": x_offset,
                "origin_y": y_offset + line.baseline_y,
            }))

    out.append(TextRunCmd(
        runs=runs,
        color=layer.color,
        strokeColor=layer.stroke.color if layer.stroke else None,
        strokeWidth=layer.stroke.width if layer.stroke else 0.0,
        layerId=layer.id,
    ))


def _horizontal_offset(layer: TextLayer, block: ShapedBlock, line_advance: float) -> float:
    if layer.align == "center":
        return (layer.frame.w - line_advance) / 2
    if layer.align == "right":
        return layer.frame.w - line_advance
    return 0.0


def _vertical_offset(layer: TextLayer, block: ShapedBlock) -> float:
    if layer.vertical_align == "middle":
        return (layer.frame.h - block.height) / 2
    if layer.vertical_align == "bottom":
        return layer.frame.h - block.height
    return 0.0


# --------------------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------------------


def _emit_shape(layer: ShapeLayer, out: list[Any]) -> None:
    w, h = layer.frame.w, layer.frame.h
    if layer.shape == "rect":
        d = _rounded_rect_path(0, 0, w, h, layer.radius)
    elif layer.shape == "ellipse":
        d = _ellipse_path(0, 0, w, h)
    elif layer.shape == "line":
        pts = layer.points or [0, 0, w, h]
        d = f"M {pts[0]} {pts[1]} " + " ".join(
            f"L {pts[i]} {pts[i + 1]}" for i in range(2, len(pts) - 1, 2)
        )
    elif layer.shape == "polygon":
        pts = layer.points or []
        if len(pts) < 6:
            return
        d = f"M {pts[0]} {pts[1]} " + " ".join(
            f"L {pts[i]} {pts[i + 1]}" for i in range(2, len(pts) - 1, 2)
        ) + " Z"
    else:
        d = layer.path_data or ""
    if not d:
        return

    gradient = None
    if layer.gradient is not None:
        gradient = layer.gradient.model_dump(by_alias=True)

    out.append(PathCmd(
        d=d,
        fill=layer.fill,
        stroke=layer.stroke.color if layer.stroke else None,
        strokeWidth=layer.stroke.width if layer.stroke else 0.0,
        dash=layer.stroke.dash if layer.stroke else None,
        cap=layer.stroke.cap if layer.stroke else "butt",
        join=layer.stroke.join if layer.stroke else "miter",
        gradient=gradient,
    ))


def _rounded_rect_path(x: float, y: float, w: float, h: float, radius: float) -> str:
    r = min(radius, w / 2, h / 2)
    if r <= 0:
        return f"M {x} {y} L {x + w} {y} L {x + w} {y + h} L {x} {y + h} Z"
    return (
        f"M {x + r} {y} L {x + w - r} {y} A {r} {r} 0 0 1 {x + w} {y + r} "
        f"L {x + w} {y + h - r} A {r} {r} 0 0 1 {x + w - r} {y + h} "
        f"L {x + r} {y + h} A {r} {r} 0 0 1 {x} {y + h - r} "
        f"L {x} {y + r} A {r} {r} 0 0 1 {x + r} {y} Z"
    )


def _ellipse_path(x: float, y: float, w: float, h: float) -> str:
    rx, ry = w / 2, h / 2
    cx, cy = x + rx, y + ry
    return (
        f"M {cx - rx} {cy} A {rx} {ry} 0 1 0 {cx + rx} {cy} "
        f"A {rx} {ry} 0 1 0 {cx - rx} {cy} Z"
    )


def rotation_of(matrix: Mat) -> float:
    """Degrees of rotation encoded in a matrix — used by the Konva backend."""
    return math.degrees(math.atan2(matrix.b, matrix.a))
