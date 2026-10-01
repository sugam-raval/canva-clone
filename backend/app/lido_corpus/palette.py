"""A user-chosen colour palette (up to 4 colours) applied while a template is generated
(docs/palette_theme.md). Template search never looks at colour; nothing in this module
runs when no palette is given, so generation without one is exactly as before.

    plan_theme       map the template's own colours onto the palette, by role:
                     the most prominent accent colour gets palette colour 1, the next
                     colour 2, …; near-identical shades move together (a lighter shade
                     stays lighter); near-black / near-white neutrals only move to a
                     palette colour that is itself that dark / light
                     text on a shape      must contrast with the shape's NEW colour
                     text on the picture  keeps its light/dark side, so the background
                                          prompt's "keep this area dark" still holds
    prompt_block     tells the fill model the palette and the final text colours, so
                     every image prompt is written in the palette
    finalize_prompts a fixed palette line appended to every image prompt
    check_contrast   after the background is generated, measures the pixels behind every
                     text box and swaps any colour that is not readable there
    apply_theme      writes the colours into the document: shape fills and borders, the
                     root colour, every text run, paragraph attrs, `props.colors`, effects
"""

from __future__ import annotations

import colorsys
import io
import re
from dataclasses import dataclass, field

import structlog
from PIL import Image

from .generate_ai import BACKGROUND_LAYER_ID, ImageTarget
from .model import LidoTemplateFile

log = structlog.get_logger(__name__)

MAX_COLORS = 4
RGB = tuple[int, int, int]

# WCAG contrast ratios: large display text (≥ 24px) needs 3, smaller text 4.5.
LARGE_TEXT_PX = 24
LARGE_CONTRAST = 3.0
SMALL_CONTRAST = 4.5
# Colours closer than this (RGB distance) are shades of one colour and move together.
SHADE_DISTANCE = 60

BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)


# --------------------------------------------------------------------------------------
# Colour helpers
# --------------------------------------------------------------------------------------

_HEX = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)
_RGB_FN = re.compile(r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+\s*)?\)$",
                     re.IGNORECASE)


def parse_color(value: str | None) -> RGB | None:
    """'#fff', '#ffffff', 'rgb(1, 2, 3)' → (r, g, b); anything else → None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if m := _HEX.match(text):
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if m := _RGB_FN.match(text):
        rgb = tuple(int(g) for g in m.groups())
        if all(0 <= c <= 255 for c in rgb):
            return rgb  # type: ignore[return-value]
    return None


def gradient_stops(value) -> list[RGB]:
    """The stop colours of a Lido gradient ({colors: [{color, percent}], style, angle});
    [] for a flat colour."""
    if not isinstance(value, dict):
        return []
    return [rgb for stop in value.get("colors") or []
            if (rgb := parse_color((stop or {}).get("color"))) is not None]


def _alpha(value: str) -> float:
    m = re.match(r"^rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([\d.]+)\s*\)$", value or "")
    return float(m.group(1)) if m else 1.0


def recolor_gradient(value: dict, mapping: dict[RGB, RGB]) -> dict:
    """The same gradient with every stop recoloured, keeping each stop's transparency
    (a colour fading to transparent stays a fade)."""
    out = {**value, "colors": []}
    for stop in value.get("colors") or []:
        old = parse_color(stop.get("color"))
        if old is None or old not in mapping:
            out["colors"].append(dict(stop))
            continue
        r, g, b = mapping[old]
        out["colors"].append({**stop, "color": f"rgba({r}, {g}, {b}, {_alpha(stop['color']):g})"})
    return out


def parse_palette(values: list[str] | None) -> list[RGB]:
    """The user's colours, validated: at most MAX_COLORS, duplicates removed, order kept
    (the first colour is the primary). Raises ValueError on a colour it can't read."""
    out: list[RGB] = []
    for value in values or []:
        rgb = parse_color(value)
        if rgb is None:
            raise ValueError(f"not a colour: {value!r} (use #rrggbb)")
        if rgb not in out:
            out.append(rgb)
    if len(out) > MAX_COLORS:
        raise ValueError(f"at most {MAX_COLORS} colours")
    return out


