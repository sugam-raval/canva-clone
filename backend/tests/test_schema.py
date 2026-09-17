"""Schema tests — IMPLEMENTATION_PLAN §5.1: validation, migrations, round-trip JSON."""

import json

import pytest

from app.schema.doc import (
    Canvas,
    DesignDoc,
    FontRef,
    Frame,
    GenerationParams,
    GroupLayer,
    ImageLayer,
    LayerMeta,
    ShapeLayer,
    TextLayer,
)
from app.schema.migrate import UnknownSchemaVersion, migrate
from app.schema.openai_schema import to_openai_strict
from app.schema.validate import validate_doc


def _doc(**kw) -> DesignDoc:
    return DesignDoc(
        id="doc_1",
        canvas=Canvas(width=1080, height=1920, safeMargin=72),
        fonts=[FontRef(family="Inter", weights=[400, 900])],
        palette=["#0F172A", "#F5B700"],
        **kw,
    )


def test_round_trip_preserves_every_layer_type():
    doc = _doc(layers=[
        ImageLayer(id="i", frame=Frame(x=0, y=0, w=10, h=10)),
        TextLayer(id="t", frame=Frame(x=0, y=0, w=10, h=10), fontFamily="Inter"),
        ShapeLayer(id="s", frame=Frame(x=0, y=0, w=10, h=10), shape="ellipse"),
        GroupLayer(id="g", frame=Frame(x=0, y=0, w=10, h=10), children=[
            TextLayer(id="gt", frame=Frame(x=1, y=1, w=5, h=5), fontFamily="Inter"),
        ]),
    ])
    wire = json.loads(doc.model_dump_json(by_alias=True, exclude_none=True))
    back = DesignDoc.model_validate(wire)
    assert [layer.type for layer in back.layers] == ["image", "text", "shape", "group"]
    assert back.layers[3].children[0].id == "gt"
    # Wire format is camelCase, matching the plan's TypeScript verbatim.
    assert "safeMargin" in wire["canvas"]


def test_validate_rejects_duplicate_layer_ids():
    doc = _doc(layers=[
        TextLayer(id="dup", frame=Frame(x=0, y=0, w=5, h=5), fontFamily="Inter"),
        TextLayer(id="dup", frame=Frame(x=0, y=0, w=5, h=5), fontFamily="Inter"),
    ])
    result = validate_doc(doc)
    assert not result.ok
    assert "duplicate-layer-id" in {e.code for e in result.errors}


def test_validate_rejects_undeclared_font():
    doc = _doc(layers=[TextLayer(id="t", frame=Frame(x=0, y=0, w=5, h=5),
                                fontFamily="Nonexistent")])
    assert "undeclared-font" in {e.code for e in validate_doc(doc).errors}


def test_inv1_text_may_never_carry_raster_generation_params():
    """INV-1: no layer of type text may ever be replaced by a raster."""
    doc = _doc(layers=[TextLayer(
        id="t", frame=Frame(x=0, y=0, w=5, h=5), fontFamily="Inter",
        meta=LayerMeta(generation=GenerationParams(
            adapter="TextToImage", model="m", prompt="a headline", seed=1)),
    )])
    result = validate_doc(doc)
    assert not result.ok
    assert "inv1-text-rasterised" in {e.code for e in result.errors}


def test_inv1_allows_non_raster_provenance_on_text():
    doc = _doc(layers=[TextLayer(
        id="t", frame=Frame(x=0, y=0, w=5, h=5), fontFamily="Inter",
        meta=LayerMeta(generation=GenerationParams(
            adapter="CopyWriter", model="gpt", prompt="write a headline", seed=1)),
    )])
    assert validate_doc(doc).ok


def test_migrate_v1_to_v3_is_ordered_and_idempotent():
    v1 = {"schemaVersion": 1, "id": "d", "canvas": {"width": 10, "height": 10},
          "layers": [{"id": "top", "z": 5}, {"id": "bottom", "z": 1}]}
    out = migrate(v1)
    assert out["schemaVersion"] == 3
    assert [layer["id"] for layer in out["layers"]] == ["bottom", "top"]
    assert migrate(out) == out


def test_migrate_v2_lifts_loose_prompt_into_meta_generation():
    v2 = {"schemaVersion": 2, "id": "d", "canvas": {"width": 10, "height": 10},
          "layers": [{"id": "a", "prompt": "a shoe", "seed": 7, "model": "t2i"}]}
    out = migrate(v2)
    gen = out["layers"][0]["meta"]["generation"]
    assert gen["prompt"] == "a shoe" and gen["seed"] == 7 and gen["model"] == "t2i"
    assert "prompt" not in out["layers"][0]


def test_migrate_refuses_a_future_schema_version():
    with pytest.raises(UnknownSchemaVersion):
        migrate({"schemaVersion": 99, "id": "d"})


def test_openai_strict_schema_is_actually_strict():
    """§1.3 constrains the LLM against this exact schema, so it must satisfy the
    structured-outputs subset: every property required, no extras, no unsupported
    validation keywords."""
    from app.schema.brief import DesignBrief
    from app.schema.composer import ComposerOutput

    for model in (DesignBrief, ComposerOutput):
        schema = to_openai_strict(model)["schema"]
        stack = [schema]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            for banned in ("pattern", "minimum", "maxLength", "default",
                           "minItems", "oneOf", "discriminator", "allOf"):
                assert banned not in node, f"{model.__name__} leaked {banned}"
            if "properties" in node:
                assert node.get("additionalProperties") is False
                assert set(node["required"]) == set(node["properties"])
            stack.extend(node.values())
