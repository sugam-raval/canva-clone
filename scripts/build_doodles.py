#!/usr/bin/env python3
"""(Re)build the Lucide part of the icon library, backend/app/lido_create/data/doodles.yaml.

Lucide (https://lucide.dev, ISC licence — see data/doodles.LICENSE.md) draws every icon
as strokes on a 24 x 24 grid, which is exactly what Lido's DrawLayer draws. This script
fetches the icons listed in CATALOG below from the lucide-static package, turns each
SVG's elements (path, circle, ellipse, rect, line, polyline, polygon) into one path, and
writes them into doodles.yaml. Hand-drawn entries (`source: hand`) already in the file
are kept as they are, so the library can grow both ways:

    python scripts/build_doodles.py            # refresh the Lucide entries
    make lido-doodles                          # then look at every doodle on one sheet

To add a Lucide icon: add a line to CATALOG and rerun. To add your own: write an entry
with `source: hand` straight into doodles.yaml (see the comment at its top).
"""

from __future__ import annotations

import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "backend" / "app" / "lido_create" / "data" / "doodles.yaml"
LUCIDE = "1.49.0"
URL = f"https://unpkg.com/lucide-static@{LUCIDE}/icons/{{}}.svg"

# our name: (lucide icon, themes, the text types it sits beside)
CATALOG: dict[str, tuple[str, list[str], list[str]]] = {
    "location_pin": ("map-pin", ["contact", "address", "visit", "store"], ["address"]),
    "globe": ("globe", ["contact", "website", "online"], ["website"]),
    "phone": ("phone", ["contact", "call"], ["phone"]),
    "mail": ("mail", ["contact", "email"], ["email"]),
    "clock": ("clock", ["hours", "time", "open", "event"], []),
    "calendar": ("calendar", ["date", "event", "booking", "schedule"], []),
    "ticket": ("ticket", ["event", "ticket", "admission", "show"], []),
    "tag": ("tag", ["price", "sale", "offer", "shop"], []),
    "percent": ("percent", ["sale", "discount", "offer"], []),
    "chat": ("message-circle", ["contact", "message", "support", "chat"], []),
    "at_sign": ("at-sign", ["contact", "social", "email"], []),
    "link": ("link", ["website", "online"], []),
    "delivery": ("truck", ["delivery", "shipping", "order"], []),
    "shopping_bag": ("shopping-bag", ["shop", "fashion", "sale", "retail"], []),
    "cart": ("shopping-cart", ["shop", "grocery", "order", "retail"], []),
    "store": ("store", ["shop", "store", "opening", "retail"], []),
}


# glyphs drawn inside solid list bullets (lists.py: check_circle, arrow_circle)
BULLETS: dict[str, tuple[str, list[str]]] = {
    "tick": ("check", ["done", "features", "benefits", "checklist"]),
    "chevron": ("chevron-right", ["steps", "next", "services"]),
}

_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _f(el, name: str, default: float = 0.0) -> float:
    return float(el.get(name, default))


def element_path(el) -> str | None:
    """One SVG element as path data (arcs kept: the runtime flattens them)."""
    tag = el.tag.split("}")[-1]
    if tag == "path":
        d = (el.get("d") or "").strip()
        # A path's first moveto is absolute even when written "m"; once paths are joined
        # into one it would become relative to the previous piece — anchor it at 0,0
        # (keeping later pairs relative, as the SVG spec reads them).
        return f"M 0 0 {d}" if d[:1] == "m" else d
    if tag in ("circle", "ellipse"):
        cx, cy = _f(el, "cx"), _f(el, "cy")
        rx = _f(el, "r") if tag == "circle" else _f(el, "rx")
        ry = _f(el, "r") if tag == "circle" else _f(el, "ry")
        return (f"M {cx - rx} {cy} A {rx} {ry} 0 1 0 {cx + rx} {cy} "
                f"A {rx} {ry} 0 1 0 {cx - rx} {cy} Z")
    if tag == "rect":
        x, y, w, h = _f(el, "x"), _f(el, "y"), _f(el, "width"), _f(el, "height")
        r = min(_f(el, "rx", _f(el, "ry")), w / 2, h / 2)
        if not r:
            return f"M {x} {y} H {x + w} V {y + h} H {x} Z"
        return (f"M {x + r} {y} H {x + w - r} A {r} {r} 0 0 1 {x + w} {y + r} "
                f"V {y + h - r} A {r} {r} 0 0 1 {x + w - r} {y + h} H {x + r} "
                f"A {r} {r} 0 0 1 {x} {y + h - r} V {y + r} A {r} {r} 0 0 1 {x + r} {y} Z")
    if tag == "line":
        return f"M {_f(el, 'x1')} {_f(el, 'y1')} L {_f(el, 'x2')} {_f(el, 'y2')}"
    if tag in ("polyline", "polygon"):
        nums = _NUM.findall(el.get("points", ""))
        pts = [f"{nums[i]} {nums[i + 1]}" for i in range(0, len(nums) - 1, 2)]
        if not pts:
            return None
        return "M " + " L ".join(pts) + (" Z" if tag == "polygon" else "")
    return None


def _download(url: str, tries: int = 4) -> bytes:
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except OSError:  # timeouts and resets: the CDN is flaky now and then
            if attempt == tries:
                raise
            time.sleep(attempt)
    raise AssertionError("unreachable")


def fetch(icon: str) -> str:
    root = ET.fromstring(_download(URL.format(icon)))
    parts = [d for el in root.iter() if (d := element_path(el))]
    if not parts:
        raise ValueError("no drawable elements")
    return " ".join(" ".join(p.split()) for p in parts)


def main() -> int:
    existing = yaml.safe_load(LIBRARY.read_text()) if LIBRARY.is_file() else []
    hand = [d for d in existing or [] if d.get("source") == "hand"]
    taken = {d["name"] for d in hand}
    built, missing = [], []
    jobs = [(name, icon, themes, pairs, False) for name, (icon, themes, pairs) in CATALOG.items()]
    jobs += [(name, icon, themes, [], True) for name, (icon, themes) in BULLETS.items()]
    for name, icon, themes, pairs, bullet in jobs:
        if name in taken:
            continue  # a hand-drawn version wins
        try:
            path = fetch(icon)
        except Exception as exc:  # noqa: BLE001 — report and carry on
            missing.append(f"{name} (lucide {icon}): {exc}")
            continue
        entry = {"name": name, "themes": themes, "source": f"lucide:{icon}", "path": path}
        if pairs:
            entry["pairs_with"] = pairs
        if bullet:
            entry["bullet"] = True
        built.append(entry)
        print(f"  {name:<16} ← lucide {icon}")
    header = LIBRARY.read_text().split("\n- ", 1)[0] if LIBRARY.is_file() else ""
    body = yaml.safe_dump(hand + built, sort_keys=False, allow_unicode=True, width=100,
                          default_flow_style=None)
    LIBRARY.write_text((header.rstrip() + "\n\n" if header.strip().startswith("#") else "")
                       + body)
    print(f"\n{len(built)} from Lucide {LUCIDE}, {len(hand)} hand-drawn kept → {LIBRARY}")
    for m in missing:
        print(f"  ! {m}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