def to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def to_css(rgb: RGB) -> str:
    """The format the templates use."""
    return f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"


def luminance(rgb: RGB) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB, b: RGB) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def is_light(rgb: RGB) -> bool:
    """Reads better on black than on white."""
    return contrast(rgb, BLACK) >= contrast(rgb, WHITE)


def _hls(rgb: RGB) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))


def _from_hls(h: float, lum: float, s: float) -> RGB:
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, lum)), s)
    return round(r * 255), round(g * 255), round(b * 255)


def is_neutral(rgb: RGB) -> bool:
    _, lum, s = _hls(rgb)
    return s < 0.15 or lum > 0.93 or lum < 0.07


def _distance(a: RGB, b: RGB) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def shift_lightness(rgb: RGB, delta: float) -> RGB:
    h, lum, s = _hls(rgb)
    return _from_hls(h, lum + delta, s)


def toward(rgb: RGB, light: bool, pole_contrast: float) -> RGB | None:
    """The same hue made lighter (or darker) until it has `pole_contrast` against black
    (or white). None if even the extreme doesn't get there."""
    h, lum, s = _hls(rgb)
    pole = BLACK if light else WHITE
    for step in range(1, 21):
        cand = _from_hls(h, lum + (step * 0.05 if light else -step * 0.05), s)
        if contrast(cand, pole) >= pole_contrast:
            return cand
    return None


_HUES = ((10, "red"), (20, "red-orange"), (38, "orange"), (52, "golden yellow"),
         (66, "yellow"), (85, "lime"), (165, "green"), (185, "teal"), (198, "cyan"),
         (245, "blue"), (265, "indigo"), (290, "purple"), (325, "magenta"), (352, "pink"),
         (360, "red"))


def color_name(rgb: RGB) -> str:
    """A rough English name, for image prompts (image models read names better than hex)."""
    h, lum, s = _hls(rgb)
    if s < 0.12 or lum < 0.05 or lum > 0.97:
        if lum < 0.12:
            return "black"
        if lum > 0.92:
            return "white"
        return "charcoal grey" if lum < 0.35 else "light grey" if lum > 0.7 else "grey"
    deg = h * 360
    name = next(n for top, n in _HUES if deg <= top)
    if lum > 0.88 and 20 <= deg <= 70:
        return "cream"
    if name in ("orange", "red-orange", "golden yellow") and lum < 0.4:
        return "brown"
    if lum < 0.25:
        name = f"deep {name}"
    elif lum > 0.8:
        name = f"pale {name}"
    elif s < 0.35:
        name = f"muted {name}"
    return name


def describe(rgb: RGB) -> str:
    return f"{color_name(rgb)} ({to_hex(rgb)})"


# --------------------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------------------


@dataclass
class _Box:
    x: float
    y: float
    w: float
    h: float
    round: bool = False

    def contains(self, px: float, py: float) -> bool:
        if self.round:
            rx, ry = self.w / 2 or 1, self.h / 2 or 1
            return ((px - self.x - rx) / rx) ** 2 + ((py - self.y - ry) / ry) ** 2 <= 1
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


def _box(props: dict, shape: str | None = None) -> _Box:
    pos, size = props.get("position") or {}, props.get("boxSize") or {}
    return _Box(float(pos.get("x") or 0), float(pos.get("y") or 0),
                float(size.get("width") or 0), float(size.get("height") or 0),
                round=shape in ("circle", "ellipse"))


@dataclass
class TextRun:
    """One visible colour of a text layer."""
    old: RGB
    new: RGB
    weight: float


@dataclass
class TextPlan:
    layer_id: str
    box: _Box
    font_px: float
    runs: dict[RGB, TextRun] = field(default_factory=dict)
    backdrop_shape: str | None = None
    """The shape this text sits on, or None when it sits on the picture."""

    @property
    def required(self) -> float:
        return LARGE_CONTRAST if self.font_px >= LARGE_TEXT_PX else SMALL_CONTRAST


