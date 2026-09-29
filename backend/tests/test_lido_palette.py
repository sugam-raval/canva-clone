"""The user colour palette (docs/palette_theme.md): applied during generation to text,
shapes and images; absent, generation is exactly as before. Offline — the LLM and the
image adapters are the recording fakes from test_lido_generate_template."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from test_lido_generate_template import (  # noqa: F401 — fixtures used by name
    PROMPT,
    TEMPLATE_ID,
    _output,
    fakes,
    offline_fonts,
    offline_matcher,
    store,
)

from app.api.schemas import LidoGenerateRequest
from app.lido_corpus import generate_ai
from app.lido_corpus.loader import DEFAULT_CORPUS_DIR, load_enriched
from app.lido_corpus.palette import (
    MAX_COLORS,
    apply_theme,
    contrast,
    is_light,
    parse_color,
    parse_palette,
    plan_theme,
)
from app.lido_corpus.pipeline import generate_lido_design

NAVY, RED, CREAM = "#1d3557", "#e63946", "#f1faee"


def _template(name: str):
    return load_enriched(DEFAULT_CORPUS_DIR / f"{name}.json")


def _colors(layer: dict) -> set[str]:
    """Every colour a text layer carries: paragraph attrs, marks and props.colors."""
    found = set(layer["props"].get("colors") or [])
    for para in layer["props"]["doc"]["content"]:
        if "color" in (para.get("attrs") or {}):
            found.add(para["attrs"]["color"])
        for node in para.get("content") or []:
            for mark in node.get("marks") or []:
                if mark.get("type") == "color":
                    found.add(mark["attrs"]["color"])
    return found


# -- parsing -----------------------------------------------------------------------------


def test_parse_palette_reads_common_formats_and_keeps_order():
    assert parse_palette(["#FFF", "#1d3557", "rgb(230, 57, 70)", "#1D3557"]) == [
        (255, 255, 255), (29, 53, 87), (230, 57, 70)]
    assert parse_palette(None) == [] and parse_palette([]) == []
    with pytest.raises(ValueError):
        parse_palette(["tomato"])
    with pytest.raises(ValueError):
        parse_palette([f"#00000{i}" for i in range(MAX_COLORS + 1)])


def test_request_accepts_up_to_four_colours_and_treats_empty_as_none():
    body = LidoGenerateRequest(prompt="p", palette=["#FFF", NAVY])
    assert body.palette == ["#ffffff", NAVY]
    assert LidoGenerateRequest(prompt="p", palette=[]).palette is None
    assert LidoGenerateRequest(prompt="p").palette is None
    with pytest.raises(ValidationError):
        LidoGenerateRequest(prompt="p", palette=["#000", "#111", "#222", "#333", "#444"])
    with pytest.raises(ValidationError):
        LidoGenerateRequest(prompt="p", palette=["not-a-colour"])


# -- the plan ----------------------------------------------------------------------------


def test_shapes_take_palette_colours_and_their_text_stays_readable():
    template = _template("template_1789")          # red panels with white text on them
    plan = plan_theme(template, parse_palette([NAVY, RED, CREAM]))
    assert plan.shapes and all(c == parse_color(NAVY) for c in plan.shapes.values())
    on_shapes = [tp for tp in plan.texts.values() if tp.backdrop_shape]
    assert on_shapes
    for tp in on_shapes:
        for run in tp.runs.values():
            assert contrast(run.new, plan.shapes[tp.backdrop_shape]) >= tp.required


def test_a_light_template_panel_is_not_turned_dark():
    template = _template("template_10091")         # a pale panel with black text on it
    plan = plan_theme(template, parse_palette([NAVY, "#f4d35e"]))
    (panel,) = plan.shapes.values()
    assert is_light(panel)


def test_text_on_the_picture_keeps_its_light_or_dark_side():
    template = _template("template_227")           # white text on the photo
    plan = plan_theme(template, parse_palette([NAVY, RED, CREAM]))
    for tp in plan.texts.values():
        for run in tp.runs.values():
            assert is_light(run.new) == is_light(run.old)


def test_apply_theme_rewrites_marks_paragraph_colours_and_props_colors():
    template = _template("template_7347")          # coloured marks over black paragraphs
    plan = plan_theme(template, parse_palette([NAVY, "#f4a261", CREAM]))
    layers = {lid: layer.model_dump(mode="json") for lid, layer in template.layers.items()}
    apply_theme(layers, plan)
    for lid, tp in plan.texts.items():
        wanted = {f"rgb({r.new[0]}, {r.new[1]}, {r.new[2]})" for r in tp.runs.values()}
        assert wanted <= _colors(layers[lid])
        old_orange = "rgb(232, 143, 9)"
        assert old_orange not in _colors(layers[lid])


# -- the pipeline ------------------------------------------------------------------------


async def test_no_palette_changes_nothing(fakes):  # noqa: F811
    install, _, _ = fakes
    llm = install(_output())
    result = await generate_lido_design(PROMPT, generate_images=False, template_id=TEMPLATE_ID)

    assert "COLOUR PALETTE" not in llm.calls[0]["user"]
    assert result.theme is None and "theme" not in result.document[0]["meta"]["generation"]
    original = _template(TEMPLATE_ID)
    for lid, layer in result.document[0]["layers"].items():
        if layer["type"]["resolvedName"] == "TextLayer":
            assert _colors(layer) == _colors(original.layers[lid].model_dump(mode="json"))


async def test_palette_reaches_the_prompts_the_images_and_the_document(fakes):  # noqa: F811
    install, opaque, transparent = fakes
    llm = install(_output())

    result = await generate_lido_design(PROMPT, template_id=TEMPLATE_ID,
                                        palette=[NAVY, RED, CREAM])

    user = llm.calls[0]["user"]
    assert "COLOUR PALETTE" in user and NAVY in user
    assert "Colour palette (dominant first)" in opaque.calls[0]["prompt"]
    assert "keeps its natural colours" in transparent.calls[0]["prompt"]
    theme = result.document[0]["meta"]["generation"]["theme"]
    assert theme["palette"] == [NAVY, RED, CREAM] == result.theme["palette"]


async def test_text_unreadable_on_the_generated_background_is_swapped(fakes):  # noqa: F811
    """The fake background is flat mid-green: the template's white text, mapped to the
    palette's cream, would be unreadable there, so a readable palette colour wins."""
    install, _, _ = fakes
    install(_output())

    result = await generate_lido_design(PROMPT, template_id=TEMPLATE_ID,
                                        palette=[NAVY, RED, CREAM])

    green = (40, 200, 90)
    assert result.theme["contrastFixed"]
    for lid in result.theme["contrastFixed"]:
        for color in _colors(result.document[0]["layers"][lid]):
            rgb = parse_color(color)
            if rgb is not None and rgb != (0, 0, 0):
                assert contrast(rgb, green) >= 3.0


def test_prompt_block_is_only_built_with_a_theme():
    template = _template(TEMPLATE_ID)
    texts, images = generate_ai.text_targets(template), generate_ai.image_targets(template)
    plain = generate_ai.build_user_message(PROMPT, template, texts, images)
    themed = generate_ai.build_user_message(
        PROMPT, template, texts, images,
        theme=plan_theme(template, parse_palette([NAVY])))
    assert "COLOUR PALETTE" not in plain and "COLOUR PALETTE" in themed
