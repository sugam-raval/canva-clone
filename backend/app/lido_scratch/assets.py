"""Image generation for a scratch design.

Unlike the corpus flow, there is no stock photo underneath — a scratch design's
background and photo frames are empty until something fills them. Failures are still
swallowed per-slot (§0.9): a design with a flat palette ground beats an error page, and
`spec.background.color` is always a real colour for exactly this reason.

A `cutout` photo element goes through `TransparentImage` instead of `TextToImage` — it
is meant to float directly on the page as a subject, not sit cover-cropped inside a
frame, so it needs a real alpha channel rather than an opaque rectangle.
"""

from __future__ import annotations

import asyncio
import uuid

from app.adapters.base import AdapterError
from app.adapters.registry import text_to_image as get_text_to_image
from app.adapters.registry import transparent_image as get_transparent_image
from app.lido_corpus.assets_ai import NEGATIVE_TEXT
from app.storage.assets import store_bytes, url_for

from . import background
from . import palette as pal
from .spec import DesignSpec


def _background_prompt(spec: DesignSpec) -> str | None:
    """The finished background prompt, assembled in `background.build_prompt`.

    Nothing is taken from the model verbatim any more. It chose a style and, at most,
    a motif; the recipe, the design's own palette, the safe-zone clause and the quality
    floor are added here, deterministically. A prompt the model wrote freehand used to
    come back as a literal, evenly-detailed photograph of the subject in colours that
    had nothing to do with the palette — which is precisely what made these pages look
    plain next to a designed poster.
    """
    return background.build_prompt(
        spec.background.style,
        spec.palette or [spec.background.color],
        motif=spec.background.motif,
        safe_zone=spec.background.safe_zone,
    )


async def _generate_opaque(prompt: str, width: int, height: int,
                           negative: str = NEGATIVE_TEXT) -> bytes | None:
    try:
        result = await get_text_to_image().generate(
            prompt=prompt, negative_prompt=negative,
            width=max(64, min(2048, width)), height=max(64, min(2048, height)),
        )
        return result.data
    except (AdapterError, ValueError):
        return None


#: Asked for "happy customers outside a restaurant" on a wide transparent canvas, an
#: image model fills the width by repeating the subject — a real run came back as the
#: same group of people smeared across the frame four times. A cutout is one subject,
#: whole, and it has to be said explicitly in both directions.
_CUTOUT_FRAMING = (
    "ONE single subject only, complete and whole, centred in frame, entirely within "
    "the canvas, clean crisp silhouette edges, isolated on a fully transparent "
    "background, nothing else in the image"
)

_CUTOUT_NEGATIVES = (
    "duplicate, duplicated subject, repeated subject, multiple copies, two of the "
    "same, mirrored copy, cloned, collage, tiled, pattern repeat, row of identical "
    "figures, cropped limbs, cut off at the edge, background, backdrop, scenery, "
    "floor, shadow on the ground, white box, solid background"
)


async def _generate_cutout(prompt: str, width: int, height: int) -> bytes | None:
    cutout_prompt = f"{prompt}. {_CUTOUT_FRAMING}."
    try:
        result = await get_transparent_image().generate(
            prompt=cutout_prompt,
            negative_prompt=f"{NEGATIVE_TEXT}, {_CUTOUT_NEGATIVES}",
            width=max(64, min(2048, width)), height=max(64, min(2048, height)),
        )
        return result.data
    except (AdapterError, ValueError):
        return None


async def _generate(prompt: str, width: int, height: int, *, cutout: bool,
                    negative: str = NEGATIVE_TEXT) -> str | None:
    data = await (_generate_cutout(prompt, width, height) if cutout
                 else _generate_opaque(prompt, width, height, negative))
    if data is None:
        return None
    try:
        blob = store_bytes(None, f"scratch-{uuid.uuid4().hex}", data)
    except ValueError:
        return None
    return url_for(blob.storage_key)


#: Appended to every subject photo. A hero cutout shot on a phone camera under flat
#: light is the other half of why these pages looked cheap — the ground was improved
#: and the subject on it still read as a stock thumbnail.
_SUBJECT_QUALITY = (
    "professional advertising photography, dramatic directional studio lighting, "
    "shallow depth of field, rich saturated colour, crisp detail, commercial quality, "
    "clean uncluttered composition"
)


def _subject_prompt(prompt: str, spec: DesignSpec) -> str:
    """A photo element's own prompt, lifted to advertising quality and tied to the
    design's palette so the subject and the ground read as one photograph."""
    accent = pal.accent_of(spec.palette) if spec.palette else None
    tie = f", lit with a subtle {pal.color_name(accent)} accent" if accent else ""
    return f"{prompt}{tie}. {_SUBJECT_QUALITY}."


async def generate_assets(spec: DesignSpec) -> tuple[str | None, dict[int, str]]:
    """Returns `(background_url, {element_index: photo_url})`.

    Background and photos are generated concurrently — they are independent calls to
    the same provider, and a poster with three frames would otherwise serialise four
    round trips into the request.
    """
    jobs: list[tuple[int | None, str, int, int, bool, str]] = []

    background_prompt = _background_prompt(spec)
    if background_prompt:
        # The background carries its style's own negatives as well as the shared ones:
        # "smooth airbrushed gradient" ruins a torn-brush ground and is exactly what a
        # model produces when only told to avoid text.
        jobs.append((None, background_prompt, spec.width, spec.height, False,
                     background.negative_prompt(spec.background.style)))

    for index, element in enumerate(spec.elements):
        if element.kind != "photo" or not element.image_prompt:
            continue
        width = int(max(64, element.w * spec.width))
        height = int(max(64, (element.h or 0.25) * spec.height))
        jobs.append((index, _subject_prompt(element.image_prompt, spec), width, height,
                     element.cutout, NEGATIVE_TEXT))

    if not jobs:
        return None, {}

    results = await asyncio.gather(
        *(_generate(prompt, w, h, cutout=cutout, negative=negative)
          for _, prompt, w, h, cutout, negative in jobs)
    )

    background_url: str | None = None
    photos: dict[int, str] = {}
    for (index, _prompt, _w, _h, _cutout, _negative), url in zip(jobs, results):
        if url is None:
            continue
        if index is None:
            background_url = url
        else:
            photos[index] = url
    return background_url, photos
