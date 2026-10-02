"""Design (elements) -> a raw Lido.js export, in exactly the shape the editor writes and
the rest of the pipeline expects (see docs/TEMPLATE_EXPORT_RULES.md)."""

from __future__ import annotations

import uuid

from app.lido_create.check import background_at, draw_seed, luminance
from app.lido_create.draw import draw_path
from app.lido_create.kit import (
    FONT_URLS,
    LOGOS,
    Design,
    Element,
    Gradient,
    H,
    Palette,
    Photo,
    Variant,
    W,
    line_count,
    pick_photo,
)
from app.lido_create.shapes import BORDER_STYLES, LINE_STYLES, TEXT_EFFECTS, frames

SHAPE_SCALE = W / (640 / 3)  # the `scale` Lido writes for a shape drawn on a fresh canvas
# Lido draws a corner radius of roundedCorners / scale pixels (measured on the editor's
# own rendering, lidojs_templates/lido_core/), so px -> roundedCorners multiplies by it.
ROUNDED_PER_PX = SHAPE_SCALE

LIDO_TEXT_TYPE = {"headline": "bodyText", "kicker": "bodyText", "body": "bodyText",
                  "item": "bodyText", "cta": "static", "badge": "static", "caption": "static",
                  "website": "website", "phone": "phoneNumber", "email": "email",
                  "address": "address"}

CIRCLE_PATH = ("M 500 250.002 c 0 138.065 -111.931 249.996 -250 249.996 c -138.071 0 "
               "-250 -111.931 -250 -249.996 C 0 111.93 111.929 0 250 0 s 250 111.93 "
               "250 250.002 Z")


def rgb(c) -> str:
    return f"rgb({c[0]}, {c[1]}, {c[2]})"


def rgba(c, alpha: float) -> str:
    return f"rgba({c[0]}, {c[1]}, {c[2]}, {alpha:g})"


