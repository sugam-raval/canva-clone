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
import re
import uuid
from dataclasses import dataclass
from typing import Protocol

import structlog
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image

from app import costs
from app.adapters.registry import text_to_image, transparent_image
from app.config import get_settings
from app.lido_corpus.assets_ai import generate_template_images
from app.lido_corpus.generate_ai import ImageTarget
from app.lido_corpus.generated import upload_asset
from app.lido_corpus.model import ImageSpec
from app.lido_create.kit import Design, Element, Photo, Variant, pick_photo
from app.lido_create.shapes import frames

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

    async def render(self, element: Element) -> Photo | None:
        """The element's subject rendered and uploaded; None if either step failed."""
        try:
            with costs.step("photo"):
                return await self._generate(element)
        except (BotoCoreError, ClientError, OSError) as exc:
            log.warning("lido.drafts.photo_upload_failed", error=str(exc)[:300])
            return None

    async def photo_for(self, element: Element, v: Variant) -> Photo:
        if not element.subject:
            log.warning("lido.drafts.photo_no_subject", clip=element.clip)
            return await self.fallback.photo_for(element, v)
        return await self.render(element) or await self.fallback.photo_for(element, v)


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


async def resolve_photos(design: Design, v: Variant, source: PhotoSource,
                         prefetch: PhotoPrefetch | None = None) -> list[Photo]:
    """One photo per photo element, in element order (what `lido.to_lido` expects),
    fetched concurrently — from `prefetch` where it already started a fitting one."""
    if prefetch is not None:
        return await prefetch.resolve(design, v)
    return list(await asyncio.gather(
        *(source.photo_for(e, v) for e in design.elements if e.kind == "photo")))


# A started photo still fits a frame whose w/h is within this factor of the shape it
# was rendered at: cover-cropping it then loses at most a third of the picture.
ASPECT_TOLERANCE = 1.5


@dataclass
class _Started:
    subject: str
    aspect: float  # w / h it is rendered at
    cutout: bool
    task: asyncio.Task
    planned: bool  # started from the plan (before any design existed)
    claimed: bool = False

    def shape_fits(self, aspect: float, cutout: bool) -> bool:
        return self.cutout == cutout and (
            cutout or max(aspect / self.aspect, self.aspect / aspect) <= ASPECT_TOLERANCE)

    def finished_photo(self) -> Photo | None:
        """Its photo, if it has already rendered successfully."""
        if not self.task.done() or self.task.cancelled() or self.task.exception():
            return None
        return self.task.result()


_WORD = re.compile(r"[a-z0-9]{3,}")
SAME_SUBJECT = 0.6  # subject_overlap at which two sentences describe the same picture


def subject_overlap(a: str, b: str) -> float:
    """How much of the shorter sentence the longer one contains. The designer usually
    rewrites the plan's subject longer and richer; measured against all words of both,
    draft #56's plan and design subjects (the same washing machine) scored 39%, while
    14 of the plan's 15 words were in the design's."""
    if a == b:
        return 1.0
    wa, wb = set(_WORD.findall(a.lower())), set(_WORD.findall(b.lower()))
    return len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0


