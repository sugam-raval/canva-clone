"""Costs (app/costs): prices from pricing.yaml, and the bill every OpenAI call is charged
to — hand-checked arithmetic, so a wrong price list or a lost call shows up here."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest

from app import costs


def test_text_calls_are_priced_per_million_tokens_with_cached_input_cheaper():
    # gpt-6-astra: $10 input, $1 cached input, $50 output per 1M tokens
    usd = costs.text_cost("gpt-6-astra", input_tokens=10_000, cached_tokens=2_000,
                          output_tokens=3_000)
    assert usd == pytest.approx((8_000 * 10 + 2_000 * 1 + 3_000 * 50) / 1e6)  # $0.232


def test_images_are_priced_by_their_tokens():
    # gpt-image-2.5-flare: $5 text input, $8 image input, $30 output per 1M tokens
    usd = costs.image_cost("gpt-image-2.5-flare", text_input_tokens=100,
                           image_input_tokens=0, output_tokens=4_000)
    assert usd == pytest.approx((100 * 5 + 4_000 * 30) / 1e6)  # $0.1205


def test_a_dated_snapshot_uses_its_family_price_and_an_unknown_model_is_unknown():
    assert costs.text_cost("gpt-4o-2024-08-06", 1_000_000, 0, 0) == pytest.approx(2.50)
    assert costs.text_cost("gpt-4o-mini-2024-07-18", 1_000_000, 0, 0) == pytest.approx(0.15)
    assert costs.text_cost("some-new-model", 1_000, 0, 1_000) is None  # never "$0"


def test_usage_from_both_openai_apis_lands_on_the_open_bill_with_its_step():
    bill: list[costs.Charge] = []
    responses_usage = NS(input_tokens=1_000, output_tokens=200,
                         input_tokens_details=NS(cached_tokens=400))
    chat_usage = NS(prompt_tokens=500, completion_tokens=100, prompt_tokens_details=None)
    with costs.collect(bill):
        with costs.step("design"):
            costs.record_text("gpt-6-astra", responses_usage)
        with costs.step("repair"):
            costs.record_text("gpt-4o", chat_usage)
    costs.record_text("gpt-4o", chat_usage)  # outside any bill: charged to nobody
    assert [(c.step, c.input_tokens, c.cached_tokens, c.output_tokens) for c in bill] == [
        ("design", 1_000, 400, 200), ("repair", 500, 0, 100)]
    total = costs.summary(bill)
    assert total["totalUsd"] == pytest.approx(
        (600 * 10 + 400 * 1 + 200 * 50) / 1e6 + (500 * 2.5 + 100 * 10) / 1e6)
    assert set(total["byStepUsd"]) == {"design", "repair"} and total["unknownCalls"] == 0


def test_tasks_started_inside_a_bill_are_charged_to_it():
    async def photo():
        with costs.step("photo"):
            costs.record_image("gpt-image-2.5-flare", NS(output_tokens=1_000,
                                                         input_tokens_details=None,
                                                         input_tokens=50))

    async def run(bill):
        with costs.collect(bill):
            await asyncio.gather(photo(), photo())

    a: list[costs.Charge] = []
    b: list[costs.Charge] = []

    async def both():
        await asyncio.gather(run(a), run(b))

    asyncio.run(both())
    assert len(a) == len(b) == 2 and {c.step for c in a + b} == {"photo"}


def test_a_hung_image_is_counted_as_unknown_not_hidden():
    from openai import APITimeoutError

    from app.adapters.openai_adapters import _call_images

    class Images:
        def __init__(self):
            self.calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise APITimeoutError(request=None)  # type: ignore[arg-type]
            return NS(usage=NS(input_tokens=60, output_tokens=2_000,
                               input_tokens_details=NS(text_tokens=60, image_tokens=0)))

    class Client:
        images = Images()

    bill: list[costs.Charge] = []
    with costs.collect(bill), costs.step("photo"):
        result = asyncio.run(_call_images(Client(), model="gpt-image-2.5-flare", prompt="p"))
        costs.record_image("gpt-image-2.5-flare", result.usage)
    total = costs.summary(bill)
    assert total["unknownCalls"] == 1 and "timed out" in total["calls"][0]["note"]
    assert total["totalUsd"] == pytest.approx((60 * 5 + 2_000 * 30) / 1e6)
