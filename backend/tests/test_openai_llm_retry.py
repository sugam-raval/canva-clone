"""OpenAILLM's self-healing retries for chat.completions and the Responses API.

A caller sizes `max_tokens`/`reasoning.effort` for whichever model is configured —
generate_ai.py, for one, gives a reasoning model headroom for hidden thinking tokens
and a fixed global effort. Swap in a different model and either can be rejected
outright:

    chat.completions, gpt-4o-2024-11-20 (16384-token ceiling):
        max_tokens is too large: 32000. This model supports at most 16384 completion
        tokens, whereas you provided 32000.

    Responses API, gpt-5-pro (only accepts effort='high'):
        Unsupported value: 'low' is not supported with the 'gpt-5-pro' model.
        Supported values are: 'high'.

    chat.completions, gpt-5-pro (Responses-only model):
        This model is only supported in v1/responses and not in v1/chat/completions.

Rather than have every caller (or this adapter) know every model's limits ahead of
time, it learns each one from the API's own 4xx the first time it's hit, and pins the
fix for that model afterwards.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIStatusError
from pydantic import BaseModel

from app.adapters.openai_adapters import OpenAILLM


class Answer(BaseModel):
    text: str


def _status_error(message: str, *, status_code: int = 400, param: str | None = None,
                  code: str | None = "invalid_value") -> APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    body = {"message": message, "type": "invalid_request_error", "param": param, "code": code}
    return APIStatusError(message, response=response, body=body)


def _completion(text: str = "hi"):
    return type("Completion", (), {
        "choices": [type("Choice", (), {
            "finish_reason": "stop",
            "message": type("Message", (), {
                "content": Answer(text=text).model_dump_json(), "refusal": None,
            })(),
        })()],
        "usage": type("Usage", (), {"prompt_tokens": 10, "completion_tokens": 5})(),
    })()


def _response(text: str = "hi"):
    return type("Response", (), {
        "status": "completed",
        "incomplete_details": None,
        "output_parsed": Answer(text=text),
        "output_text": Answer(text=text).model_dump_json(),
        "usage": type("Usage", (), {"input_tokens": 10, "output_tokens": 5})(),
    })()


@pytest.fixture(autouse=True)
def clear_learned_state():
    OpenAILLM._rejected_params.clear()
    OpenAILLM._max_completion_tokens.clear()
    OpenAILLM._required_reasoning_effort.clear()
    OpenAILLM._responses_only_models.clear()
    yield
    OpenAILLM._rejected_params.clear()
    OpenAILLM._max_completion_tokens.clear()
    OpenAILLM._required_reasoning_effort.clear()
    OpenAILLM._responses_only_models.clear()


@pytest.fixture
def fake_client(monkeypatch):
    chat_create = AsyncMock()
    responses_parse = AsyncMock()
    client = type("Client", (), {
        "chat": type("Chat", (), {"completions": type("Completions", (), {
            "create": chat_create,
        })()})(),
        "responses": type("Responses", (), {"parse": responses_parse})(),
    })()
    monkeypatch.setattr("app.adapters.openai_adapters._client", lambda: client)
    return type("Fakes", (), {"chat": chat_create, "responses": responses_parse})()


# -- chat.completions: completion-token ceiling ------------------------------------------


async def test_completion_token_ceiling_is_clamped_and_retried(fake_client):
    too_large = _status_error(
        "max_tokens is too large: 32000. This model supports at most 16384 "
        "completion tokens, whereas you provided 32000.",
        param="max_tokens",
    )
    fake_client.chat.side_effect = [too_large, _completion()]

    result = await OpenAILLM().complete_json(
        system="s", user="u", schema=Answer, model="gpt-4o-2024-11-20", max_tokens=32000,
    )

    assert result.parsed == Answer(text="hi")
    assert fake_client.chat.call_count == 2
    assert fake_client.chat.call_args_list[0].kwargs["max_tokens"] == 32000
    assert fake_client.chat.call_args_list[1].kwargs["max_tokens"] == 16384
    assert OpenAILLM._max_completion_tokens["gpt-4o-2024-11-20"] == 16384


async def test_learned_ceiling_is_applied_before_the_first_call(fake_client):
    OpenAILLM._max_completion_tokens["gpt-4o-2024-11-20"] = 16384
    fake_client.chat.side_effect = [_completion()]

    await OpenAILLM().complete_json(
        system="s", user="u", schema=Answer, model="gpt-4o-2024-11-20", max_tokens=32000,
    )

    assert fake_client.chat.call_count == 1
    assert fake_client.chat.call_args_list[0].kwargs["max_tokens"] == 16384


async def test_ceiling_clamp_and_param_rename_both_apply(fake_client):
    """A model needing max_completion_tokens (not max_tokens) whose value is also
    too large — both self-healing paths have to compose, not just one or the other."""
    renamed = _status_error("Unsupported parameter: 'max_tokens'.", param="max_tokens",
                            code="unsupported_parameter")
    too_large = _status_error(
        "This model supports at most 16384 completion tokens, whereas you provided "
        "32000.", param="max_completion_tokens",
    )
    fake_client.chat.side_effect = [renamed, too_large, _completion()]

    result = await OpenAILLM().complete_json(
        system="s", user="u", schema=Answer, model="o1-mini", max_tokens=32000,
    )

    assert result.parsed == Answer(text="hi")
    assert fake_client.chat.call_count == 3
    final_kwargs = fake_client.chat.call_args_list[2].kwargs
    assert "max_tokens" not in final_kwargs
    assert final_kwargs["max_completion_tokens"] == 16384


async def test_an_unrelated_400_is_not_treated_as_a_token_ceiling(fake_client):
    other = _status_error("invalid schema", code="invalid_value")
    fake_client.chat.side_effect = [other]

    with pytest.raises(Exception, match="invalid schema"):
        await OpenAILLM().complete_json(
            system="s", user="u", schema=Answer, model="gpt-4o-2024-11-20", max_tokens=4096,
        )

    assert OpenAILLM._max_completion_tokens == {}


# -- Responses API: a model that only accepts one reasoning.effort value -----------------


async def test_required_reasoning_effort_is_learned_and_retried(fake_client):
    """gpt-5-pro rejects the global LLM_REASONING_EFFORT default ('low') and only
    accepts 'high' — this is the exact 400 reported against the live API. Exercises
    `_complete_json_reasoning` directly since routing into it (via `complete_json`)
    is `settings.llm_reasoning_effort`'s job, already covered by the routing tests
    below — this test is about what happens once inside that path."""
    wrong_effort = _status_error(
        "Unsupported value: 'low' is not supported with the 'gpt-5-pro' model. "
        "Supported values are: 'high'.",
        param="reasoning.effort",
    )
    fake_client.responses.side_effect = [wrong_effort, _response()]
    wrong_effort = _status_error(
        "Unsupported value: 'low' is not supported with the 'gpt-5-pro' model. "
        "Supported values are: 'high'.",
        param="reasoning.effort",
    )
    fake_client.responses.side_effect = [wrong_effort, _response()]

    result = await OpenAILLM()._complete_json_reasoning(
        system="s", user="u", schema=Answer, model="gpt-5-pro", effort="low", max_tokens=4096,
    )

    assert result.parsed == Answer(text="hi")
    assert fake_client.responses.call_count == 2
    assert fake_client.responses.call_args_list[0].kwargs["reasoning"] == {"effort": "low"}
    assert fake_client.responses.call_args_list[1].kwargs["reasoning"] == {"effort": "high"}
    assert OpenAILLM._required_reasoning_effort["gpt-5-pro"] == "high"


async def test_learned_required_effort_is_applied_before_the_first_call(fake_client):
    OpenAILLM._required_reasoning_effort["gpt-5-pro"] = "high"
    fake_client.responses.side_effect = [_response()]

    await OpenAILLM()._complete_json_reasoning(
        system="s", user="u", schema=Answer, model="gpt-5-pro", effort="low", max_tokens=4096,
    )

    assert fake_client.responses.call_count == 1
    assert fake_client.responses.call_args_list[0].kwargs["reasoning"] == {"effort": "high"}


async def test_no_effort_configured_omits_the_reasoning_param(fake_client):
    """Several gpt-5-family models work fine with no `reasoning` key at all — the API
    applies its own default rather than rejecting the call."""
    fake_client.responses.side_effect = [_response()]

    await OpenAILLM()._complete_json_reasoning(
        system="s", user="u", schema=Answer, model="gpt-5", effort=None, max_tokens=4096,
    )

    assert "reasoning" not in fake_client.responses.call_args_list[0].kwargs


# -- chat.completions -> Responses API reroute for a Responses-only model ----------------


async def test_responses_only_model_reroutes_from_chat_to_responses(fake_client):
    """A model configured with no reasoning effort (the gpt-4o pattern) that turns
    out to exist only on the Responses API must not just fail — gpt-5-pro 404s on
    chat.completions with this exact message."""
    responses_only = _status_error(
        "This model is only supported in v1/responses and not in v1/chat/completions.",
        status_code=404, param="model", code=None,
    )
    fake_client.chat.side_effect = [responses_only]
    fake_client.responses.side_effect = [_response()]

    result = await OpenAILLM().complete_json(
        system="s", user="u", schema=Answer, model="gpt-5-pro", max_tokens=4096,
    )

    assert result.parsed == Answer(text="hi")
    assert fake_client.chat.call_count == 1
    assert fake_client.responses.call_count == 1
    assert "reasoning" not in fake_client.responses.call_args_list[0].kwargs
    assert "gpt-5-pro" in OpenAILLM._responses_only_models


async def test_learned_responses_only_model_skips_chat_entirely(fake_client):
    OpenAILLM._responses_only_models.add("gpt-5-pro")
    fake_client.responses.side_effect = [_response()]

    await OpenAILLM().complete_json(
        system="s", user="u", schema=Answer, model="gpt-5-pro", max_tokens=4096,
    )

    assert fake_client.chat.call_count == 0
    assert fake_client.responses.call_count == 1


async def test_unrelated_404_is_not_treated_as_responses_only(fake_client):
    other = _status_error("model not found", status_code=404, param="model", code=None)
    fake_client.chat.side_effect = [other]

    with pytest.raises(Exception, match="model not found"):
        await OpenAILLM().complete_json(
            system="s", user="u", schema=Answer, model="totally-made-up", max_tokens=4096,
        )

    assert OpenAILLM._responses_only_models == set()
