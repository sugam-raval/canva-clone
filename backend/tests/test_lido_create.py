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
from app.lido_create.kit import (
    FONT_SETS,
    PALETTES,
    THEMES_BY_NAME,
    Canvas,
    Design,
    Element,
    Photo,
    Variant,
)
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
                  fonts=v.fonts.name, background=c.background, elements=c.els)


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

    LAYOUTS = ("centre_stage", "split_half", "top_band")

    def __init__(self):
        self.calls: list[str] = []  # the designer's calls
        self.plan_calls: list[dict] = []  # the art director's calls
        self.failures: dict[int, AdapterError] = {}  # designer call number (1-based) -> error

    async def complete_json(self, *, system, user, schema, **kwargs):
        if schema.__name__ == "DesignPlan":
            self.plan_calls.append({"user": user, **kwargs})
            return LLMResult(parsed=schema(
                texts=[{"role": "headline", "text": "Grand Night"}],
                photos=[{"from_brief": "dinner party", "subject": "a dinner party",
                         "role": "hero", "frame": "cutout"}],
                logo=True, exclude=[], moods=["warm_handmade"],
                layout=self.LAYOUTS[(len(self.plan_calls) - 1) % 3], custom_layout=None,
                shapes=["rhombus"], draw=[], effects=[], gradient=None,
                photo_theme="business", notes="warm and bold"), raw="", model="fake")
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
            fonts=v.fonts.name, photo_theme="business", background=None,
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
    for name, value in (("llm_model_fast", "gpt-4o-mini"), ("lido_plan_model", ""),
                        ("lido_plan_reasoning_effort", ""), ("lido_layout_model", ""),
                        ("lido_layout_reasoning_effort", "")):
        monkeypatch.setattr(get_settings(), name, value)  # not whatever .env says
    monkeypatch.setattr(brief, "RETRY_DELAYS", (0.0, 0.0))
    from app.lido_create import plan as plan_module
    monkeypatch.setattr(plan_module, "FREE_SHARE", 0.0)  # only the forced free variation
    return TestClient(create_app()), fake, tmp_path


def test_prompt_becomes_a_saved_draft(api):
    client, fake, folder = api
    response = client.post("/v1/lido/drafts", json={"prompt": "Grand opening dinner party"})
    assert response.status_code == 200, response.text
    [draft] = response.json()

    assert len(fake.calls) == 2  # first answer failed the checks, the repair passed
    assert len(fake.plan_calls) == 1  # one art-director plan, on the fast model
    assert fake.plan_calls[0]["model"] == "gpt-4o-mini"
    assert draft["plan"]["photos"][0]["subject"] == "a dinner party"
    assert draft["fingerprint"].startswith(draft["planLayout"])
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
    # each variation got its own plan and layout; the last one is a free invention
    assert len({d["planLayout"] for d in drafts_made}) == 3
    assert drafts_made[-1]["planLayout"] == "custom"


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


# -- Lido's full feature set (docs/LIDO_CAPABILITIES.md) ---------------------------------


def test_every_lido_shape_has_a_real_outline():
    from app.lido_create.shapes import SHAPES, shape_contains

    assert len(SHAPES) == 20
    for name in SHAPES:
        assert shape_contains(name, 0.5, 0.5), f"{name}: centre should be inside"
    assert not shape_contains("triangle", 0.05, 0.05)  # the empty top-left corner
    assert not shape_contains("arrowRight", 0.95, 0.05)  # beside the arrow's tip
    assert shape_contains("arrowRight", 0.99, 0.5)  # the tip itself
    assert not shape_contains("cross", 0.1, 0.1)


def test_frames_keep_their_aspect_and_hit_test_their_outline():
    from app.lido_create.shapes import frame_contains, frames

    lib = frames()
    assert len(lib) == 41 and "letter_A" in lib and "brush_band" in lib
    assert frame_contains("circle", 0.5, 0.5) and not frame_contains("circle", 0.02, 0.02)
    assert not frame_contains("ring", 0.5, 0.5)  # the donut's hole
    assert not frame_contains("letter_A", 0.05, 0.1)  # beside the A's apex
    c = Canvas(_variant())
    photo = c.photo(100, 100, 400, 999, frame="brush_band")
    assert photo.h == pytest.approx(400 / lib["brush_band"].aspect, abs=0.01)


