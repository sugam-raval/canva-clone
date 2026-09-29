"""Image generation for a filled Lido template, driven by each layer's `ImageSpec`.

The prompt for every image comes from `generate_ai` (the template's reference prompt,
adapted to the request). Which adapter renders it comes only from the template's own
metadata: `transparent=True` goes through `TransparentImage` for a real alpha cutout,
anything else through `TextToImage`. Logos and other `generate=False` / locked layers
never reach this module — `generate_ai.image_targets` filters them out.

Failures are swallowed per image (§0.9): that layer keeps the template's original
image rather than the whole request failing, and the caller is told which ones.
"""

from __future__ import annotations

import asyncio
import io

import structlog
from PIL import Image, ImageDraw, ImageFilter, ImageStat

from app.adapters.base import AdapterError
from app.adapters.registry import text_to_image as get_text_to_image
from app.adapters.registry import transparent_image as get_transparent_image
from app.config import get_settings

from .generate_ai import ImageTarget

log = structlog.get_logger(__name__)

NEGATIVE_TEXT = (
    "text, letters, words, numbers, typography, watermark, logo, signature, caption, "
    "ui, frame, border"
)

# Asked for a subject on a transparent canvas, image models tend to repeat it across the
# frame or crop it at the edge; both have to be ruled out explicitly.
_CUTOUT_FRAMING = (
    "ONE single subject only, complete and whole, centred in frame, entirely within the "
    "canvas, clean crisp silhouette edges, isolated on a fully transparent background, "
    "nothing else in the image"
)
_CUTOUT_NEGATIVES = (
    "duplicate subject, repeated subject, multiple copies, collage, tiled, cropped or cut "
    "off at the edge, background, backdrop, scenery, table surface, floor, cast shadow, "
    "white box, solid background"
)

# The provider renders at a fixed ~1024x1024 pixel budget whatever size is asked for, so
# requesting more only upsamples. Keep the layer's aspect at that budget instead.
_RENDER_LONG_EDGE = 1024


def render_dims(width: float, height: float, long_edge: int = _RENDER_LONG_EDGE) -> tuple[int, int]:
    scale = long_edge / max(width, height, 1)
    return max(64, round(width * scale)), max(64, round(height * scale))


async def _render(target: ImageTarget, prompt: str, quality: str) -> bytes | None:
    width, height = render_dims(target.width, target.height)
    if target.spec.transparent:
        adapter = get_transparent_image()
        prompt = f"{prompt}\n\n{_CUTOUT_FRAMING}."
        negative = f"{NEGATIVE_TEXT}, {_CUTOUT_NEGATIVES}"
    else:
        adapter = get_text_to_image()
        negative = NEGATIVE_TEXT
    try:
        result = await adapter.generate(prompt=prompt, negative_prompt=negative,
                                        width=width, height=height, quality=quality)
        return result.data
    except (AdapterError, ValueError) as exc:
        log.warning("lido.template_image.failed", layer_id=target.layer_id,
                    transparent=target.spec.transparent, error=str(exc))
        return None


async def generate_template_images(targets: list[ImageTarget],
                                   prompts: dict[str, str]) -> dict[str, bytes]:
    """Render every target that has a prompt, concurrently. Returns
    `{layer_id: png_bytes}` for the ones that succeeded."""
    jobs = [t for t in targets if prompts.get(t.layer_id)]
    if not jobs:
        return {}
    quality = get_settings().lido_template_image_quality
    results = await asyncio.gather(
        *(_render(t, prompts[t.layer_id], quality) for t in jobs)
    )
    return {t.layer_id: data for t, data in zip(jobs, results) if data is not None}


def mask_reserved_areas(data: bytes, canvas_width: float, canvas_height: float,
                        reserved: list[tuple[float, float, float, float]]) -> bytes:
    """Paint over every `(x, y, width, height)` in `reserved`, in canvas units scaled to
    `data`'s actual pixel size, with the LOCAL average color around each box — sampled
    from a margin just outside it, not the whole image — and blend the edge with a soft
    feather instead of a hard rectangle. A single whole-image average reads as an
    obviously pasted-on flat patch the moment the background isn't uniform (a gradient,
    a photo) — exactly where this most needs to look right, since a busy generated photo
    is exactly what triggers this function in the first place.

    A background image is one flat picture generated from one text prompt; a separate
    photo frame or logo then sits on top of part of it at render time. The prompt asks
    the model to leave that part blank, but a text-to-image model routinely ignores a
    "leave this blank" instruction — especially when the request's own subject is
    strongly implied everywhere else in the prompt (a pizza brief drawing pizza across
    the whole canvas, including the area reserved for the separate photo layers). This
    makes the guarantee structural instead of relying on the model obeying that
    instruction, for every template, automatically — see
    docs/TEMPLATE_EXPORT_RULES.md."""
    if not reserved:
        return data
    img = Image.open(io.BytesIO(data)).convert("RGB")
    sx = img.width / canvas_width if canvas_width else 1.0
    sy = img.height / canvas_height if canvas_height else 1.0
    boxes = [
        (max(0, int(x * sx)), max(0, int(y * sy)),
         min(img.width, int((x + w) * sx)), min(img.height, int((y + h) * sy)))
        for x, y, w, h in reserved
    ]
    boxes = [b for b in boxes if b[2] > b[0] and b[3] > b[1]]
    if not boxes:
        return data

    # Everything outside every reserved box — excludes one box's own area from another
    # box's local sample too, so two adjacent reserved boxes don't sample each other.
    outside = Image.new("L", img.size, 255)
    outside_draw = ImageDraw.Draw(outside)
    for box in boxes:
        outside_draw.rectangle(box, fill=0)
    global_mean = ImageStat.Stat(img, mask=outside).mean
    global_fill = tuple(round(c) for c in global_mean) if global_mean else (255, 255, 255)

    paint = img.copy()
    paint_draw = ImageDraw.Draw(paint)
    box_mask = Image.new("L", img.size, 0)
    box_mask_draw = ImageDraw.Draw(box_mask)
    for x0, y0, x1, y1 in boxes:
        # Wide enough to reach past whatever leaked right up to the box's own edge (the
        # immediately adjacent pixels are the least trustworthy sample, since a leak
        # commonly fades out approaching the edge rather than stopping cleanly at it)
        # into genuinely unaffected background.
        margin = max(24, round(0.25 * max(x1 - x0, y1 - y0)))
        hx0, hy0 = max(0, x0 - margin), max(0, y0 - margin)
        hx1, hy1 = min(img.width, x1 + margin), min(img.height, y1 + margin)
        local_mask = outside.crop((hx0, hy0, hx1, hy1))
        local_mean = ImageStat.Stat(img.crop((hx0, hy0, hx1, hy1)), mask=local_mask).mean \
            if local_mask.getbbox() else None
        fill = tuple(round(c) for c in local_mean) if local_mean else global_fill
        paint_draw.rectangle((x0, y0, x1, y1), fill=fill)
        box_mask_draw.rectangle((x0, y0, x1, y1), fill=255)

    feather = max(4, round(0.01 * min(img.width, img.height)))
    soft_mask = box_mask.filter(ImageFilter.GaussianBlur(feather))
    result = Image.composite(paint, img, soft_mask)
    out = io.BytesIO()
    result.save(out, format="PNG")
    return out.getvalue()