@dataclass
class ThemePlan:
    palette: list[RGB]
    color_map: dict[RGB, RGB] = field(default_factory=dict)
    """Template colour → new colour, for everything that isn't a visible text colour."""
    shapes: dict[str, RGB] = field(default_factory=dict)
    """Shape layer → its new fill colour."""
    texts: dict[str, TextPlan] = field(default_factory=dict)
    contrast_fixed: list[str] = field(default_factory=list)

    def new_color(self, old: RGB) -> RGB:
        return self.color_map.get(old, old)

    # -- prompts ------------------------------------------------------------------------

    def prompt_block(self, roles: dict[str, str] | None = None) -> str:
        """For the fill model's user message (never sent without a palette)."""
        roles = roles or {}
        names = ["primary", "secondary", "accent", "extra"]
        lines = ["COLOUR PALETTE — chosen by the user; it replaces the template's own colours:"]
        lines += [f"- {names[i]}: {describe(c)}" for i, c in enumerate(self.palette)]
        text = []
        for plan in self.texts.values():
            main = max(plan.runs.values(), key=lambda r: r.weight, default=None)
            if main is None:
                continue
            side = "light" if is_light(main.new) else "dark"
            text.append(f"- {roles.get(plan.layer_id, 'text')} layer {plan.layer_id}: "
                        f"{to_hex(main.new)} ({side} text"
                        + (" on its own shape)" if plan.backdrop_shape else " on the picture)"))
        if text:
            lines += ["", "Final colour of each text layer in this design:"] + text
        lines += [
            "",
            ("Every image prompt you write must use this palette as its colour scheme: "
            "backgrounds, panels, gradients, lighting, props and small accents come from "
            "these colours (the primary dominates). Keep the areas behind light text dark "
            "and the areas behind dark text light, exactly where the image notes say text "
            "sits. A product, food or person keeps its natural colours; the palette goes into "
            "its setting, props and lighting. Any colour named in a reference prompt or in "
            "the notes is the template's old colour: use the palette instead."),
        ]
        return "\n".join(lines)

    def finalize_prompts(self, prompts: dict[str, str],
                         targets: list[ImageTarget]) -> dict[str, str]:
        """A fixed palette line on every image prompt, so the palette never depends on
        the model having followed the instruction."""
        colours = ", ".join(describe(c) for c in self.palette)
        out = dict(prompts)
        for t in targets:
            prompt = out.get(t.layer_id)
            if not prompt:
                continue
            if t.spec.transparent:
                line = (f"Colour palette for any props, garnish or accents: {colours}. "
                        "The subject itself keeps its natural colours.")
            elif t.layer_id != BACKGROUND_LAYER_ID and t.spec.kind != "decorative_shape":
                line = (f"Colour palette for the setting, props and lighting: {colours}. "
                        "The main subject (food, product, person) keeps its natural colours.")
            else:
                line = (f"Colour palette (dominant first): {colours}. Build the scene's colour "
                        "scheme — backgrounds, panels, lighting and accents — from these colours.")
            out[t.layer_id] = f"{prompt}\n\n{line}"
        return out

    def to_json(self) -> dict:
        return {"palette": [to_hex(c) for c in self.palette],
                "colorMap": {to_hex(k): to_hex(v) for k, v in self.color_map.items()},
                "textColors": {lid: {to_hex(r.old): to_hex(r.new) for r in p.runs.values()}
                               for lid, p in self.texts.items()},
                "contrastFixed": self.contrast_fixed}


def _z_order(template: LidoTemplateFile) -> list[str]:
    """Layer ids bottom to top (children in order, depth first)."""
    out: list[str] = []

    def walk(lid: str) -> None:
        layer = template.layers.get(lid)
        if layer is None:
            return
        for cid in layer.child:
            out.append(cid)
            walk(cid)

    walk(BACKGROUND_LAYER_ID)
    for lid in template.layers:
        if lid != BACKGROUND_LAYER_ID and lid not in out:
            out.append(lid)
    return out


def _text_nodes(doc: dict):
    for para in (doc or {}).get("content") or []:
        attrs = para.get("attrs") or {}
        for node in para.get("content") or []:
            yield attrs, node


