#!/usr/bin/env python3
"""Build the font pack used by the layout engine and both renderers.

Google Fonts ships variable TTFs. We download those and *instance* them to static
per-weight TTFs with fontTools, because:

  * HarfBuzz (shaping) and Skia (rasterising) then load byte-identical outlines, which
    is what INV-3 (render parity) requires — no risk of the two applying a variation
    axis differently;
  * the browser can load the same static files over @font-face, so the editor previews
    the face the exporter will actually draw;
  * font licensing (§4.1) is simpler to track per file.

All fonts here are SIL OFL 1.1, which permits embedding and redistribution.
Run: python scripts/fetch_fonts.py
"""

from __future__ import annotations

import io
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

RAW = "https://raw.githubusercontent.com/google/fonts/main"
OUT = Path(__file__).resolve().parent.parent / "backend" / "assets_local" / "fonts"

# family -> (repo path, axes to pin besides wght, weights, style, vibe)
SPECS: list[dict] = [
    # geometric / neutral UI
    {"family": "Inter", "path": "ofl/inter/Inter[opsz,wght].ttf",
     "pin": {"opsz": 32}, "weights": [400, 500, 700, 900], "style": "normal",
     "vibe": "geometric", "license": "OFL-1.1"},
    {"family": "Inter", "path": "ofl/inter/Inter-Italic[opsz,wght].ttf",
     "pin": {"opsz": 32}, "weights": [400, 700], "style": "italic",
     "vibe": "geometric", "license": "OFL-1.1"},
    {"family": "Montserrat", "path": "ofl/montserrat/Montserrat[wght].ttf",
     "pin": {}, "weights": [400, 700, 900], "style": "normal",
     "vibe": "geometric", "license": "OFL-1.1"},
    {"family": "Poppins", "path": "ofl/poppins/Poppins-Regular.ttf", "pin": {},
     "weights": [400], "style": "normal", "vibe": "geometric", "license": "OFL-1.1",
     "static": True},
    {"family": "Poppins", "path": "ofl/poppins/Poppins-Bold.ttf", "pin": {},
     "weights": [700], "style": "normal", "vibe": "geometric", "license": "OFL-1.1",
     "static": True},
    {"family": "Poppins", "path": "ofl/poppins/Poppins-Black.ttf", "pin": {},
     "weights": [900], "style": "normal", "vibe": "geometric", "license": "OFL-1.1",
     "static": True},
    {"family": "Space Grotesk", "path": "ofl/spacegrotesk/SpaceGrotesk[wght].ttf",
     "pin": {}, "weights": [400, 700], "style": "normal",
     "vibe": "geometric", "license": "OFL-1.1"},
    {"family": "DM Sans", "path": "ofl/dmsans/DMSans[opsz,wght].ttf",
     "pin": {"opsz": 24}, "weights": [400, 700], "style": "normal",
     "vibe": "geometric", "license": "OFL-1.1"},
    # humanist
    {"family": "Source Sans 3", "path": "ofl/sourcesans3/SourceSans3[wght].ttf",
     "pin": {}, "weights": [400, 600, 700], "style": "normal",
     "vibe": "humanist", "license": "OFL-1.1"},
    {"family": "Noto Sans", "path": "ofl/notosans/NotoSans[wdth,wght].ttf",
     "pin": {"wdth": 100}, "weights": [400, 700], "style": "normal",
     "vibe": "humanist", "license": "OFL-1.1"},
    # serif editorial
    {"family": "Playfair Display", "path": "ofl/playfairdisplay/PlayfairDisplay[wght].ttf",
     "pin": {}, "weights": [400, 700, 900], "style": "normal",
     "vibe": "serif-editorial", "license": "OFL-1.1"},
    {"family": "Playfair Display",
     "path": "ofl/playfairdisplay/PlayfairDisplay-Italic[wght].ttf",
     "pin": {}, "weights": [400, 700], "style": "italic",
     "vibe": "serif-editorial", "license": "OFL-1.1"},
    # display bold
    {"family": "Bebas Neue", "path": "ofl/bebasneue/BebasNeue-Regular.ttf", "pin": {},
     "weights": [400], "style": "normal", "vibe": "display-bold", "license": "OFL-1.1",
     "static": True},
    {"family": "Archivo Black", "path": "ofl/archivoblack/ArchivoBlack-Regular.ttf",
     "pin": {}, "weights": [400], "style": "normal", "vibe": "display-bold",
     "license": "OFL-1.1", "static": True},
    {"family": "Oswald", "path": "ofl/oswald/Oswald[wght].ttf", "pin": {},
     "weights": [400, 700], "style": "normal", "vibe": "display-bold",
     "license": "OFL-1.1"},
    # Heavy display faces. Bebas and Oswald are condensed; these are the wide, dense
    # poster faces a promotional headline is usually set in.
    {"family": "Anton", "path": "ofl/anton/Anton-Regular.ttf", "pin": {},
     "weights": [400], "style": "normal", "vibe": "display-bold",
     "license": "OFL-1.1", "static": True},
    {"family": "Abril Fatface", "path": "ofl/abrilfatface/AbrilFatface-Regular.ttf",
     "pin": {}, "weights": [400], "style": "normal", "vibe": "display-bold",
     "license": "OFL-1.1", "static": True},
    {"family": "Alfa Slab One", "path": "ofl/alfaslabone/AlfaSlabOne-Regular.ttf",
     "pin": {}, "weights": [400], "style": "normal", "vibe": "display-bold",
     "license": "OFL-1.1", "static": True},
    # Script. Used only for a short accent line set beside a display face — the
    # "Summer" above "FASHION SALE" — never for body copy, and never uppercased.
    {"family": "Great Vibes", "path": "ofl/greatvibes/GreatVibes-Regular.ttf", "pin": {},
     "weights": [400], "style": "normal", "vibe": "script", "license": "OFL-1.1",
     "static": True},
    {"family": "Dancing Script", "path": "ofl/dancingscript/DancingScript[wght].ttf",
     "pin": {}, "weights": [400, 700], "style": "normal", "vibe": "script",
     "license": "OFL-1.1"},
    {"family": "Pacifico", "path": "ofl/pacifico/Pacifico-Regular.ttf", "pin": {},
     "weights": [400], "style": "normal", "vibe": "script", "license": "OFL-1.1",
     "static": True},
]


