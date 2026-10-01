"""Preview screenshots: draw the Lido layers as plain HTML/CSS (text wraps like the Lido
editor, frames use the same clipPath and image offsets) and screenshot it with headless
Chrome. Close to the editor but not identical — rounded corners are approximate."""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from app.lido_create.lido import ROUNDED_PER_PX
from app.lido_create.shapes import SHAPES

BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")


def css_color(c) -> str:
    """A Lido colour — a CSS string or a gradient {colors, style, angle} — as CSS."""
    if not isinstance(c, dict):
        return c or "transparent"
    stops = ", ".join(f"{s['color']} {s['percent']}%" for s in c.get("colors") or [])
    if c.get("style") == "radial":
        return f"radial-gradient({stops})"
    return f"linear-gradient({c.get('angle', 180)}deg, {stops})"


def _dash(style: str, weight: float) -> str:
    if style == "shortDashes":
        return f'stroke-dasharray="{weight * 2.5} {weight * 1.5}"'
    if style == "dots":
        return f'stroke-dasharray="0.01 {weight * 2}" stroke-linecap="round"'
    return ""


def _shape(p: dict, base: str) -> str:
    """Fill as a clipped div (so CSS gradients work), outline as an SVG on top of it
    (so dashed/dotted borders follow the outline, not the box)."""
    w, h = p["boxSize"]["width"], p["boxSize"]["height"]
    name = p.get("shape") or "rectangle"
    pts = SHAPES[name].points if name in SHAPES else ()
    radius = p.get("roundedCorners", 0) / (p.get("scale") or ROUNDED_PER_PX) \
        if name == "rectangle" else 0
    if name == "circle":
        clip, outline = "border-radius:50%;", \
            f'<ellipse cx="{w / 2}" cy="{h / 2}" rx="{w / 2}" ry="{h / 2}"'
    elif pts:
        poly = ",".join(f"{x * 100:.2f}% {y * 100:.2f}%" for x, y in pts)
        clip = f"clip-path:polygon({poly});"
        outline = '<polygon points="' + " ".join(f"{x * w:.2f},{y * h:.2f}" for x, y in pts) + '"'
    else:
        clip = f"border-radius:{radius}px;"
        outline = f'<rect x="0" y="0" width="{w}" height="{h}" rx="{radius}"'
    out = (f'<div style="{base}background:{css_color(p["color"])};{clip}'
           f'opacity:{p.get("transparency", 1)};"></div>')
    b = p.get("border")
    if b:
        wt = b.get("weight", 2)
        # SVG strokes are centred on the outline; clip to the shape so it reads as inside
        out += (f'<svg style="{base}overflow:visible;opacity:{p.get("transparency", 1)}" '
                f'viewBox="0 0 {w} {h}">{outline} fill="none" stroke="{b["color"]}" '
                f'stroke-width="{wt}" {_dash(b.get("style", "solid"), wt)}/></svg>')
    return out


def _marker(kind: str, x: float, y: float, m: float, color: str, pointing: int) -> str:
    """A line-end marker at (x, y); `pointing` is +1 at the end, -1 at the start."""
    if kind in ("none", None):
        return ""
    fill, stroke = (("none", color) if kind.startswith("outline") else (color, "none"))
    k = kind.removeprefix("outline").lower()
    if k == "arrow":
        tip = x + pointing * m * 0.1
        return (f'<polyline points="{tip - pointing * m},{y - m * 0.7} {tip},{y} '
                f'{tip - pointing * m},{y + m * 0.7}" fill="none" stroke="{color}" '
                f'stroke-width="{m * 0.35}" stroke-linecap="round" stroke-linejoin="round"/>')
    if k == "triangle":
        return (f'<polygon points="{x + pointing * m * 0.6},{y} {x - pointing * m * 0.6},'
                f'{y - m * 0.7} {x - pointing * m * 0.6},{y + m * 0.7}" fill="{color}"/>')
    if k == "bar":
        return f'<rect x="{x - m * 0.12}" y="{y - m}" width="{m * 0.24}" height="{m * 2}" fill="{color}"/>'
    sw = f'stroke-width="{m * 0.3}"'
    if k == "circle":
        return f'<circle cx="{x}" cy="{y}" r="{m * 0.6}" fill="{fill}" stroke="{stroke}" {sw}/>'
    if k == "square":
        return (f'<rect x="{x - m * 0.55}" y="{y - m * 0.55}" width="{m * 1.1}" '
                f'height="{m * 1.1}" fill="{fill}" stroke="{stroke}" {sw}/>')
    if k == "diamond":
        return (f'<polygon points="{x},{y - m * 0.75} {x + m * 0.75},{y} {x},{y + m * 0.75} '
                f'{x - m * 0.75},{y}" fill="{fill}" stroke="{stroke}" {sw}/>')
    return ""


