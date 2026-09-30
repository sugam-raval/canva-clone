"""Designing new templates (app/lido_create): the recipes, the design checks, and the
prompt → draft API. Offline — the LLM is a fake that replays recipe layouts, photos are a
fixed list and no screenshot is taken — so these pin the guarantees (every recipe passes
its own checks, broken layouts are caught and repaired, drafts land on disk and come back
through the API), not any model's taste."""

from __future__ import annotations

import json
import random

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import AdapterError, LLMResult
from app.lido_create import brief, drafts
from app.lido_create.check import validate
from app.lido_create.kit import FONT_SETS, PALETTES, THEMES_BY_NAME, Canvas, Design, Photo, Variant
from app.lido_create.lido import to_lido
from app.lido_create.recipes import RECIPES, mirror

PHOTOS = [Photo(f"https://example.test/{i}.png", 1200, 800 + 100 * i, (tag,))
          for i, tag in enumerate(["business", "food", "fashion", "fashion", "business"])]


def _variant(palette=0, fonts=0, theme="business") -> Variant:
    return Variant(PALETTES[palette], FONT_SETS[fonts], THEMES_BY_NAME[theme],
                   random.Random(0), PHOTOS)


def _recipe_design(name: str, v: Variant) -> Design:
    c = Canvas(v)
    RECIPES[name].build(c)
    return Design(recipe=name, theme=v.theme.name, palette=v.palette.name,
                  fonts=v.fonts.name, elements=c.els)


@pytest.mark.parametrize("name", list(RECIPES))
def test_every_recipe_passes_its_own_checks_in_some_dress(name):
    """Not every palette × font × theme fits every recipe (the generator retries), but
    each recipe must work in at least one, and produce valid Lido JSON."""
    passing = None
    for p in range(len(PALETTES)):
        for f in range(len(FONT_SETS)):
            v = _variant(p, f)
            d = _recipe_design(name, v)
            if not validate(d, v):
                passing = (d, v)
                break
        if passing:
            break
    assert passing, f"{name} fails its checks in every palette/font pairing"
    doc = to_lido(*passing)
    layers = doc[0]["layers"]
    assert layers["ROOT"]["type"]["resolvedName"] == "RootLayer"
    assert len(layers["ROOT"]["child"]) == len(passing[0].elements)
    assert sum(lr["type"].get("type") == "logo" for lr in layers.values()) == 1


def test_mirror_flips_positions_and_alignment():
    v = _variant()
    d = _recipe_design("split_offer", v)
    m = mirror(d)
    photo, mphoto = d.elements[0], m.elements[0]
    assert mphoto.x == pytest.approx(1080 - photo.x - photo.w)
    assert {e.align for e in m.elements if e.kind == "text"} <= {"right", "center"}


def test_checks_catch_text_on_a_photo_line_breaks_and_emoji():
    v = _variant()
    d = _recipe_design("split_offer", v)
    headline = next(e for e in d.elements if e.text_type == "headline")
    headline.x = 600  # onto the photo half
    body = next(e for e in d.elements if e.text_type == "body")
    body.text = "Line one\nLine two 📞"
    errors = " | ".join(validate(d, v))
    assert "sits on a photo" in errors or "straddles" in errors
    assert "line break" in errors
    assert "emoji" in errors


class _FakeLLM:
    """Replays a pro recipe as the model's answer; the first answer carries a line break so
    the repair round is exercised."""

    def __init__(self):
        self.calls: list[str] = []
        self.failures: dict[int, AdapterError] = {}  # call number (1-based) -> error

    async def complete_json(self, *, system, user, schema, **_):
        self.calls.append(user)
        if len(self.calls) in self.failures:
            raise self.failures[len(self.calls)]
        v = _variant()
        design = _recipe_design("fresh_promo", v)  # rich enough for the creative checks
        if len(self.calls) == 1:
            next(e for e in design.elements if e.text_type == "headline").text = "Grand\nNight"
        parsed = schema(
            name="test_layout", idea="A centred invite.",
            colors=brief.BriefColors(bg="#241640", ink="#ffffff", accent="#ff6b6b",
                                     on_accent="#241640", soft="#ffde96"),
            fonts=v.fonts.name, photo_theme="business",
            elements=[e.model_copy(update={"subject": "a dinner party"} if e.kind == "photo"
                                   else {}) for e in design.elements])
        return LLMResult(parsed=parsed, raw="", model="fake")


@pytest.fixture
def api(tmp_path, monkeypatch):
    from app.adapters import registry
    from app.api.main import create_app
    from app.config import get_settings

    fake = _FakeLLM()
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    monkeypatch.setattr(drafts, "photo_pool", lambda: PHOTOS)
    monkeypatch.setattr(drafts, "screenshot", lambda layers, out: False)
    monkeypatch.setattr(registry, "llm", lambda: fake)
    monkeypatch.setattr(get_settings(), "openai_api_key", "test-key")
    monkeypatch.setattr(brief, "RETRY_DELAYS", (0.0, 0.0))
    return TestClient(create_app()), fake, tmp_path


