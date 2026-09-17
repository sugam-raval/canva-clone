"""Per-layer AI operations — IMPLEMENTATION_PLAN §3.3.

Every one of these preserves the layer's identity and frame, so the edit is
non-destructive in the layer sense: the user can always undo, and the layer keeps its
place in the stack and its generation history.
"""

from __future__ import annotations

import io
import uuid

import structlog
from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError
from app.adapters.registry import inpainter as get_inpainter
from app.adapters.registry import llm as get_llm
from app.db import repo
from app.pipelines.part_one.assets import remove_background
from app.schema.composer import RewriteOutput
from app.schema.doc import DesignDoc, find_layer
from app.storage import assets as storage
from app.util.safety import isolate_untrusted_text

log = structlog.get_logger(__name__)


def _require_image_layer(doc: DesignDoc, layer_id: str):
    layer, _ = find_layer(doc, layer_id)
    if layer is None:
        raise ValueError(f"layer {layer_id} not found")
    if layer.type != "image":
        raise ValueError(f"layer {layer_id} is a {layer.type} layer, not an image")
    return layer


async def remove_layer_background(session: AsyncSession, doc: DesignDoc, layer_id: str,
                                  user_id: str | None) -> dict:
    """§3.3 remove-bg: matting + refine on an opaque layer, sets hasAlpha."""
    layer = _require_image_layer(doc, layer_id)
    if not layer.asset_id:
        raise ValueError("layer has no asset to matte")

    asset_id, width, height = await remove_background(session, user_id, layer.asset_id)
    layer.asset_id = asset_id
    layer.has_alpha = True
    layer.natural_size.w, layer.natural_size.h = width, height
    layer.fit = "contain"
    layer.meta.notes["removedBackground"] = True
    return {"assetId": asset_id, "hasAlpha": True,
            "naturalSize": {"w": width, "h": height}, "fit": "contain"}


async def expand_layer(session: AsyncSession, doc: DesignDoc, layer_id: str,
                       user_id: str | None, *, edges: dict, prompt: str | None) -> dict:
    """§3.3 expand (outpaint): grow the frame and inpaint the new edges, keeping the
    original pixels bit-identical inside."""
    layer = _require_image_layer(doc, layer_id)
    asset = await repo.get_asset(session, layer.asset_id) if layer.asset_id else None
    if not asset:
        raise ValueError("layer has no asset to expand")
    data = storage.read_bytes(asset["storage_key"])
    if not data:
        raise ValueError("layer asset has no stored bytes")

    left = max(0, int(edges.get("l", 0)))
    right = max(0, int(edges.get("r", 0)))
    top = max(0, int(edges.get("t", 0)))
    bottom = max(0, int(edges.get("b", 0)))
    if not (left or right or top or bottom):
        raise ValueError("expand requires at least one non-zero edge")

    with Image.open(io.BytesIO(data)) as source:
        source = source.convert("RGBA")
        new_w = source.width + left + right
        new_h = source.height + top + bottom
        canvas = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
        canvas.paste(source, (left, top))

        # White marks the pixels to regenerate; the original region stays untouched.
        mask = Image.new("L", (new_w, new_h), 255)
        ImageDraw.Draw(mask).rectangle(
            [left, top, left + source.width - 1, top + source.height - 1], fill=0)

        image_buf, mask_buf = io.BytesIO(), io.BytesIO()
        canvas.convert("RGB").save(image_buf, format="PNG")
        mask.save(mask_buf, format="PNG")

    generation = layer.meta.generation
    base_prompt = prompt or (generation.prompt if generation else "")
    result = await get_inpainter().fill(
        image_buf.getvalue(), mask_buf.getvalue(),
        prompt=f"{base_prompt}, extend the scene naturally beyond its edges, "
               f"consistent lighting and perspective",
        negative_prompt=(generation.negative_prompt if generation else "") or "",
    )

    new_asset = await _store_derived(session, user_id, result.data, layer.asset_id,
                                     "expand")
    # Grow the frame by the same amount, so the visible content does not shift.
    layer.frame.x -= left
    layer.frame.y -= top
    layer.frame.w += left + right
    layer.frame.h += top + bottom
    layer.asset_id = new_asset
    layer.natural_size.w, layer.natural_size.h = result.width, result.height
    layer.crop = None
    return {
        "assetId": new_asset,
        "frame": layer.frame.model_dump(by_alias=True),
        "naturalSize": {"w": result.width, "h": result.height},
    }


