"""Design (elements) -> a raw Lido.js export, in exactly the shape the editor writes and
the rest of the pipeline expects (see docs/TEMPLATE_EXPORT_RULES.md)."""

from __future__ import annotations

import uuid

from lido_layouts.check import background_at, luminance
from lido_layouts.kit import (
    FONT_URLS,
    LOGOS,
    Design,
    Element,
    H,
    Variant,
    W,
    line_count,
    pick_photo,
)

SHAPE_SCALE = W / (640 / 3)  # the `scale` Lido writes for a shape drawn on a fresh canvas
# Lido's `roundedCorners` is not in pixels; on the existing previews a value of ~4x the
# visible radius matches. Approximate — check buttons in the editor.
ROUNDED_PER_PX = 4

LIDO_TEXT_TYPE = {"headline": "bodyText", "kicker": "bodyText", "body": "bodyText",
                  "item": "bodyText", "cta": "static", "badge": "static",
                  "website": "website", "phone": "phoneNumber", "email": "email",
                  "address": "address"}

CIRCLE_PATH = ("M 500 250.002 c 0 138.065 -111.931 249.996 -250 249.996 c -138.071 0 "
               "-250 -111.931 -250 -249.996 C 0 111.93 111.929 0 250 0 s 250 111.93 "
               "250 250.002 Z")


def rgb(c) -> str:
    return f"rgb({c[0]}, {c[1]}, {c[2]})"


def _layer(type_: str | None, resolved: str, props: dict, fixed=None, replace=None) -> dict:
    return {"type": {"type": type_, "resolvedName": resolved, "fixedText": fixed,
                     "replacableText": replace},
            "child": [], "props": props, "locked": False, "parent": "ROOT"}


def _text(e: Element, v: Variant) -> dict:
    family = v.fonts.family(e.font or "body")
    color = rgb(v.palette.color(e.color or "ink"))
    lines, _ = line_count(v.fonts, e)
    lh = e.line_height or 1.3
    kind = LIDO_TEXT_TYPE[e.text_type or "body"]
    static = kind == "static"
    return _layer(kind, "TextLayer", {
        "doc": {"type": "doc", "content": [{
            "type": "paragraph",
            "attrs": {"color": color, "indent": 0, "fontSize": f"{e.size}px",
                      "listType": "", "textAlign": e.align or "left", "fontFamily": family,
                      "lineHeight": str(lh), "marginLeft": None,
                      "letterSpacing": e.letter_spacing or 0,
                      "textTransform": "uppercase" if e.uppercase else "none"},
            "content": [{"text": e.text, "type": "text",
                         "marks": [{"type": "color", "attrs": {"color": color}}]}],
        }]},
        "fonts": [{"name": family, "fonts": [{"urls": [FONT_URLS[family]]}]}],
        "scale": 1, "colors": [color], "rotate": 0,
        "boxSize": {"width": e.w, "height": round(len(lines) * e.size * lh, 2)},
        "position": {"x": e.x, "y": e.y}, "fontSizes": [e.size],
    }, fixed=e.text if static else "", replace="" if static else e.text)


def _shape(e: Element, v: Variant) -> dict:
    props = {"shape": "circle" if e.shape == "circle" else "rectangle",
             "position": {"x": e.x, "y": e.y}, "boxSize": {"width": e.w, "height": e.h},
             "rotate": 0, "color": rgb(v.palette.color(e.color or "accent")),
             "scale": SHAPE_SCALE}
    if e.radius and e.shape != "circle":
        props["roundedCorners"] = round(e.radius * ROUNDED_PER_PX)
    if e.opacity is not None and e.opacity < 1:
        props["transparency"] = e.opacity
    return _layer(None, "ShapeLayer", props)


def clip_path(clip: str, cw: float, ch: float, r: float = 0) -> str:
    """Crop shape in the frame's own space (500 units wide; `scale` stretches it)."""
    if clip == "circle":
        return CIRCLE_PATH
    if clip == "arch":
        a = cw / 2
        k = 0.5523 * a
        return (f"M 0 {ch} L 0 {a} C 0 {a - k:.3f} {a - k:.3f} 0 {a} 0 "
                f"C {a + k:.3f} 0 {cw} {a - k:.3f} {cw} {a} L {cw} {ch} Z")
    if clip == "rounded" and r:
        return (f"M {r:.3f} 0 L {cw - r:.3f} 0 Q {cw} 0 {cw} {r:.3f} L {cw} {ch - r:.3f} "
                f"Q {cw} {ch} {cw - r:.3f} {ch} L {r:.3f} {ch} Q 0 {ch} 0 {ch - r:.3f} "
                f"L 0 {r:.3f} Q 0 0 {r:.3f} 0 Z")
    return f"M 0 0 L {cw} 0 L {cw} {ch} L 0 {ch} Z"


def _photo(e: Element, v: Variant) -> dict:
    p = pick_photo(v, e.w, e.h)
    cw = 500.0
    ch = 500.0 if e.clip == "circle" else round(500.0 * e.h / e.w, 4)
    scale = e.w / cw
    s = max(cw / p.w, ch / p.h)  # cover: fill the frame, crop the overflow
    bw, bh = p.w * s, p.h * s
    focus = 0.5 if e.focus is None else e.focus
    return _layer(None, "FrameLayer", {
        "clipPath": clip_path(e.clip or "rect", cw, ch, (e.radius or 0) / scale),
        "position": {"x": e.x, "y": e.y}, "boxSize": {"width": e.w, "height": e.h},
        "rotate": 0, "scale": scale,
        "image": {"url": p.url, "thumb": p.url, "boxSize": {"width": bw, "height": bh},
                  "position": {"x": (cw - bw) / 2, "y": (ch - bh) * focus}, "rotate": 0},
    })


def _logo(e: Element, index: int, design: Design, v: Variant) -> dict:
    under = background_at(design.elements, index, e.x + e.w / 2, e.y + e.h / 2, v.palette)
    dark = under == "photo" or luminance(under) < 0.4  # type: ignore[arg-type]
    url = LOGOS["white" if dark else "black"]
    return _layer("logo", "FrameLayer", {
        "image": {"url": url, "thumb": url, "rotate": 0,
                  "boxSize": {"width": e.w, "height": e.h}, "position": {"x": 0, "y": 0}},
        "scale": 1,
        "style": {"width": f"{e.w}px", "height": f"{e.h}px", "display": "flex",
                  "overflow": "hidden", "alignItems": "center", "justifyContent": "center"},
        "rotate": 0, "boxSize": {"width": e.w, "height": e.h},
        "position": {"x": e.x, "y": e.y},
        "imageStyle": {"width": "100%", "height": "100%", "display": "block",
                       "objectFit": "contain"},
    })


def to_lido(design: Design, v: Variant) -> list[dict]:
    layers: dict[str, dict] = {"ROOT": {
        "type": {"type": "bgImage", "resolvedName": "RootLayer", "fixedText": None,
                 "replacableText": None},
        "child": [],
        "props": {"boxSize": {"width": W, "height": H}, "position": {"x": 0, "y": 0},
                  "rotate": 0, "color": rgb(v.palette.bg), "image": None, "video": None},
        "locked": False, "parent": None,
    }}
    for i, e in enumerate(design.elements):
        if e.kind == "text":
            layer = _text(e, v)
        elif e.kind == "shape":
            layer = _shape(e, v)
        elif e.kind == "photo":
            layer = _photo(e, v)
        else:
            layer = _logo(e, i, design, v)
        lid = str(uuid.uuid4())
        layers[lid] = layer
        layers["ROOT"]["child"].append(lid)
    return [{"layers": layers}]
