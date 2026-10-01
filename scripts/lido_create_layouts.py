#!/usr/bin/env python3
"""Generate new Lido.js post templates (raw exports, no `meta`) plus preview screenshots,
into lidojs_templates/drafts/ for review. How it works: docs/AI_TEMPLATE_GENERATION.md.

Each template is a layout recipe (or, with --ai, a layout the LLM invents) dressed in a
palette, a font pairing and a copy theme, optionally mirrored. Every one must pass the
mechanical design checks in backend/app/lido_create/check.py; a combination that fails is
discarded and another is tried.

    python scripts/lido_create_layouts.py                  # 5 new drafts from the recipes
    python scripts/lido_create_layouts.py --count 10 --seed 7
    python scripts/lido_create_layouts.py --recipe arch_showcase --theme beauty --count 3
    python scripts/lido_create_layouts.py --palette plum-coral --fonts modern-serif
    python scripts/lido_create_layouts.py --ai --count 2   # LLM-invented layouts
    python scripts/lido_create_layouts.py --ai --idea "testimonial quote with a portrait"
    python scripts/lido_create_layouts.py --list           # recipes, palettes, fonts, themes

After review, move a keeper into the corpus and onboard it as usual:

    mv lidojs_templates/drafts/template_N.json lidojs_templates/
    mv lidojs_templates/drafts/previews/template_N.png lidojs_templates/previews/
    make lido-add TEMPLATE=template_N KIND=post
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.lido_create.check import validate
from app.lido_create.drafts import FIRST_ID, next_ids, save_draft
from app.lido_create.kit import (
    DRAFTS_DIR,
    FONT_SETS,
    FONT_SETS_BY_NAME,
    PALETTES,
    PALETTES_BY_NAME,
    THEMES,
    THEMES_BY_NAME,
    Canvas,
    Design,
    Variant,
    photo_pool,
    theme_photo_count,
)
from app.lido_create.recipes import RECIPES, mirror
from app.lido_create.render import browser, overview


def build(recipe: str, v: Variant, mirrored: bool) -> Design:
    c = Canvas(v)
    RECIPES[recipe].build(c)
    d = Design(recipe=recipe, theme=v.theme.name, palette=v.palette.name,
               fonts=v.fonts.name, background=c.background, elements=c.els)
    return mirror(d) if mirrored else d


def signature(d: Design) -> str:
    return f"{d.recipe}|{d.theme}|{d.palette}|{d.fonts}|{int(d.mirrored)}"


def photos_needed(recipe: str, photos) -> int:
    probe = Canvas(Variant(PALETTES[0], FONT_SETS[0], THEMES[0], random.Random(0), photos))
    RECIPES[recipe].build(probe)
    return sum(e.kind == "photo" for e in probe.els)


def _fresh(rng: random.Random, options: list, used: set[str]):
    """A random option not used yet in this batch (all of them once every one has been)."""
    return rng.choice([o for o in options if o.name not in used] or options)


def from_recipes(args, rng: random.Random, photos, history: set[str], count: int):
    """Yield `count` passing designs, cycling through recipes, palettes, fonts and themes
    so a batch varies."""
    recipes = args.recipe or list(RECIPES)
    needed = {r: photos_needed(r, photos) for r in recipes}
    order: list[str] = []
    made = 0
    used: dict[str, set[str]] = {"palette": set(), "fonts": set(), "theme": set()}
    for _ in range(count * 40):
        if made == count:
            return
        if not order:
            order = rng.sample(recipes, len(recipes))
        recipe = order[0]
        # a theme only dresses a recipe it has enough matching photos for (no portrait
        # paired with a plate of food), unless the theme was asked for explicitly
        themes = [t for t in THEMES if theme_photo_count(t, photos) >= needed[recipe]]
        v = Variant(
            PALETTES_BY_NAME[args.palette] if args.palette
            else _fresh(rng, PALETTES, used["palette"]),
            FONT_SETS_BY_NAME[args.fonts] if args.fonts
            else _fresh(rng, FONT_SETS, used["fonts"]),
            THEMES_BY_NAME[args.theme] if args.theme
            else _fresh(rng, themes or THEMES, used["theme"]),
            rng, photos)
        mirrored = RECIPES[recipe].mirrorable and rng.random() < 0.5
        design = build(recipe, v, mirrored)
        if signature(design) in history:
            continue
        errors = validate(design, v)
        if errors:
            if args.verbose:
                print(f"    rejected {signature(design)}: {errors[0]}")
            continue
        order.pop(0)
        used["palette"].add(v.palette.name)
        used["fonts"].add(v.fonts.name)
        used["theme"].add(v.theme.name)
        made += 1
        yield design, v
    print(f"  only {made} of {count} could be made — every other combination failed the "
          "checks (loosen --recipe/--theme/--palette/--fonts, or rerun with --verbose)")


async def from_ai(args, rng: random.Random, photos, count: int):
    """LLM-invented layouts, each dressed in a different palette/fonts/theme from the
    same rotation the recipes use (the model only designs the layout)."""
    from app.lido_create.ai import invent
    avoid: list[str] = []
    used: dict[str, set[str]] = {"palette": set(), "fonts": set(), "theme": set()}
    themes = [t for t in THEMES if theme_photo_count(t, photos) >= 1] or THEMES
    for i in range(count):
        v = Variant(
            PALETTES_BY_NAME[args.palette] if args.palette
            else _fresh(rng, PALETTES, used["palette"]),
            FONT_SETS_BY_NAME[args.fonts] if args.fonts
            else _fresh(rng, FONT_SETS, used["fonts"]),
            THEMES_BY_NAME[args.theme] if args.theme else _fresh(rng, themes, used["theme"]),
            rng, photos)
        for key, value in (("palette", v.palette), ("fonts", v.fonts), ("theme", v.theme)):
            used[key].add(value.name)
        print(f"  asking the LLM for layout {i + 1}/{count} "
              f"({v.theme.name}, {v.palette.name}, {v.fonts.name})...")
        design, errors, idea = await invent(v, hint=args.idea, avoid=avoid,
                                            repairs=args.repairs)
        avoid.append(idea)
        if errors and not args.keep_failed:
            print("    still failing after repairs, skipped:\n      - "
                  + "\n      - ".join(errors))
            continue
        yield design, v, errors


def save(design: Design, v: Variant, tid: int, out: Path, preview: bool,
         errors: list[str] | None = None) -> Path | None:
    record = save_draft(design, v, tid, out=out, preview=preview,
                        info={"problems": errors or []})
    texts = record["textCount"]
    flag = f"  ({len(errors)} unresolved problem(s))" if errors else ""
    print(f"  template_{tid}  {design.recipe:<18} {design.theme:<10} {design.palette:<17} "
          f"{design.fonts:<17} {'mirrored ' if design.mirrored else ''}{texts} texts{flag}")
    png = out / "previews" / f"template_{tid}.png"
    return png if record["hasPreview"] else None


def list_options() -> None:
    print("recipes:")
    for r in RECIPES.values():
        print(f"  {r.name:<16} {r.description}")
    print("\npalettes:  " + ", ".join(p.name for p in PALETTES))
    print("fonts:     " + ", ".join(f"{f.name} ({f.display})" for f in FONT_SETS))
    print("themes:    " + ", ".join(t.name for t in THEMES))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=5, help="templates to make (default 5)")
    parser.add_argument("--recipe", action="append", choices=list(RECIPES),
                        help="only these layout recipes (repeatable)")
    parser.add_argument("--theme", choices=[t.name for t in THEMES])
    parser.add_argument("--palette", choices=[p.name for p in PALETTES])
    parser.add_argument("--fonts", choices=[f.name for f in FONT_SETS])
    parser.add_argument("--seed", type=int, help="same seed = same batch")
    parser.add_argument("--ai", action="store_true",
                        help="let the LLM invent new layouts instead of using the recipes")
    parser.add_argument("--idea", help="with --ai: a short brief for the layout idea")
    parser.add_argument("--repairs", type=int, default=2,
                        help="with --ai: repair rounds for a layout that fails the checks")
    parser.add_argument("--keep-failed", action="store_true",
                        help="with --ai: save a layout even if repairs didn't fix it")
    parser.add_argument("--start-id", type=int, default=FIRST_ID)
    parser.add_argument("--out", type=Path, default=DRAFTS_DIR)
    parser.add_argument("--no-preview", action="store_true", help="skip the screenshots")
    parser.add_argument("--verbose", action="store_true", help="show rejected combinations")
    parser.add_argument("--list", action="store_true", help="list the options and exit")
    args = parser.parse_args()

    if args.list:
        list_options()
        return 0
    preview = not args.no_preview
    if preview and browser() is None:
        print("no Chrome/Chromium found — writing templates without previews")
        preview = False

    rng = random.Random(args.seed)
    (args.out / "previews").mkdir(parents=True, exist_ok=True)
    # Combinations already generated into this folder, so a rerun never repeats one.
    history_file = args.out / ".history.json"
    history = set(json.loads(history_file.read_text())) if history_file.is_file() else set()
    print("collecting placeholder photos from the corpus...")
    photos = photo_pool()
    if not photos:
        print("no usable photos found in lidojs_templates/", file=sys.stderr)
        return 1

    ids = iter(next_ids(args.count, args.start_id))
    pngs: list[Path] = []
    print(f"writing to {args.out}/")

    if args.ai:
        async def run() -> None:
            async for design, v, errors in from_ai(args, rng, photos, args.count):
                png = save(design, v, next(ids), args.out, preview, errors)
                pngs.extend([png] if png else [])
        asyncio.run(run())
    else:
        for design, v in from_recipes(args, rng, photos, history, args.count):
            history.add(signature(design))
            png = save(design, v, next(ids), args.out, preview)
            pngs.extend([png] if png else [])
        history_file.write_text(json.dumps(sorted(history), indent=1))

    if pngs:
        overview(pngs, args.out / "overview.png")
        print(f"\npreviews in {args.out / 'previews'}; whole batch at a glance: "
              f"{args.out / 'overview.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