def test_lines_and_drawings_may_not_cross_text():
    v = _variant()
    d = _recipe_design("spotlight_launch", v)
    assert validate(d, v, creative=True) == []
    headline = next(e for e in d.elements if e.text_type == "headline")
    d.elements.append(Element(kind="line", x=headline.x, y=headline.y + headline.h / 2,
                              w=headline.w, h=4, color="accent"))
    assert any("line crosses headline" in e for e in validate(d, v))


def test_text_on_a_gradient_must_read_at_its_weakest_point():
    from app.lido_create.kit import Gradient

    v = _variant()
    d = _recipe_design("split_offer", v)
    assert validate(d, v) == []
    # the canvas fades from navy to white: the white text on it fails where it's pale
    d.background = Gradient(style="linear", angle=90, start="bg", end="ink")
    errors = " | ".join(validate(d, v))
    assert "weakest point" in errors


def test_new_features_are_written_the_way_lido_stores_them():
    from app.lido_create.kit import Gradient

    v = _variant()
    c = Canvas(v)
    c.background = Gradient(style="radial", start="soft", end="bg")
    c.shape(10, 10, 200, 80, "accent", kind="chevron",
            gradient=Gradient(style="linear", angle=45), stroke="ink", stroke_width=3,
            stroke_style="dashed")
    c.line(10, 200, 300, style="dotted", end="arrow")
    c.draw("circle", 10, 300, 200, 90)
    c.photo(300, 300, 300, 1, frame="letter_A")
    c.text("Hello", "headline", x=10, y=600, w=400, font="display", size=80, effect="hollow")
    d = Design(recipe="t", theme="business", palette="navy-amber", fonts=v.fonts.name,
               background=c.background, elements=c.els)
    layers = to_lido(d, v, photos=[PHOTOS[0]])[0]["layers"]
    by = {lr["type"]["resolvedName"]: lr["props"] for lr in layers.values()}

    root = by["RootLayer"]["color"]
    assert root["style"] == "radial" and len(root["colors"]) == 2
    shape = by["ShapeLayer"]
    assert shape["shape"] == "chevron" and shape["color"]["angle"] == 45
    assert shape["color"]["colors"][1]["color"].endswith(", 0)")  # fades to transparent
    assert shape["border"]["style"] == "shortDashes"
    assert by["LineLayer"]["style"] == "dots" and by["LineLayer"]["arrowEnd"] == "arrow"
    assert by["DrawLayer"]["path"].startswith("M ") and by["DrawLayer"]["width"] == 6
    frame = next(lr["props"] for lr in layers.values()
                 if lr["type"]["resolvedName"] == "FrameLayer" and lr["type"]["type"] != "logo")
    assert frame["scale"] == pytest.approx(300 / frames_lib()["letter_A"].w)
    assert by["TextLayer"]["effect"]["name"] == "hollow"


def frames_lib():
    from app.lido_create.shapes import frames
    return frames()


def test_mirroring_turns_asymmetric_shapes_and_line_ends():
    v = _variant()
    c = Canvas(v)
    c.shape(0, 0, 100, 50, "accent", kind="arrowRight")
    c.shape(0, 100, 100, 50, "accent", kind="chevron")
    c.line(0, 300, 200, end="arrow")
    m = mirror(Design(recipe="t", theme="business", palette="x", fonts="x", elements=c.els))
    arrow, chevron, line = m.elements
    assert arrow.shape == "arrowLeft"
    assert chevron.rotate == 180
    assert (line.line_start, line.line_end) == ("arrow", "none")


def test_ai_designs_must_use_lidos_wider_vocabulary():
    from app.lido_create.check import families_used

    v = _variant()
    plain = _recipe_design("split_offer", v)  # circles and rectangles only
    assert families_used(plain) == set()
    assert any("only uses circles and rectangles" in e
               for e in validate(plain, v, creative=True))
    assert families_used(_recipe_design("spotlight_launch", v)) >= {
        "gradient", "shape", "line", "draw", "frame", "effect"}


# -- art director: the plan and the catalogue ---------------------------------------------


def test_the_layout_catalogue_and_mood_map_only_use_real_names():
    from app.lido_create.catalog import layouts, moods, problems

    assert problems() == []
    assert len(layouts()) >= 30 and len(moods()) >= 8
    for count in range(1, 5):  # every photo count has layouts to pick from
        assert any(lay.fits(count) for lay in layouts().values())


