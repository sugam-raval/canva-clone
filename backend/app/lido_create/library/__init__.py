"""THE DESIGN LIBRARY: everything "design from scratch" can choose from, in one folder.

    shapes.yaml  frames.yaml  crops.yaml  draw.yaml        one line per item —
    effects.yaml  bullets.yaml  line_ends.yaml              name: "hint for the AI";
    backdrops.yaml                                          comment a line out and the
                                                            AI can never use it
    layouts.yaml     post structures the art director picks from
    moods.yaml       which frames/shapes/strokes/effects/backdrops fit each feeling
    icons.yaml       line icons beside contact lines and inside solid bullets
    frame_outlines.json   the frames' Lido outlines (geometry, not a menu)

How to remove or add each kind of thing: README.md in this folder.

The YAML files are the MENU; the drawing code stays in Python (shapes.py, draw.py,
lists.py, backdrops.py, lido.py). `enabled()` joins the two: what a menu lists, checked
against what the code can draw — so a misspelt or undrawable name stops the backend at
startup with a message, instead of quietly never being used.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from functools import cache
from pathlib import Path

import yaml

# this folder; LIDO_LIBRARY_DIR points at a copy instead (the tests use it to switch
# items off without touching these files)
LIBRARY = Path(os.environ.get("LIDO_LIBRARY_DIR") or Path(__file__).parent)

# the one-line-per-item menus (each `<kind>.yaml` in this folder)
MENUS = ("shapes", "frames", "crops", "draw", "effects", "bullets", "line_ends", "backdrops")


class LibraryError(ValueError):
    """A library file that can't be used as written."""


def path(name: str) -> Path:
    """A file in the library folder."""
    return LIBRARY / name


def load_yaml(name: str):
    """A library YAML file, with a readable error when it isn't valid YAML."""
    file = path(name)
    try:
        return yaml.safe_load(file.read_text())
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        raise LibraryError(
            f"library/{name}{where} is not valid YAML ({getattr(exc, 'problem', exc)}) — "
            "a text containing ': ' or '#' must be wrapped in double quotes") from exc


@cache
def menu(kind: str) -> dict[str, str]:
    """`library/<kind>.yaml` as {name: hint}, in file order — commented-out lines are
    simply not there."""
    data = load_yaml(f"{kind}.yaml") or {}
    if not isinstance(data, dict):
        raise LibraryError(f"library/{kind}.yaml must be `name: \"hint\"` lines, one per item")
    return {str(name): str(hint or "") for name, hint in data.items()}


def enabled(kind: str, drawable: Iterable[str]) -> tuple[str, ...]:
    """The names `library/<kind>.yaml` lists, after checking the code can draw each one
    (`drawable`). A name it can't is a mistake — a typo, or a new item whose drawing
    code isn't written yet — and stops the backend here, saying which."""
    known = set(drawable)
    names = tuple(menu(kind))
    unknown = [n for n in names if n not in known]
    if unknown:
        raise LibraryError(
            f"library/{kind}.yaml lists {', '.join(map(repr, unknown))}, which the code "
            f"can't draw (only: {', '.join(sorted(known))}). Fix the spelling, or add "
            f"its drawing code first — see library/README.md.")
    return names


def hint(kind: str, name: str) -> str:
    """The hint `library/<kind>.yaml` gives `name` (empty if it gives none)."""
    return menu(kind).get(name, "")