def _line(p: dict) -> str:
    w, t = p["boxSize"]["width"], p["boxSize"]["height"]
    m = max(t * 2.2, 9)
    pos, color = p["position"], p.get("color", "black")
    turn = f"transform:rotate({p['rotate']}deg);" if p.get("rotate") else ""
    inset_s = m * 0.6 if p.get("arrowStart", "none") != "none" else 0
    inset_e = m * 0.6 if p.get("arrowEnd", "none") != "none" else 0
    cy = m
    return (f'<svg style="position:absolute;left:{pos["x"]}px;top:{pos["y"] + t / 2 - m}px;'
            f'width:{w}px;height:{m * 2}px;overflow:visible;{turn}" viewBox="0 0 {w} {m * 2}">'
            f'<line x1="{inset_s}" y1="{cy}" x2="{w - inset_e}" y2="{cy}" stroke="{color}" '
            f'stroke-width="{t}" {_dash(p.get("style", "solid"), t)}/>'
            + _marker(p.get("arrowStart"), inset_s, cy, m, color, -1)
            + _marker(p.get("arrowEnd"), w - inset_e, cy, m, color, 1) + "</svg>")


def _draw(p: dict, base: str) -> str:
    w, h, sc = p["boxSize"]["width"], p["boxSize"]["height"], p.get("scale") or 1
    return (f'<svg style="{base}overflow:visible;opacity:{p.get("transparency", 1)}" '
            f'viewBox="0 0 {w} {h}"><g transform="scale({sc})"><path d="{p["path"]}" '
            f'fill="none" stroke="{p.get("color", "black")}" stroke-width="{p["width"] / sc}" '
            f'stroke-linecap="round" stroke-linejoin="round"/></g></svg>')


def _text_effect(effect: dict | None, size_px: float, color: str) -> str:
    """CSS approximations of Lido's text effects."""
    if not effect:
        return ""
    s = effect.get("settings") or {}
    name = effect.get("name")
    if name == "hollow":
        width = max(1.0, size_px * s.get("thickness", 50) / 100 * 0.035)
        return f"color:transparent;-webkit-text-stroke:{width:.2f}px {color};"
    if name == "lift":
        k = s.get("intensity", 50) / 100
        return (f"text-shadow:0 {size_px * 0.04:.1f}px {size_px * 0.3 * k:.1f}px "
                f"rgba(0,0,0,{0.25 + 0.45 * k:.2f});")
    if name == "shadow":
        dist = s.get("offset", 30) / 100 * size_px * 0.2
        a = math.radians(s.get("direction", -45))
        blur = s.get("blur", 10) / 100 * size_px * 0.3
        alpha = 1 - s.get("transparency", 40) / 100
        rgb = s.get("color", "rgb(0, 0, 0)").replace("rgb(", "rgba(").replace(")", f", {alpha:.2f})")
        return (f"text-shadow:{dist * math.cos(a):.1f}px {-dist * math.sin(a):.1f}px "
                f"{blur:.1f}px {rgb};")
    return ""


def _root_background(color) -> str:
    # a gradient's transparent end shows the white page underneath
    return f"{css_color(color)}, #fff" if isinstance(color, dict) else css_color(color)


