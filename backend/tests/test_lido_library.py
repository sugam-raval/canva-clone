"""The design library (app/lido_create/library/): commenting a line out of a menu takes
that item away from the AI everywhere — its instructions, the plan, the reply schema —
and a name the code can't draw stops the app with a message."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.lido_create import library

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture
def copy_of_library(tmp_path):
    """A copy of the library to edit, and a way to run Python against it."""
    lib = tmp_path / "library"
    shutil.copytree(library.LIBRARY, lib, ignore=shutil.ignore_patterns("*.py", "__pycache__"))

    def run(code: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "LIDO_LIBRARY_DIR": str(lib)}
        return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env,
                              capture_output=True, text=True, timeout=120, check=False)

    return lib, run


def _comment_out(file: Path, name: str) -> None:
    text = file.read_text()
    assert f"\n{name}: " in text
    file.write_text(text.replace(f"\n{name}: ", f"\n# {name}: "))


def test_every_menu_lists_only_what_the_code_can_draw():
    from app.lido_create import backdrops, kit

    assert set(library.MENUS) == {p.stem for p in library.LIBRARY.glob("*.yaml")} - {
        "layouts", "moods", "icons"}
    assert kit.ENABLED_SHAPES and kit.ENABLED_FRAMES and kit.ENABLED_CROPS
    assert backdrops.STYLES
    for kind in library.MENUS:
        assert all(library.hint(kind, name) for name in library.menu(kind)), kind


def test_the_ai_s_schema_and_instructions_offer_exactly_the_menus():
    from app.adapters.openai_schema import response_format
    from app.lido_create import ai, brief, kit

    schema = json.dumps(response_format(brief.BriefDesign))
    for name in kit.ENABLED_SHAPES + kit.ENABLED_DRAW + kit.ENABLED_BULLETS:
        assert f'"{name}"' in schema
    for name in kit.ENABLED_SHAPES + kit.ENABLED_CROPS + kit.ENABLED_EFFECTS:
        assert name in ai.SYSTEM
    assert library.hint("shapes", "chevron") in ai.SYSTEM


def test_a_commented_out_item_is_gone_for_the_ai(copy_of_library):
    lib, run = copy_of_library
    _comment_out(lib / "shapes.yaml", "chevron")
    _comment_out(lib / "frames.yaml", "torn_paper")
    _comment_out(lib / "draw.yaml", "zigzag")
    _comment_out(lib / "backdrops.yaml", "spotlight")
    result = run("""
import json
from app.adapters.openai_schema import response_format
from app.lido_create import ai, brief, catalog, kit, plan, backdrops
schema = json.dumps(response_format(brief.BriefDesign))
print(json.dumps({
    "schema": [n for n in ("chevron", "torn_paper", "zigzag") if f'"{n}"' in schema],
    # the menu sections of the designer's instructions (its general design advice may
    # still name an example; the schema is what makes it impossible to use)
    "designer": [n for n in ("chevron", "torn_paper", "zigzag")
                 if f"- {n} (" in ai.SYSTEM or f" {n} (" in ai.SYSTEM.split("FRAMES (photo")[1]],
    "director": [n for n in ("chevron", "torn_paper", "zigzag", "spotlight")
                 if n in plan.SYSTEM.split("NAMES YOU MAY USE")[1]],
    "moods": "chevron" in catalog.mood_guide(),
    "backdrops": list(backdrops.STYLES),
    "still_drawable": "chevron" in kit.SHAPES,
}))
""")
    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout.strip().splitlines()[-1])
    assert seen["schema"] == [] and seen["designer"] == [] and seen["director"] == []
    assert seen["moods"] is False
    assert "spotlight" not in seen["backdrops"]
    assert seen["still_drawable"]  # the code can still draw it; the AI just can't pick it


def test_a_misspelt_name_stops_the_app_with_a_message(copy_of_library):
    lib, run = copy_of_library
    with (lib / "shapes.yaml").open("a") as f:
        f.write('chevronn: "a typo"\n')
    result = run("import app.lido_create.kit")
    assert result.returncode != 0
    assert "library/shapes.yaml lists 'chevronn', which the code can't draw" in result.stderr


def test_a_menu_that_is_not_name_hint_lines_is_reported(copy_of_library):
    lib, run = copy_of_library
    (lib / "draw.yaml").write_text("- underline\n- circle\n")
    result = run("import app.lido_create.kit")
    assert result.returncode != 0
    assert "library/draw.yaml must be `name: \"hint\"` lines" in result.stderr


def test_switching_off_every_draw_preset_drops_hand_drawn_accents(copy_of_library):
    lib, run = copy_of_library
    for name in library.menu("draw"):
        _comment_out(lib / "draw.yaml", name)
    result = run("""
from app.lido_create import check, kit
print(kit.DrawOut in kit._OUT_KINDS, "draw" in check.FEATURE_FAMILIES)
""")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["False", "False"]