class PhotoPrefetch:
    """Photos rendered while the design is still being made, instead of after it — and
    each rendered once.

    `from_plan` starts every planned photo the moment the art director has written the
    plan (at its frame's aspect, or the orientation the plan gave it). When a design
    has as many photos as the plan, they ARE the plan's photos — the designer builds
    exactly the plan — so they are paired with those renders whatever words the
    designer used. A photo is only rendered again when its frame's shape is far from
    the one it was started at (`ASPECT_TOLERANCE`): `from_design` starts those (and,
    without a plan, every photo), called with each better draft so they render while
    repair rounds run. `resolve` hands each photo of the final design its render; one
    that failed falls back to another finished render that fits, before rendering
    anew. Only a generating source has anything to start early."""

    def __init__(self, source: PhotoSource):
        self.source = source
        self.started: list[_Started] = []

    @property
    def active(self) -> bool:
        return isinstance(self.source, GeneratedPhotos)

    def _start(self, subject: str, aspect: float, cutout: bool, *, planned: bool) -> None:
        if not self.active or not subject:
            return
        h = 1000.0
        element = Element(kind="photo", x=0, y=0, w=h * aspect, h=h, subject=subject,
                          clip="cutout" if cutout else None)
        task = asyncio.ensure_future(self.source.render(element))  # type: ignore[attr-defined]
        self.started.append(_Started(subject, aspect, cutout, task, planned))
        log.info("lido.drafts.photo_started", aspect=round(aspect, 2), cutout=cutout,
                 planned=planned, subject=subject[:60])

    def from_plan(self, plan) -> None:
        from app.lido_create.plan import ORIENTATION_ASPECT

        for p in plan.photos:
            frame = frames().get(p.frame)
            aspect = frame.aspect if frame else (
                1.0 if p.frame == "circle" else ORIENTATION_ASPECT[p.orientation])
            self._start(p.subject, aspect, p.frame == "cutout", planned=True)

    def _by_plan(self, photos: list[Element]) -> bool:
        planned = sum(s.planned for s in self.started)
        return planned > 0 and planned == len(photos)

    def _pairs(self, photos: list[Element]) -> list[_Started | None]:
        """The render each photo element would use, one render per photo: planned ones
        first when the counts match (best subject overlap breaks ties between several),
        else any whose subject is the same picture; never one whose shape doesn't fit."""
        by_plan = self._by_plan(photos)
        scored = []
        for i, e in enumerate(photos):
            aspect, cutout = e.w / max(e.h, 1), e.clip == "cutout"
            for j, s in enumerate(self.started):
                if s.claimed or not s.shape_fits(aspect, cutout):
                    continue
                overlap = subject_overlap(s.subject, e.subject or "")
                if by_plan and s.planned:
                    scored.append((1 + overlap, i, j))
                elif overlap >= SAME_SUBJECT:
                    scored.append((overlap, i, j))
        out: list[_Started | None] = [None] * len(photos)
        used: set[int] = set()
        for _, i, j in sorted(scored, reverse=True):
            if out[i] is None and j not in used:
                out[i] = self.started[j]
                used.add(j)
        return out

    def from_design(self, design: Design, v: Variant | None = None) -> None:
        photos = [e for e in design.elements if e.kind == "photo"]
        for e, render in zip(photos, self._pairs(photos), strict=True):
            if render is None:  # no plan, or a frame far from the shape it was started at
                self._start(e.subject or "", e.w / max(e.h, 1), e.clip == "cutout",
                            planned=False)

    def cancel(self) -> None:
        """Its design failed: stop whatever is still rendering."""
        for s in self.started:
            s.task.cancel()

    def _stand_in(self, e: Element, by_plan: bool) -> Photo | None:
        """A finished, unused render that fits `e` — for when its own render failed."""
        aspect, cutout = e.w / max(e.h, 1), e.clip == "cutout"
        for s in self.started:
            if s.claimed or not s.shape_fits(aspect, cutout):
                continue
            if (by_plan and s.planned) or subject_overlap(s.subject, e.subject or "") \
                    >= SAME_SUBJECT:
                photo = s.finished_photo()
                if photo is not None:
                    s.claimed = True
                    return photo
        return None

    async def resolve(self, design: Design, v: Variant) -> list[Photo]:
        """One photo per photo element, in element order; unused renders are dropped."""
        photos = [e for e in design.elements if e.kind == "photo"]
        by_plan = self._by_plan(photos)
        pairs = self._pairs(photos)
        for render in pairs:  # claimed up front, so no two photos take the same render
            if render is not None:
                render.claimed = True

        async def one(e: Element, render: _Started | None) -> Photo:
            photo = await render.task if render is not None else None
            if photo is None and render is not None:
                log.warning("lido.drafts.prefetched_photo_failed", subject=render.subject[:60])
                photo = self._stand_in(e, by_plan)
            return photo or await self.source.photo_for(e, v)

        out = list(await asyncio.gather(*(one(e, r) for e, r in zip(photos, pairs,
                                                                     strict=True))))
        unused = [s for s in self.started if not s.claimed]
        for s in unused:
            if not s.task.done():  # abandoned mid-render: OpenAI may still bill it
                costs.record_unknown(get_settings().image_model, "image",
                                     "cancelled: not used by the final design", "photo")
            s.task.cancel()
        log.info("lido.drafts.photo_prefetch", photos=len(photos), renders=len(self.started),
                 reused=sum(s.claimed for s in self.started), wasted=len(unused))
        return out
