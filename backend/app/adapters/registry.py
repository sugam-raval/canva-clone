"""Adapter selection — IMPLEMENTATION_PLAN §0.3.

"Each adapter lives in `packages/ml-adapters/` with a local implementation and a hosted
implementation, selected by env var. Ship hosted first."

`auto` picks the best implementation that is actually usable right now, so a missing API
key or a missing optional dependency degrades instead of crashing.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import structlog

from app.adapters import local_adapters as local
from app.adapters import stub_adapters as stub
from app.config import get_settings

log = structlog.get_logger(__name__)


def _openai():
    from app.adapters import openai_adapters

    return openai_adapters


@lru_cache(maxsize=1)
def text_to_image() -> Any:
    settings = get_settings()
    choice = settings.adapter_text_to_image
    if choice in ("openai", "auto") and settings.has_openai:
        return _openai().OpenAITextToImage()
    if choice == "openai" and not settings.has_openai:
        log.warning("adapter.fallback", capability="TextToImage", reason="no OPENAI_API_KEY")
    return stub.StubTextToImage()


@lru_cache(maxsize=1)
def transparent_image() -> Any:
    """§1.4.2 Path A (native transparent generation) when available, else Path B
    (generate then matte), else the stub."""
    settings = get_settings()
    choice = settings.adapter_transparent_image
    if choice in ("openai", "auto") and settings.has_openai:
        return _openai().OpenAITransparentImage()
    if choice == "matte":
        return MattedTransparentImage()
    if choice == "openai" and not settings.has_openai:
        log.warning("adapter.fallback", capability="TransparentImage",
                    reason="no OPENAI_API_KEY")
    return stub.StubTransparentImage()


@lru_cache(maxsize=1)
def matting() -> Any:
    settings = get_settings()
    choice = settings.adapter_matting
    if choice in ("rembg", "auto") and local.RembgMatting.available():
        return local.RembgMatting()
    if choice == "rembg":
        log.warning("adapter.fallback", capability="Matting",
                    reason="rembg not installed; pip install -e '.[localml]'")
    if choice == "stub":
        return local.GrabCutMatting()
    return local.GrabCutMatting()


@lru_cache(maxsize=1)
def inpainter() -> Any:
    settings = get_settings()
    choice = settings.adapter_inpainter
    if choice in ("openai", "auto") and settings.has_openai:
        return _openai().OpenAIInpainter()
    return local.OpenCVInpainter()


@lru_cache(maxsize=1)
def glyph_detector() -> Any:
    """The §1.4.6 gate. Never returns the no-op stub when a real image model is in use —
    that combination would silently disable INV-1 enforcement."""
    settings = get_settings()
    choice = settings.adapter_glyph_detector
    if choice == "stub" and not settings.has_openai:
        return stub.StubGlyphDetector()
    if choice in ("openai", "vision") and settings.has_openai:
        return _openai().OpenAIVisionGlyphDetector()
    return local.OpenCVGlyphDetector()


@lru_cache(maxsize=1)
def vision_glyph_detector() -> Any | None:
    """Escalation path for an ambiguous gate result; None when unavailable."""
    settings = get_settings()
    return _openai().OpenAIVisionGlyphDetector() if settings.has_openai else None


@lru_cache(maxsize=1)
def upscaler() -> Any:
    return local.LanczosUpscaler()


@lru_cache(maxsize=1)
def embedder() -> Any:
    """Local sentence-transformer by default: retrieval runs on every request, so a
    local model keeps it off the network and out of the per-request cost (§1.2, §6)."""
    settings = get_settings()
    choice = settings.adapter_embedder
    if choice in ("sentence-transformers", "st", "local", "auto"):
        from app.adapters.embedding_adapters import SentenceTransformerEmbedder

        if SentenceTransformerEmbedder.available():
            return SentenceTransformerEmbedder()
        log.warning("adapter.fallback", capability="Embedder",
                    reason="sentence-transformers not installed; "
                           "pip install -e '.[embed]'")
    if choice in ("openai",) and settings.has_openai:
        return _openai().OpenAIEmbedder()
    if choice == "openai":
        log.warning("adapter.fallback", capability="Embedder", reason="no OPENAI_API_KEY")
    return stub.HashEmbedder(settings.embedding_dim)


@lru_cache(maxsize=1)
def llm() -> Any:
    settings = get_settings()
    if settings.adapter_llm in ("openai", "auto") and settings.has_openai:
        return _openai().OpenAILLM()
    return stub.StubLLM()


class MattedTransparentImage:
    """§1.4.2 Path B — generate on a plain backdrop, then matte and refine.

    Recorded in `params["path"]` so a document says which path produced its subject.
    """

    name = "composite:t2i+matting"

    async def generate(self, *, prompt: str, negative_prompt: str = "", width: int = 1024,
                       height: int = 1024, seed: int = 0, steps: int = 30,
                       cfg: float = 5.0, quality: str = "medium") -> Any:
        base = await text_to_image().generate(
            prompt=f"{prompt}, isolated on a plain flat seamless background",
            negative_prompt=negative_prompt, width=width, height=height, seed=seed,
            steps=steps, cfg=cfg, quality=quality,
        )
        alpha = await matting().infer(base.data)
        rgba = local.refine_alpha(base.data, alpha)
        trimmed, natural_w, natural_h = local.trim_transparent_border(rgba)
        base.data = trimmed
        base.has_alpha = True
        base.width, base.height = natural_w, natural_h
        base.params = {**base.params, "path": "B:matted", "matting": matting().name}
        return base


def describe() -> dict[str, str]:
    """Which implementation each capability resolved to — surfaced at /v1/health."""
    return {
        "TextToImage": text_to_image().name,
        "TransparentImage": transparent_image().name,
        "Matting": matting().name,
        "Inpainter": inpainter().name,
        "GlyphDetector": glyph_detector().name,
        "Upscaler": upscaler().name,
        "Embedder": embedder().name,
        "LLM": llm().name,
    }


def reset() -> None:
    """Clear cached adapters — used by tests that flip env vars."""
    for fn in (text_to_image, transparent_image, matting, inpainter, glyph_detector,
               vision_glyph_detector, upscaler, embedder, llm):
        fn.cache_clear()
