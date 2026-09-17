"""Throwaway SVG renderer for Lido templates — NOT a real editor.

Good enough to sanity-check layer positions, text and clip shapes without wiring up
Lido.js itself (whose repo link turned out to be dead) or the full Konva/Skia renderer
from `IMPLEMENTATION_PLAN.md`. Approximates FrameLayer's local 0..500 clip space and
ShapeLayer's circle/octagon; skips true text wrapping and the `scale` field's exact
semantics (they're close enough to final pixel values in these fixtures to render
sanely without it). Output is a single self-contained HTML file per template — open
directly in a browser, no server needed. Image URLs are loaded live from
assets.quickhub.ai, so this only shows real photos/logos when opened as a real local
file, not inside a sandboxed artifact viewer.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .model import LidoTemplateFile

_OCTAGON_PTS = "150,0 350,0 500,150 500,350 350,500 150,500 0,350 0,150"


def _text_align_anchor(align: str | None) -> str:
    return {"center": "middle", "right": "end", "justify": "start"}.get(align or "left", "start")


def _apply_transform(text: str, transform: str | None) -> str:
    if transform == "uppercase":
        return text.upper()
    if transform == "capitalize":
        return text.title()
    return text


def _render_text_layer(layer_id: str, layer: dict) -> str:
    props = layer["props"]
    pos = props.get("position", {"x": 0, "y": 0})
    doc = props.get("doc", {})
    lines: list[str] = []
    for para in doc.get("content", []):
        attrs = para.get("attrs", {})
        font_size = float(str(attrs.get("fontSize", "16px")).replace("px", "") or 16)
        color = attrs.get("color", "black")
        family = (attrs.get("fontFamily") or "sans-serif").split(",")[0]
        anchor = _text_align_anchor(attrs.get("textAlign"))
        line_height = float(attrs.get("lineHeight") or 1.2)
        text = "".join(
            _apply_transform(n.get("text", ""), attrs.get("textTransform"))
            for n in para.get("content", [])
        )
        if not text:
            continue
        lines.append(
            f'<tspan x="0" dy="{line_height}em" font-size="{font_size}" fill="{html.escape(color)}" '
            f'font-family="{html.escape(family)}" text-anchor="{anchor}">{html.escape(text)}</tspan>'
        )
    if not lines:
        return ""
    first_size = 16
    for para in doc.get("content", []):
        try:
            first_size = float(str(para.get("attrs", {}).get("fontSize", "16px")).replace("px", ""))
            break
        except ValueError:
            pass
    return (
        f'<g transform="translate({pos.get("x", 0)},{pos.get("y", 0)})">'
        f'<text x="0" y="{first_size}">{"".join(lines)}</text></g>'
    )


def _render_frame_layer(layer_id: str, layer: dict) -> str:
    props = layer["props"]
    box = props.get("boxSize", {})
    x, y = box.get("x", props.get("position", {}).get("x", 0)), box.get("y", props.get("position", {}).get("y", 0))
    w, h = box.get("width", 100), box.get("height", 100)
    clip_d = props.get("clipPath", "M 0 0 L 500 0 L 500 500 L 0 500 Z")
    image = props.get("image", {})
    img_pos = image.get("position", {"x": 0, "y": 0})
    img_scale = props.get("scale", 1)
    url = html.escape(image.get("url", ""))
    return (
        f'<clipPath id="clip-{layer_id}"><path d="{html.escape(clip_d)}"/></clipPath>'
        f'<g transform="translate({x},{y}) scale({w / 500},{h / 500})">'
        f'<image href="{url}" width="500" height="500" clip-path="url(#clip-{layer_id})" '
        f'transform="translate({img_pos.get("x", 0)},{img_pos.get("y", 0)}) scale({img_scale})" '
        f'preserveAspectRatio="xMidYMid slice"/></g>'
    )


def _render_shape_layer(layer_id: str, layer: dict) -> str:
    props = layer["props"]
    box = props.get("boxSize", {})
    x, y = box.get("x", 0), box.get("y", 0)
    w, h = box.get("width", 100), box.get("height", 100)
    color = html.escape(props.get("color", "black"))
    shape = props.get("shape", "rect")
    if shape == "circle":
        return f'<ellipse cx="{x + w / 2}" cy="{y + h / 2}" rx="{w / 2}" ry="{h / 2}" fill="{color}"/>'
    if shape == "octagon":
        return (
            f'<g transform="translate({x},{y}) scale({w / 500},{h / 500})">'
            f'<polygon points="{_OCTAGON_PTS}" fill="{color}"/></g>'
        )
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}"/>'


def render_layer(layer_id: str, layer: dict) -> str:
    resolved = layer.get("type", {}).get("resolvedName")
    try:
        if resolved == "TextLayer":
            return _render_text_layer(layer_id, layer)
        if resolved == "FrameLayer":
            return _render_frame_layer(layer_id, layer)
        if resolved == "ShapeLayer":
            return _render_shape_layer(layer_id, layer)
    except Exception as exc:  # a throwaway preview should degrade, never crash the page
        return f'<!-- failed to render {layer_id} ({resolved}): {exc} -->'
    return ""


def render_preview_html(layers: dict[str, Any], title: str = "Lido preview") -> str:
    root = layers["ROOT"]
    box = root["props"].get("boxSize", {"width": 675, "height": 675})
    w, h = box.get("width", 675), box.get("height", 675)
    bg_color = html.escape(root["props"].get("color", "white"))
    bg_image = (root["props"].get("image") or {}).get("url", "")

    order = root.get("child", [])
    body = []
    if bg_image:
        body.append(f'<image href="{html.escape(bg_image)}" x="0" y="0" width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice"/>')
    for lid in order:
        layer = layers.get(lid)
        if layer:
            body.append(render_layer(lid, layer))

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{margin:0;background:#e5e5e5;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:sans-serif}}
.frame{{background:white;box-shadow:0 4px 24px rgba(0,0,0,.25)}}</style></head>
<body>
<svg class="frame" width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="background:{bg_color}">
{''.join(body)}
</svg>
</body></html>"""


def write_preview(layers: dict[str, Any], out_path: Path, title: str = "Lido preview") -> Path:
    out_path.write_text(render_preview_html(layers, title), encoding="utf-8")
    return out_path