def _node_color(attrs: dict, node: dict) -> str | None:
    for mark in node.get("marks") or []:
        if mark.get("type") == "color":
            return (mark.get("attrs") or {}).get("color")
    return attrs.get("color")


def _font_px(props: dict) -> float:
    sizes = props.get("fontSizes") or [16]
    return float(max(sizes)) * float(props.get("scale") or 1)


def _visible_colors(props: dict) -> dict[RGB, float]:
    """Visible text colour → weight (characters × font size²)."""
    out: dict[RGB, float] = {}
    size = _font_px(props)
    for attrs, node in _text_nodes(props.get("doc")):
        rgb = parse_color(_node_color(attrs, node))
        text = node.get("text") or ""
        if rgb is not None and text.strip():
            out[rgb] = out.get(rgb, 0.0) + len(text) * size * size
    return out


def _role_map(usage: dict[RGB, float], palette: list[RGB],
              side_hint: dict[RGB, bool] | None = None) -> dict[RGB, RGB]:
    """Chromatic template colours by prominence → palette colours in the user's order,
    each taking the next palette colour on its own light/dark side (a dark panel with
    white text on it stays dark; if the palette has no colour that dark, the next one is
    darkened). Shades of one colour follow it, keeping their lightness offset. Neutrals
    move only to a palette colour that is as dark / as light as they are. `side_hint`
    overrides the light/dark side of a colour (a shape is the opposite of its text)."""
    side_hint = side_hint or {}
    mapping: dict[RGB, RGB] = {}
    chromatic = sorted((c for c in usage if not is_neutral(c)), key=lambda c: -usage[c])
    families: list[tuple[RGB, RGB]] = []          # (family's lead colour, its palette colour)
    used: list[RGB] = []
    for c in chromatic:
        lead = next(((lc, pc) for lc, pc in families if _distance(lc, c) < SHADE_DISTANCE), None)
        if lead is not None:
            lc, pc = lead
            mapping[c] = shift_lightness(pc, _hls(c)[1] - _hls(lc)[1])
            continue
        light = side_hint.get(c, is_light(c))
        same_side = [p for p in palette if is_light(p) == light]
        fresh = [p for p in same_side if p not in used]
        if fresh or same_side:
            target = (fresh or same_side)[0]
        else:
            base = next((p for p in palette if p not in used), palette[0])
            pole = BLACK if light else WHITE
            target = toward(base, light, min(contrast(c, pole), 7.0)) or base
        used.append(target)
        families.append((c, target))
        mapping[c] = target
    darkest = min(palette, key=luminance)
    lightest = max(palette, key=luminance)
    for c in usage:
        if c in mapping:
            continue
        if luminance(c) < 0.05 and luminance(darkest) <= 0.04:
            mapping[c] = darkest
        elif luminance(c) > 0.8 and luminance(lightest) >= 0.75:
            mapping[c] = lightest
    return mapping


def _pick_readable(preferred: RGB, backdrop: RGB, required: float,
                   palette: list[RGB]) -> RGB:
    """`preferred` if readable on `backdrop`; else the first readable palette colour;
    else the preferred hue pushed lighter/darker until readable; else black or white."""
    if contrast(preferred, backdrop) >= required:
        return preferred
    for c in palette:
        if contrast(c, backdrop) >= required:
            return c
    light = not is_light(backdrop)
    h, lum, s = _hls(preferred)
    for step in range(1, 21):
        cand = _from_hls(h, lum + (step * 0.05 if light else -step * 0.05), s)
        if contrast(cand, backdrop) >= required:
            return cand
    return max((BLACK, WHITE), key=lambda c: contrast(c, backdrop))


def _keep_side(old: RGB, new: RGB, palette: list[RGB]) -> RGB:
    """Text on the picture: the new colour stays on the old colour's light/dark side,
    at least about as far from the opposite pole as the old colour was."""
    light = is_light(old)
    pole = BLACK if light else WHITE
    need = min(contrast(old, pole), 7.0)
    if is_light(new) == light and contrast(new, pole) >= need:
        return new
    for c in palette:
        if is_light(c) == light and contrast(c, pole) >= need:
            return c
    return toward(new, light, need) or old


