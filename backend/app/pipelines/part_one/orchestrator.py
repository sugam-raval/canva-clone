"""Part One orchestrator — IMPLEMENTATION_PLAN §1, §0.9.

    parse -> retrieve -> compose -> [emit skeleton] -> assets -> harmonise -> solve
          -> assemble

Stages 1-3 are cheap and sequential. Stage 4 is expensive and parallel. Stages 5-6 are
deterministic code, not AI.

The hard requirement (§0.9) is that `doc.skeleton` reaches the client in under 3 s: the
user watches placeholders fill in rather than staring at a spinner. Everything after the
skeleton emit is best-effort — §0.9's degrade rule says a partial design always beats an
error page, so every later stage is wrapped and failures become degraded layers, not
failed requests.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import repo
from app.layout.solver import SolveOpts, solve
from app.pipelines.part_one.art_direction import direct_art, seed_from
from app.pipelines.part_one.assets import AssetOutcome, run_asset_jobs
from app.pipelines.part_one.brief import parse_brief
from app.pipelines.part_one.compose import compose, expand
from app.pipelines.part_one.fit import fit_subjects
from app.pipelines.part_one.harmonize import harmonize
from app.pipelines.part_one.retrieve import retrieve_templates
from app.renderer.core import to_draw_list
from app.renderer.skia_backend import render_webp
from app.schema.brief import DesignBrief
from app.schema.doc import DesignDoc, ShapeStroke, find_layer, replace_layer
from app.schema.events import (
    BriefReady,
    Clarify,
    DocSkeleton,
    DocSolved,
    JobFailed,
    LayerPatch,
    RequestDone,
    RequestFailed,
    RequestStarted,
)
from app.schema.template import TemplateSkeleton
from app.storage import assets as storage
from app.storage.resolver import resolve_for

log = structlog.get_logger(__name__)

Emit = Callable[[object], Awaitable[None]]

PLAN = ["brief.parse", "art.direct", "template.retrieve", "compose.layout",
        "asset.background",
        "asset.subject", "harmonize.palette", "harmonize.contrast", "harmonize.shadow",
        "layout.solve", "doc.assemble", "doc.thumbnail"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class BudgetExceeded(Exception):
    pass


class GenerationResult:
    def __init__(self, doc_ids: list[str], cost_cents: int, brief: DesignBrief | None,
                 clarification: dict | None = None):
        self.doc_ids = doc_ids
        self.cost_cents = cost_cents
        self.brief = brief
        self.clarification = clarification


async def _noop(_event) -> None:
    return None


async def generate(
    session: AsyncSession, *, prompt: str, user_id: str | None, request_id: str,
    count: int = 1, brand_kit: dict | None = None, emit: Emit | None = None,
    allow_clarification: bool = True,
) -> GenerationResult:
    emit = emit or _noop
    settings = get_settings()
    started = time.monotonic()
    cost = 0

    await emit(RequestStarted(requestId=request_id, plan=PLAN))

    # -- 1.1 brief.parse ---------------------------------------------------------------
    brief, brief_cost = await parse_brief(prompt, brand_kit=brand_kit, count=count)
    cost += brief_cost
    await emit(BriefReady(brief=brief))
    await repo.update_generation_request(session, request_id, brief=brief.model_dump(
        by_alias=True, exclude_none=True), state="composing")

    if allow_clarification and brief.needs_clarification is not None:
        await emit(Clarify(requestId=request_id,
                           question=brief.needs_clarification.question,
                           options=brief.needs_clarification.options))
        await repo.update_generation_request(session, request_id, state="awaiting-answer")
        return GenerationResult([], cost, brief, {
            "question": brief.needs_clarification.question,
            "options": brief.needs_clarification.options,
        })

    # -- 1.2 template.retrieve + art.direct --------------------------------------------
    # §1.8: for N variations use N distinct templates, not N seeds of one — the variety
    # users want is layout variety, not noise variety.
    #
    # Art direction decides what this design's imagery is OF, and retrieval decides which
    # layouts could hold it. Neither depends on the other and both are a round trip, so
    # they run together — sequencing them would spend a second of the 3 s skeleton budget
    # for nothing. The seed is the request id, so the same prompt asked twice is directed
    # differently while one request always reproduces (INV-2).
    candidates, (direction, art_cost) = await asyncio.gather(
        retrieve_templates(session, brief, limit=max(3, count)),
        direct_art(brief, seed=seed_from(request_id)),
    )
    cost += art_cost
    log.info("art.direct.ready", scene=direction.scene[:60],
             motifs=direction.motifs.model_dump(exclude_none=True),
             density=direction.density)
    if not candidates:
        await emit(RequestFailed(reason="no template matched this brief"))
        await repo.update_generation_request(session, request_id, state="failed",
                                             error="no template matched")
        return GenerationResult([], cost, brief)

    # -- 1.3 compose.layout ------------------------------------------------------------
    doc_ids: list[str] = []
    docs: list[tuple[DesignDoc, TemplateSkeleton]] = []
    for index in range(min(count, len(candidates))):
        pool = candidates[index:] + candidates[:index]
        output, compose_cost = await compose(brief, pool, direction)
        cost += compose_cost
        skeleton = next((c for c in candidates if c.id == output.template_id), candidates[0])
        doc_id = str(uuid.uuid4())
        doc = expand(skeleton, output, brief, doc_id=doc_id, request_id=request_id,
                     direction=direction)
        docs.append((doc, skeleton))
        doc_ids.append(doc_id)
        await repo.insert_document(session, doc, user_id)

    # §0.9: emit the skeleton NOW. The client renders text, shapes and palette-coloured
    # placeholder rectangles while the expensive work runs.
    for doc, _ in docs:
        await emit(DocSkeleton(doc=doc.model_dump(by_alias=True, exclude_none=True)))
    elapsed = time.monotonic() - started
    log.info("skeleton.emitted", seconds=round(elapsed, 2), docs=len(docs))
    if elapsed > settings.skeleton_deadline_seconds:
        log.warning("skeleton.slow", seconds=round(elapsed, 2),
                    budget=settings.skeleton_deadline_seconds)

    await repo.update_generation_request(session, request_id, state="generating",
                                         doc_id=doc_ids[0] if doc_ids else None,
                                         chosen_template_id=docs[0][1].id if docs else None)

    # -- 1.4 assets, 1.5 harmonise, 1.6 solve, 1.7 assemble ----------------------------
    for doc, skeleton in docs:
        cost += await _finish_document(session, doc, skeleton, user_id, request_id,
                                       emit, budget_remaining=settings
                                       .max_cost_cents_per_request - cost)

    if user_id:
        await repo.add_usage(session, user_id, cost)
    await repo.update_generation_request(session, request_id, state="done",
                                         cost_cents=cost)
    await emit(RequestDone(docId=doc_ids[0] if doc_ids else "", costCents=cost,
                           summary=_summary(docs)))
    log.info("request.done", request_id=request_id, seconds=round(time.monotonic() - started, 2),
             cost_cents=cost)
    return GenerationResult(doc_ids, cost, brief)


def _summary(docs: list[tuple[DesignDoc, TemplateSkeleton]]) -> str:
    if not docs:
        return "No design was produced."
    doc, skeleton = docs[0]
    texts = sum(1 for layer in doc.layers if layer.type == "text")
    images = sum(1 for layer in doc.layers if layer.type == "image")
    degraded = sum(1 for layer in doc.layers if layer.meta.notes.get("degraded"))
    parts = [(f"Built a {doc.canvas.width}×{doc.canvas.height} design from "
              f"{skeleton.name!r} with {texts} editable text layer"
              f"{'s' if texts != 1 else ''} and {images} image layer"
              f"{'s' if images != 1 else ''}.")]
    if degraded:
        parts.append(f"{degraded} image could not be generated and fell back to a "
                     f"solid colour — regenerate it from the layer menu.")
    if len(docs) > 1:
        parts.append(f"{len(docs)} layout variations.")
    return " ".join(parts)


async def _finish_document(session: AsyncSession, doc: DesignDoc,
                           skeleton: TemplateSkeleton, user_id: str | None,
                           request_id: str, emit: Emit, budget_remaining: int) -> int:
    cost = 0

    async def on_result(outcome: AssetOutcome) -> None:
        nonlocal cost
        cost += outcome.cost_cents
        if outcome.error:
            await emit(JobFailed(jobId=outcome.layer_id, type="asset.generate",
                                 recoverable=True, reason=outcome.error))
            _degrade_layer(doc, outcome.layer_id)
            layer, _ = find_layer(doc, outcome.layer_id)
            if layer is not None:
                await emit(LayerPatch(layerId=outcome.layer_id, patch={
                    "placeholderColor": getattr(layer, "placeholder_color", None)
                    or (doc.palette[0] if doc.palette else "#E2E8F0"),
                    "meta": {"notes": {"degraded": True}},
                }))
            return
        _apply_patch(doc, outcome.layer_id, outcome.patch)
        await emit(LayerPatch(layerId=outcome.layer_id, patch=outcome.patch))

    if budget_remaining <= 0:
        log.warning("budget.exhausted_before_assets", doc_id=doc.id)
    else:
        try:
            await run_asset_jobs(session, doc, user_id, on_result=on_result,
                                 budget_cents=budget_remaining)
        except Exception as exc:
            log.exception("assets.stage_failed", doc_id=doc.id)
            await emit(JobFailed(jobId=doc.id, type="asset.background",
                                 recoverable=False, reason=str(exc)))

    # Reshape subject frames to the cutouts that actually arrived, before anything
    # measures geometry. Harmonisation probes what sits behind each layer and the solver
    # resolves collisions, so both need the final frames.
    try:
        fit_subjects(doc)
    except Exception:
        log.exception("fit.failed", doc_id=doc.id)

    # -- 1.5 harmonise ------------------------------------------------------------------
    try:
        resolved = await resolve_for(session, doc)
        harmonised = harmonize(doc, resolve_asset=resolved.url_resolver(),
                               load_image=resolved.image_loader())
        doc.layers = harmonised.layers
        doc.palette = harmonised.palette
        doc.canvas = harmonised.canvas
    except Exception:
        log.exception("harmonize.failed", doc_id=doc.id)

    # -- 1.6 solve ----------------------------------------------------------------------
    result = solve(doc, SolveOpts(grid_baseline=skeleton.grid_baseline,
                                  language=_language_of(doc)))
    doc.layers = result.doc.layers
    doc.canvas = result.doc.canvas
    doc.updated_at = _now()
    await emit(DocSolved(doc=doc.model_dump(by_alias=True, exclude_none=True),
                         violations=[v.as_dict() for v in result.violations]))

    # -- 1.7 assemble + thumbnail -------------------------------------------------------
    await repo.update_document(session, doc)
    try:
        await _write_thumbnail(session, doc, user_id)
    except Exception:
        log.exception("thumbnail.failed", doc_id=doc.id)
    return cost


def _language_of(doc: DesignDoc) -> str:
    brief = getattr(doc.provenance, "brief", None) or {}
    return brief.get("language", "en") or "en"


def _apply_patch(doc: DesignDoc, layer_id: str, patch: dict) -> None:
    layer, _ = find_layer(doc, layer_id)
    if layer is None:
        return
    merged = layer.model_dump(by_alias=True, exclude_none=True)
    for key, value in patch.items():
        if key == "meta" and isinstance(value, dict):
            existing = merged.get("meta", {})
            meta = {**existing, **{k: v for k, v in value.items() if k != "notes"}}
            meta["notes"] = {**existing.get("notes", {}), **value.get("notes", {})}
            merged["meta"] = meta
        else:
            merged[key] = value
    replace_layer(doc.layers, layer_id, type(layer).model_validate(merged))


def _degrade_layer(doc: DesignDoc, layer_id: str) -> None:
    """§0.9: substitute a graceful fallback and mark it, rather than failing."""
    layer, _ = find_layer(doc, layer_id)
    if layer is None:
        return
    layer.meta.notes["degraded"] = True
    if layer.constraints.optional:
        layer.visible = False
    elif getattr(layer, "placeholder_color", None) is None:
        layer.placeholder_color = doc.palette[0] if doc.palette else "#E2E8F0"


async def _write_thumbnail(session: AsyncSession, doc: DesignDoc,
                           user_id: str | None) -> None:
    resolved = await resolve_for(session, doc)
    scale = min(1.0, 512 / max(1, doc.canvas.width))
    draw_list = to_draw_list(doc, scale=scale, resolve_asset=resolved.url_resolver())
    data = render_webp(draw_list, resolved.image_loader(), quality=82)
    storage.get_backend().put(storage.doc_thumb_key(doc.id), data, "image/webp")

    asset_id = await repo.insert_asset(
        session, user_id=user_id, kind="thumb",
        storage_key=storage.doc_thumb_key(doc.id), mime="image/webp",
        width=draw_list.width, height=draw_list.height, has_alpha=False,
        size_bytes=len(data), gen_hash=None, gen_params=None,
    )
    await repo.set_document_thumb(session, doc.id, asset_id)


async def regenerate_layer(session: AsyncSession, doc: DesignDoc, layer_id: str,
                           user_id: str | None, *, prompt_override: str | None = None,
                           seed: int | None = None) -> AssetOutcome:
    """§3.3 `layer.regenerate` — reuse stored GenerationParams with a new seed."""
    from app.pipelines.part_one.assets import run_asset_job

    layer, _ = find_layer(doc, layer_id)
    if layer is None or layer.type != "image" or layer.meta.generation is None:
        raise ValueError(f"layer {layer_id} cannot be regenerated")

    params = layer.meta.generation
    if prompt_override:
        params.prompt = prompt_override
    params.seed = seed if seed is not None else (params.seed + 1) % (2 ** 31)
    layer.asset_id = ""
    outcome = await run_asset_job(session, doc, layer, user_id)
    if outcome.patch:
        _apply_patch(doc, layer_id, outcome.patch)
    return outcome


def reshape_layer(doc: DesignDoc, layer_id: str, *, motif: str | None = None,
                  seed: int | None = None, density: int | None = None) -> dict:
    """Rebuild a vector motif in place — the ornament counterpart to `regenerate_layer`.

    Costs nothing and calls no model, because ornament is procedural: the same three
    numbers that produced the path produce another one. Omitting `seed` re-rolls, which
    is the common case — a designer cycling blobs until one sits right.

    The path is rebuilt at the layer's *current* frame rather than the frame the skeleton
    authored, so a motif the user has already resized re-rolls at the size they chose.
    """
    from app.templates_corpus.ornament import MOTIFS, is_stroked, render_motif

    layer, _ = find_layer(doc, layer_id)
    if layer is None or layer.type != "shape" or layer.meta.ornament is None:
        raise ValueError(f"layer {layer_id} is not a vector motif")

    params = layer.meta.ornament
    if motif is not None:
        if motif not in MOTIFS:
            raise ValueError(f"unknown motif {motif!r}")
        params.motif = motif
    if density is not None:
        params.density = max(1, min(5, density))
    params.seed = seed if seed is not None else (params.seed + 1) % (2 ** 31)

    path_data = render_motif(params.motif, layer.frame.w, layer.frame.h,
                             seed=params.seed, density=params.density)
    if not path_data:
        raise ValueError(f"motif {params.motif!r} produced no geometry at this size")

    # Open contours must be stroked and closed ones filled, so switching between the two
    # families has to move the colour across rather than leave the layer invisible.
    colour = layer.fill or (layer.stroke.color if layer.stroke else "#FFFFFF")
    if is_stroked(params.motif):
        width = layer.stroke.width if layer.stroke else max(1.0, layer.frame.h * 0.02)
        layer.stroke = ShapeStroke(color=colour, width=width)
        layer.fill = None
    else:
        layer.fill = colour
        layer.stroke = None

    layer.shape = "path"
    layer.path_data = path_data
    return {"pathData": path_data, "fill": layer.fill,
            "stroke": layer.stroke.model_dump(by_alias=True) if layer.stroke else None,
            "meta": {"ornament": params.model_dump(by_alias=True)}}


async def run_with_timeout(coro, seconds: float):
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except TimeoutError:
        log.error("pipeline.timeout", seconds=seconds)
        raise
