"""The editable design knowledge the art director works from:

    data/layouts.yaml   the layout catalogue — post structures to pick from
    data/moods.yaml     the mood map — which frames/shapes/strokes/effects fit a feel

Both are plain YAML, meant to grow over time. They are checked on load: an unknown frame,
shape, stroke or effect name is reported (`problems()`) instead of silently doing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings
from app.lido_create.backdrops import STYLES as BACKDROP_STYLES
from app.lido_create.draw import DRAW_PRESETS
from app.lido_create.shapes import SHAPES, TEXT_EFFECTS, frames

DATA = Path(__file__).parent / "data"
CLIPS = ("rect", "rounded", "circle", "arch", "hexagon", "diamond", "blob", "leaf", "cutout")
# --------------------------------------------------------------------------------------
# PHOTO LIMIT — how many photos (and so generated images) a new template may have.
#
# MAX_PHOTOS is the one place it is read (from LIDO_MAX_PHOTOS in backend/.env); the
# plan, the checks, the designer's rules and the layout catalogue all use it.
#
# Within 1-4 — just change backend/.env and restart the backend:
#     LIDO_MAX_PHOTOS=3        # today: at most 3 images per template
#     LIDO_MAX_PHOTOS=4        # multiple photos back on, up to 4 (all layouts return)
#
# MORE THAN 4 (e.g. 6) needs these changes too — each spot is marked "PHOTO LIMIT":
#   1. app/config.py         `lido_max_photos` — raise `le=4` to the new most (e.g. 6).
#   2. here                  LAYOUT_MAX_PHOTOS — raise it, so layouts.yaml may hold
#                            layouts written for that many photos.
#   3. data/layouts.yaml     add layouts for 5-6 photos (e.g. a 3x2 grid), and widen
#                            ranges like `photos: [3, 4]` to `[3, 6]` where they fit.
#   4. check.py              min_photo_side() — pick a smaller minimum for 5+ photos
#                            (three per row at 1080px wide leaves ~300px each).
#   5. plan.py               the art director's rule "With 3 or 4 photos…" and the wide
#                            frame swap (`len(plan.photos) >= 3`) — reword for 5+.
#   6. ai.py                 the designer's rule "1 to {max_photos} photos…" already
#                            follows MAX_PHOTOS; check the layout advice still fits.
#   7. tests/test_lido_create.py  test_lido_max_photos_caps_the_plan_and_the_catalogue
#                            — add a case for the new most.
# Every image still renders in parallel (photos.PhotoPrefetch), so more photos cost more
# money, not more waiting — but each one more is another chance a request stalls.
# --------------------------------------------------------------------------------------
LAYOUT_MAX_PHOTOS = 4  # PHOTO LIMIT: the most photos a layout in layouts.yaml may need
MAX_PHOTOS = get_settings().lido_max_photos


@dataclass(frozen=True)
class Layout:
    name: str
    photos: tuple[int, int]
    suits: tuple[str, ...]
    idea: str

    def fits(self, photos: int) -> bool:
        return self.photos[0] <= photos <= self.photos[1]


@dataclass(frozen=True)
class Mood:
    name: str
    when: tuple[str, ...]
    frames: tuple[str, ...]
    shapes: tuple[str, ...]
    draw: tuple[str, ...]
    effects: tuple[str, ...]
    gradient: str
    avoid: str
    feel: str
    backdrops: tuple[str, ...] = ()


def _list(value) -> tuple[str, ...]:
    return tuple(str(v) for v in (value or []))


def _load(name: str) -> list[dict]:
    path = DATA / name
    try:
        return yaml.safe_load(path.read_text()) or []
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        raise ValueError(f"{path.name}{where} is not valid YAML ({getattr(exc, 'problem', exc)})"
                         " — a text containing ': ' must be wrapped in double quotes") from exc


@lru_cache(maxsize=1)
def layouts() -> dict[str, Layout]:
    """The catalogue as written, held to MAX_PHOTOS: a layout's photo range is capped
    at it, and a layout that needs more photos than that is left out."""
    raw = _load("layouts.yaml")
    out = {}
    for item in raw:
        lo, hi = (int(n) for n in (item.get("photos") or [1, 1])[:2])
        if lo > MAX_PHOTOS:
            continue
        out[item["name"]] = Layout(item["name"], (lo, min(hi, MAX_PHOTOS)),
                                   _list(item.get("suits")),
                                   " ".join(str(item.get("idea", "")).split()))
    return out


@lru_cache(maxsize=1)
def moods() -> dict[str, Mood]:
    raw = _load("moods.yaml")
    return {m["name"]: Mood(m["name"], _list(m.get("when")), _list(m.get("frames")),
                            _list(m.get("shapes")), _list(m.get("draw")),
                            _list(m.get("effects")), str(m.get("gradient") or "none"),
                            str(m.get("avoid") or ""), str(m.get("feel") or ""),
                            _list(m.get("backdrops")))
            for m in raw}


def problems() -> list[str]:
    """Every name in the two files that doesn't exist in Lido or the generator."""
    found = []
    for lay in layouts().values():
        if not (1 <= lay.photos[0] <= lay.photos[1] <= LAYOUT_MAX_PHOTOS):
            found.append(f"layout {lay.name}: photos {list(lay.photos)} must be within "
                         f"1-{LAYOUT_MAX_PHOTOS}")
        if not lay.idea:
            found.append(f"layout {lay.name}: no idea text")
    known_frames = set(frames()) | set(CLIPS)
    for m in moods().values():
        found += [f"mood {m.name}: unknown frame {f!r}" for f in m.frames if f not in known_frames]
        found += [f"mood {m.name}: unknown shape {s!r}" for s in m.shapes if s not in SHAPES]
        found += [f"mood {m.name}: unknown draw {d!r}" for d in m.draw if d not in DRAW_PRESETS]
        found += [f"mood {m.name}: unknown effect {e!r}" for e in m.effects
                  if e not in TEXT_EFFECTS]
        found += [f"mood {m.name}: unknown backdrop {b!r}" for b in m.backdrops
                  if b not in BACKDROP_STYLES]
    return found


def layout_menu() -> str:
    """The catalogue as the art director reads it."""
    return "\n".join(f"- {lay.name} (photos {lay.photos[0]}-{lay.photos[1]}; "
                     f"suits {', '.join(lay.suits)}): {lay.idea}"
                     for lay in layouts().values())


def mood_guide() -> str:
    lines = []
    for m in moods().values():
        lines.append(
            f"- {m.name} — when: {', '.join(m.when)}. frames: {', '.join(m.frames) or '-'}; "
            f"shapes: {', '.join(m.shapes) or '-'}; draw: {', '.join(m.draw) or 'none'}; "
            f"effects: {', '.join(m.effects) or 'none'}; gradient: {m.gradient}; "
            f"backdrops: {', '.join(m.backdrops) or 'none'}; "
            f"avoid: {m.avoid}; feel: {m.feel}")
    return "\n".join(lines)
