"""`DesignSpec` -> Lido.js layers.

Purely mechanical: every structure Lido needs but a model should never have to write —
the ProseMirror `doc` tree, the webfont descriptor, the parallel `colors`/`fontSizes`
arrays, the clip path — is generated here from the spec's flat fields. Because nothing
in this module makes a design decision, a spec that passed `layout.repair()` always
compiles to a document that parses.
"""

from __future__ import annotations

import uuid

from app.util.color import parse_hex

from . import fonts
from .layout import LayoutResult, element_height, font_px, line_height, tracking_em
from .spec import DesignSpec, SpecElement

RECT_CLIP = "M 0 0 L 500 0 L 500 500 L 0 500 Z"
CIRCLE_CLIP = "M 250 0 A 250 250 0 1 1 250 500 A 250 250 0 1 1 250 0 Z"

#: Spec role -> Lido's own semantic `type.type` tag. These are what
#: `app.lido_corpus.loader` reads back to rebuild slots, so a generated document
#: round-trips through the corpus loader as if it had been exported from the editor.
_LIDO_TYPE: dict[str, str] = {
    "headline": "bodyText",
    "subhead": "bodyText",
    "body": "bodyText",
    "cta": "bodyText",
    "brand": "bodyText",
    "label": "static",
    "phone": "phoneNumber",
    "address": "address",
    "website": "website",
    "email": "website",  # Lido has no native "email" tag; "website" is the closest
    "feature": "bodyText",
    "offer": "bodyText",
    "tagline": "bodyText",
}

#: Text always sits above imagery, and a scrim always sits below it. A cutout draws
#: above decorative shapes — it is a hero subject the composition wants visible, not
#: background texture — but still beneath text, which stays legible above everything.
#:
#: `decor` overrides these per element via `SpecElement.z`, because ornament does not
#: fit one tier: a badge disc has to clear the photo it is stamped on while a contact
#: band has to stay under everything, and both are shapes.
_DRAW_ORDER = {"scrim": 0, "photo": 1, "shape": 2, "cutout": 3, "text": 5}


def _rgb(hex_color: str) -> str:
    r, g, b = parse_hex(hex_color)
    return f"rgb({r}, {g}, {b})"


def _prosemirror(element: SpecElement, family: str, size_px: float, color: str,
                 width_px: float) -> dict:
    """One paragraph per physical line, styled identically.

    The colour is written twice — as a paragraph attr and as a mark on the text node —
    because the editor reads the mark and our SVG preview reads the attr. Lines come
    from `fonts.wrap_text`, not a bare `.split("\n")` — a Lido `TextLayer` never
    reflows on its own, so a long line that is not pre-wrapped here runs straight off
    the canvas at render time.
    """
    rgb = _rgb(color)
    tracking_px = tracking_em(element) * size_px
    attrs = {
        "color": rgb,
        "indent": 0,
        "fontSize": f"{round(size_px)}px",
        "listType": "",
        "textAlign": element.align,
        "fontFamily": family,
        # Leading by size class, not one number for the page: display type set at 1.2
        # floats apart, body copy set at 0.94 collides with itself.
        "lineHeight": f"{line_height(element):.2f}",
        "marginLeft": None,
        # None rather than "0px" when untracked: the editor treats an explicit zero as
        # an override and stops the face's own spacing applying.
        "letterSpacing": f"{tracking_px:.2f}px" if abs(tracking_px) >= 0.05 else None,
        "textTransform": None if element.transform == "none" else element.transform,
    }
    lines = fonts.wrap_text(element.text or "", family, size_px, width_px,
                            tracking_em(element))
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": dict(attrs),
                "content": [{
                    "text": line,
                    "type": "text",
                    "marks": [{"type": "color", "attrs": {"color": rgb}}],
                }],
            }
            for line in lines
        ],
    }


def _text_layer(element: SpecElement, spec: DesignSpec, scale: float) -> dict:
    is_display = element.size in ("display", "title")
    family = fonts.face_for(element.font, spec.vibe, display=is_display)
    size_px = font_px(element, spec, scale)
    color = element.color or "#FFFFFF"
    width = element.w * spec.width
    height = element_height(element, spec, scale) * spec.height

    return {
        "type": {
            "type": _LIDO_TYPE.get(element.role or "body", "bodyText"),
            "resolvedName": "TextLayer",
            "fixedText": None,
            "replacableText": element.text or "",
        },
        "child": [],
        "props": {
            "doc": _prosemirror(element, family, size_px, color, width),
            "fonts": fonts.descriptor(family),
            "scale": 1,
            "colors": [_rgb(color)],
            "rotate": 0,
            "boxSize": {"width": width, "height": height},
            "position": {"x": element.x * spec.width, "y": element.y * spec.height},
            "fontSizes": [round(size_px)],
        },
        "locked": False,
        "parent": "ROOT",
    }