def _plan(**overrides):
    from app.lido_create.plan import DesignPlan

    base = {"texts": [{"role": "headline", "text": "Summer Style Sale"}],
            "photos": [{"from_brief": "model", "subject": "a model", "role": "hero",
                        "frame": "rect"}],
            "logo": True, "exclude": [], "moods": ["bold_loud"], "layout": "split_half",
            "custom_layout": None, "shapes": [], "draw": [], "effects": [],
            "gradient": None, "photo_theme": "fashion", "notes": ""}
    return DesignPlan.model_validate({**base, **overrides})


def test_the_design_must_build_the_plan():
    v = _variant()
    d = _recipe_design("split_offer", v)  # 1 photo, a logo, "50% Off", "$" free
    assert validate(d, v, plan=_plan()) == []

    three = _plan(photos=[{"from_brief": f"pose {i}", "subject": f"pose {i}",
                           "role": "hero" if i == 0 else "supporting", "frame": "rect"}
                          for i in range(3)])
    assert any("exactly 3 photos" in e for e in validate(d, v, plan=three))
    assert any("no logo" in e for e in validate(d, v, plan=_plan(logo=False)))
    no_offers = validate(d, v, plan=_plan(exclude=["discount", "offer_badge"]))
    assert any("rules out offer badges" in e for e in no_offers)  # "Free Consult" badge
    assert any("frames" in e or "frame" in e
               for e in validate(d, v, plan=_plan(photos=[
                   {"from_brief": "x", "subject": "x", "role": "hero", "frame": "letter_A"}])))
    assert any("draw" in e for e in validate(d, v, plan=_plan(draw=["underline"])))


def test_a_plan_cleans_up_names_the_model_made_up():
    from app.lido_create.plan import _clean

    plan = _clean(_plan(photos=[{"from_brief": "x", "subject": "x", "role": "supporting",
                                 "frame": "sparkly"}],
                        shapes=["chevron", "unicorn"], layout="not_in_catalogue",
                        exclude=["logo"]))
    assert plan.photos[0].frame == "rounded" and plan.photos[0].role == "hero"
    assert plan.shapes == ["chevron"]
    assert plan.layout == "custom" and plan.logo is False
    with_cta = _clean(_plan(texts=[{"role": "headline", "text": "Hi"},
                                   {"role": "cta", "text": "Join"}], exclude=["button"]))
    assert "button" not in with_cta.exclude  # a requested CTA beats a stray exclusion


def test_photos_the_brief_never_asked_for_are_dropped():
    from app.lido_create.plan import _clean

    def photo(quote, role="supporting"):
        return {"from_brief": quote, "subject": quote, "role": role, "frame": "circle"}

    brief = "Launch post for our new organic face cream. Soft and elegant."
    padded = _clean(_plan(photos=[photo("organic face cream", "hero"),
                                  photo("natural ingredients like flowers"),
                                  photo("hand applying the cream")]), brief)
    assert [p.from_brief for p in padded.photos] == ["organic face cream"]
    yoga = "Show Tree Pose (Vrikshasana), Warrior Pose and Lotus Pose."
    poses = _clean(_plan(photos=[photo("Tree Pose (Vrikshasana)", "hero"),
                                 photo("Warrior Pose"), photo("Lotus Pose")]), yoga)
    assert len(poses.photos) == 3


def test_two_photos_of_the_same_quoted_thing_become_one():
    from app.lido_create.plan import _clean

    def photo(quote, role="supporting"):
        return {"from_brief": quote, "subject": quote, "role": role, "frame": "circle"}

    brief = "Launch our new organic face cream. Show the before and after of a facial."
    twice = _clean(_plan(photos=[photo("organic face cream", "hero"),
                                 photo("organic face cream")]), brief)
    assert len(twice.photos) == 1
    pair = _clean(_plan(photos=[photo("before and after", "hero"),
                                photo("before and after")]), brief)
    assert len(pair.photos) == 2  # one quote naming two things backs two photos


# -- the list block: every item, arranged by count ----------------------------------------


