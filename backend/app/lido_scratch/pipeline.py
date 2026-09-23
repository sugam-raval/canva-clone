"""End-to-end scratch generation:

    brief -> design spec (LLM) -> layout repair -> ornament -> assets -> compile -> save

The counterpart to `app.lido_corpus.pipeline`, with the retrieval step replaced by an
actual design step. Nothing here reaches the DB; the result is written to
`lido_generated/` as a file and returned in full in the same call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.schema.brief import DesignBrief

from .assets import generate_assets
from .builder import build_layers
from .decor import decorate
from .design_ai import design_spec
from .imagery import ensure_subject
from .layout import repair
from .spec import DesignSpec
from .store import build_document, new_id, save


@dataclass
class ScratchResult:
    design_id: str
    document: list[dict]
    spec: DesignSpec
    path: str
    llm_designed: bool
    """False when no LLM was configured and the mechanical grid produced the layout."""
    font_scale: float
    background_url: str | None = None
    photo_urls: dict[int, str] = field(default_factory=dict)


async def generate_scratch_design(
    brief: DesignBrief,
    prompt: str,
    *,
    generate_images: bool = True,
    directory: Path | None = None,
) -> ScratchResult:
    spec, llm_designed = await design_spec(brief)
    # Before `repair`, so a backfilled subject is laid out with everything else rather
    # than squeezed into what the finished layout happened to leave over.
    ensure_subject(spec, brief)
    layout = repair(spec)
    # Ornament last: every mark is placed against wrapped, de-overlapped, recoloured
    # geometry, so it can sit under the headline that actually got set rather than the
    # one the model imagined.
    decorate(spec, layout.font_scale)

    background_url, photo_urls = (
        await generate_assets(spec) if generate_images else (None, {})
    )

    layers = build_layers(layout, background_url=background_url, photo_urls=photo_urls)

    design_id = new_id(spec.name)
    document = build_document(
        design_id, layers,
        name=spec.name,
        kind=spec.kind or brief.kind,
        prompt=prompt,
        tags=list(brief.mood)[:3],
        description=f"Generated from scratch: {prompt}"[:200],
    )
    path = save(design_id, document, directory)

    return ScratchResult(
        design_id=design_id,
        document=document,
        spec=spec,
        path=str(path),
        llm_designed=llm_designed,
        font_scale=layout.font_scale,
        background_url=background_url,
        photo_urls=photo_urls,
    )
