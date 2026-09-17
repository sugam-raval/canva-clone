"""Asset workers — IMPLEMENTATION_PLAN §1.4.

All jobs in this stage are independent: the orchestrator fans them out and streams each
result back as a `layer.patch`.

Enforces:
  * §1.4.6 glyph gate — INV-1, no baked-in text, with retry then inpaint fallback
  * §6.1 content-addressed cache — identical generation parameters are free
  * §6.4 resolution discipline — generate at the smallest size covering the layer
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, ImageResult, TextBox
from app.adapters.registry import glyph_detector as get_glyph_detector
from app.adapters.registry import inpainter as get_inpainter
from app.adapters.registry import matting as get_matting
from app.adapters.registry import text_to_image as get_t2i
from app.adapters.registry import transparent_image as get_transparent
from app.adapters.registry import upscaler as get_upscaler
from app.config import get_settings
from app.db import repo
from app.schema.doc import DesignDoc, GenerationParams, ImageLayer
from app.storage import assets as storage

log = structlog.get_logger(__name__)

# §6.4: generate at the smallest resolution that covers the layer's on-canvas size x1.2.
RESOLUTION_HEADROOM = 1.2
MIN_GENERATION_PX = 512
MAX_GENERATION_PX = 2048


@dataclass
class AssetOutcome:
    layer_id: str
    asset_id: str | None = None
    patch: dict = field(default_factory=dict)
    cost_cents: int = 0
    cached: bool = False
    degraded: bool = False
    error: str | None = None
    glyph_retries: int = 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def target_size(layer: ImageLayer, doc: DesignDoc) -> tuple[int, int]:
    """Pixel size to request from the model."""
    width = max(MIN_GENERATION_PX, int(layer.frame.w * RESOLUTION_HEADROOM))
    height = max(MIN_GENERATION_PX, int(layer.frame.h * RESOLUTION_HEADROOM))
    # Print documents are generated at half size and upscaled on export (§1.4.1).
    if doc.canvas.dpi >= 200:
        width, height = width // 2, height // 2
    scale = min(1.0, MAX_GENERATION_PX / max(width, height))
    return max(64, int(width * scale)), max(64, int(height * scale))


def gen_hash_for(params: GenerationParams, width: int, height: int) -> str:
    return storage.canonical_gen_hash({
        "adapter": params.adapter,
        "model": params.model,
        "prompt": params.prompt,
        "negativePrompt": params.negative_prompt or "",
        "seed": params.seed,
        "params": {**params.params, "w": width, "h": height},
    })


# --------------------------------------------------------------------------------------
# §1.4.6 Glyph gate — enforces INV-1
# --------------------------------------------------------------------------------------


class GlyphsDetected(Exception):
    def __init__(self, boxes: list[TextBox], coverage: float):
        self.boxes = boxes
        self.coverage = coverage
        super().__init__(f"{len(boxes)} text regions covering {coverage:.2%}")


async def assert_no_glyphs(data: bytes) -> None:
    settings = get_settings()
    boxes = await get_glyph_detector().detect(data)
    coverage = sum(b.area for b in boxes)
    if coverage > settings.glyph_gate_max_coverage or len(boxes) > settings.glyph_gate_max_boxes:
        raise GlyphsDetected(boxes, coverage)


STRONGER_NEGATIVES = [
    ("text, letters, words, numbers, typography, watermark, logo, signature, caption"),
    ("absolutely no text of any kind, no letters, no words, no numerals, no watermark, "
     "no logo, no signature, no caption, no subtitles, no labels, no packaging text"),
    ("a completely wordless image, free of all writing, lettering, glyphs, symbols, "
     "labels, packaging copy, signage and watermarks"),
]


async def _generate_with_glyph_gate(
    generate, *, prompt: str, negative: str, width: int, height: int, seed: int,
) -> tuple[ImageResult, int, float]:
    """Generate, then gate. On failure strengthen the negative, change the seed and drop
    CFG slightly (§1.4.6). After the retries are exhausted, inpaint the detected boxes.
    """
    settings = get_settings()
    attempts = settings.glyph_gate_retries + 1
    last: ImageResult | None = None
    last_boxes: list[TextBox] = []

    for attempt in range(attempts):
        stronger = STRONGER_NEGATIVES[min(attempt, len(STRONGER_NEGATIVES) - 1)]
        merged = f"{negative}, {stronger}" if attempt else negative
        result = await generate(
            prompt=prompt, negative_prompt=merged, width=width, height=height,
            seed=seed + attempt * 7919, cfg=max(3.0, 4.5 - 0.3 * attempt),
        )
        last = result
        try:
            await assert_no_glyphs(result.data)
            return result, attempt, 0.0
        except GlyphsDetected as exc:
            last_boxes = exc.boxes
            log.warning("glyph_gate.triggered", attempt=attempt,
                        boxes=len(exc.boxes), coverage=round(exc.coverage, 4))

    # §1.4.6: "After 2 failed retries, inpaint the detected boxes away."
    if last is not None and last_boxes:
        try:
            patched = await _inpaint_text_regions(last, last_boxes)
            # Re-gate: inpainting is not guaranteed to have removed everything, and
            # claiming success without checking is how leakage reaches a user.
            try:
                await assert_no_glyphs(patched.data)
                log.info("glyph_gate.inpainted", boxes=len(last_boxes))
                return patched, attempts, 0.0
            except GlyphsDetected as exc:
                log.warning("glyph_gate.survived_inpaint",
                            coverage=round(exc.coverage, 4))
                return patched, attempts, exc.coverage
        except AdapterError as exc:
            log.warning("glyph_gate.inpaint_failed", error=str(exc))

    if last is None:
        raise AdapterError("image generation produced no result")
    # Ship it and mark it: a degraded image beats no design (§0.9). The residual
    # coverage is recorded so §5.3's glyph-leakage metric can count it.
    residual = sum(box.area for box in last_boxes)
    return last, attempts, residual


async def _inpaint_text_regions(result: ImageResult, boxes: list[TextBox]) -> ImageResult:
    """Paint out detected glyph regions using the surrounding context."""
    mask = Image.new("L", (result.width, result.height), 0)
    from PIL import ImageDraw

    draw = ImageDraw.Draw(mask)
    pad = max(4, int(0.006 * max(result.width, result.height)))
    for box in boxes:
        x0 = max(0, int(box.x * result.width) - pad)
        y0 = max(0, int(box.y * result.height) - pad)
        x1 = min(result.width, int((box.x + box.w) * result.width) + pad)
        y1 = min(result.height, int((box.y + box.h) * result.height) + pad)
        draw.rectangle([x0, y0, x1, y1], fill=255)
    buf = io.BytesIO()
    mask.save(buf, format="PNG")

    filled = await get_inpainter().fill(
        result.data, buf.getvalue(),
        prompt="continue the surrounding scene seamlessly, empty, no text",
    )
    filled.params = {**result.params, "glyphGateInpainted": True}
    filled.model = result.model
    return filled


# --------------------------------------------------------------------------------------
# Asset jobs
# --------------------------------------------------------------------------------------


async def run_asset_job(session: AsyncSession, doc: DesignDoc, layer: ImageLayer,
                        user_id: str | None) -> AssetOutcome:
    """Produce the asset for one image layer and return the patch to apply."""
    params = layer.meta.generation
    if params is None:
        return AssetOutcome(layer.id, error="layer has no generation params")

    width, height = target_size(layer, doc)
    transparent = bool(params.params.get("transparent")) or layer.has_alpha

    # §6.1: content-addressed cache. Identical parameters cost nothing.
    probe = params.model_copy(update={"model": "resolved"})
    cache_key = gen_hash_for(probe, width, height)
    cached = await repo.find_asset_by_gen_hash(session, cache_key)
    if cached:
        log.info("asset.cache_hit", layer_id=layer.id)
        return AssetOutcome(
            layer.id, asset_id=str(cached["id"]), cached=True,
            patch={
                "assetId": str(cached["id"]),
                "hasAlpha": bool(cached["has_alpha"]),
                "naturalSize": {"w": cached["width"] or width,
                                "h": cached["height"] or height},
            },
        )

    adapter = get_transparent() if transparent else get_t2i()
    degraded = False
    retries = 0
    leakage = 0.0
    try:
        result, retries, leakage = await _generate_with_glyph_gate(
            adapter.generate, prompt=params.prompt,
            negative=params.negative_prompt or "", width=width, height=height,
            seed=params.seed,
        )
    except AdapterError as exc:
        log.error("asset.generate_failed", layer_id=layer.id, error=str(exc))
        return AssetOutcome(layer.id, error=str(exc), degraded=True)

    data, natural_w, natural_h = result.data, result.width, result.height
    if transparent:
        from app.adapters.local_adapters import trim_transparent_border

        data, natural_w, natural_h = trim_transparent_border(data)

    asset_id = await _store(session, user_id, data, params, result, cache_key,
                            transparent)

    patch = {
        "assetId": asset_id,
        "hasAlpha": transparent,
        "naturalSize": {"w": natural_w, "h": natural_h},
        "meta": {
            "generation": {
                **params.model_dump(by_alias=True, exclude_none=True),
                "model": result.model,
                "params": {**params.params, **result.params},
                "producedAt": _now(),
            },
            "notes": ({"degraded": True} if degraded else {})
            | ({"glyphGateRetries": retries} if retries else {})
            | ({"glyphLeakageCoverage": round(leakage, 5)} if leakage > 0 else {}),
        },
    }
    return AssetOutcome(layer.id, asset_id=asset_id, patch=patch,
                        cost_cents=result.cost_cents, degraded=degraded,
                        glyph_retries=retries)


async def _store(session: AsyncSession, user_id: str | None, data: bytes,
                 params: GenerationParams, result: ImageResult, cache_key: str,
                 transparent: bool) -> str:
    import uuid

    asset_id = str(uuid.uuid4())
    blob = storage.store_bytes(user_id, asset_id, data)
    return await repo.insert_asset(
        session, user_id=user_id, kind="image", storage_key=blob.storage_key,
        mime=blob.mime, width=blob.width, height=blob.height,
        has_alpha=transparent or blob.has_alpha, size_bytes=blob.size_bytes,
        gen_hash=cache_key,
        gen_params={**params.model_dump(by_alias=True, exclude_none=True),
                    "model": result.model},
    )


# What one generation is assumed to cost when admitting layers against a budget. The
# real figure comes back on the result; this only has to be right enough to stop a
# design with many props from planning to overspend.
ESTIMATED_IMAGE_COST_CENTS = 5


async def run_asset_jobs(session: AsyncSession, doc: DesignDoc, user_id: str | None,
                         *, on_result=None, concurrency: int = 3,
                         budget_cents: int | None = None) -> list[AssetOutcome]:
    """Fan out every pending image layer.

    §1.4 ordering rule: the background is generated FIRST, because subject harmonisation
    needs its palette and light direction. Everything else then runs in parallel.

    A design may now ask for several props beside its subject, so the order in which the
    rest run matters: they are admitted by constraint priority, highest first, and once
    `budget_cents` is spoken for the remainder are reported as degraded rather than
    generated. Props are optional layers, so §0.9 hides them and the design still ships —
    what must never happen is a subject going ungenerated because four leaves were
    generated ahead of it.
    """
    pending = [layer for layer in doc.layers
               if layer.type == "image" and not layer.asset_id
               and layer.meta.generation is not None]
    if not pending:
        return []

    backgrounds = [layer for layer in pending if layer.role == "background"]
    others = sorted((layer for layer in pending if layer.role != "background"),
                    key=lambda layer: -layer.constraints.priority)
    outcomes: list[AssetOutcome] = []

    for layer in backgrounds:
        outcome = await run_asset_job(session, doc, layer, user_id)
        outcomes.append(outcome)
        if on_result:
            await on_result(outcome)

    semaphore = asyncio.Semaphore(concurrency)

    async def run(layer: ImageLayer) -> AssetOutcome:
        async with semaphore:
            try:
                outcome = await run_asset_job(session, doc, layer, user_id)
            except Exception as exc:
                log.exception("asset.job_crashed", layer_id=layer.id)
                outcome = AssetOutcome(layer.id, error=str(exc), degraded=True)
            if on_result:
                await on_result(outcome)
            return outcome

    if budget_cents is not None:
        spent = sum(o.cost_cents for o in outcomes)
        affordable = max(0, (budget_cents - spent) // ESTIMATED_IMAGE_COST_CENTS)
        skipped = others[affordable:]
        others = others[:affordable]
        for layer in skipped:
            log.info("asset.skipped_over_budget", layer_id=layer.id, role=layer.role,
                     priority=layer.constraints.priority)
            outcome = AssetOutcome(layer.id, error="skipped: request budget exhausted",
                                   degraded=True)
            outcomes.append(outcome)
            if on_result:
                await on_result(outcome)

    if others:
        outcomes.extend(await asyncio.gather(*(run(layer) for layer in others)))
    return outcomes


# --------------------------------------------------------------------------------------
# §1.4.4 upscale and §1.4.5 provided assets
# --------------------------------------------------------------------------------------


async def maybe_upscale(session: AsyncSession, user_id: str | None, asset_id: str,
                        needed_w: float, needed_h: float) -> str:
    """§1.4.4: upscale when the stored asset is smaller than the frame it must fill."""
    asset = await repo.get_asset(session, asset_id)
    if not asset or not asset.get("width"):
        return asset_id
    if asset["width"] >= needed_w * 1.2 and asset["height"] >= needed_h * 1.2:
        return asset_id
    if needed_w < 400 and needed_h < 400:   # §6.6: skip upscaling small layers
        return asset_id

    data = storage.read_bytes(asset["storage_key"])
    if not data:
        return asset_id
    scale = 2 if needed_w / max(1, asset["width"]) <= 2 else 4
    result = await get_upscaler().upscale(data, scale=scale)
    import uuid

    new_id = str(uuid.uuid4())
    blob = storage.store_bytes(user_id, new_id, result.data)
    return await repo.insert_asset(
        session, user_id=user_id, kind="image", storage_key=blob.storage_key,
        mime=blob.mime, width=blob.width, height=blob.height,
        has_alpha=blob.has_alpha, size_bytes=blob.size_bytes,
        gen_hash=storage.canonical_gen_hash({"source": asset_id, "scale": scale,
                                             "upscaler": get_upscaler().name}),
        gen_params={"source": asset_id, "scale": scale},
    )


async def remove_background(session: AsyncSession, user_id: str | None,
                            asset_id: str) -> tuple[str, int, int]:
    """§1.4.5 / §3.3: matte a provided or generated opaque image into a cutout.

    Applies the full §1.4.2 `refine_alpha` chain, so the edge gets trimap refinement and
    colour decontamination rather than a hard binary cut.
    """
    from app.adapters.local_adapters import refine_alpha, trim_transparent_border

    asset = await repo.get_asset(session, asset_id)
    if not asset:
        raise AdapterError(f"asset {asset_id} not found", recoverable=False)
    data = storage.read_bytes(asset["storage_key"])
    if not data:
        raise AdapterError(f"asset {asset_id} has no stored bytes", recoverable=False)

    alpha = await get_matting().infer(data)
    rgba = refine_alpha(data, alpha)
    trimmed, natural_w, natural_h = trim_transparent_border(rgba)

    import uuid

    new_id = str(uuid.uuid4())
    blob = storage.store_bytes(user_id, new_id, trimmed)
    stored = await repo.insert_asset(
        session, user_id=user_id, kind="image", storage_key=blob.storage_key,
        mime=blob.mime, width=natural_w, height=natural_h, has_alpha=True,
        size_bytes=blob.size_bytes,
        gen_hash=storage.canonical_gen_hash({"source": asset_id, "op": "remove-bg",
                                             "matting": get_matting().name}),
        gen_params={"source": asset_id, "op": "remove-bg"},
    )
    # §1.4.2: keep the raw matte — the refine-edge tool reuses it.
    storage.get_backend().put(storage.mask_key(user_id, new_id), alpha, "image/png")
    return stored, natural_w, natural_h
