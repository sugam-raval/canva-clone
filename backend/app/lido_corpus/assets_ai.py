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

import structlog

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
