"""Adapter tests: the stubs used without an API key, and what the registry reports."""

import io

from PIL import Image

from app.adapters.registry import describe, reset
from app.adapters.stub_adapters import StubTextToImage, StubTransparentImage
from app.config import get_settings


async def test_stub_image_generation_is_deterministic():
    a = await StubTextToImage().generate(prompt="navy studio", seed=42, width=256, height=256)
    b = await StubTextToImage().generate(prompt="navy studio", seed=42, width=256, height=256)
    c = await StubTextToImage().generate(prompt="navy studio", seed=43, width=256, height=256)
    assert a.data == b.data
    assert a.data != c.data


async def test_transparent_stub_actually_has_alpha():
    result = await StubTransparentImage().generate(prompt="shoe", width=256, height=256)
    with Image.open(io.BytesIO(result.data)) as img:
        assert img.mode == "RGBA"
        alpha = img.split()[-1]
        assert alpha.getextrema()[0] == 0, "cutout must have fully transparent pixels"
        assert alpha.getextrema()[1] == 255, "cutout must have fully opaque pixels"


def test_registry_reports_every_capability():
    reset()
    resolved = describe()
    assert set(resolved) == {"TextToImage", "TransparentImage", "LLM", "TemplateEmbedder"}
    # Without a key the LLM must refuse rather than fabricate (see StubLLM).
    if not get_settings().has_openai:
        assert resolved["LLM"] == "stub:llm-unavailable"
