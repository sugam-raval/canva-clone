"""Adapter tests, focused on the glyph gate that enforces INV-1.

Appendix A.1: "Baked-in text. Any text in a generated raster is unfixable by the user.
Negative prompts alone are not enough; the glyph gate is mandatory." A regression here
silently disables the only mechanical defence, so it is tested against both a text and
a no-text corpus.
"""

import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.adapters.local_adapters import OpenCVGlyphDetector
from app.adapters.registry import describe, reset
from app.adapters.stub_adapters import StubTextToImage, StubTransparentImage
from app.config import get_settings
from app.layout.fonts import get_registry

GATE_MAX_COVERAGE = 0.004   # §1.4.6
GATE_MAX_BOXES = 2


def render_text(text: str, *, size: int = 64, lines: int = 1,
                bg=(28, 36, 58), fg=(240, 240, 240)) -> bytes:
    font_path = get_registry().face("Inter", 700).path
    img = Image.new("RGB", (1024, 640), bg)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(font_path), size)
    for i in range(lines):
        draw.text((70, 80 + i * int(size * 1.5)), text, font=font, fill=fg)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def gate_fires(boxes) -> bool:
    coverage = sum(b.area for b in boxes)
    return coverage > GATE_MAX_COVERAGE or len(boxes) > GATE_MAX_BOXES


@pytest.mark.parametrize("text,size,lines,bg,fg", [
    ("SUMMER SALE", 64, 1, (28, 36, 58), (240, 240, 240)),
    ("limited time offer only", 26, 1, (28, 36, 58), (240, 240, 240)),
    ("engineered midsole", 36, 3, (28, 36, 58), (240, 240, 240)),
    ("shutterstock", 44, 1, (28, 36, 58), (120, 130, 150)),          # faint watermark
    ("NEW ARRIVAL", 64, 1, (240, 240, 235), (30, 30, 30)),           # dark on light
    ("terms and conditions apply see site", 18, 1, (28, 36, 58), (240, 240, 240)),
])
async def test_glyph_gate_catches_rendered_text(text, size, lines, bg, fg):
    boxes = await OpenCVGlyphDetector().detect(render_text(text, size=size, lines=lines,
                                                           bg=bg, fg=fg))
    assert gate_fires(boxes), f"glyph gate missed {text!r} — INV-1 would be violated"


@pytest.mark.parametrize("prompt", ["shoe", "running shoe", "bottle", "perfume",
                                    "chair", "headphones"])
async def test_glyph_gate_ignores_transparent_subjects(prompt):
    """A cutout's silhouette must not read as text, or every subject would be re-rolled."""
    result = await StubTransparentImage().generate(prompt=prompt, width=1024, height=640)
    boxes = await OpenCVGlyphDetector().detect(result.data)
    assert not gate_fires(boxes), f"glyph gate false-positived on a {prompt} cutout"


@pytest.mark.parametrize("prompt", ["navy backdrop", "sunset wall", "studio grey", "forest"])
async def test_glyph_gate_ignores_clean_backgrounds(prompt):
    result = await StubTextToImage().generate(prompt=prompt, width=1024, height=640)
    boxes = await OpenCVGlyphDetector().detect(result.data)
    assert not gate_fires(boxes)


async def test_stub_image_generation_is_deterministic():
    """INV-2 holds exactly in stub mode: same prompt and seed, same bytes."""
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


def test_registry_never_pairs_a_real_image_model_with_the_no_op_glyph_detector():
    """The stub detector reports nothing; combined with a real image model that would
    silently switch INV-1 enforcement off."""
    reset()
    try:
        resolved = describe()
        if not resolved["TextToImage"].startswith("stub:"):
            assert not resolved["GlyphDetector"].startswith("stub:")
    finally:
        reset()


def test_registry_reports_every_capability():
    reset()
    resolved = describe()
    assert set(resolved) == {
        "TextToImage", "TransparentImage", "Matting", "Inpainter",
        "GlyphDetector", "Upscaler", "Embedder", "LLM",
    }
    # Without a key the LLM must refuse rather than fabricate (see StubLLM).
    if not get_settings().has_openai:
        assert resolved["LLM"] == "stub:llm-unavailable"