def test_prompt_becomes_a_saved_draft(api):
    client, fake, folder = api
    response = client.post("/v1/lido/drafts", json={"prompt": "Grand opening dinner party"})
    assert response.status_code == 200, response.text
    [draft] = response.json()

    assert len(fake.calls) == 2  # first answer failed the checks, the repair passed
    assert "Grand opening dinner party" in fake.calls[0]
    assert "line break" in fake.calls[1]
    assert draft["problems"] == [] and draft["attempts"] == 2
    assert draft["source"] == "brief" and draft["prompt"] == "Grand opening dinner party"
    assert draft["colors"]["accent"] == "#ff6b6b"
    assert draft["photoSubjects"] == ["a dinner party"]
    layers = draft["document"][0]["layers"]
    assert layers["ROOT"]["props"]["color"] == "rgb(36, 22, 64)"

    tid = draft["id"]
    assert (folder / f"{tid}.json").is_file() and (folder / f"{tid}.info.json").is_file()
    assert json.loads((folder / f"{tid}.json").read_text()) == draft["document"]

    listed = client.get("/v1/lido/drafts").json()
    assert [d["id"] for d in listed] == [tid] and listed[0]["document"] is None
    assert client.get(f"/v1/lido/drafts/{tid}").json()["document"] == draft["document"]
    assert client.get(f"/v1/lido/drafts/{tid}/preview.png").status_code == 404
    assert client.delete(f"/v1/lido/drafts/{tid}").status_code == 204
    assert client.get("/v1/lido/drafts").json() == []


def test_variations_get_distinct_ids_and_directions(api):
    client, _, _ = api
    drafts_made = client.post("/v1/lido/drafts",
                              json={"prompt": "Launch party", "variations": 3}).json()
    assert len({d["id"] for d in drafts_made}) == 3
    assert len({d["direction"] for d in drafts_made}) == 3


def test_bad_ids_are_not_found(api):
    client, _, _ = api
    assert client.get("/v1/lido/drafts/../../etc").status_code == 404
    assert client.get("/v1/lido/drafts/template_1x").status_code == 404


def test_a_transient_api_failure_is_retried(api):
    client, fake, _ = api
    fake.failures = {1: AdapterError("LLM API 520: Error code: 520 - {...}")}
    response = client.post("/v1/lido/drafts", json={"prompt": "Grand opening"})
    assert response.status_code == 200, response.text
    assert len(fake.calls) == 2  # the 520, then the retry (which passes)


def test_a_persistent_outage_is_a_readable_503(api):
    client, fake, _ = api
    fake.failures = {n: AdapterError("LLM API 520: Error code: 520 - {'type': 'cf'}")
                     for n in range(1, 10)}
    response = client.post("/v1/lido/drafts", json={"prompt": "Grand opening"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "temporarily unavailable (LLM API 520)" in detail and "{" not in detail
    assert len(fake.calls) == 3  # first try + 2 retries


def test_a_failed_variation_does_not_sink_the_others(api):
    client, fake, _ = api
    fake.failures = {1: AdapterError("refused", recoverable=False)}
    made = client.post("/v1/lido/drafts", json={"prompt": "Launch", "variations": 3}).json()
    assert len(made) == 2


def test_a_failed_repair_keeps_the_last_design(api):
    client, fake, _ = api
    fake.failures = {2: AdapterError("refused", recoverable=False)}  # the repair call
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Launch"}).json()
    assert any("line break" in p for p in draft["problems"])


def test_rotated_shapes_and_new_crops_hit_test_their_real_outline():
    from app.lido_create.check import covers
    from app.lido_create.kit import Element

    diamond = Element(kind="shape", shape="rectangle", x=0, y=0, w=100, h=100, rotate=45)
    assert covers(diamond, 50, 50) and covers(diamond, 50, -15)  # tip pokes above the box
    assert not covers(diamond, 2, 2)  # the unrotated square's corner is empty
    hexagon = Element(kind="photo", clip="hexagon", x=0, y=0, w=200, h=100)
    assert covers(hexagon, 100, 50) and not covers(hexagon, 5, 5)


def test_dots_expand_and_compact_round_trip():
    from app.lido_create.ai import compact, expand_dots
    from app.lido_create.kit import Element

    grid = Element(kind="dots", x=100, y=200, w=80, h=50, rows=3, cols=4, dot=8,
                   color="accent")
    circles = expand_dots(grid)
    assert len(circles) == 12 and {c.w for c in circles} == {8}
    assert circles[-1].x + 8 == pytest.approx(180) and circles[-1].y + 8 == pytest.approx(250)
    [back] = compact(circles)
    assert back["kind"] == "dots" and (back["rows"], back["cols"]) == (3, 4)


def test_a_cutout_frame_without_a_cutout_photo_falls_back_to_a_blob_crop():
    v = _variant()
    d = _recipe_design("fresh_promo", v)
    layers = to_lido(d, v, photos=[PHOTOS[0]])[0]["layers"]  # an opaque photo
    frames = [lr for lr in layers.values()
              if lr["type"]["resolvedName"] == "FrameLayer" and lr["type"]["type"] != "logo"]
    assert frames[0]["props"]["clipPath"].startswith("M ")
    cut = Photo("https://example.test/cut.png", 800, 800, ("business",), cutout=True)
    layers = to_lido(d, v, photos=[cut])[0]["layers"]
    frame = next(lr for lr in layers.values()
                 if lr["type"]["resolvedName"] == "FrameLayer" and lr["type"]["type"] != "logo")
    assert "clipPath" not in frame["props"]
    assert frame["props"]["imageStyle"]["objectFit"] == "contain"


def test_creative_checks_flag_plain_layouts_and_unbulleted_items():
    v = _variant()
    plain = _recipe_design("split_offer", v)
    assert any("bare" in e for e in validate(plain, v, creative=True))
    assert not any("bare" in e for e in validate(plain, v))  # recipes are exempt
    rich = _recipe_design("geo_agency", v)
    assert validate(rich, v, creative=True) == []
    # drop the bullet bars (22px wide shapes beside the items): now the items fail
    rich.elements = [e for e in rich.elements if not (e.kind == "shape" and e.w == 22)]
    assert any("bullet marker" in e for e in validate(rich, v, creative=True))