def plan_theme(template: LidoTemplateFile, palette: list[RGB]) -> ThemePlan:
    plan = ThemePlan(palette=list(palette))
    order = _z_order(template)
    usage: dict[RGB, float] = {}
    shapes: list[tuple[str, _Box, RGB | None]] = []
    for lid in order:
        layer = template.layers[lid]
        props, kind = layer.props, layer.type.resolvedName
        if kind == "ShapeLayer":
            box = _box(props, props.get("shape"))
            fill = parse_color(props.get("color"))
            if fill is not None:
                usage[fill] = usage.get(fill, 0.0) + max(box.w * box.h, 1.0)
            for stop in gradient_stops(props.get("color")):
                # a gradient counts once per stop, at half weight: it covers the area
                # between them
                usage[stop] = usage.get(stop, 0.0) + max(box.w * box.h, 1.0) / 2
            fill = fill or next(iter(gradient_stops(props.get("color"))), None)
            border = parse_color((props.get("border") or {}).get("color"))
            if border is not None:
                usage[border] = usage.get(border, 0.0) + (box.w + box.h) * 2
            shapes.append((lid, box, fill))
        elif kind == "TextLayer":
            for rgb, w in _visible_colors(props).items():
                usage[rgb] = usage.get(rgb, 0.0) + w
        elif kind in ("LineLayer", "DrawLayer"):
            stroke = parse_color(props.get("color"))
            if stroke is not None:
                box = _box(props)
                usage[stroke] = usage.get(stroke, 0.0) + (box.w + box.h) * 2
    root_props = template.layers[BACKGROUND_LAYER_ID].props \
        if BACKGROUND_LAYER_ID in template.layers else {}
    for root_color in [parse_color(root_props.get("color")),
                       *gradient_stops(root_props.get("color"))]:
        if root_color is not None:
            usage.setdefault(root_color, 1.0)

    # A shape with text on it keeps the opposite side of that text (a mid-tone red
    # panel under white text is a dark panel as far as the design is concerned).
    side_hint: dict[RGB, bool] = {}
    for i, lid in enumerate(order):
        layer = template.layers[lid]
        if layer.type.resolvedName != "TextLayer":
            continue
        colors = _visible_colors(layer.props)
        if not colors:
            continue
        main = max(colors, key=colors.get)
        box = _box(layer.props)
        cx, cy = box.x + box.w / 2, box.y + box.h / 2
        below = [s for s in shapes if order.index(s[0]) < i and s[1].contains(cx, cy)]
        if below and below[-1][2] is not None:
            side_hint.setdefault(below[-1][2], not is_light(main))
    plan.color_map = _role_map(usage, plan.palette, side_hint)
    for lid, _box_, fill in shapes:
        if fill is not None:
            plan.shapes[lid] = plan.new_color(fill)

    for i, lid in enumerate(order):
        layer = template.layers[lid]
        if layer.type.resolvedName != "TextLayer":
            continue
        props = layer.props
        box = _box(props)
        cx, cy = box.x + box.w / 2, box.y + box.h / 2
        below = [s for s in shapes if order.index(s[0]) < i and s[1].contains(cx, cy)]
        tp = TextPlan(lid, box, _font_px(props), backdrop_shape=below[-1][0] if below else None)
        for old, w in _visible_colors(props).items():
            new = plan.new_color(old)
            if tp.backdrop_shape and tp.backdrop_shape in plan.shapes:
                new = _pick_readable(new, plan.shapes[tp.backdrop_shape], tp.required,
                                     plan.palette)
            elif new != old:
                new = _keep_side(old, new, plan.palette)
            tp.runs[old] = TextRun(old, new, w)
        plan.texts[lid] = tp
    return plan


# --------------------------------------------------------------------------------------
# After the images: is every text readable on the real picture?
# --------------------------------------------------------------------------------------


