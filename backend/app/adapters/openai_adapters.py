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

import structlog
from openai import APIError, APIStatusError, AsyncOpenAI, RateLimitError
from PIL import Image

from app.adapters.base import AdapterError, ImageResult, LLMResult, TextBox, TModel
from app.config import get_settings
from app.schema.openai_schema import response_format

log = structlog.get_logger(__name__)

# `gpt-image-1` renders only these three; §1.4.1 says ask for the nearest supported
# size then crop/scale to the exact canvas dimensions.
_SUPPORTED_SIZES = ((1024, 1024), (1024, 1536), (1536, 1024))

# `gpt-image-2` and later accept any size whose width and height are both divisible by
# 16, which changes the §1.4.1 story materially. Asking the fixed 1024x1024 for a
# 1080x1350 poster meant cover-cropping 135px off the top and bottom of the render —
# and the top is exactly where `background.safe_zone` asked for calm, empty space for
# the headline. The crop was quietly throwing away the composition the prompt had just
# paid for. On a flexible model we render at the canvas's own aspect ratio instead, so
# `fit_to_canvas` only ever rescales.
_FIXED_SIZE_MODEL_PREFIXES = ("gpt-image-1", "dall-e")
_FLEX_SIZE_MULTIPLE = 16
_FLEX_TARGET_PIXELS = 1024 * 1024
"""Pixel budget a flexible render is scaled to hit.

Not a minimum or maximum edge: the API's own floor is a *pixel budget* ("requested
resolution is below the current minimum pixel budget" — 768x768 is refused where
960x704 is accepted), so an edge-based clamp both fails that floor on small frames and
lets cost drift with the canvas shape. Scaling the canvas's ratio to a fixed area
instead keeps every render the same size and the same price as the old 1024x1024,
whatever the poster's proportions are.
"""

_FLEX_MAX_ASPECT = 3.0
"""The API's own limit: "the maximum supported aspect ratio is 3:1". Clamping to it
here beats letting the request be refused and retried at a fixed size — the retry
succeeds but comes back square, and cover-cropping a square into a wide banner frame
throws away two thirds of what was generated.
"""


def supports_flexible_size(model: str) -> bool:
    return not model.startswith(_FIXED_SIZE_MODEL_PREFIXES)


def _round_to(value: float, multiple: int) -> int:
    return max(multiple, round(value / multiple) * multiple)


def flexible_size(width: int, height: int) -> tuple[int, int]:
    """The canvas's aspect ratio, clamped to 3:1, at the target pixel budget, /16.

    A frame past 3:1 renders at 3:1 and `fit_to_canvas` crops the rest — the closest
    legal shape to what was asked for, rather than the square the provider's own
    fallback would hand back.
    """
    width, height = max(1, width), max(1, height)
    ratio = min(max(width / height, 1 / _FLEX_MAX_ASPECT), _FLEX_MAX_ASPECT)
    render_h = _round_to(math.sqrt(_FLEX_TARGET_PIXELS / ratio), _FLEX_SIZE_MULTIPLE)
    render_w = _round_to(render_h * ratio, _FLEX_SIZE_MULTIPLE)
    # Rounding one edge up and the other down can carry a 3:1 request just past 3:1,
    # which the API refuses outright — so give the short edge one more step.
    while render_w / render_h > _FLEX_MAX_ASPECT:
        render_h += _FLEX_SIZE_MULTIPLE
    while render_h / render_w > _FLEX_MAX_ASPECT:
        render_w += _FLEX_SIZE_MULTIPLE
    return render_w, render_h


def render_size(model: str, width: int, height: int) -> tuple[int, int]:
    """The size to actually ask the provider for, given which model is in use."""
    if supports_flexible_size(model):
        return flexible_size(width, height)
    return nearest_supported_size(width, height)

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
        # Ahead of APIStatusError, which it subclasses — the other way round this
        # branch never runs.
        raise AdapterError(f"rate limited: {exc}", recoverable=True) from exc
    except APIStatusError as exc:
        # A model we believed was flexible rejecting the size is the one provider
        # difference worth absorbing rather than failing on: retry once at the nearest
        # fixed size instead of returning no image at all. Any other status is a real
        # error and is translated as before.
        retry = _fixed_size_retry(exc, kwargs)
        if retry is None:
            raise _as_adapter_error(exc) from exc
        try:
            return await client.images.generate(**retry)
        except APIError as inner:
            raise _as_adapter_error(inner) from inner
    except APIError as exc:
        raise AdapterError(f"image API error: {exc}", recoverable=True) from exc


def _as_adapter_error(exc: APIError) -> AdapterError:
    status = getattr(exc, "status_code", None)
    if status is None:
        return AdapterError(f"image API error: {exc}", recoverable=True)
    recoverable = status in (408, 409, 429) or status >= 500
    return AdapterError(f"image API {status}: {exc}", recoverable=recoverable)


def _fixed_size_retry(exc: APIStatusError, kwargs: dict) -> dict | None:
    """The same request at a fixed supported size, or None if that is not the problem."""
    if exc.status_code != 400 or "size" not in str(exc).lower():
        return None
    size = str(kwargs.get("size", ""))
    if "x" not in size:
        return None
    try:
        width, height = (int(part) for part in size.split("x", 1))
    except ValueError:
        return None
    fallback_w, fallback_h = nearest_supported_size(width, height)
    if (fallback_w, fallback_h) == (width, height):
        return None  # already fixed-size; retrying would send the identical request
    log.warning("adapter.size_fallback", requested=size,
                fallback=f"{fallback_w}x{fallback_h}")
    return {**kwargs, "size": f"{fallback_w}x{fallback_h}"}