def _shape_layer(element: SpecElement, spec: DesignSpec) -> dict:
    x, y = element.x * spec.width, element.y * spec.height
    width = element.w * spec.width
    height = (element.h if element.h is not None else 0.25) * spec.height
    return {
        "type": {"type": None, "resolvedName": "ShapeLayer",
                 "fixedText": None, "replacableText": None},
        "child": [],
        "props": {
            "color": _rgb(element.color or "#FFFFFF"),
            "shape": element.shape or "rect",
            "scale": 1,
            "rotate": 0,
            # x/y live inside boxSize as well as in position: the editor reads
            # `position`, the SVG preview reads `boxSize`, and a shape missing either
            # one silently renders at the origin.
            "boxSize": {"x": x, "y": y, "width": width, "height": height},
            "position": {"x": x, "y": y},
            "transparency": element.opacity,
        },
        "locked": False,
        "parent": "ROOT",
    }


def _frame_layer(element: SpecElement, spec: DesignSpec, url: str | None) -> dict:
    x, y = element.x * spec.width, element.y * spec.height
    width = element.w * spec.width
    height = (element.h if element.h is not None else 0.25) * spec.height

    if element.cutout:
        # No crop, no colour box: the alpha channel is the whole point, so the image
        # is contain-fit inside its box (the same `imageStyle` a logo lockup uses in
        # the corpus templates) rather than cover-cropped inside a clip shape.
        return {
            "type": {"type": None, "resolvedName": "FrameLayer",
                     "fixedText": None, "replacableText": None},
            "child": [],
            "props": {
                "image": {
                    "url": url or "",
                    "thumb": url or "",
                    "rotate": 0,
                    "boxSize": {"width": 500, "height": 500},
                    "position": {"x": 0, "y": 0},
                },
                "imageStyle": {
                    "width": "100%", "height": "100%",
                    "display": "block", "objectFit": "contain",
                },
                "scale": 1,
                "rotate": 0,
                "boxSize": {"x": x, "y": y, "width": width, "height": height},
                "clipPath": RECT_CLIP,
                "position": {"x": x, "y": y},
            },
            "locked": False,
            "parent": "ROOT",
        }

    return {
        "type": {"type": None, "resolvedName": "FrameLayer",
                 "fixedText": None, "replacableText": None},
        "child": [],
        "props": {
            "image": {
                "url": url or "",
                "thumb": url or "",
                "rotate": 0,
                "boxSize": {"width": 500, "height": 500},
                "position": {"x": 0, "y": 0},
            },
            "scale": 1,
            "rotate": 0,
            "boxSize": {"x": x, "y": y, "width": width, "height": height},
            "clipPath": CIRCLE_CLIP if element.shape == "circle" else RECT_CLIP,
            "position": {"x": x, "y": y},
        },
        "locked": False,
        "parent": "ROOT",
    }


def _order_key(element: SpecElement) -> int:
    if element.z is not None:
        return element.z
    if element.kind == "shape":
        return _DRAW_ORDER["scrim"] if element.behind else _DRAW_ORDER["shape"]
    if element.kind == "photo" and element.cutout:
        return _DRAW_ORDER["cutout"]
    return _DRAW_ORDER[element.kind]


def build_layers(
    layout: LayoutResult,
    *,
    background_url: str | None = None,
    photo_urls: dict[int, str] | None = None,
) -> dict[str, dict]:
    """Compile to `{layer_id: layer}` with `ROOT` first.

    `photo_urls` is keyed by the element's index in `spec.elements`, since a photo
    element has no identity of its own until it becomes a layer here.
    """
    spec, scale = layout.spec, layout.font_scale
    photo_urls = photo_urls or {}

    root_props: dict = {
        "color": _rgb(spec.background.color),
        "rotate": 0,
        "boxSize": {"width": spec.width, "height": spec.height},
        "position": {"x": 0, "y": 0},
    }
    if background_url:
        root_props["image"] = {
            "url": background_url,
            "thumb": background_url,
            "rotate": 0,
            "boxSize": {"width": spec.width, "height": spec.height},
            "position": {"x": 0, "y": 0},
            "transparency": 1,
        }

    layers: dict[str, dict] = {
        "ROOT": {
            "type": {
                "type": "bgImage" if background_url else None,
                "resolvedName": "RootLayer",
                "fixedText": None,
                "replacableText": None,
            },
            "child": [],
            "props": root_props,
            "locked": False,
            "parent": None,
        }
    }

    indexed = list(enumerate(spec.elements))
    indexed.sort(key=lambda pair: _order_key(pair[1]))

    order: list[str] = []
    for index, element in indexed:
        if element.kind == "text" and not (element.text or "").strip():
            continue
        layer_id = str(uuid.uuid4())
        if element.kind == "text":
            layers[layer_id] = _text_layer(element, spec, scale)
        elif element.kind == "shape":
            layers[layer_id] = _shape_layer(element, spec)
        else:
            layers[layer_id] = _frame_layer(element, spec, photo_urls.get(index))
        order.append(layer_id)

    layers["ROOT"]["child"] = order
    return layers