def html(layers: dict) -> str:
    root = layers["ROOT"]["props"]
    w, h = root["boxSize"]["width"], root["boxSize"]["height"]
    faces, parts = {}, []
    for lid in layers["ROOT"]["child"]:
        layer = layers[lid]
        p, rn = layer["props"], layer["type"]["resolvedName"]
        pos, box = p["position"], p["boxSize"]
        turn = f"transform:rotate({p['rotate']}deg);" if p.get("rotate") else ""
        base = (f"position:absolute;left:{pos['x']}px;top:{pos['y']}px;"
                f"width:{box['width']}px;height:{box['height']}px;{turn}")
        if rn == "TextLayer":
            for f in p["fonts"]:
                faces[f["name"]] = f["fonts"][0]["urls"][0]
            para = p["doc"]["content"][0]
            a = para["attrs"]
            text = "".join(n["text"] for n in para["content"])
            size = float(str(a["fontSize"]).removesuffix("px"))
            parts.append(
                f'<div style="{base}height:auto;font-family:\'{a["fontFamily"]}\';'
                f'font-size:{a["fontSize"]};line-height:{a["lineHeight"]};'
                f'letter-spacing:{a["letterSpacing"]}em;text-align:{a["textAlign"]};'
                f'text-transform:{a["textTransform"]};color:{a["color"]};'
                f'{_text_effect(p.get("effect"), size, a["color"])}">{text}</div>')
        elif rn == "ShapeLayer":
            parts.append(_shape(p, base))
        elif rn == "LineLayer":
            parts.append(_line(p))
        elif rn == "DrawLayer":
            parts.append(_draw(p, base))
        elif "clipPath" in p:
            img, sc = p["image"], p["scale"]
            cw, ch = box["width"] / sc, box["height"] / sc
            parts.append(
                f'<svg style="{base}" viewBox="0 0 {cw} {ch}"><defs><clipPath id="c{lid}">'
                f'<path d="{p["clipPath"]}"/></clipPath></defs><image clip-path="url(#c{lid})"'
                f' href="{img["url"]}" x="{img["position"]["x"]}" y="{img["position"]["y"]}"'
                f' width="{img["boxSize"]["width"]}" height="{img["boxSize"]["height"]}"'
                f' preserveAspectRatio="none"/></svg>')
        else:
            parts.append(f'<img src="{p["image"]["url"]}" style="{base}object-fit:contain;">')
    css = "".join(f"@font-face{{font-family:'{n}';src:url({u});}}" for n, u in faces.items())
    return (f"<!doctype html><html><head><meta charset=utf-8><style>{css}"
            f"html,body{{margin:0}}#c{{position:relative;width:{w}px;height:{h}px;"
            f"overflow:hidden;background:{_root_background(root['color'])};}}"
            f"</style></head><body><div id=c>"
            + "".join(parts) + "</div></body></html>")


def browser() -> str | None:
    return next((b for b in map(shutil.which, BROWSERS) if b), None)


def screenshot(layers: dict, out: Path) -> bool:
    exe = browser()
    if exe is None:
        return False
    root = layers["ROOT"]["props"]["boxSize"]
    w, h = int(root["width"]), int(root["height"])
    with tempfile.TemporaryDirectory() as tmp:
        page, shot = Path(tmp) / "page.html", Path(tmp) / "shot.png"
        page.write_text(html(layers))
        # The window is taller than the canvas: headless Chrome's viewport is a bit
        # shorter than --window-size, which would otherwise cut off the bottom.
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={w},{h + 300}", "--virtual-time-budget=10000",
                        f"--screenshot={shot}", page.as_uri()],
                       capture_output=True, timeout=120, check=False)
        if not shot.is_file():
            return False
        Image.open(shot).convert("RGB").crop((0, 0, w, h)).save(out)
    return True


def overview(pngs: list[Path], out: Path, tile: int = 360) -> None:
    """One contact sheet of the whole batch, to review everything at a glance."""
    if not pngs:
        return
    cols = min(len(pngs), 4)
    rows = (len(pngs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tile + 10) + 10, rows * (tile + 10) + 10), "white")
    for i, path in enumerate(pngs):
        im = Image.open(path).convert("RGB").resize((tile, tile))
        sheet.paste(im, (10 + (i % cols) * (tile + 10), 10 + (i // cols) * (tile + 10)))
    sheet.save(out)
