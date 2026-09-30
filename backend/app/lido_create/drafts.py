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
from app.lido_create.photos import CachedPhotos, PhotoSource, resolve_photos
from app.lido_create.render import screenshot

log = structlog.get_logger(__name__)

FIRST_ID = 90001  # generated templates live in their own id range, clear of real exports
DRAFT_NAME = re.compile(r"template_(\d+)")
_id_lock = asyncio.Lock()


def photo_source() -> PhotoSource:
    """The one place that decides where new templates' photos come from."""
    return CachedPhotos()


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


async def create_from_prompt(prompt: str, *, variations: int = 1,
                             source: PhotoSource | None = None) -> list[dict]:
    """Design `variations` templates from one prompt (in parallel, each in a different
    creative direction when there's more than one) and save them as drafts."""
    source = source or photo_source()
    photos = await asyncio.to_thread(photo_pool)
    if not photos:
        raise RuntimeError("no placeholder photos found in lidojs_templates/")
    rng = random.Random()
    directions: list[str | None] = ([None] if variations == 1
                                    else rng.sample(DIRECTIONS, variations))
    outcomes = await asyncio.gather(*(
        design_from_brief(prompt, photos, direction=d, rng=random.Random(rng.random()))
        for d in directions), return_exceptions=True)
    results = [o for o in outcomes if not isinstance(o, BaseException)]
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    if not results:
        raise failures[0]  # every variation failed: report why
    for exc in failures:  # some did: keep the ones that worked
        log.warning("lido.drafts.variation_failed", error=str(exc)[:300])

    saved = []
    for r in results:
        chosen = await resolve_photos(r.design, r.variant, source)
        async with _id_lock:
            tid = next_ids(1)[0]
            # claim the id before the slow screenshot, so a parallel request can't take it
            _paths(tid)[0].write_text("[]")
        record = await asyncio.to_thread(
            save_draft, r.design, r.variant, tid, photos=chosen,
            info={"source": "brief", "prompt": prompt, "name": r.name, "idea": r.idea,
                  "direction": r.direction, "attempts": r.attempts, "colors": r.colors,
                  "photoSource": source.name, "problems": r.errors})
        saved.append({**record, "document": json.loads(_paths(tid)[0].read_text())})
    return saved
