#!/usr/bin/env python3
"""Check the icon library and draw every icon on a contact sheet, to review new ones:

    make lido-doodles                       # → lidojs_templates/doodles/sheet_<n>.png
    python scripts/doodle_sheet.py --only phone mail globe

Each icon goes through the real Lido writer and preview renderer (a DrawLayer, as a
template would hold it), so the sheet shows what the editor will show. Exits non-zero
if the library has problems (bad path, duplicate name, path leaving its box…).
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.lido_create.doodles import library, problems, stroke_width
from app.lido_create.kit import CORPUS_DIR, FONT_SETS, PALETTES, THEMES, Design, Element, Variant
from app.lido_create.lido import to_lido
from app.lido_create.render import browser, screenshot

OUT = CORPUS_DIR / "doodles"
COLS, ROWS, CELL = 8, 6, 135  # 48 doodles per 1080 x 1080 sheet


def sheet(names: list[str], out: Path) -> None:
    v = Variant(PALETTES[0], FONT_SETS[0], THEMES[0], random.Random(0), [])
    els = [Element(kind="shape", shape="rectangle", x=0, y=0, w=1080, h=1080, color="bg")]
    for i, name in enumerate(names):
        cx, cy = (i % COLS) * CELL, (i // COLS) * CELL
        size = 70
        els.append(Element(kind="draw", x=cx + (CELL - size) / 2, y=cy + 18, w=size, h=size,
                           color="ink",
                           stroke_width=stroke_width(size), doodle=name))
        els.append(Element(kind="text", text=name, text_type="caption", x=cx + 4,
                           y=cy + 98, w=CELL - 8, h=16, size=13, font="body",
                           align="center", color="ink"))
    d = Design(recipe="doodles", theme="x", palette=v.palette.name, fonts=v.fonts.name,
               elements=els)
    screenshot(to_lido(d, v)[0]["layers"], out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", help="just these doodles")
    args = parser.parse_args()
    found = problems()
    for p in found:
        print(f"  ! {p}")
    names = args.only or list(library())
    unknown = [n for n in names if n not in library()]
    if unknown:
        print(f"unknown doodle(s): {', '.join(unknown)}", file=sys.stderr)
        return 1
    print(f"{len(library())} doodles, {len(found)} problem(s)")
    if browser() is None:
        print("no Chrome/Chromium found — skipping the sheets")
        return 1 if found else 0
    OUT.mkdir(parents=True, exist_ok=True)
    per = COLS * ROWS
    for n, start in enumerate(range(0, len(names), per), 1):
        out = OUT / f"sheet_{n}.png"
        sheet(names[start:start + per], out)
        print(f"  {out}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
