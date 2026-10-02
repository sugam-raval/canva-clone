"""Where a new template's photos come from — chosen by `LIDO_DRAFT_PHOTOS`:

    cache     (default) every photo frame gets a placeholder already used by the corpus
              (`CachedPhotos`): free and instant, and the pipeline regenerates photo
              slots per brief anyway, so a draft only needs a photo that looks right.
    generate  every photo frame is rendered from its `subject` — what the picture should
              show, written from the user's prompt — by the same code that renders
              images when filling a template (`lido_corpus.assets_ai`), uploaded the
              same way (`lido_corpus.generated.upload_asset`) and referenced by its
              permanent public URL (`GeneratedPhotos`).

A frame whose generation fails (no subject, the provider refused or is down, the upload
failed) keeps a cached placeholder instead of failing the whole draft. With no
OPENAI_API_KEY the image adapters are stubs that draw gradients, not photos, so
`generate` degrades to the cache as a whole. The draft API picks the source in one
place: `app/lido_create/drafts.py:photo_source`.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from typing import Protocol

import structlog
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image

from app.adapters.registry import text_to_image, transparent_image
from app.config import get_settings
from app.lido_corpus.assets_ai import generate_template_images
from app.lido_corpus.generate_ai import ImageTarget
from app.lido_corpus.generated import upload_asset
from app.lido_corpus.model import ImageSpec
from app.lido_create.kit import Design, Element, Photo, Variant, pick_photo

log = structlog.get_logger(__name__)

GENERATED_TAG = "generated"  # in a generated Photo's tags, so a fallback can be told apart
ASSET_FOLDER = "drafts"  # generated photos land in public/lido-generated/drafts/


class PhotoSource(Protocol):
    name: str

    async def photo_for(self, element: Element, v: Variant) -> Photo: ...


class CachedPhotos:
    """Placeholder photos already used by the corpus templates: on-theme first, then
    the one whose shape is closest to the frame's."""

    name = "corpus-cache"

    async def photo_for(self, element: Element, v: Variant) -> Photo:
        return pick_photo(v, element.w, element.h, cutout=element.clip == "cutout")


def image_target(element: Element) -> ImageTarget:
    """The photo element as a "fill a template" image slot, so it is rendered by exactly
    the same code (`lido_corpus.assets_ai`): same adapters, framing, negatives, quality."""
    cutout = element.clip == "cutout"
    spec = ImageSpec(kind="subject_cutout" if cutout else "background_photo",
                     transparent=cutout, prompt=element.subject)
    return ImageTarget(layer_id=f"photo-{uuid.uuid4().hex}", spec=spec,
                       width=element.w, height=element.h)


class GeneratedPhotos:
    """Renders each photo element's `subject` through the template flow's image
    generation (`generate_template_images`) at the frame's aspect ratio — a real alpha
    cutout for clip="cutout", an opaque photo otherwise — and uploads it like the
    template flow does (`upload_asset`). Falls back to `fallback` per frame."""

    name = "generated"

    def __init__(self, fallback: PhotoSource | None = None):
        self.fallback = fallback or CachedPhotos()

    async def _generate(self, element: Element) -> Photo | None:
        target = image_target(element)
        rendered = await generate_template_images([target], {target.layer_id: element.subject})
        data = rendered.get(target.layer_id)
        if data is None:  # already logged by assets_ai
            return None
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            alpha = im.mode in ("RGBA", "LA")
        url = await asyncio.to_thread(upload_asset, ASSET_FOLDER, target.layer_id, data)
        return Photo(url, w, h, (GENERATED_TAG,), cutout=target.spec.transparent and alpha)

    async def photo_for(self, element: Element, v: Variant) -> Photo:
        if not element.subject:
            log.warning("lido.drafts.photo_no_subject", clip=element.clip)
            return await self.fallback.photo_for(element, v)
        try:
            photo = await self._generate(element)
        except (BotoCoreError, ClientError, OSError) as exc:
            log.warning("lido.drafts.photo_upload_failed", error=str(exc)[:300])
            photo = None
        return photo or await self.fallback.photo_for(element, v)


def configured_source() -> PhotoSource:
    """The source `LIDO_DRAFT_PHOTOS` selects. `generate` without a real image model
    (no OPENAI_API_KEY, or the adapters forced to stub) uses the cache."""
    choice = get_settings().lido_draft_photos.strip().lower()
    if choice == "generate":
        stubbed = [a.name for a in (text_to_image(), transparent_image())
                   if a.name.startswith("stub")]
        if not stubbed:
            return GeneratedPhotos()
        log.warning("lido.drafts.photo_generation_unavailable", adapters=stubbed,
                    reason="image adapters are stubs (no OPENAI_API_KEY?); using the cache")
    elif choice != "cache":
        log.warning("lido.drafts.unknown_photo_source", value=choice, using="cache")
    return CachedPhotos()


async def resolve_photos(design: Design, v: Variant, source: PhotoSource) -> list[Photo]:
    """One photo per photo element, in element order (what `lido.to_lido` expects),
    fetched concurrently."""
    return list(await asyncio.gather(
        *(source.photo_for(e, v) for e in design.elements if e.kind == "photo")))