async def erase_region(session: AsyncSession, doc: DesignDoc, layer_id: str,
                       user_id: str | None, *, mask_asset_id: str | None,
                       brush_path: list[list[float]] | None,
                       brush_width: float) -> dict:
    """§3.3 erase: brush mask -> inpaint that region of this layer only."""
    layer = _require_image_layer(doc, layer_id)
    asset = await repo.get_asset(session, layer.asset_id) if layer.asset_id else None
    if not asset:
        raise ValueError("layer has no asset to erase from")
    data = storage.read_bytes(asset["storage_key"])
    if not data:
        raise ValueError("layer asset has no stored bytes")

    with Image.open(io.BytesIO(data)) as source:
        width, height = source.width, source.height

    if mask_asset_id:
        mask_asset = await repo.get_asset(session, mask_asset_id)
        if not mask_asset:
            raise ValueError("mask asset not found")
        mask_bytes = storage.read_bytes(mask_asset["storage_key"])
        if not mask_bytes:
            raise ValueError("mask asset has no stored bytes")
    elif brush_path:
        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        # Brush points arrive in the layer's local space, normalised 0..1.
        points = [(p[0] * width, p[1] * height) for p in brush_path if len(p) >= 2]
        if len(points) == 1:
            radius = brush_width / 2
            draw.ellipse([points[0][0] - radius, points[0][1] - radius,
                          points[0][0] + radius, points[0][1] + radius], fill=255)
        elif len(points) > 1:
            draw.line(points, fill=255, width=int(brush_width), joint="curve")
        buf = io.BytesIO()
        mask.save(buf, format="PNG")
        mask_bytes = buf.getvalue()
    else:
        raise ValueError("erase requires either maskAssetId or brushPath")

    result = await get_inpainter().fill(
        data, mask_bytes,
        prompt="remove the masked object and continue the surrounding scene seamlessly")
    new_asset = await _store_derived(session, user_id, result.data, layer.asset_id,
                                     "erase")
    layer.asset_id = new_asset
    return {"assetId": new_asset}


async def _store_derived(session: AsyncSession, user_id: str | None, data: bytes,
                         source_asset_id: str, op: str) -> str:
    asset_id = str(uuid.uuid4())
    blob = storage.store_bytes(user_id, asset_id, data)
    return await repo.insert_asset(
        session, user_id=user_id, kind="image", storage_key=blob.storage_key,
        mime=blob.mime, width=blob.width, height=blob.height,
        has_alpha=blob.has_alpha, size_bytes=blob.size_bytes,
        gen_hash=storage.canonical_gen_hash(
            {"source": source_asset_id, "op": op, "bytes": len(data)}),
        gen_params={"source": source_asset_id, "op": op},
    )


# --------------------------------------------------------------------------------------
# Copy rewriting — §3.3
# --------------------------------------------------------------------------------------

REWRITE_SYSTEM = """\
You rewrite the copy of a design. You are given the current text layers and an
instruction from the user.

RULES
- Rewrite ALL the given layers together so they stay coherent with each other: a
  headline and its subhead must read as one voice, not two.
- Respect each layer's character limit exactly. Count characters. If the natural
  rewrite is too long, write something shorter rather than exceeding the limit.
- Keep the language of the original copy unless the instruction says otherwise.
- Do not add quotation marks, labels or commentary. Return only the rewritten text.
- Do not pre-uppercase text; case transforms are applied when the design is rendered.
- Return an entry for every layer id you were given, even if unchanged.
"""


async def rewrite_copy(doc: DesignDoc, layer_ids: list[str],
                       instruction: str) -> tuple[list[dict], int]:
    """§3.3: rewrite selected text layers together so they stay coherent."""
    layers = []
    for layer_id in layer_ids:
        layer, _ = find_layer(doc, layer_id)
        if layer is None or layer.type != "text":
            continue
        limit = int(layer.auto_fit.max * 2) if layer.auto_fit else 120
        layers.append((layer, max(12, min(280, limit))))
    if not layers:
        raise ValueError("no text layers selected")

    described = "\n".join(
        f"- id={layer.id} role={layer.role} maxChars={limit} current={layer.content!r}"
        for layer, limit in layers)
    # §7: the user's instruction is trusted, but the existing copy may itself have come
    # from an untrusted source, so it is passed as a delimited data block.
    user = (f"Instruction: {instruction.strip()}\n\n"
            f"Layers to rewrite:\n{described}\n\n"
            f"{isolate_untrusted_text(chr(10).join(l.content for l, _ in layers), source='existing design copy')}")

    try:
        result = await get_llm().complete_json(
            system=REWRITE_SYSTEM, user=user, schema=RewriteOutput, temperature=0.7)
    except AdapterError as exc:
        raise ValueError(f"copy rewriting is unavailable: {exc}") from exc

    limits = {layer.id: limit for layer, limit in layers}
    patches = []
    for entry in result.parsed.layers:
        layer, _ = find_layer(doc, entry.layer_id)
        if layer is None or layer.type != "text":
            continue
        content = entry.content.strip()
        limit = limits.get(entry.layer_id, 120)
        if len(content) > limit:
            content = content[:max(1, limit - 1)].rstrip() + "…"
        layer.content = content
        patches.append({"layerId": layer.id, "content": content})
    return patches, result.cost_cents