def _decode_first(result: Any) -> bytes:
    data = getattr(result, "data", None)
    if not data:
        raise AdapterError("image API returned no data")
    b64 = getattr(data[0], "b64_json", None)
    if not b64:
        raise AdapterError("image API returned no b64_json payload")
    return base64.b64decode(b64)


class OpenAITextToImage:
    @property
    def name(self) -> str:
        return f"openai:{get_settings().image_model}"

    async def generate(self, *, prompt: str, negative_prompt: str = "", width: int = 1024,
                       height: int = 1024, seed: int = 0, steps: int = 28,
                       cfg: float = 4.5, quality: str = "medium") -> ImageResult:
        settings = get_settings()
        render_w, render_h = render_size(settings.image_model, width, height)
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

    @property
    def name(self) -> str:
        return f"openai:{get_settings().image_model}/transparent"

    async def generate(self, *, prompt: str, negative_prompt: str = "", width: int = 1024,
                       height: int = 1024, seed: int = 0, steps: int = 30,
                       cfg: float = 5.0, quality: str = "medium") -> ImageResult:
        settings = get_settings()
        render_w, render_h = render_size(settings.image_model, width, height)
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
    @property
    def name(self) -> str:
        return f"openai:{get_settings().image_model}/edit"

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

    # model -> params that model rejected, learned from its 400s so we pay them once.
    _rejected_params: dict[str, set[str]] = {}

    @classmethod
    async def _create_completion(cls, kwargs: dict[str, Any]):
        """Reasoning models (o-series, gpt-5/6 'thinking' variants) reject `temperature`
        and `max_tokens`, wanting `max_completion_tokens` and their fixed temperature
        instead. Rather than hardcode a model list that goes stale as OpenAI ships new
        ones, adapt to whichever parameter the API actually rejects."""
        rejected = cls._rejected_params.setdefault(kwargs["model"], set())

        def adapt(param: str) -> bool:
            if param == "max_tokens" and "max_tokens" in kwargs:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
            elif param == "temperature" and "temperature" in kwargs:
                kwargs.pop("temperature")
            else:
                return False
            return True

        for param in rejected:
            adapt(param)
        client = _client()
        for attempt in range(3):
            try:
                return await client.chat.completions.create(**kwargs)
            except APIStatusError as exc:
                if (attempt == 2 or exc.status_code != 400
                        or exc.code not in ("unsupported_parameter", "unsupported_value")
                        or not adapt(exc.param or "")):
                    raise
                rejected.add(exc.param)
        raise AssertionError("unreachable")

    async def complete_json(self, *, system: str, user: str, schema: type[TModel],
                            temperature: float = 0.2, model: str | None = None,
                            max_tokens: int = 4096) -> LLMResult:
        settings = get_settings()
        # An explicit `model=` (e.g. the glyph detector's llm_model_fast) always means
        # "use this exact non-reasoning model" and skips the Responses/reasoning path,
        # even when LLM_REASONING_EFFORT is set for the default llm_model.
        effort = settings.llm_reasoning_effort if model is None else None
        model = model or settings.llm_model
        if effort:
            return await self._complete_json_reasoning(
                system=system, user=user, schema=schema, model=model,
                effort=effort, max_tokens=max_tokens)
        return await self._complete_json_chat(
            system=system, user=user, schema=schema, model=model,
            temperature=temperature, max_tokens=max_tokens)

    async def _complete_json_chat(self, *, system: str, user: str, schema: type[TModel],
                                  temperature: float, model: str, max_tokens: int) -> LLMResult:
        kwargs: dict[str, Any] = dict(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=response_format(schema),
        )
        try:
            completion = await self._create_completion(kwargs)
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

    async def _complete_json_reasoning(self, *, system: str, user: str, schema: type[TModel],
                                       model: str, effort: str, max_tokens: int) -> LLMResult:
        """Reasoning models (gpt-6-astra and friends) are called through the Responses
        API with `reasoning.effort` rather than chat.completions' `temperature`, which
        they reject outright. `max_output_tokens` also has to cover the model's hidden
        reasoning tokens, not just the visible answer, so give it more headroom than the
        chat path's `max_tokens` needs."""
        client = _client()
        try:
            response = await client.responses.parse(
                model=model,
                instructions=system,
                input=user,
                text_format=schema,
                reasoning={"effort": effort},
                max_output_tokens=max(max_tokens, 16000),
            )
        except RateLimitError as exc:
            raise AdapterError(f"rate limited: {exc}", recoverable=True) from exc
        except APIStatusError as exc:
            raise AdapterError(f"LLM API {exc.status_code}: {exc}",
                               recoverable=exc.status_code >= 500) from exc
        except APIError as exc:
            raise AdapterError(f"LLM API error: {exc}") from exc

        if response.status == "incomplete":
            reason = (response.incomplete_details.reason if response.incomplete_details
                      else "unknown")
            raise AdapterError(f"LLM response was truncated before the schema closed "
                               f"({reason})")
        parsed = response.output_parsed
        if parsed is None:
            raise AdapterError("model refused or returned no parsable output",
                               recoverable=False)

        usage = response.usage
        p_tok = getattr(usage, "input_tokens", 0) or 0
        c_tok = getattr(usage, "output_tokens", 0) or 0
        return LLMResult(parsed=parsed, raw=response.output_text, model=model,
                         cost_cents=_llm_cost(model, p_tok, c_tok),
                         prompt_tokens=p_tok, completion_tokens=c_tok)


async def _gather_limited(coros: list, limit: int = 4) -> list:
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)
