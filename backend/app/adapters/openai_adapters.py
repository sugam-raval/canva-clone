"""OpenAI implementations of the §0.3 adapter interfaces.

Notes that matter for the invariants:

  * **INV-2 (reproducibility).** `gpt-image-1` exposes no seed parameter, so identical
    parameters do NOT reproduce byte-identical pixels. §0.2 scopes INV-2 to "where the
    provider supports seeds", so we still record every parameter (and the generated
    asset is content-addressed and cached by `gen_hash`, per §6.1, which means a repeat
    request returns the *same stored bytes* — reproducibility in practice, by cache
    rather than by seed). `params["seedSupported"] = False` records the caveat.
  * **Negative prompts.** The image API has no `negative_prompt` field, so it is folded
    into the prompt as an explicit exclusion clause. The §1.4.6 glyph gate is what
    actually enforces INV-1; negative prompts alone were never sufficient (Appendix A.1).
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
from typing import Any

from openai import APIError, APIStatusError, AsyncOpenAI, RateLimitError
from PIL import Image

from app.adapters.base import AdapterError, ImageResult, LLMResult, TextBox, TModel
from app.config import get_settings
from app.schema.openai_schema import response_format

# gpt-image-1 renders only these; §1.4.1 says ask for the nearest supported size then
# crop/scale to the exact canvas dimensions.
_SUPPORTED_SIZES = ((1024, 1024), (1024, 1536), (1536, 1024))

# Rough list prices in cents, for the §6.7 budget ledger. Approximate by design: the
# ledger exists to stop runaway spend, not to reconcile an invoice.
_IMAGE_COST_CENTS = {"low": 2, "medium": 4, "high": 17}
_LLM_COST_PER_MTOK = {"gpt-4o": (250, 1000), "gpt-4o-mini": (15, 60),
                      "text-embedding-3-small": (2, 0)}


def _client() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise AdapterError("OPENAI_API_KEY is not set", recoverable=False)
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
        timeout=180.0,
        max_retries=0,  # the job runner owns retry policy (§0.9)
    )


def _llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> int:
    for key, (inp, out) in _LLM_COST_PER_MTOK.items():
        if model.startswith(key):
            cents = (prompt_tokens * inp + completion_tokens * out) / 1_000_000
            return max(0, round(cents))
    return 0


def nearest_supported_size(width: int, height: int) -> tuple[int, int]:
    """Pick the supported render size whose aspect ratio is closest to the target."""
    target = width / max(1, height)
    return min(_SUPPORTED_SIZES, key=lambda s: abs(math.log((s[0] / s[1]) / target)))


def fit_to_canvas(data: bytes, width: int, height: int, *, keep_alpha: bool) -> bytes:
    """Resize-cover then centre-crop to exactly (width, height).

    §1.4.1: "Never stretch non-uniformly."
    """
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGBA" if keep_alpha else "RGB")
        scale = max(width / img.width, height / img.height)
        new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(new_size, Image.LANCZOS)
        left = (img.width - width) // 2
        top = (img.height - height) // 2
        img = img.crop((left, top, left + width, top + height))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        return buf.getvalue()


def compose_prompt(prompt: str, negative_prompt: str) -> str:
    """Fold the negative prompt in, since the image API has no field for it."""
    prompt = prompt.strip()
    if not negative_prompt.strip():
        return prompt
    return (
        f"{prompt}\n\n"
        f"Absolutely do not include any of the following in the image: "
        f"{negative_prompt.strip()}."
    )


async def _call_images(client: AsyncOpenAI, **kwargs) -> Any:
    try:
        return await client.images.generate(**kwargs)
    except RateLimitError as exc:
        raise AdapterError(f"rate limited: {exc}", recoverable=True) from exc
    except APIStatusError as exc:
        recoverable = exc.status_code in (408, 409, 429) or exc.status_code >= 500
        raise AdapterError(f"image API {exc.status_code}: {exc}",
                           recoverable=recoverable) from exc
    except APIError as exc:
        raise AdapterError(f"image API error: {exc}", recoverable=True) from exc


def _decode_first(result: Any) -> bytes:
    data = getattr(result, "data", None)
    if not data:
        raise AdapterError("image API returned no data")
    b64 = getattr(data[0], "b64_json", None)
    if not b64:
        raise AdapterError("image API returned no b64_json payload")
    return base64.b64decode(b64)


class OpenAITextToImage:
    name = "openai:gpt-image-1"

    async def generate(self, *, prompt: str, negative_prompt: str = "", width: int = 1024,
                       height: int = 1024, seed: int = 0, steps: int = 28,
                       cfg: float = 4.5, quality: str = "medium") -> ImageResult:
        settings = get_settings()
        render_w, render_h = nearest_supported_size(width, height)
        result = await _call_images(
            _client(),
            model=settings.image_model,
            prompt=compose_prompt(prompt, negative_prompt),
            size=f"{render_w}x{render_h}",
            quality=quality,
            n=1,
            output_format="png",
        )
        data = fit_to_canvas(_decode_first(result), width, height, keep_alpha=False)
        return ImageResult(
            data=data, mime="image/png", width=width, height=height,
            model=settings.image_model, has_alpha=False,
            cost_cents=_IMAGE_COST_CENTS.get(quality, 4),
            params={"renderSize": f"{render_w}x{render_h}", "quality": quality,
                    "seedSupported": False, "requestedSeed": seed},
        )


class OpenAITransparentImage:
    """§1.4.2 Path A — native transparent generation. Cleanest edges, no matting."""

    name = "openai:gpt-image-1/transparent"

    async def generate(self, *, prompt: str, negative_prompt: str = "", width: int = 1024,
                       height: int = 1024, seed: int = 0, steps: int = 30,
                       cfg: float = 5.0, quality: str = "medium") -> ImageResult:
        settings = get_settings()
        render_w, render_h = nearest_supported_size(width, height)
        result = await _call_images(
            _client(),
            model=settings.image_model,
            prompt=compose_prompt(prompt, negative_prompt),
            size=f"{render_w}x{render_h}",
            quality=quality,
            n=1,
            background="transparent",
            output_format="png",
        )
        raw = _decode_first(result)
        # Do NOT cover-crop a cutout: cropping can slice through the subject. Trim the
        # transparent border and letterbox instead (§1.4.2 trim_transparent_border).
        data = trim_and_fit_alpha(raw, width, height)
        return ImageResult(
            data=data, mime="image/png", width=width, height=height,
            model=settings.image_model, has_alpha=True,
            cost_cents=_IMAGE_COST_CENTS.get(quality, 4),
            params={"renderSize": f"{render_w}x{render_h}", "quality": quality,
                    "background": "transparent", "seedSupported": False,
                    "requestedSeed": seed},
        )


def trim_and_fit_alpha(data: bytes, width: int, height: int) -> bytes:
    """Trim the transparent border to a tight bbox, then fit inside (width, height)
    preserving aspect. Used for subjects, where cropping would cut the product."""
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGBA")
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        scale = min(width / img.width, height / img.height)
        new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(new_size, Image.LANCZOS)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.paste(img, ((width - img.width) // 2, (height - img.height) // 2))
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()


class OpenAIInpainter:
    name = "openai:gpt-image-1/edit"

    async def fill(self, image: bytes, mask: bytes, *, prompt: str = "",
                   negative_prompt: str = "") -> ImageResult:
        settings = get_settings()
        client = _client()
        # The edits endpoint regenerates where the mask is TRANSPARENT, which is the
        # inverse of our convention (white = regenerate). Convert here.
        api_mask = _to_api_mask(mask, image)
        try:
            result = await client.images.edit(
                model=settings.image_model,
                image=("image.png", image, "image/png"),
                mask=("mask.png", api_mask, "image/png"),
                prompt=compose_prompt(prompt or "seamlessly continue the surrounding "
                                      "scene with consistent lighting", negative_prompt),
                n=1,
            )
        except RateLimitError as exc:
            raise AdapterError(f"rate limited: {exc}", recoverable=True) from exc
        except APIStatusError as exc:
            raise AdapterError(f"edit API {exc.status_code}: {exc}",
                               recoverable=exc.status_code >= 500) from exc
        data = _decode_first(result)
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.width, img.height
        return ImageResult(data=data, mime="image/png", width=w, height=h,
                           model=settings.image_model, has_alpha=True,
                           cost_cents=_IMAGE_COST_CENTS["medium"])


def _to_api_mask(mask: bytes, reference: bytes) -> bytes:
    """Our masks are white-where-regenerate; the API wants alpha-zero-where-regenerate."""
    with Image.open(io.BytesIO(mask)) as m, Image.open(io.BytesIO(reference)) as ref:
        m = m.convert("L").resize((ref.width, ref.height), Image.NEAREST)
        rgba = Image.new("RGBA", m.size, (0, 0, 0, 255))
        # alpha = 255 - mask: opaque where we keep, transparent where we regenerate.
        rgba.putalpha(Image.eval(m, lambda v: 255 - v))
        buf = io.BytesIO()
        rgba.save(buf, format="PNG")
        return buf.getvalue()


class OpenAIEmbedder:
    name = "openai:text-embedding-3-small"

    def __init__(self) -> None:
        self.dim = get_settings().embedding_dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        settings = get_settings()
        try:
            result = await _client().embeddings.create(
                model=settings.embedding_model, input=texts,
            )
        except APIError as exc:
            raise AdapterError(f"embedding API error: {exc}") from exc
        return [item.embedding for item in result.data]


class OpenAIVisionGlyphDetector:
    """Vision-model text detection for the §1.4.6 glyph gate.

    Used as the escalation path when the cheap local detector is uncertain: a vision
    call per generated image would dominate the §6 latency budget.
    """

    name = "openai:vision-glyph"

    async def detect(self, image: bytes) -> list[TextBox]:
        from pydantic import BaseModel, Field

        class _Box(BaseModel):
            x: float = Field(ge=0, le=1)
            y: float = Field(ge=0, le=1)
            w: float = Field(ge=0, le=1)
            h: float = Field(ge=0, le=1)

        class _Boxes(BaseModel):
            has_text: bool
            boxes: list[_Box]

        b64 = base64.b64encode(image).decode()
        llm = OpenAILLM()
        result = await llm.complete_json(
            system=(
                "You detect rendered text in images. Report every region containing "
                "letters, numerals or wordmarks as a normalised bounding box (0..1). "
                "Ignore textures that merely resemble writing. Report nothing else."
            ),
            user=[  # type: ignore[arg-type]
                {"type": "text", "text": "List all text regions in this image."},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}},
            ],
            schema=_Boxes,
            model=get_settings().llm_model_fast,
            temperature=0.0,
        )
        parsed: Any = result.parsed
        if not parsed.has_text:
            return []
        return [TextBox(x=b.x, y=b.y, w=b.w, h=b.h, score=1.0) for b in parsed.boxes]


class OpenAILLM:
    """Structured-output LLM. Generation is constrained to the Pydantic schema, so an
    invalid `DesignBrief` or `ComposerOutput` is not merely unlikely — it is unpresentable
    (§1.1, §1.3)."""

    name = "openai:llm"

    async def complete_json(self, *, system: str, user: str, schema: type[TModel],
                            temperature: float = 0.2, model: str | None = None,
                            max_tokens: int = 4096) -> LLMResult:
        settings = get_settings()
        model = model or settings.llm_model
        content: Any = user
        try:
            completion = await _client().chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                response_format=response_format(schema),
            )
        except RateLimitError as exc:
            raise AdapterError(f"rate limited: {exc}", recoverable=True) from exc
        except APIStatusError as exc:
            raise AdapterError(f"LLM API {exc.status_code}: {exc}",
                               recoverable=exc.status_code >= 500) from exc
        except APIError as exc:
            raise AdapterError(f"LLM API error: {exc}") from exc

        choice = completion.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            raise AdapterError("LLM response was truncated before the schema closed")
        raw = choice.message.content or ""
        if getattr(choice.message, "refusal", None):
            raise AdapterError(f"model refused: {choice.message.refusal}",
                               recoverable=False)
        try:
            parsed = schema.model_validate_json(raw)
        except Exception as exc:
            raise AdapterError(f"schema-constrained output failed validation: {exc}") from exc

        usage = completion.usage
        p_tok = getattr(usage, "prompt_tokens", 0) or 0
        c_tok = getattr(usage, "completion_tokens", 0) or 0
        return LLMResult(parsed=parsed, raw=raw, model=model,
                         cost_cents=_llm_cost(model, p_tok, c_tok),
                         prompt_tokens=p_tok, completion_tokens=c_tok)


async def _gather_limited(coros: list, limit: int = 4) -> list:
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)
