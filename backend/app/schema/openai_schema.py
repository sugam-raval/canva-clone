"""Pydantic JSON Schema -> OpenAI Structured Outputs (strict) JSON Schema.

IMPLEMENTATION_PLAN §1.1 and §1.3 require the LLM to be constrained against the same
schema the rest of the system validates with, so drift is impossible. Pydantic emits
full JSON Schema; OpenAI's strict mode accepts only a subset. This module performs the
lossless-where-it-matters conversion:

  * every object gets `additionalProperties: false`
  * every property is listed in `required` (optionality is expressed as a `null` union,
    which is what strict mode demands)
  * validation keywords strict mode rejects (pattern, minimum, minLength, ...) are
    stripped from the schema and re-applied by Pydantic on the way back in, so the
    constraint is still enforced — just one step later
  * `oneOf` -> `anyOf`, single-element `allOf` flattened, `const` -> single-value `enum`
  * `default` removed (strict mode requires the model to emit every field explicitly)
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel

# Keywords OpenAI strict mode rejects outright. Pydantic still enforces them when we
# validate the model's reply, so nothing is actually lost.
_UNSUPPORTED = {
    "minLength", "maxLength", "pattern", "format",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minItems", "maxItems", "uniqueItems",
    "minProperties", "maxProperties",
    "default", "examples", "discriminator", "$comment", "deprecated",
    "patternProperties", "propertyNames", "contains",
}


def _strip(node: Any) -> Any:
    if isinstance(node, list):
        return [_strip(n) for n in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED:
            continue
        out[key] = _strip(value)

    # `const: X` -> `enum: [X]`
    if "const" in out:
        out["enum"] = [out.pop("const")]

    # `oneOf` is not supported; `anyOf` is. Our unions are disjoint so this is safe.
    if "oneOf" in out:
        out["anyOf"] = out.pop("oneOf")

    # Pydantic wraps a $ref in allOf when the field carries a description/default.
    if "allOf" in out and len(out["allOf"]) == 1:
        merged = out.pop("allOf")[0]
        for key, value in merged.items():
            out.setdefault(key, value)

    return out


def _enforce(node: Any) -> Any:
    """Recursively require every property and forbid extras."""
    if isinstance(node, list):
        return [_enforce(n) for n in node]
    if not isinstance(node, dict):
        return node

    out = {k: _enforce(v) for k, v in node.items()}

    if out.get("type") == "object" or "properties" in out:
        props: dict[str, Any] = out.get("properties", {})
        out["additionalProperties"] = False
        # Strict mode: every key in `properties` must appear in `required`. A field the
        # model may legitimately omit is expressed by allowing null instead.
        out["required"] = list(props.keys())
    return out


def to_openai_strict(model: type[BaseModel], name: str | None = None) -> dict[str, Any]:
    """Return `{"name","strict":true,"schema":{...}}` ready for `response_format`."""
    raw = model.model_json_schema(by_alias=True, ref_template="#/$defs/{model}")
    schema = _enforce(_strip(copy.deepcopy(raw)))
    schema.setdefault("type", "object")
    return {
        "name": name or model.__name__,
        "strict": True,
        "schema": schema,
    }


def response_format(model: type[BaseModel], name: str | None = None) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": to_openai_strict(model, name)}
