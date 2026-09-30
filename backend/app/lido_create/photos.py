"""Where a new template's photos come from.

Today every photo frame gets a placeholder from the existing corpus (`CachedPhotos`):
the pipeline regenerates photo slots per brief anyway, so a draft only needs a photo that
looks right in the preview. Each photo element also carries a `subject` — what the
picture should show, written from the user's prompt — so a generating source can be
dropped in later without touching the designer:

    class GeneratedPhotos:
        name = "generated"
        async def photo_for(self, element, v):
            # registry.text_to_image().generate(prompt=element.subject, ...), upload the
            # bytes to the asset store, return Photo(url, width, height, tags=())

and pass it to `resolve_photos` (the draft API picks the source in one place:
`app/lido_create/drafts.py:photo_source`).
"""

from __future__ import annotations

from typing import Protocol

from app.lido_create.kit import Design, Element, Photo, Variant, pick_photo


class PhotoSource(Protocol):
    name: str

    async def photo_for(self, element: Element, v: Variant) -> Photo: ...


class CachedPhotos:
    """Placeholder photos already used by the corpus templates: on-theme first, then
    the one whose shape is closest to the frame's."""

    name = "corpus-cache"

    async def photo_for(self, element: Element, v: Variant) -> Photo:
        return pick_photo(v, element.w, element.h)


async def resolve_photos(design: Design, v: Variant, source: PhotoSource) -> list[Photo]:
    """One photo per photo element, in element order (what `lido.to_lido` expects)."""
    return [await source.photo_for(e, v) for e in design.elements if e.kind == "photo"]
