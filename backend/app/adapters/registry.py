"""Adapter selection for the Lido.js (template) flow.

`auto` picks the best implementation that is actually usable right now, so a missing API
key degrades to the stub instead of crashing. The embedding model used for template
matching lives in `app/lido_corpus/match_index.py`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import structlog

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
    """Native transparent generation (subject cutouts), else the stub."""
    settings = get_settings()
    choice = settings.adapter_transparent_image
    if choice in ("openai", "auto") and settings.has_openai:
        return _openai().OpenAITransparentImage()
    if choice == "openai" and not settings.has_openai:
        log.warning("adapter.fallback", capability="TransparentImage",
                    reason="no OPENAI_API_KEY")
    return stub.StubTransparentImage()


@lru_cache(maxsize=1)
def llm() -> Any:
    settings = get_settings()
    if settings.adapter_llm in ("openai", "auto") and settings.has_openai:
        return _openai().OpenAILLM()
    return stub.StubLLM()


def describe() -> dict[str, str]:
    """Which implementation each capability resolved to — surfaced at /v1/health.
    `LLM` names the configured model (LLM_MODEL), so a swap in .env is visible here."""
    from app.lido_corpus.match_index import embedder_name

    return {
        "TextToImage": text_to_image().name,
        "TransparentImage": transparent_image().name,
        "LLM": llm().name,
        "TemplateEmbedder": embedder_name(),
    }


def reset() -> None:
    """Clear cached adapters — used by tests that flip env vars."""
    for fn in (text_to_image, transparent_image, llm):
        fn.cache_clear()
