"""Draft storage: generated templates waiting for review, in the `lido_drafts` table
(infra/initdb/006_lido_drafts.sql). Nothing is written to disk.

Each draft is one row, known everywhere by the table's own `id`:

    document     the raw Lido export (what gets exported into the corpus)
    preview_url  a screenshot of it (best effort: needs Chrome), uploaded to the object
                 store under public/lido-generated/drafts/<id>/
    info         how it was made — prompt, idea, colours, fonts, photo subjects, check
                 results — for the review UI

Drafts are never read by matching; a draft only becomes a real template when it is
exported into `lidojs_templates/` (`make lido-draft-export ID=<id>`, which gives it a
free `template_<n>` name) and onboarded with `make lido-add`.
"""

from __future__ import annotations

import asyncio
import random
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import structlog
from botocore.exceptions import BotoCoreError, ClientError

from app.db import repo
from app.db.session import session_scope
from app.lido_corpus.generated import upload_asset
from app.lido_corpus.palette import parse_palette
from app.lido_create.brief import DIRECTIONS, brand_palette, design_from_brief
from app.lido_create.kit import Design, Photo, Variant, photo_pool
from app.lido_create.lido import to_lido
from app.lido_create.photos import (
    GENERATED_TAG,
    PhotoPrefetch,
    PhotoSource,
    configured_source,
    resolve_photos,
)
from app.lido_create.render import screenshot

log = structlog.get_logger(__name__)

ASSET_FOLDER = "drafts"  # previews land in public/lido-generated/drafts/<id>/


def photo_source() -> PhotoSource:
    """The one place that decides where new templates' photos come from
    (LIDO_DRAFT_PHOTOS: cache | generate — see `photos.configured_source`)."""
    return configured_source()


# --------------------------------------------------------------------------------------
# Where drafts are kept: the database. Behind a small interface so tests can keep them
# in memory.
# --------------------------------------------------------------------------------------


class DraftStore(Protocol):
    async def insert(self, row: dict[str, Any]) -> int: ...

    async def set_preview(self, draft_id: int, url: str) -> None: ...

    async def set_timing(self, draft_id: int, timing: dict[str, int]) -> None: ...

    async def list(self, limit: int | None) -> list[dict[str, Any]]: ...

    async def get(self, draft_id: int) -> dict[str, Any] | None: ...

    async def delete(self, draft_id: int) -> bool: ...

    async def fingerprints(self, limit: int) -> list[str]: ...


class DbDraftStore:
    """`lido_drafts` in Postgres. Each call is its own transaction: a draft is saved the
    moment it is made, whatever happens to the other variations of the same request."""

    async def insert(self, row: dict[str, Any]) -> int:
        async with session_scope() as s:
            return await repo.insert_lido_draft(s, **row)

    async def set_preview(self, draft_id: int, url: str) -> None:
        async with session_scope() as s:
            await repo.set_lido_draft_preview(s, draft_id, url)

    async def set_timing(self, draft_id: int, timing: dict[str, int]) -> None:
        async with session_scope() as s:
            await repo.set_lido_draft_timing(s, draft_id, timing)

    async def list(self, limit: int | None) -> list[dict[str, Any]]:
        async with session_scope() as s:
            return await repo.list_lido_drafts(s, limit=limit)

    async def get(self, draft_id: int) -> dict[str, Any] | None:
        async with session_scope() as s:
            return await repo.get_lido_draft(s, draft_id)

    async def delete(self, draft_id: int) -> bool:
        async with session_scope() as s:
            return await repo.delete_lido_draft(s, draft_id)

    async def fingerprints(self, limit: int) -> list[str]:
        async with session_scope() as s:
            return await repo.recent_draft_fingerprints(s, limit)


_STORE = DbDraftStore()


def store() -> DraftStore:
    return _STORE


def _record(row: dict[str, Any]) -> dict[str, Any]:
    """A stored row as the review UI's record (the camelCase LidoDraftInfo fields)."""
    created = row["created_at"]
    record = {
        **(row.get("info") or {}),
        "id": row["id"],
        "createdAt": created.isoformat() if isinstance(created, datetime) else created,
        "source": row["source"],
        "prompt": row["prompt"] or None,
        "name": row["name"] or None,
        "fingerprint": row["fingerprint"],
        "previewUrl": row["preview_url"],
        "hasPreview": bool(row["preview_url"]),
        "generationMs": row.get("generation_ms"),
        "timing": row.get("timing") or {},
    }
    record.setdefault("problems", [])
    if "document" in row:
        record["document"] = row["document"]
    return record


# --------------------------------------------------------------------------------------
# Saving, reading, deleting
# --------------------------------------------------------------------------------------


