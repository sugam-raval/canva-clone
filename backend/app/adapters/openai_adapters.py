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

import base64
import io
import math
import re
from typing import Any

import structlog
from openai import APIError, APIStatusError, AsyncOpenAI, RateLimitError
from PIL import Image

from app.adapters.base import AdapterError, ImageResult, LLMResult, TModel
from app.adapters.openai_schema import response_format
from app.config import get_settings

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


_MAX_COMPLETION_TOKENS_RE = re.compile(r"at most (\d+) completion tokens")


def _completion_token_ceiling(exc: APIStatusError) -> int | None:
    """The model's real completion-token limit, parsed from "this model supports at
    most N completion tokens, whereas you provided ...", or None if that is not why
    the request was rejected."""
    if exc.status_code != 400:
        return None
    match = _MAX_COMPLETION_TOKENS_RE.search(str(exc))
    return int(match.group(1)) if match else None


def _clamp_max_tokens(kwargs: dict, ceiling: int) -> None:
    for key in ("max_tokens", "max_completion_tokens"):
        if key in kwargs and kwargs[key] > ceiling:
            kwargs[key] = ceiling


_REQUIRED_REASONING_EFFORT_RE = re.compile(r"Supported values are: '(\w+)'")


def _required_reasoning_effort(exc: APIStatusError) -> str | None:
    """The one `reasoning.effort` value a model insists on (gpt-5-pro accepts only
    'high' and rejects the global LLM_REASONING_EFFORT default of 'low' with
    "Unsupported value: 'low' ... Supported values are: 'high'."), or None if that is
    not why the request was rejected."""
    if exc.status_code != 400 or exc.param != "reasoning.effort":
        return None
    match = _REQUIRED_REASONING_EFFORT_RE.search(str(exc))
    return match.group(1) if match else None


def _responses_only_model(exc: APIStatusError) -> bool:
    """True when a model was rejected by chat.completions because it only exists on
    the Responses API (gpt-5-pro: "This model is only supported in v1/responses and
    not in v1/chat/completions") — i.e. it needs the reasoning path regardless of
    whether LLM_REASONING_EFFORT happens to be set."""
    return exc.status_code == 404 and "v1/responses" in str(exc)


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