def _backdrop(image: Image.Image, box: _Box, canvas_w: float, canvas_h: float) -> RGB | None:
    if not (canvas_w and canvas_h and box.w and box.h):
        return None
    sx, sy = image.width / canvas_w, image.height / canvas_h
    left, top = max(0, int(box.x * sx)), max(0, int(box.y * sy))
    right = min(image.width, int((box.x + box.w) * sx))
    bottom = min(image.height, int((box.y + box.h) * sy))
    if right - left < 2 or bottom - top < 2:
        return None
    crop = image.crop((left, top, right, bottom)).convert("RGB").resize((24, 24))
    pixels = sorted(crop.getdata(), key=luminance)
    return pixels[len(pixels) // 2]                  # the median-luminance pixel


def check_contrast(plan: ThemePlan, background: bytes | None,
                   canvas_w: float, canvas_h: float) -> None:
    """Swap any text colour that isn't readable on the generated background behind it.
    Text on a shape was already checked against the shape's colour."""
    if not background:
        return
    try:
        image = Image.open(io.BytesIO(background))
        image.load()
    except OSError as exc:
        log.warning("lido.palette.background_unreadable", error=str(exc))
        return
    for tp in plan.texts.values():
        if tp.backdrop_shape:
            continue
        backdrop = _backdrop(image, tp.box, canvas_w, canvas_h)
        if backdrop is None:
            continue
        for run in tp.runs.values():
            fixed = _pick_readable(run.new, backdrop, tp.required, plan.palette)
            if fixed != run.new:
                run.new = fixed
                if tp.layer_id not in plan.contrast_fixed:
                    plan.contrast_fixed.append(tp.layer_id)
    if plan.contrast_fixed:
        log.info("lido.palette.contrast_fixed", layers=plan.contrast_fixed)


# --------------------------------------------------------------------------------------
# Write it into the document
# --------------------------------------------------------------------------------------


def _recolor(value: str | None, mapping: dict[RGB, RGB]) -> str | None:
    rgb = parse_color(value)
    if rgb is None or rgb not in mapping:
        return value
    return to_css(mapping[rgb])


def apply_theme(layers: dict[str, dict], plan: ThemePlan) -> None:
    """In place, on a filled document's `layers`."""
    for lid, layer in layers.items():
        props = layer.get("props") or {}
        kind = (layer.get("type") or {}).get("resolvedName")
        if kind == "RootLayer" and "color" in props:
            props["color"] = recolor_gradient(props["color"], plan.color_map) \
                if isinstance(props["color"], dict) else _recolor(props["color"], plan.color_map)
        elif kind in ("LineLayer", "DrawLayer") and "color" in props:
            props["color"] = _recolor(props["color"], plan.color_map)
        elif kind == "ShapeLayer":
            if isinstance(props.get("color"), dict):
                props["color"] = recolor_gradient(props["color"], plan.color_map)
            elif lid in plan.shapes:
                props["color"] = to_css(plan.shapes[lid])
            border = props.get("border")
            if isinstance(border, dict) and "color" in border:
                border["color"] = _recolor(border["color"], plan.color_map)
        elif kind == "TextLayer":
            tp = plan.texts.get(lid)
            visible = {r.old: r.new for r in tp.runs.values()} if tp else {}
            mapping = {**plan.color_map, **visible}
            main = max(tp.runs.values(), key=lambda r: r.weight).new \
                if tp and tp.runs else None
            for para in (props.get("doc") or {}).get("content") or []:
                attrs = para.get("attrs") or {}
                if "color" in attrs:
                    # A paragraph colour hidden under a colour mark still shows in some
                    # renderers: give it the layer's main colour when it isn't visible.
                    old = parse_color(attrs["color"])
                    attrs["color"] = (to_css(visible[old]) if old in visible
                                      else to_css(main) if main else
                                      _recolor(attrs["color"], mapping))
                for node in para.get("content") or []:
                    for mark in node.get("marks") or []:
                        if mark.get("type") == "color" and isinstance(mark.get("attrs"), dict):
                            mark["attrs"]["color"] = _recolor(mark["attrs"].get("color"),
                                                              mapping)
            if isinstance(props.get("colors"), list):
                props["colors"] = list(dict.fromkeys(
                    _recolor(c, mapping) for c in props["colors"]))
            settings = (props.get("effect") or {}).get("settings")
            if isinstance(settings, dict) and "color" in settings:
                settings["color"] = _recolor(settings["color"], mapping)