def upload_preview(draft_id: int, data: bytes) -> str | None:
    """Upload a draft's screenshot; its public URL, or None when the store is down.
    Blocking (boto3); call it off the event loop."""
    try:
        return upload_asset(f"{ASSET_FOLDER}/{draft_id}", "preview", data)
    except (BotoCoreError, ClientError, OSError) as exc:
        log.warning("lido.drafts.preview_upload_failed", draft=draft_id, error=str(exc)[:300])
        return None


def _preview(doc: list[dict], draft_id: int) -> str | None:
    """Screenshot the document and upload it; None without Chrome or an object store."""
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "preview.png"
        if not screenshot(doc[0]["layers"], png):
            return None
        return upload_preview(draft_id, png.read_bytes())


def _ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def design_info(design: Design) -> dict[str, Any]:
    """What a design itself says about how it was made."""
    return {
        "source": design.recipe.split(":")[0] if ":" in design.recipe else "recipe",
        "layout": design.recipe,
        "theme": design.theme,
        "palette": design.palette,
        "fonts": design.fonts,
        "mirrored": design.mirrored,
        "textCount": sum(e.kind == "text" for e in design.elements),
        "photoSubjects": [e.subject for e in design.elements
                          if e.kind == "photo" and e.subject],
        "problems": [],
    }


async def save_draft(design: Design, v: Variant, *, photos: list[Photo] | None = None,
                     logo_url: str | None = None, preview: bool = True,
                     info: dict | None = None, timing: dict[str, int] | None = None,
                     started: float | None = None) -> dict:
    """Store the template as a new draft, then its preview (stored under the draft's
    id, so it is taken once the row exists); return its record (with the document).

    `timing`: how long the steps before this took (ms); with `started` (the request's
    `time.perf_counter()`), the save time and the total are added and stored too."""
    drafts = store()
    save_started = time.perf_counter()
    doc = to_lido(design, v, photos, logo_url=logo_url)
    meta = {**design_info(design), **(info or {})}
    source = meta.pop("source")
    prompt, name, fingerprint = meta.pop("prompt", ""), meta.pop("name", ""), \
        meta.pop("fingerprint", None)
    row = {"source": source, "prompt": prompt or "", "name": name or "",
           "fingerprint": fingerprint, "preview_url": None, "info": meta,
           "document": doc, "created_at": datetime.now(UTC)}
    draft_id = await drafts.insert(row)
    if preview and (url := await asyncio.to_thread(_preview, doc, draft_id)):
        await drafts.set_preview(draft_id, url)
        row["preview_url"] = url
    if timing is not None and started is not None:
        timing = {**timing, "saveMs": _ms_since(save_started), "totalMs": _ms_since(started)}
        await drafts.set_timing(draft_id, timing)
        log.info("lido.drafts.timing", draft=draft_id, **timing)
        row.update(timing=timing, generation_ms=timing["totalMs"])
    return _record({**row, "id": draft_id})


async def list_drafts(limit: int | None = 60) -> list[dict]:
    """Every draft (up to `limit`), newest first, without documents."""
    return [_record(r) for r in await store().list(limit)]


async def get_draft(draft_id: int) -> dict | None:
    row = await store().get(draft_id)
    return _record(row) if row else None


async def delete_draft(draft_id: int) -> bool:
    """Remove the row. Its preview and photos stay in the object store: the document may
    already have been exported into the corpus, which still points at them."""
    return await store().delete(draft_id)


async def recent_fingerprints(limit: int = 10) -> list[str]:
    """The notebook: one line per recent prompt-designed draft, newest first."""
    return await store().fingerprints(limit)


# --------------------------------------------------------------------------------------
# Designing from a prompt
# --------------------------------------------------------------------------------------


def _fallbacks(source: PhotoSource, photos: list[Photo]) -> int:
    """How many photos a generating source had to fill from the cache instead."""
    if source.name != "generated":
        return 0
    return sum(GENERATED_TAG not in p.tags for p in photos)


def _with_logo(plan):
    """The client gave a logo: the plan places one, whatever the brief seemed to say."""
    plan.logo = True
    plan.exclude = [x for x in plan.exclude if x != "logo"]
    return plan


async def _plans(prompt: str, variations: int, rng: random.Random,
                 logo: bool = False, on_plan=None) -> list:
    """One art-director plan per variation, made one after another so each knows which
    layouts the others took. A failed plan falls back to designing without one.
    `on_plan(i, plan)` hears about each plan the moment it is written."""
    from app.lido_create.plan import make_plan

    recent = await recent_fingerprints()
    plans: list = []
    taken: list[str] = []
    for i in range(variations):
        try:
            # with several variations, at least one is a free invention
            free = True if variations > 1 and i == variations - 1 else None
            plan = await make_plan(prompt, recent=recent, avoid_layouts=taken, free=free,
                                   rng=random.Random(rng.random()))
            taken.append(plan.layout)
            plans.append(_with_logo(plan) if logo else plan)
            if on_plan is not None:
                on_plan(i, plan)
        except Exception as exc:  # noqa: BLE001 — the designer can still work without it
            log.warning("lido.drafts.plan_failed", error=str(exc)[:300])
            plans.append(None)
    return plans