class OpenAILLM:
    """Structured-output LLM. Generation is constrained to the Pydantic schema, so an
    invalid `DesignBrief` or `ComposerOutput` is not merely unlikely — it is unpresentable
    (§1.1, §1.3)."""

    @property
    def name(self) -> str:
        """Surfaced at /v1/health and in warmup.complete — states the actual configured
        model (LLM_MODEL), not just "openai:llm", so a model swap in .env is visible
        without having to trigger a real generation to confirm it took effect."""
        settings = get_settings()
        effort = (settings.llm_reasoning_effort or "").strip()
        suffix = f" (thinking:{effort})" if effort else ""
        return f"openai:{settings.llm_model}{suffix}"

    # model -> params that model rejected, learned from its 400s so we pay them once.
    _rejected_params: dict[str, set[str]] = {}
    # model -> its real completion-token ceiling, learned the same way. A caller like
    # generate_ai.py sizes max_tokens for a reasoning model's hidden thinking tokens;
    # a plain chat model (gpt-4o and friends: 16384) rejects that outright.
    _max_completion_tokens: dict[str, int] = {}
    # model -> the only `reasoning.effort` value it accepts (e.g. gpt-5-pro: "high"),
    # learned from its 400s the same way.
    _required_reasoning_effort: dict[str, str] = {}
    # Models that exist only on the Responses API, learned from a chat.completions
    # 404 — so LLM_REASONING_EFFORT does not need to be set just to reach them.
    _responses_only_models: set[str] = set()

    @classmethod
    async def _create_completion(cls, kwargs: dict[str, Any]):
        """Reasoning models (o-series, gpt-5/6 'thinking' variants) reject `temperature`
        and `max_tokens`, wanting `max_completion_tokens` and their fixed temperature
        instead. Rather than hardcode a model list that goes stale as OpenAI ships new
        ones, adapt to whichever parameter the API actually rejects."""
        model = kwargs["model"]
        rejected = cls._rejected_params.setdefault(model, set())
        ceiling = cls._max_completion_tokens.get(model)
        if ceiling is not None:
            _clamp_max_tokens(kwargs, ceiling)

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
        for attempt in range(4):
            try:
                return await client.chat.completions.create(**kwargs)
            except APIStatusError as exc:
                new_ceiling = _completion_token_ceiling(exc)
                if new_ceiling is not None:
                    cls._max_completion_tokens[model] = new_ceiling
                    _clamp_max_tokens(kwargs, new_ceiling)
                    continue
                if (attempt == 3 or exc.status_code != 400
                        or exc.code not in ("unsupported_parameter", "unsupported_value")
                        or not adapt(exc.param or "")):
                    raise
                rejected.add(exc.param)
        raise AssertionError("unreachable")

    async def complete_json(self, *, system: str, user: str, schema: type[TModel],
                            temperature: float = 0.2, model: str | None = None,
                            max_tokens: int = 4096,
                            reasoning_effort: str | None = None) -> LLMResult:
        settings = get_settings()
        # An explicit `model=` (e.g. the glyph detector's llm_model_fast) always means
        # "use this exact non-reasoning model" and skips the Responses/reasoning path,
        # even when LLM_REASONING_EFFORT is set for the default llm_model.
        # `reasoning_effort` only raises/lowers effort for a model already configured as
        # a reasoning model; it never pushes a non-reasoning llm_model onto that path.
        global_effort = (settings.llm_reasoning_effort or "").strip() or None
        effort = (reasoning_effort or global_effort) if model is None and global_effort else None
        model = model or settings.llm_model
        # A model that only exists on the Responses API (gpt-5-pro) needs that path
        # even with no effort configured — otherwise every call 404s on chat.completions
        # first. Once learned (below), skip straight there.
        if effort or model in self._responses_only_models:
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
            if _responses_only_model(exc):
                self._responses_only_models.add(model)
                return await self._complete_json_reasoning(
                    system=system, user=user, schema=schema, model=model,
                    effort=None, max_tokens=max_tokens)
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

    @classmethod
    async def _create_response(cls, kwargs: dict[str, Any]):
        """Mirrors `_create_completion`'s self-healing: some reasoning models accept
        only one `reasoning.effort` value (gpt-5-pro: 'high' only) and reject any
        other the caller happens to be configured with. Learn it from the API's own
        400 and pin it for this model, the same way a completion-token ceiling is."""
        model = kwargs["model"]
        required = cls._required_reasoning_effort.get(model)
        if required is not None:
            kwargs = {**kwargs, "reasoning": {"effort": required}}
        client = _client()
        for attempt in range(2):
            try:
                return await client.responses.parse(**kwargs)
            except APIStatusError as exc:
                value = _required_reasoning_effort(exc)
                if attempt == 1 or value is None:
                    raise
                cls._required_reasoning_effort[model] = value
                kwargs = {**kwargs, "reasoning": {"effort": value}}
        raise AssertionError("unreachable")

    async def _complete_json_reasoning(self, *, system: str, user: str, schema: type[TModel],
                                       model: str, effort: str | None,
                                       max_tokens: int) -> LLMResult:
        """Reasoning models (gpt-6-astra, the gpt-5 family, and friends) are called
        through the Responses API with `reasoning.effort` rather than chat.completions'
        `temperature`, which they reject outright. `effort` may be None (no
        LLM_REASONING_EFFORT configured, or a model reached only because it turned out
        to be Responses-only) — the API then applies its own default rather than
        rejecting the call. `max_output_tokens` also has to cover the model's hidden
        reasoning tokens, not just the visible answer, so give it more headroom than the
        chat path's `max_tokens` needs."""
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": system,
            "input": user,
            "text_format": schema,
            "max_output_tokens": max(max_tokens, 16000),
        }
        if effort:
            kwargs["reasoning"] = {"effort": effort}
        try:
            response = await self._create_response(kwargs)
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
