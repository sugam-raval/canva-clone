"""Which model, at which reasoning effort, runs each step of designing from a prompt —
from LIDO_PLAN_MODEL / LIDO_PLAN_REASONING_EFFORT and LIDO_LAYOUT_MODEL /
LIDO_LAYOUT_REASONING_EFFORT, turned into the arguments `LLM.complete_json` takes.

    step     model setting empty →           effort setting empty →
    plan     LLM_MODEL_FAST                  no reasoning
    layout   LLM_MODEL                       LLM_REASONING_EFFORT (for LLM_MODEL), else none

Naming LLM_MODEL itself as the layout model keeps its configured reasoning, so
"LIDO_LAYOUT_MODEL=gpt-6-astra" no longer silently turns astra's thinking off.
"""

from __future__ import annotations

from app.config import get_settings


def _options(name: str, effort: str) -> dict:
    s = get_settings()
    name, effort = name.strip(), effort.strip()
    if effort:  # an explicit effort: that model, with reasoning at that effort
        return {"model": name or s.llm_model, "reasoning_effort": effort}
    if not name or name == s.llm_model:
        return {"model": None}  # LLM_MODEL with its own LLM_REASONING_EFFORT, if any
    return {"model": name}  # another model, no reasoning (e.g. gpt-4o)


def plan_call() -> dict:
    s = get_settings()
    return _options(s.lido_plan_model or s.llm_model_fast, s.lido_plan_reasoning_effort)


def layout_call() -> dict:
    s = get_settings()
    return _options(s.lido_layout_model, s.lido_layout_reasoning_effort)


def repair_call() -> dict:
    """LIDO_REPAIR_MODEL / LIDO_REPAIR_REASONING_EFFORT; both empty: the layout's own."""
    s = get_settings()
    if not s.lido_repair_model.strip() and not s.lido_repair_reasoning_effort.strip():
        return layout_call()
    return _options(s.lido_repair_model or s.lido_layout_model, s.lido_repair_reasoning_effort)


def describe(options: dict) -> str:
    s = get_settings()
    model = options.get("model") or s.llm_model
    effort = options.get("reasoning_effort") or (
        s.llm_reasoning_effort if options.get("model") is None else None)
    return f"{model}" + (f" (reasoning: {effort})" if effort else "")
