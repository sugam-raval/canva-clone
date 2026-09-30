"""Preview screenshots: draw the Lido layers as plain HTML/CSS (text wraps like the Lido
editor, frames use the same clipPath and image offsets) and screenshot it with headless
Chrome. Close to the editor but not identical — rounded corners are approximate."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from app.lido_create.lido import ROUNDED_PER_PX

BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")


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
            parts.append(
                f'<div style="{base}height:auto;font-family:\'{a["fontFamily"]}\';'
                f'font-size:{a["fontSize"]};line-height:{a["lineHeight"]};'
                f'letter-spacing:{a["letterSpacing"]}em;text-align:{a["textAlign"]};'
                f'text-transform:{a["textTransform"]};color:{a["color"]};">{text}</div>')
        elif rn == "ShapeLayer":
            radius = ("50%" if p["shape"] == "circle"
                      else f"{p.get('roundedCorners', 0) / ROUNDED_PER_PX}px")
            b = p.get("border")
            border = (f"border:{b['weight']}px {b['style']} {b['color']};box-sizing:border-box;"
                      if b else "")
            parts.append(f'<div style="{base}background:{p["color"]};border-radius:{radius};'
                         f'opacity:{p.get("transparency", 1)};{border}"></div>')
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
            f"overflow:hidden;background:{root['color']};}}</style></head><body><div id=c>"
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