@pytest.mark.parametrize(("count", "columns"), [(2, 1), (4, 1), (5, 2), (6, 2), (8, 3), (9, 3)])
def test_a_list_keeps_every_item_and_picks_columns_by_count(count, columns):
    from app.lido_create.ai import normalise

    v = _variant()
    items = [f"Feature number {i + 1}" for i in range(count)]
    els = normalise([Element(kind="list", x=70, y=500, w=940, h=420, items=items,
                             bullet="dot", divider="line", size=28)], v)
    shown = [e for e in els if e.text_type == "item"]
    assert [e.text for e in shown] == items  # all of them, in order, word for word
    assert len({round(e.x) for e in shown}) == columns
    dividers = [e for e in els if e.kind == "line"]
    assert len(dividers) == (columns - 1 if columns > 1 else count - 1)
    assert all(e.y + e.h <= 920 + 1 for e in shown)  # the block fits its area


def test_a_long_list_shrinks_to_fit_instead_of_dropping_items():
    from app.lido_create.ai import normalise

    v = _variant()
    items = [f"A rather long feature description {i}" for i in range(9)]
    els = normalise([Element(kind="list", x=70, y=600, w=700, h=300, items=items,
                             bullet="check", size=34)], v)
    shown = [e for e in els if e.text_type == "item"]
    assert len(shown) == 9 and shown[0].size < 34


def test_the_plan_s_list_items_must_all_appear():
    v = _variant()
    d = _recipe_design("service_list", v)  # shows 3 items
    shown = [e.text for e in d.elements if e.text_type == "item"]
    plan = _plan(texts=[{"role": "headline", "text": "x"}]
                 + [{"role": "item", "text": t} for t in [*shown, "Extra Service"]])
    assert any("'Extra Service' from the plan is missing" in e
               for e in validate(d, v, plan=plan))


def test_text_left_on_a_photo_gets_a_card_under_it():
    from app.lido_create.brief import back_text_on_photos

    v = _variant()
    c = Canvas(v)
    c.photo(0, 0, 1080, 1080)  # a full-bleed photo...
    c.logo(70, 50)
    c.headline("Smile Brighter", x=70, y=400, w=700, max_lines=1, start=80, smallest=60)
    d = Design(recipe="t", theme="business", palette="x", fonts="x", elements=c.els)
    assert any("sits on a photo" in e for e in validate(d, v))
    fixed = back_text_on_photos(d, v)
    assert not any("headline" in e and "sits on a photo" in e for e in validate(fixed, v))
    card = fixed.elements[2]
    assert card.kind == "shape" and card.color == "bg"  # ink text on a bg-coloured card


def test_a_logo_on_top_of_the_headline_moves_to_a_free_corner():
    from app.lido_create.brief import relocate_logo

    v = _variant()
    c = Canvas(v)
    c.photo(540, 300, 500, 500)
    hl = c.headline("Grand Opening", x=70, y=60, w=600, max_lines=1, start=80, smallest=60)
    c.logo(hl.x + 20, hl.y)  # right on top of the headline
    d = Design(recipe="t", theme="business", palette="x", fonts="x", elements=c.els)
    assert any("logo overlaps" in e for e in validate(d, v))
    moved = relocate_logo(d, v)
    assert not any("logo" in e for e in validate(moved, v))


@pytest.mark.parametrize(("layout_model", "layout_effort", "expected"), [
    ("", "", {"model": None}),  # LLM_MODEL with LLM_REASONING_EFFORT
    ("gpt-6-astra", "", {"model": None}),  # naming LLM_MODEL keeps its reasoning
    ("gpt-6-astra", "medium", {"model": "gpt-6-astra", "reasoning_effort": "medium"}),
    ("gpt-6-luna", "low", {"model": "gpt-6-luna", "reasoning_effort": "low"}),
    ("gpt-4o", "", {"model": "gpt-4o"}),  # a plain model, no reasoning
])
def test_layout_model_settings(monkeypatch, layout_model, layout_effort, expected):
    from app.config import get_settings
    from app.lido_create.models import layout_call, plan_call

    s = get_settings()
    monkeypatch.setattr(s, "llm_model", "gpt-6-astra")
    monkeypatch.setattr(s, "llm_model_fast", "gpt-4o-mini")
    monkeypatch.setattr(s, "lido_layout_model", layout_model)
    monkeypatch.setattr(s, "lido_layout_reasoning_effort", layout_effort)
    monkeypatch.setattr(s, "lido_plan_model", "")
    monkeypatch.setattr(s, "lido_plan_reasoning_effort", "")
    assert layout_call() == expected
    assert plan_call() == {"model": "gpt-4o-mini"}
