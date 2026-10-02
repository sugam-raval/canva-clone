"""Draft storage: generated templates waiting for review in `lidojs_templates/drafts/`.

Each draft is three files, all named after the template:

    template_<id>.json              the raw Lido export (what gets moved into the corpus)
    previews/template_<id>.png      a screenshot of it (best effort: needs Chrome)
    template_<id>.info.json         how it was made — prompt, idea, colours, fonts,
                                    photo subjects, check results — for the UI

The folder is never read by matching; a draft only becomes a real template when it is
moved into `lidojs_templates/` and onboarded with `make lido-add`.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.lido_create.brief import DIRECTIONS, design_from_brief
from app.lido_create.kit import CORPUS_DIR, DRAFTS_DIR, Design, Photo, Variant, photo_pool
from app.lido_create.lido import to_lido
from app.lido_create.photos import GENERATED_TAG, PhotoSource, configured_source, resolve_photos
from app.lido_create.render import screenshot

log = structlog.get_logger(__name__)

FIRST_ID = 90001  # generated templates live in their own id range, clear of real exports
DRAFT_NAME = re.compile(r"template_(\d+)")
_id_lock = asyncio.Lock()


def photo_source() -> PhotoSource:
    """The one place that decides where new templates' photos come from
    (LIDO_DRAFT_PHOTOS: cache | generate — see `photos.configured_source`)."""
    return configured_source()


def used_ids() -> set[int]:
    ids = set()
    # the drafts folder normally sits inside the corpus; scanned on its own too in case
    # it has been pointed elsewhere
    for p in [*CORPUS_DIR.rglob("template_*"), *DRAFTS_DIR.rglob("template_*")]:
        m = DRAFT_NAME.fullmatch(p.name.split(".")[0])
        if m:
            ids.add(int(m.group(1)))
    return ids


def next_ids(count: int, start: int = FIRST_ID) -> list[int]:
    taken, out, n = used_ids(), [], start
    while len(out) < count:
        if n not in taken:
            out.append(n)
        n += 1
    return out


def _paths(tid: int, out: Path | None = None) -> tuple[Path, Path, Path]:
    out = out or DRAFTS_DIR  # read at call time, so tests can point it elsewhere
    return (out / f"template_{tid}.json", out / "previews" / f"template_{tid}.png",
            out / f"template_{tid}.info.json")


def save_draft(design: Design, v: Variant, tid: int, *, out: Path | None = None,
               photos: list[Photo] | None = None, preview: bool = True,
               info: dict | None = None) -> dict:
    """Write the template, its preview and its info file; return the info."""
    doc = to_lido(design, v, photos)
    path, png, info_path = _paths(tid, out)
    png.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    shot = preview and screenshot(doc[0]["layers"], png)
    record = {
        "id": f"template_{tid}",
        "createdAt": datetime.now(UTC).isoformat(),
        "source": design.recipe.split(":")[0] if ":" in design.recipe else "recipe",
        "layout": design.recipe,
        "theme": design.theme,
        "palette": design.palette,
        "fonts": design.fonts,
        "mirrored": design.mirrored,
        "textCount": sum(e.kind == "text" for e in design.elements),
        "photoSubjects": [e.subject for e in design.elements
                          if e.kind == "photo" and e.subject],
        "hasPreview": bool(shot),
        "problems": [],
        **(info or {}),
    }
    info_path.write_text(json.dumps(record, indent=2) + "\n")
    return record


def _record(tid: int, out: Path | None) -> dict:
    path, png, info_path = _paths(tid, out)
    if info_path.is_file():
        record = json.loads(info_path.read_text())
    else:  # made before info files existed, or copied in by hand
        record = {"id": path.stem, "source": "manual", "problems": [],
                  "createdAt": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()}
    record["hasPreview"] = png.is_file()
    return record


def list_drafts(out: Path | None = None) -> list[dict]:
    """Every draft, newest first."""
    folder = out or DRAFTS_DIR
    records = [_record(int(m.group(1)), out) for p in folder.glob("template_*.json")
               if (m := DRAFT_NAME.fullmatch(p.stem))]
    return sorted(records, key=lambda r: r.get("createdAt", ""), reverse=True)


def draft_id(name: str) -> int:
    m = DRAFT_NAME.fullmatch(name)
    if not m:
        raise ValueError(f"not a draft id: {name!r}")
    return int(m.group(1))


def get_draft(name: str, out: Path | None = None) -> dict | None:
    tid = draft_id(name)
    path = _paths(tid, out)[0]
    if not path.is_file():
        return None
    return {**_record(tid, out), "document": json.loads(path.read_text())}


def preview_path(name: str, out: Path | None = None) -> Path | None:
    png = _paths(draft_id(name), out)[1]
    return png if png.is_file() else None


def delete_draft(name: str, out: Path | None = None) -> bool:
    found = False
    for p in _paths(draft_id(name), out):
        if p.is_file():
            p.unlink()
            found = True
    return found


def recent_fingerprints(limit: int = 10) -> list[str]:
    """The notebook: one line per recent prompt-designed draft, newest first."""
    return [r["fingerprint"] for r in list_drafts() if r.get("fingerprint")][:limit]


def _fallbacks(source: PhotoSource, photos: list[Photo]) -> int:
    """How many photos a generating source had to fill from the cache instead."""
    if source.name != "generated":
        return 0
    return sum(GENERATED_TAG not in p.tags for p in photos)


async def _plans(prompt: str, variations: int, rng: random.Random) -> list:
    """One art-director plan per variation, made one after another so each knows which
    layouts the others took. A failed plan falls back to designing without one."""
    from app.lido_create.plan import make_plan

    recent = await asyncio.to_thread(recent_fingerprints)
    plans: list = []
    taken: list[str] = []
    for i in range(variations):
        try:
            # with several variations, at least one is a free invention
            free = True if variations > 1 and i == variations - 1 else None
            plan = await make_plan(prompt, recent=recent, avoid_layouts=taken, free=free,
                                   rng=random.Random(rng.random()))
            taken.append(plan.layout)
            plans.append(plan)
        except Exception as exc:  # noqa: BLE001 — the designer can still work without it
            log.warning("lido.drafts.plan_failed", error=str(exc)[:300])
            plans.append(None)
    return plans


async def create_from_prompt(prompt: str, *, variations: int = 1,
                             source: PhotoSource | None = None) -> list[dict]:
    """Design `variations` templates from one prompt and save them as drafts: the art
    director plans each one (fast), then the designers build them in parallel."""
    from app.lido_create.plan import fingerprint

    source = source or photo_source()
    photos = await asyncio.to_thread(photo_pool)
    if not photos:
        raise RuntimeError("no placeholder photos found in lidojs_templates/")
    rng = random.Random()
    plans = await _plans(prompt, variations, rng)
    fallback_directions = rng.sample(DIRECTIONS, variations)
    outcomes = await asyncio.gather(*(
        design_from_brief(prompt, photos, plan=plan, rng=random.Random(rng.random()),
                          direction=None if plan else fallback_directions[i])
        for i, plan in enumerate(plans)), return_exceptions=True)
    done = [(o, plans[i]) for i, o in enumerate(outcomes) if not isinstance(o, BaseException)]
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    if not done:
        raise failures[0]  # every variation failed: report why
    for exc in failures:  # some did: keep the ones that worked
        log.warning("lido.drafts.variation_failed", error=str(exc)[:300])

    # every photo of every variation at once: generated ones take a while each
    chosen_all = await asyncio.gather(*(resolve_photos(r.design, r.variant, source)
                                        for r, _ in done))
    saved = []
    for (r, plan), chosen in zip(done, chosen_all):
        async with _id_lock:
            tid = next_ids(1)[0]
            # claim the id before the slow screenshot, so a parallel request can't take it
            _paths(tid)[0].write_text("[]")
        plan_info = {"plan": plan.model_dump(), "fingerprint": fingerprint(plan),
                     "planLayout": plan.layout} if plan else {}
        record = await asyncio.to_thread(
            save_draft, r.design, r.variant, tid, photos=chosen,
            info={"source": "brief", "prompt": prompt, "name": r.name, "idea": r.idea,
                  "direction": r.direction, "attempts": r.attempts, "colors": r.colors,
                  "features": r.features, **plan_info,
                  "photoSource": source.name, "photoFallbacks": _fallbacks(source, chosen),
                  "problems": r.errors})
        saved.append({**record, "document": json.loads(_paths(tid)[0].read_text())})
    return saved