Progress = Callable[[dict[str, Any]], None]


async def create_from_prompt(prompt: str, *, variations: int = 1,
                             source: PhotoSource | None = None,
                             palette: list[str] | None = None,
                             logo_url: str | None = None,
                             on_progress: Progress | None = None) -> list[dict]:
    """Design `variations` templates from one prompt and save them as drafts: the art
    director plans each one (fast), then each variation is designed, gets its photos and
    is saved on its own — a quick one doesn't wait for a slow one.

    `palette`: up to 4 brand colours (#rrggbb, first = primary), the same palette "fill a
    template" takes; every variation is drawn in exactly these (`brief.brand_palette`
    maps them onto the design's colour roles) instead of colours the model picks.
    `logo_url`: the client's logo, placed in every variation's logo element (each one
    gets a logo).

    Generated photos don't wait for the design: each variation's start rendering as soon
    as its plan is written, and any a draft adds while repairs run (`PhotoPrefetch`).

    `on_progress` hears each step as it starts — {"stage": planning | designing |
    repairing | photos | saving, "variation": i, …} — and {"stage": "draft",
    "variation": i, "draft": record} the moment a variation is saved."""
    from app.lido_create.plan import fingerprint

    emit = on_progress or (lambda event: None)
    started = time.perf_counter()
    source = source or photo_source()
    photos = await asyncio.to_thread(photo_pool)
    if not photos:
        raise RuntimeError("no placeholder photos found in lidojs_templates/")
    rng = random.Random()
    brand = brand_palette(parse_palette(palette)) if palette else None
    prefetches = [PhotoPrefetch(source) for _ in range(variations)]
    emit({"stage": "planning"})
    plan_started = time.perf_counter()
    plans = await _plans(prompt, variations, rng, logo=bool(logo_url),
                         on_plan=lambda i, plan: prefetches[i].from_plan(plan))
    plan_ms = _ms_since(plan_started)
    fallback_directions = rng.sample(DIRECTIONS, variations)
    brand_info = {"brandPalette": palette} if palette else {}

    async def variation(i: int, plan, seed: float) -> dict:
        def repairing(attempt: int, problems: int) -> None:
            emit({"stage": "repairing", "variation": i, "attempt": attempt,
                  "problems": problems})

        try:
            emit({"stage": "designing", "variation": i})
            t0 = time.perf_counter()
            r = await design_from_brief(prompt, photos, plan=plan, rng=random.Random(seed),
                                        direction=None if plan else fallback_directions[i],
                                        palette=brand, logo=bool(logo_url),
                                        on_draft=prefetches[i].from_design,
                                        on_repair=repairing)
            design_ms = _ms_since(t0)
            emit({"stage": "photos", "variation": i})
            t0 = time.perf_counter()
            chosen = await resolve_photos(r.design, r.variant, source, prefetches[i])
            photos_ms = _ms_since(t0)
        except BaseException:
            prefetches[i].cancel()
            raise
        emit({"stage": "saving", "variation": i})
        plan_info = {"plan": plan.model_dump(), "fingerprint": fingerprint(plan),
                     "planLayout": plan.layout} if plan else {}
        record = await save_draft(
            r.design, r.variant, photos=chosen, logo_url=logo_url,
            info={"source": "brief", "prompt": prompt, "name": r.name, "idea": r.idea,
                  "direction": r.direction, "attempts": r.attempts, "colors": r.colors,
                  "features": r.features, **plan_info, **r.extras,
                  **brand_info, "logoUrl": logo_url,
                  "photoSource": source.name, "photoFallbacks": _fallbacks(source, chosen),
                  "problems": r.errors},
            timing={"planMs": plan_ms, "designMs": design_ms, "photosMs": photos_ms},
            started=started)
        emit({"stage": "draft", "variation": i, "draft": record})
        return record

    outcomes = await asyncio.gather(*(variation(i, plan, rng.random())
                                      for i, plan in enumerate(plans)),
                                    return_exceptions=True)
    saved = [o for o in outcomes if not isinstance(o, BaseException)]
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    if not saved:
        raise failures[0]  # every variation failed: report why
    for exc in failures:  # some did: keep the ones that worked
        log.warning("lido.drafts.variation_failed", error=str(exc)[:300])
    return saved