def slug(family: str) -> str:
    return family.replace(" ", "")


def font_key(family: str, weight: int, style: str) -> str:
    return f"{slug(family)}-{weight}{'i' if style == 'italic' else ''}"


def fetch(path: str) -> bytes:
    url = f"{RAW}/{urllib.parse.quote(path)}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    catalog: dict[str, dict] = {}
    cache: dict[str, bytes] = {}

    for spec in SPECS:
        family, path = spec["family"], spec["path"]
        if path not in cache:
            print(f"  fetching {path}")
            try:
                cache[path] = fetch(path)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! FAILED {path}: {exc}", file=sys.stderr)
                continue
        raw = cache[path]

        for weight in spec["weights"]:
            key = font_key(family, weight, spec["style"])
            dest = OUT / f"{key}.ttf"
            if spec.get("static"):
                dest.write_bytes(raw)
            else:
                font = TTFont(io.BytesIO(raw))
                axes = {"wght": weight, **spec["pin"]}
                available = {a.axisTag for a in font["fvar"].axes}
                axes = {k: v for k, v in axes.items() if k in available}
                inst = instancer.instantiateVariableFont(font, axes, inplace=True,
                                                         updateFontNames=False)
                inst.save(dest)
            catalog[key] = {
                "family": family,
                "weight": weight,
                "style": spec["style"],
                "vibe": spec["vibe"],
                "file": dest.name,
                "license": spec["license"],
                "embeddable": True,
                "bytes": dest.stat().st_size,
            }
            print(f"    -> {dest.name} ({dest.stat().st_size // 1024} KB)")

    (OUT / "catalog.json").write_text(json.dumps(catalog, indent=2, sort_keys=True))
    families = sorted({v["family"] for v in catalog.values()})
    print(f"\n{len(catalog)} faces across {len(families)} families -> {OUT}")
    print("families:", ", ".join(families))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
