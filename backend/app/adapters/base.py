"""Model adapter interfaces — IMPLEMENTATION_PLAN §0.3.

"Treat every model as a swappable adapter behind an interface. Do not hardcode a
vendor." Each capability below has at least two implementations (a hosted one and a
local/stub one) selected by env var in `registry.py`.

Part Two capabilities (Segmenter, Detector, DepthEstimator, TextRecognizer, Vectorizer)
are intentionally absent: that pipeline is deferred.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)


class AdapterError(RuntimeError):
    """Recoverable adapter failure. The job runner retries, then degrades (§0.9)."""

    def __init__(self, message: str, *, recoverable: bool = True):
        super().__init__(message)
        self.recoverable = recoverable


@dataclass
class ImageResult:
    data: bytes
    mime: str
    width: int
    height: int
    model: str
    has_alpha: bool = False
    cost_cents: int = 0
    # Echoed back into GenerationParams so INV-2 holds for providers that support seeds.
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class TextBox:
    """Axis-aligned text region, normalised 0..1 of the image."""

    x: float
    y: float
    w: float
    h: float
    score: float = 1.0

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)


@dataclass
class LLMResult:
    parsed: Any
    raw: str
    model: str
    cost_cents: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class TextToImage(Protocol):
    name: str

    async def generate(
        self, *, prompt: str, negative_prompt: str = "", width: int = 1024,
        height: int = 1024, seed: int = 0, steps: int = 28, cfg: float = 4.5,
        quality: str = "medium",
    ) -> ImageResult: ...


class TransparentImage(Protocol):
    """Text-to-image with a real alpha channel — §1.4.2 Path A."""

    name: str

    async def generate(
        self, *, prompt: str, negative_prompt: str = "", width: int = 1024,
        height: int = 1024, seed: int = 0, steps: int = 30, cfg: float = 5.0,
        quality: str = "medium",
    ) -> ImageResult: ...


class Matting(Protocol):
    """Background removal producing a soft alpha — §1.4.2 Path B, §3.3 remove-bg."""

    name: str

    async def infer(self, image: bytes) -> bytes:
        """Return an 8-bit single-channel PNG alpha matte the size of the input."""
        ...


class Inpainter(Protocol):
    """Fill a masked region — §3.3 expand (outpaint) and erase."""

    name: str

    async def fill(self, image: bytes, mask: bytes, *, prompt: str = "",
                   negative_prompt: str = "") -> ImageResult:
        """`mask` is 8-bit; white (255) marks the pixels to regenerate."""
        ...


class GlyphDetector(Protocol):
    """Detection only, no recognition — enforces INV-1 via the §1.4.6 glyph gate."""

    name: str

    async def detect(self, image: bytes) -> list[TextBox]: ...


class Upscaler(Protocol):
    name: str

    async def upscale(self, image: bytes, scale: int = 2) -> ImageResult: ...


class Embedder(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class LLM(Protocol):
    name: str

    async def complete_json(
        self, *, system: str, user: str, schema: type[TModel], temperature: float = 0.2,
        model: str | None = None, max_tokens: int = 4096, reasoning_effort: str | None = None,
    ) -> LLMResult:
        """Return a `schema` instance. Implementations MUST constrain generation to the
        schema (§1.1, §1.3) rather than parsing free text and hoping."""
        ...