def lido_gradient(g: Gradient, base: str, palette: Palette) -> dict:
    """A Gradient as Lido stores it: `color` becomes {colors: [2 stops], style, angle}."""
    start = palette.color(g.start or base)
    end = palette.color(g.end) if g.end else start
    return {"colors": [{"color": rgba(start, 1), "percent": g.start_at or 0},
                       {"color": rgba(end, 1 if g.end else 0),
                        "percent": 100 if g.end_at is None else g.end_at}],
            "style": g.style, "angle": 180 if g.angle is None else g.angle}


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
    extra = {}
    if e.effect:
        name, settings = TEXT_EFFECTS[e.effect]
        settings = dict(settings)
        if e.effect == "shadow":
            settings["color"] = rgb(v.palette.color(e.effect_color)) if e.effect_color \
                else "rgb(0, 0, 0)"
        extra["effect"] = {"name": name, "settings": settings}
    return _layer(kind, "TextLayer", {**extra,
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
    color = lido_gradient(e.gradient, e.color or "accent", v.palette) if e.gradient \
        else rgb(v.palette.color(e.color or "accent"))
    props = {"shape": e.shape or "rectangle",
             "position": {"x": e.x, "y": e.y}, "boxSize": {"width": e.w, "height": e.h},
             "rotate": e.rotate or 0, "color": color, "scale": SHAPE_SCALE}
    if e.stroke and e.stroke_width:
        props["border"] = {"color": rgb(v.palette.color(e.stroke)),
                           "style": BORDER_STYLES[e.stroke_style or "solid"],
                           "weight": e.stroke_width}
    if e.radius and e.shape in (None, "rectangle"):
        props["roundedCorners"] = round(e.radius * ROUNDED_PER_PX)
    if e.opacity is not None and e.opacity < 1:
        props["transparency"] = e.opacity
    return _layer(None, "ShapeLayer", props)


# An organic blob (the one template_18064 uses), drawn in a 500 x 500 box.
BLOB_500 = ("M 430 90 C 480 150 490 240 465 320 C 440 400 370 455 290 470 C 210 485 130 "
            "465 75 410 C 20 355 5 270 25 190 C 45 110 115 55 200 35 C 285 15 380 30 430 90 Z")


def _polygon(points, cw: float, ch: float) -> str:
    return ("M " + " L ".join(f"{x * cw:.3f} {y * ch:.3f}" for x, y in points) + " Z")


def _scaled(path: str, sx: float, sy: float) -> str:
    """A path written for a 500 x 500 box, stretched to cw x ch (commands keep, x/y pairs
    scale)."""
    out, xy = [], 0
    for token in path.split():
        if token.isalpha():
            out.append(token)
            continue
        out.append(f"{float(token) * (sx if xy % 2 == 0 else sy):.3f}")
        xy += 1
    return " ".join(out)


def clip_path(clip: str, cw: float, ch: float, r: float = 0) -> str:
    """Crop shape in the frame's own space (500 units wide; `scale` stretches it)."""
    from app.lido_create.check import POLYGONS
    if clip == "circle":
        return CIRCLE_PATH
    if clip in POLYGONS:
        return _polygon(POLYGONS[clip], cw, ch)
    if clip == "blob":
        return _scaled(BLOB_500, cw / 500, ch / 500)
    if clip == "leaf":  # big rounded top-left and bottom-right corners, the others square
        k = min(cw, ch) * 0.35
        return (f"M {k:.3f} 0 L {cw} 0 L {cw} {ch - k:.3f} Q {cw} {ch} {cw - k:.3f} {ch} "
                f"L 0 {ch} L 0 {k:.3f} Q 0 0 {k:.3f} 0 Z")
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


def _cutout(e: Element, p: Photo) -> dict:
    """A transparent subject: no crop, the whole image fitted inside the box."""
    return _layer(None, "FrameLayer", {
        "image": {"url": p.url, "thumb": p.url, "rotate": 0,
                  "boxSize": {"width": e.w, "height": e.h}, "position": {"x": 0, "y": 0}},
        "scale": 1, "rotate": 0,
        "boxSize": {"width": e.w, "height": e.h}, "position": {"x": e.x, "y": e.y},
        "imageStyle": {"width": "100%", "height": "100%", "display": "block",
                       "objectFit": "contain"},
    })


def _line(e: Element, v: Variant) -> dict:
    return _layer(None, "LineLayer", {
        "style": LINE_STYLES[e.stroke_style or "solid"],
        "boxSize": {"width": e.w, "height": e.h},
        "color": rgb(v.palette.color(e.color or "accent")),
        "position": {"x": e.x, "y": e.y}, "scale": 1, "rotate": e.rotate or 0,
        "arrowStart": e.line_start or "none", "arrowEnd": e.line_end or "none",
    })


def _draw(e: Element, v: Variant) -> dict:
    path, _ = draw_path(e.draw or "underline", e.w, e.h, e.stroke_width or 6,
                        seed=draw_seed(e))
    return _layer(None, "DrawLayer", {
        "path": path, "color": rgb(v.palette.color(e.color or "accent")),
        "width": e.stroke_width or 6,
        "position": {"x": e.x, "y": e.y}, "boxSize": {"width": e.w, "height": e.h},
        "rotate": e.rotate or 0, "scale": 1,
        "transparency": 1 if e.opacity is None else e.opacity,
    })


def _photo(e: Element, p: Photo) -> dict:
    if e.clip == "cutout":
        if p.cutout:
            return _cutout(e, p)
        e = e.model_copy(update={"clip": "blob"})  # a placeholder photo, not a cutout
    if e.frame:  # a Lido frame outline, used as drawn: its natural size is its bounds
        f = frames()[e.frame]
        cw, ch, path = f.w, f.h, f.path
    else:
        cw = 500.0
        ch = 500.0 if e.clip == "circle" else round(500.0 * e.h / e.w, 4)
        path = None
    scale = e.w / cw
    s = max(cw / p.w, ch / p.h)  # cover: fill the frame, crop the overflow
    bw, bh = p.w * s, p.h * s
    focus = 0.5 if e.focus is None else e.focus
    return _layer(None, "FrameLayer", {
        "clipPath": path or clip_path(e.clip or "rect", cw, ch, (e.radius or 0) / scale),
        "position": {"x": e.x, "y": e.y}, "boxSize": {"width": e.w, "height": e.h},
        "rotate": e.rotate or 0, "scale": scale,
        "image": {"url": p.url, "thumb": p.url, "boxSize": {"width": bw, "height": bh},
                  "position": {"x": (cw - bw) / 2, "y": (ch - bh) * focus}, "rotate": 0},
    })


def _logo(e: Element, index: int, design: Design, v: Variant,
          logo_url: str | None = None) -> dict:
    """The client's logo when given (fitted inside the box, any aspect), else the stock
    placeholder in whichever of black/white reads on what's behind it."""
    url = logo_url
    if url is None:
        under = background_at(design.elements, index, e.x + e.w / 2, e.y + e.h / 2,
                              v.palette, design.background)
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


def to_lido(design: Design, v: Variant, photos: list[Photo] | None = None,
            logo_url: str | None = None) -> list[dict]:
    """`photos` fills the photo elements in order (see `photos.resolve_photos`); without
    it each one gets a cached corpus photo. `logo_url` is the client's logo for the logo
    element; without it the stock placeholder is used."""
    queue = list(photos or [])
    layers: dict[str, dict] = {"ROOT": {
        "type": {"type": "bgImage", "resolvedName": "RootLayer", "fixedText": None,
                 "replacableText": None},
        "child": [],
        "props": {"boxSize": {"width": W, "height": H}, "position": {"x": 0, "y": 0},
                  "rotate": 0,
                  "color": lido_gradient(design.background, "bg", v.palette)
                  if design.background else rgb(v.palette.bg),
                  "image": None, "video": None},
        "locked": False, "parent": None,
    }}
    for i, e in enumerate(design.elements):
        if e.kind == "text":
            layer = _text(e, v)
        elif e.kind == "shape":
            layer = _shape(e, v)
        elif e.kind == "photo":
            layer = _photo(e, queue.pop(0) if queue
                           else pick_photo(v, e.w, e.h, cutout=e.clip == "cutout"))
        elif e.kind == "line":
            layer = _line(e, v)
        elif e.kind == "draw":
            layer = _draw(e, v)
        else:
            layer = _logo(e, i, design, v, logo_url)
        lid = str(uuid.uuid4())
        layers[lid] = layer
        layers["ROOT"]["child"].append(lid)
    return [{"layers": layers}]
