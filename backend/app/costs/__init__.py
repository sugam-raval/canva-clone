"""What each OpenAI call costs, and the running bill of one piece of work.

    pricing.yaml   the price list (USD per 1M tokens) — edit it when OpenAI's prices change

Prices: `text_cost()` / `image_cost()` turn the token counts OpenAI returns with every
call into dollars. A model missing from the price list gives None ("unknown"), never 0.

The bill: wrap a piece of work in `collect(ledger)` and every call the OpenAI adapters
make inside it — however deep, in any task started inside it — is added to `ledger` as
a `Charge` (`record_text`, `record_image`). `step("plan")` labels the charges made inside
it. A call that was abandoned before OpenAI answered (a timed-out image, a cancelled
draft) is recorded with `record_unknown`: OpenAI may still bill it, so it is counted, not
hidden. `summary()` adds a ledger up.

Context variables carry the ledger and step into every asyncio task created inside
`collect()`/`step()`, so concurrent drafts and photos each land on the right bill.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import structlog
import yaml

log = structlog.get_logger(__name__)

PRICING_FILE = Path(__file__).parent / "pricing.yaml"
PER_TOKEN = 1 / 1_000_000  # prices are per 1M tokens


@dataclass
class Charge:
    step: str  # plan | design | repair | photo | … (what the call was for)
    model: str
    kind: str  # text | image
    input_tokens: int = 0  # text: prompt tokens (cached ones included); image: text prompt
    cached_tokens: int = 0  # text: prompt tokens served from OpenAI's cache
    image_input_tokens: int = 0  # image: reference images sent along
    output_tokens: int = 0  # text: reply incl. reasoning; image: the generated picture
    usd: float | None = None  # None: not priced (unknown model, or no usage came back)
    note: str = ""  # why the cost is unknown (timed out, cancelled…)


_LEDGER: contextvars.ContextVar[list[Charge] | None] = contextvars.ContextVar(
    "cost_ledger", default=None)
_STEP: contextvars.ContextVar[str] = contextvars.ContextVar("cost_step", default="other")


# -- prices ------------------------------------------------------------------------------


@cache
def prices() -> dict[str, dict[str, dict[str, float]]]:
    data = yaml.safe_load(PRICING_FILE.read_text()) or {}
    return {group: {str(m): {k: float(v) for k, v in (rates or {}).items()}
                    for m, rates in (data.get(group) or {}).items()}
            for group in ("text", "images")}


def _rates(group: str, model: str) -> dict[str, float] | None:
    """The price entry for `model`: its own, or the longest listed name it starts with."""
    table = prices()[group]
    if model in table:
        return table[model]
    matches = [name for name in table if model.startswith(name)]
    return table[max(matches, key=len)] if matches else None


def text_cost(model: str, input_tokens: int, cached_tokens: int,
              output_tokens: int) -> float | None:
    """USD for one text call (cached prompt tokens at the cached rate)."""
    r = _rates("text", model)
    if r is None:
        return None
    cached = min(cached_tokens, input_tokens)
    return ((input_tokens - cached) * r["input"]
            + cached * r.get("cached_input", r["input"])
            + output_tokens * r["output"]) * PER_TOKEN


def image_cost(model: str, text_input_tokens: int, image_input_tokens: int,
               output_tokens: int) -> float | None:
    """USD for one image call."""
    r = _rates("images", model)
    if r is None:
        return None
    return (text_input_tokens * r.get("text_input", 0)
            + image_input_tokens * r.get("image_input", 0)
            + output_tokens * r["output"]) * PER_TOKEN


# -- the bill ----------------------------------------------------------------------------


@contextmanager
def collect(ledger: list[Charge]) -> Iterator[list[Charge]]:
    """Every charge made inside (in this task and the tasks it starts) goes on `ledger`."""
    token = _LEDGER.set(ledger)
    try:
        yield ledger
    finally:
        _LEDGER.reset(token)


@contextmanager
def step(name: str) -> Iterator[None]:
    """Label the charges made inside as `name` (plan, design, repair, photo…)."""
    token = _STEP.set(name)
    try:
        yield
    finally:
        _STEP.reset(token)


def _add(charge: Charge) -> Charge:
    ledger = _LEDGER.get()
    if ledger is not None:
        ledger.append(charge)
    return charge


def _int(value: Any) -> int:
    return int(value or 0)


def record_text(model: str, usage: Any) -> Charge:
    """A finished text call, from its `usage` (chat completions or Responses API)."""
    # Responses API: input/output_tokens; chat completions: prompt/completion_tokens
    inp = _int(getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None))
    out = _int(getattr(usage, "output_tokens", None)
               or getattr(usage, "completion_tokens", None))
    details = (getattr(usage, "input_tokens_details", None)
               or getattr(usage, "prompt_tokens_details", None))
    cached = _int(getattr(details, "cached_tokens", None))
    usd = text_cost(model, inp, cached, out)
    return _add(Charge(_STEP.get(), model, "text", input_tokens=inp, cached_tokens=cached,
                       output_tokens=out, usd=usd,
                       note="" if usd is not None else "model not in costs/pricing.yaml"))


def record_image(model: str, usage: Any) -> Charge:
    """A finished image call, from the `usage` the Images API returns."""
    if usage is None:
        return record_unknown(model, "image", "the API returned no usage")
    details = getattr(usage, "input_tokens_details", None)
    text_in = _int(getattr(details, "text_tokens", None)) if details else _int(
        getattr(usage, "input_tokens", None))
    image_in = _int(getattr(details, "image_tokens", None)) if details else 0
    out = _int(getattr(usage, "output_tokens", None))
    usd = image_cost(model, text_in, image_in, out)
    return _add(Charge(_STEP.get(), model, "image", input_tokens=text_in,
                       image_input_tokens=image_in, output_tokens=out, usd=usd,
                       note="" if usd is not None else "model not in costs/pricing.yaml"))


def record_unknown(model: str, kind: str, note: str, step_name: str | None = None) -> Charge:
    """A call OpenAI may bill but whose usage we never saw (abandoned before it answered)."""
    return _add(Charge(step_name or _STEP.get(), model, kind, usd=None, note=note))


def summary(ledger: list[Charge]) -> dict[str, Any]:
    """The bill: total, per step, and every call (camelCase: stored as is)."""
    by_step: dict[str, float] = {}
    for c in ledger:
        if c.usd is not None:
            by_step[c.step] = by_step.get(c.step, 0.0) + c.usd
    unknown = [c for c in ledger if c.usd is None]
    return {
        "totalUsd": round(sum(by_step.values()), 6),
        "byStepUsd": {k: round(v, 6) for k, v in by_step.items()},
        "unknownCalls": len(unknown),
        "calls": [{"step": c.step, "model": c.model, "kind": c.kind,
                   "inputTokens": c.input_tokens, "cachedTokens": c.cached_tokens,
                   "imageInputTokens": c.image_input_tokens,
                   "outputTokens": c.output_tokens,
                   "usd": None if c.usd is None else round(c.usd, 6),
                   **({"note": c.note} if c.note else {})} for c in ledger],
        "pricing": "backend/app/costs/pricing.yaml",
    }
