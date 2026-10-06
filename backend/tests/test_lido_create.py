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
from app.lido_corpus.palette import parse_palette, to_hex
from app.lido_create import brief, drafts
from app.lido_create.check import validate
from app.lido_create.kit import (
    FONT_SETS,
    LOGOS,
    PALETTES,
    THEMES_BY_NAME,
    Canvas,
    Design,
    Element,
    Photo,
    Variant,
    to_out,
)
from app.lido_create.kit import W as W_CANVAS
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


FAKE_TEXT_USAGE = (1_000, 500)  # input, output tokens every fake LLM call "uses"
FAKE_IMAGE_TOKENS = 2_000  # output tokens every fake image "uses"


def _bill_text(model: str) -> None:
    """What the OpenAI adapter does after every call: charge it to the current bill."""
    from types import SimpleNamespace as NS

    from app import costs
    inp, out = FAKE_TEXT_USAGE
    costs.record_text(model, NS(input_tokens=inp, output_tokens=out,
                                input_tokens_details=NS(cached_tokens=0)))


class _FakeLLM:
    """Replays a pro recipe as the model's answer. The first draft carries a flaw: by
    default a line break (the mechanical fixes clean it, no repair call), or with
    `defect = "headline"` a missing headline, which only a repair round's patch fixes."""

    LAYOUTS = ("centre_stage", "split_half", "top_band")

    def __init__(self):
        self.calls: list[str] = []  # the designer's calls (drafts and repairs)
        self.plan_calls: list[dict] = []  # the art director's calls
        self.repair_calls: list[dict] = []  # the repair rounds' kwargs
        self.failures: dict[int, AdapterError] = {}  # designer call number (1-based) -> error
        self.plan_extra: dict = {}  # extra plan fields (backdrop…)
        self.plan_photo = {"from_brief": "dinner party", "subject": "a dinner party",
                           "role": "hero", "frame": "cutout"}
        self.defect: str | None = "line_break"
        self.headline: tuple[int, dict] | None = None  # (index, element) the defect took
        self.repairs_fix = True  # False: repair rounds send no edits (nothing gets fixed)

    async def complete_json(self, *, system, user, schema, **kwargs):
        if schema.__name__ == "DesignPlan":
            self.plan_calls.append({"user": user, **kwargs})
            _bill_text(kwargs.get("model") or "gpt-4o")
            return LLMResult(parsed=schema(
                texts=[{"role": "headline", "text": "Grand Night"}],
                photos=[self.plan_photo],
                logo=True, exclude=[], moods=["warm_handmade"],
                layout=self.LAYOUTS[(len(self.plan_calls) - 1) % 3], custom_layout=None,
                shapes=["rhombus"], draw=[], effects=[], gradient=None,
                photo_theme="business", notes="warm and bold", **self.plan_extra),
                raw="", model="fake")
        self.calls.append(user)
        if len(self.calls) in self.failures:
            raise self.failures[len(self.calls)]
        _bill_text(kwargs.get("model") or "gpt-6-astra")
        if schema.__name__ == "BriefRepair":
            self.repair_calls.append(kwargs)
            edits = [] if self.headline is None or not self.repairs_fix else [
                {"action": "replace", "index": self.headline[0], "element": self.headline[1]}]
            return LLMResult(parsed=schema(edits=edits), raw="", model="fake")
        v = _variant()
        design = _recipe_design("fresh_promo", v)  # rich enough for the creative checks
        elements = [to_out(e) | ({"subject": "a dinner party"} if e.kind == "photo" else {})
                    for e in design.elements]
        index = next(i for i, e in enumerate(elements) if e.get("text_type") == "headline")
        first = len(self.calls) == 1  # only the first draft is flawed
        if self.defect == "line_break" and first:
            elements[index]["text"] = "Grand\nNight"
        elif self.defect == "headline" and first:
            self.headline = (index, dict(elements[index]))
            elements[index]["text_type"] = "kicker"
        parsed = schema(
            name="test_layout", idea="A centred invite.",
            colors=brief.BriefColors(bg="#241640", ink="#ffffff", accent="#ff6b6b",
                                     on_accent="#241640", soft="#ffde96"),
            fonts=v.fonts.name, photo_theme="business", background=None, elements=elements)
        return LLMResult(parsed=parsed, raw="", model="fake")


class _MemoryDrafts:
    """`lido_drafts` in memory (drafts.DraftStore), so the tests need no database."""

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.last_id = 0  # an identity column: ids are never reused

    async def insert(self, row):
        self.last_id += 1
        self.rows[self.last_id] = {**row, "id": self.last_id}
        return self.last_id

    async def set_preview(self, draft_id, url):
        self.rows[draft_id]["preview_url"] = url

    async def set_timing(self, draft_id, timing):
        self.rows[draft_id].update(timing=timing, generation_ms=timing["totalMs"])

    async def list(self, limit):
        rows = sorted(self.rows.values(), key=lambda r: r["created_at"], reverse=True)
        return [{k: v for k, v in r.items() if k != "document"} for r in rows][:limit]

    async def get(self, draft_id):
        return self.rows.get(draft_id)

    async def delete(self, draft_id):
        return self.rows.pop(draft_id, None) is not None

    async def fingerprints(self, limit):
        return [r["fingerprint"] for r in await self.list(None) if r["fingerprint"]][:limit]


@pytest.fixture
def api(tmp_path, monkeypatch):
    from app.adapters import registry
    from app.api.main import create_app
    from app.config import get_settings

    fake = _FakeLLM()
    memory = _MemoryDrafts()
    monkeypatch.setattr(drafts, "store", lambda: memory)
    monkeypatch.setattr(drafts, "photo_pool", lambda: PHOTOS)
    monkeypatch.setattr(drafts, "screenshot", lambda layers, out: False)
    monkeypatch.setattr(registry, "llm", lambda: fake)
    monkeypatch.setattr(get_settings(), "openai_api_key", "test-key")
    for name, value in (("llm_model_fast", "gpt-4o-mini"), ("lido_plan_model", ""),
                        ("lido_plan_reasoning_effort", ""), ("lido_layout_model", ""),
                        ("lido_layout_reasoning_effort", ""), ("lido_repair_model", ""),
                        ("lido_repair_reasoning_effort", ""), ("lido_layout_candidates", 1),
                        ("lido_draft_photos", "cache")):
        monkeypatch.setattr(get_settings(), name, value)  # not whatever .env says
    monkeypatch.setattr(brief, "RETRY_DELAYS", (0.0, 0.0))
    from app.lido_create import plan as plan_module
    monkeypatch.setattr(plan_module, "FREE_SHARE", 0.0)  # only the forced free variation
    monkeypatch.chdir(tmp_path)  # anything written locally would land here
    return TestClient(create_app()), fake, memory


def test_prompt_becomes_a_saved_draft(api):
    client, fake, memory = api
    fake.defect = "headline"
    response = client.post("/v1/lido/drafts", json={"prompt": "Grand opening dinner party"})
    assert response.status_code == 200, response.text
    [draft] = response.json()

    assert len(fake.calls) == 2  # first answer failed the checks, the repair passed
    assert len(fake.plan_calls) == 1  # one art-director plan, on the fast model
    assert fake.plan_calls[0]["model"] == "gpt-4o-mini"
    assert draft["plan"]["photos"][0]["subject"] == "a dinner party"
    assert draft["fingerprint"].startswith(draft["planLayout"])
    assert "Grand opening dinner party" in fake.calls[0]
    assert "needs exactly one headline" in fake.calls[1]
    assert "\n0: {" in fake.calls[1]  # numbered, so the patch can point at elements
    assert draft["problems"] == [] and draft["attempts"] == 2
    assert [c["step"] for c in draft["llmCalls"]] == ["draft", "repair"]
    assert draft["source"] == "brief" and draft["prompt"] == "Grand opening dinner party"
    assert draft["colors"]["accent"] == "#ff6b6b"
    assert draft["photoSubjects"] == ["a dinner party"]
    layers = draft["document"][0]["layers"]
    assert layers["ROOT"]["props"]["color"] == "rgb(36, 22, 64)"

    tid = draft["id"]
    [row] = memory.rows.values()  # stored as one row, nothing on disk
    assert row["id"] == tid == 1 and row["document"] == draft["document"]
    assert row["prompt"] == "Grand opening dinner party" and row["source"] == "brief"
    assert row["fingerprint"] == draft["fingerprint"] and row["info"]["colors"]
    assert row["preview_url"] is None and not draft["hasPreview"]

    listed = client.get("/v1/lido/drafts").json()
    assert [d["id"] for d in listed] == [tid] and listed[0]["document"] is None
    assert client.get(f"/v1/lido/drafts/{tid}").json()["document"] == draft["document"]
    assert client.delete(f"/v1/lido/drafts/{tid}").status_code == 204
    assert client.get(f"/v1/lido/drafts/{tid}").status_code == 404
    assert client.get("/v1/lido/drafts").json() == []


def test_a_preview_is_uploaded_to_the_object_store(api, monkeypatch, tmp_path):
    client, _, memory = api
    uploads = []

    def shoot(layers, out):
        out.write_bytes(b"png")
        return True

    def upload(folder, name, data):
        uploads.append((folder, name, data))
        return f"https://store.test/{folder}/{name}.png"

    monkeypatch.setattr(drafts, "screenshot", shoot)
    monkeypatch.setattr(drafts, "upload_asset", upload)
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Grand opening"}).json()
    tid = draft["id"]
    assert uploads == [(f"drafts/{tid}", "preview", b"png")]  # keyed by the row id
    assert memory.rows[tid]["preview_url"] == draft["previewUrl"]
    assert draft["hasPreview"] and draft["previewUrl"] == f"https://store.test/drafts/{tid}/preview.png"
    assert client.get("/v1/lido/drafts").json()[0]["previewUrl"] == draft["previewUrl"]
    assert list(tmp_path.iterdir()) == []  # the screenshot only passed through a temp dir


def test_the_notebook_reads_recent_fingerprints_from_the_store(api):
    client, fake, _ = api
    client.post("/v1/lido/drafts", json={"prompt": "Grand opening"})
    client.post("/v1/lido/drafts", json={"prompt": "Grand opening"})
    first = client.get("/v1/lido/drafts").json()[-1]["fingerprint"]
    assert first and first in fake.plan_calls[-1]["user"]


def test_variations_get_distinct_ids_and_directions(api):
    client, _, _ = api
    drafts_made = client.post("/v1/lido/drafts",
                              json={"prompt": "Launch party", "variations": 3}).json()
    assert len({d["id"] for d in drafts_made}) == 3
    # each variation got its own plan and layout; the last one is a free invention
    assert len({d["planLayout"] for d in drafts_made}) == 3
    assert drafts_made[-1]["planLayout"] == "custom"


class _FakeImages:
    """Stands in for the image adapters: a solid PNG at the asked size, or a failure."""

    name = "fake:images"

    def __init__(self, fail: bool = False):
        self.fail, self.prompts = fail, []

    async def generate(self, *, prompt, negative_prompt="", width=1024, height=1024,
                       quality="medium", **_):
        import io

        from PIL import Image

        from app.adapters.base import ImageResult

        self.prompts.append(prompt)
        if self.fail:
            raise AdapterError("image API 500")
        from types import SimpleNamespace as NS

        from app import costs
        costs.record_image("gpt-image-2.5-flare",
                           NS(input_tokens=50, output_tokens=FAKE_IMAGE_TOKENS,
                              input_tokens_details=NS(text_tokens=50, image_tokens=0)))
        out = io.BytesIO()
        Image.new("RGB", (width, height), (200, 120, 90)).save(out, format="PNG")
        return ImageResult(data=out.getvalue(), mime="image/png", width=width,
                           height=height, model=self.name)


def _generating(monkeypatch, images: _FakeImages) -> list[str]:
    from app.config import get_settings
    from app.lido_create import photos

    uploads: list[str] = []

    def upload(folder, name, data):
        uploads.append(f"{folder}/{name}")
        return f"https://store.test/{folder}/{name}.png"

    monkeypatch.setattr(get_settings(), "lido_draft_photos", "generate")
    monkeypatch.setattr(photos, "text_to_image", lambda: images)
    monkeypatch.setattr(photos, "transparent_image", lambda: images)
    monkeypatch.setattr(photos, "upload_asset", upload)
    from app.lido_corpus import assets_ai  # the template flow's renderer, reused as is
    monkeypatch.setattr(assets_ai, "get_text_to_image", lambda: images)
    monkeypatch.setattr(assets_ai, "get_transparent_image", lambda: images)
    return uploads


def _photo_urls(draft: dict) -> list[str]:
    return [lr["props"]["image"]["url"] for lr in draft["document"][0]["layers"].values()
            if lr["type"]["resolvedName"] == "FrameLayer" and lr["type"]["type"] != "logo"]


def test_photos_come_from_the_cache_by_default(api):
    client, _, _ = api
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Grand opening"}).json()
    assert draft["photoSource"] == "corpus-cache" and draft["photoFallbacks"] == 0
    assert all(u in {p.url for p in PHOTOS} for u in _photo_urls(draft))


def test_photos_are_generated_from_their_subjects_when_configured(api, monkeypatch):
    client, _, _ = api
    images = _FakeImages()
    uploads = _generating(monkeypatch, images)
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Grand opening"}).json()
    assert draft["photoSource"] == "generated" and draft["photoFallbacks"] == 0
    assert images.prompts and images.prompts[0].startswith("a dinner party")
    assert _photo_urls(draft) == [f"https://store.test/{u}.png" for u in uploads]


def test_photos_start_from_the_plan_and_are_reused_by_the_design(api, monkeypatch):
    client, fake, _ = api
    fake.defect = "headline"  # a repair round too: the photo must not be rendered again
    images = _FakeImages()
    uploads = _generating(monkeypatch, images)
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Grand opening"}).json()
    assert len(images.prompts) == 1 and len(uploads) == 1  # started early, used once
    assert _photo_urls(draft) == [f"https://store.test/{uploads[0]}.png"]


def test_the_plan_s_photo_is_rendered_once_however_the_designer_words_it(api, monkeypatch):
    """Draft #56: the designer rewrote the plan's subject (same washing machine, longer
    sentence), it was taken for another photo and rendered a second time."""
    client, fake, _ = api
    fake.plan_photo = {**fake.plan_photo, "subject": "Elegant evening banquet, candlelit"}
    images = _FakeImages()
    uploads = _generating(monkeypatch, images)
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Grand opening"}).json()
    assert images.prompts == [images.prompts[0]] and len(uploads) == 1
    assert images.prompts[0].startswith("Elegant evening banquet")  # the plan's render
    assert _photo_urls(draft) == [f"https://store.test/{uploads[0]}.png"]


def test_subject_overlap_reads_a_richer_rewording_as_the_same_picture():
    from app.lido_create.photos import SAME_SUBJECT, subject_overlap

    plan = ("A photorealistic washing machine in a modern home setting with glossy "
            "reflections, water splashes, and fresh laundry elements")
    design = ("A large photorealistic premium metallic front-loading washing machine "
              "dominates a stylish bright modern Indian home laundry setting, with "
              "sophisticated blue and white finishes, glossy reflections, realistic "
              "shadows, subtle water splashes, neatly folded fresh laundry and elegant "
              "glowing highlights.")
    assert subject_overlap(plan, design) >= SAME_SUBJECT
    assert subject_overlap(plan, "A happy family cooking in a kitchen") < SAME_SUBJECT


def test_a_hung_image_request_is_tried_once_more():
    import asyncio

    from openai import APITimeoutError

    from app.adapters.openai_adapters import _call_images

    class Images:
        def __init__(self):
            self.calls: list[float] = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs["timeout"])
            if len(self.calls) == 1:
                raise APITimeoutError(request=None)  # type: ignore[arg-type]
            return "rendered"

    class Client:
        images = Images()

    assert asyncio.run(_call_images(Client(), model="m", prompt="p")) == "rendered"
    assert Client.images.calls == [90.0, 90.0]


def test_a_started_photo_of_the_wrong_shape_is_rendered_again(api, monkeypatch):
    client, fake, _ = api
    # the plan said a framed portrait photo, the design made it a cutout
    fake.plan_photo = {**fake.plan_photo, "frame": "rect", "orientation": "portrait"}
    images = _FakeImages()
    uploads = _generating(monkeypatch, images)
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Grand opening"}).json()
    assert len(images.prompts) == 2  # the early one is not used
    assert _photo_urls(draft) == [f"https://store.test/{uploads[-1]}.png"]


def test_a_failed_photo_generation_keeps_a_cached_placeholder(api, monkeypatch):
    client, _, _ = api
    _generating(monkeypatch, _FakeImages(fail=True))
    response = client.post("/v1/lido/drafts", json={"prompt": "Grand opening"})
    assert response.status_code == 200, response.text
    [draft] = response.json()
    urls = _photo_urls(draft)
    assert draft["photoSource"] == "generated" and draft["photoFallbacks"] == len(urls) > 0
    assert all(u in {p.url for p in PHOTOS} for u in urls)


def test_generate_without_a_real_image_model_uses_the_cache(monkeypatch):
    from app.adapters import stub_adapters as stub
    from app.config import get_settings
    from app.lido_create import photos

    monkeypatch.setattr(get_settings(), "lido_draft_photos", "generate")
    monkeypatch.setattr(photos, "text_to_image", stub.StubTextToImage)
    monkeypatch.setattr(photos, "transparent_image", stub.StubTransparentImage)
    assert photos.configured_source().name == "corpus-cache"
    monkeypatch.setattr(photos, "text_to_image", _FakeImages)
    monkeypatch.setattr(photos, "transparent_image", _FakeImages)
    assert photos.configured_source().name == "generated"
    monkeypatch.setattr(get_settings(), "lido_draft_photos", "cache")
    assert photos.configured_source().name == "corpus-cache"


def test_brand_colours_and_logo_are_used_like_fill_a_template(api):
    client, fake, memory = api
    logo = "https://brand.test/logo.png"
    response = client.post("/v1/lido/drafts", json={
        "prompt": "Grand opening", "palette": ["#0B3D2E", "#f2c14e", "#e4572e", "#f7f3e9"],
        "logoUrl": logo})
    assert response.status_code == 200, response.text
    [draft] = response.json()
    expected = brief.brand_palette(parse_palette(["#0b3d2e", "#f2c14e", "#e4572e", "#f7f3e9"]))
    assert draft["colors"] == {r: to_hex(expected.color(r)) for r in brief.ROLES}
    assert draft["colors"]["accent"] == "#0b3d2e"  # the first colour is the primary
    assert "BRAND COLOURS" in fake.calls[0] and "#0b3d2e" in fake.calls[0]
    assert draft["brandPalette"] == ["#0b3d2e", "#f2c14e", "#e4572e", "#f7f3e9"]
    assert draft["logoUrl"] == logo and draft["plan"]["logo"] is True
    layers = draft["document"][0]["layers"].values()
    logos = [lr for lr in layers if lr["type"]["type"] == "logo"]
    assert logos and all(lr["props"]["image"]["url"] == logo for lr in logos)
    assert next(iter(memory.rows.values()))["info"]["logoUrl"] == logo


def test_without_brand_inputs_the_designer_picks_and_the_stock_logo_stays(api):
    client, fake, _ = api
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Grand opening"}).json()
    assert draft["colors"]["accent"] == "#ff6b6b" and "BRAND COLOURS" not in fake.calls[0]
    assert draft.get("brandPalette") is None and draft["logoUrl"] is None
    logos = [lr for lr in draft["document"][0]["layers"].values()
             if lr["type"]["type"] == "logo"]
    assert all(lr["props"]["image"]["url"] in LOGOS.values() for lr in logos)


@pytest.mark.parametrize("body", [{"palette": ["not-a-colour"]},
                                  {"palette": ["#111111"] * 2 + ["#222", "#333", "#444"]},
                                  {"logoUrl": "ftp://brand.test/logo.png"}])
def test_bad_brand_inputs_are_rejected(api, body):
    client, fake, _ = api
    response = client.post("/v1/lido/drafts", json={"prompt": "Grand opening", **body})
    assert response.status_code == 422 and not fake.calls


@pytest.mark.parametrize("colors", [["#0b3d2e"], ["#ffc857"], ["#e4572e"], ["#ffffff"],
                                    ["#000000"], ["#ff0000", "#00ff00"],
                                    ["#777777", "#787878", "#797979"],
                                    ["#1d3557", "#457b9d", "#a8dadc", "#f1faee"]])
def test_a_brand_palette_is_always_readable(colors):
    from app.lido_corpus.palette import contrast

    p = brief.brand_palette(parse_palette(colors))
    assert p.accent == parse_palette(colors)[0]
    assert contrast(p.ink, p.bg) >= brief.TEXT_CONTRAST
    assert contrast(p.on_accent, p.accent) >= brief.TEXT_CONTRAST


def test_a_given_logo_overrides_a_plan_without_one():
    from app.lido_create.plan import DesignPlan

    plan = DesignPlan(texts=[{"role": "headline", "text": "Hi"}], photos=[], logo=False,
                      exclude=["logo", "button"], moods=["warm_handmade"],
                      layout="centre_stage", custom_layout=None, shapes=[], draw=[],
                      effects=[], gradient=None, photo_theme="business", notes="")
    plan = drafts._with_logo(plan)
    assert plan.logo is True and plan.exclude == ["button"]


def test_how_long_it_took_is_saved_with_each_draft(api):
    client, _, memory = api
    made = client.post("/v1/lido/drafts", json={"prompt": "Launch party", "variations": 2}).json()
    for draft in made:
        t = draft["timing"]
        assert set(t) == {"planMs", "designMs", "photosMs", "saveMs", "totalMs"}
        assert all(isinstance(ms, int) and ms >= 0 for ms in t.values())
        assert draft["generationMs"] == t["totalMs"] >= t["designMs"]
        row = memory.rows[draft["id"]]  # stored, not just returned
        assert row["generation_ms"] == t["totalMs"] and row["timing"] == t
    # both variations share the planning step; the list shows the total too
    assert made[0]["timing"]["planMs"] == made[1]["timing"]["planMs"]
    listed = {d["id"]: d for d in client.get("/v1/lido/drafts").json()}
    assert all(listed[d["id"]]["generationMs"] == d["generationMs"] for d in made)


def test_bad_ids_are_not_found(api):
    client, _, _ = api
    assert client.get("/v1/lido/drafts/../../etc").status_code == 404
    assert client.get("/v1/lido/drafts/template_1").status_code == 404
    assert client.get("/v1/lido/drafts/12345").status_code == 404


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
    fake.defect = "headline"
    fake.failures = {2: AdapterError("refused", recoverable=False)}  # the repair call
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Launch"}).json()
    assert any("headline" in p for p in draft["problems"])


def test_slips_the_code_can_fix_cost_no_repair_round(api):
    client, fake, _ = api  # the default flaw: a line break in the headline
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Launch"}).json()
    assert len(fake.calls) == 1 and draft["attempts"] == 1
    assert draft["problems"] == []
    headline = next(lr for lr in draft["document"][0]["layers"].values()
                    if "Grand Night" in json.dumps(lr))
    assert "\\n" not in json.dumps(headline)


def test_repairs_use_the_repair_model(api, monkeypatch):
    from app.config import get_settings

    client, fake, _ = api
    fake.defect = "headline"
    monkeypatch.setattr(get_settings(), "lido_repair_model", "gpt-4o")
    client.post("/v1/lido/drafts", json={"prompt": "Launch"})
    assert [c["model"] for c in fake.repair_calls] == ["gpt-4o"]
    assert "reasoning_effort" not in fake.repair_calls[0]


def test_several_candidates_race_and_a_passing_one_saves_the_repair(api, monkeypatch):
    from app.config import get_settings

    client, fake, _ = api
    fake.defect = "headline"  # the first candidate is flawed, the second is not
    monkeypatch.setattr(get_settings(), "lido_layout_candidates", 2)
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Launch"}).json()
    assert len(fake.calls) == 2 and not fake.repair_calls
    assert draft["problems"] == [] and draft["attempts"] == 1


def _stream(client, body) -> list[dict]:
    with client.stream("POST", "/v1/lido/drafts/stream", json=body) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        return [json.loads(line) for line in response.iter_lines() if line]


def test_the_stream_reports_each_step_then_each_draft(api):
    client, fake, memory = api
    fake.defect = "headline"
    events = _stream(client, {"prompt": "Grand opening dinner party", "variations": 2})
    stages = [e["stage"] for e in events]
    assert stages[0] == "planning" and stages[-1] == "done"
    assert stages.count("draft") == 2 and "repairing" in stages
    for i in (0, 1):  # each variation in order: designed, photographed, saved
        mine = [e["stage"] for e in events if e.get("variation") == i]
        assert mine[0] == "designing" and mine[-3:] == ["photos", "saving", "draft"]
    drafts_sent = [e["draft"] for e in events if e["stage"] == "draft"]
    assert {d["id"] for d in drafts_sent} == set(memory.rows)
    assert all("document" in d and "elapsedMs" in e for d, e in zip(drafts_sent, events))
    times = [e["elapsedMs"] for e in events]
    assert times == sorted(times)


def test_a_failure_arrives_in_the_stream(api):
    client, fake, _ = api
    fake.failures = {n: AdapterError("refused", recoverable=False) for n in range(1, 5)}
    events = _stream(client, {"prompt": "Grand opening"})
    assert events[-1]["stage"] == "error" and events[-1]["status"] == 503
    assert "refused" in events[-1]["detail"]


def test_repairs_stop_once_the_model_cannot_fix_what_is_left(api):
    client, fake, _ = api
    fake.defect, fake.repairs_fix = "headline", False
    [draft] = client.post("/v1/lido/drafts", json={"prompt": "Launch"}).json()
    # one round tried the missing headline and failed; a second would repeat it
    assert len(fake.repair_calls) == 1
    assert [c["step"] for c in draft["llmCalls"]] == ["draft", "repair"]
    assert any("headline" in p for p in draft["problems"])


def test_the_photo_minimum_shrinks_when_photos_share_the_canvas():
    v = _variant()
    d = _recipe_design("split_offer", v)
    photo = next(e for e in d.elements if e.kind == "photo")
    small = [photo.model_copy(update={"x": 60 + 300 * i, "y": 60, "w": 250, "h": 141,
                                      "frame": None, "clip": "rect"}) for i in range(3)]
    rest = [e for e in d.elements if e.kind != "photo"]
    def too_small(photos):
        errors = validate(d.model_copy(update={"elements": photos + rest}), v)
        return [e for e in errors if "too small to read (at least" in e]
    assert too_small(small[:2]) and "200px" in too_small(small[:2])[0]
    assert not too_small(small)  # 3 photos: 140px is enough


def test_photo_slips_are_fixed_by_code():
    v = _variant()
    d = _recipe_design("split_offer", v)
    p = next(i for i, e in enumerate(d.elements) if e.kind == "photo")
    photo = d.elements[p]

    off = d.model_copy(update={"elements": [
        *d.elements[:p], photo.model_copy(update={"x": W_CANVAS - photo.w / 2, "bleed": None}),
        *d.elements[p + 1:]]})
    fixed = brief.photos_inside(off, v).elements[p]
    assert fixed.x + fixed.w <= W_CANVAS + 1 and fixed.w == photo.w

    tiny = d.model_copy(update={"elements": [
        *d.elements[:p], photo.model_copy(update={"w": 160, "h": 90}), *d.elements[p + 1:]]})
    grown = brief.grow_photos(tiny, v).elements[p]
    assert min(grown.w, grown.h) >= 200 and grown.w / grown.h == pytest.approx(160 / 90)

    # sticks out past the photo's edge: decoration under it, not a snug mat
    under = Element(kind="shape", shape="circle", x=photo.x - 100, y=photo.y + 20,
                    w=photo.w * 0.8, h=photo.h * 0.8, color="accent", bleed=True)
    stacked = d.model_copy(update={"elements": [*d.elements[:p], under, *d.elements[p:]]})
    assert any("behind a photo" in e for e in validate(stacked, v, creative=True))
    cleared = brief.clear_under_photos(stacked, v)
    assert under not in cleared.elements and len(cleared.elements) == len(d.elements)


def test_four_photos_never_get_wide_frames():
    from app.lido_create.plan import _clean

    photos = [{"from_brief": w, "subject": f"the {w}", "role": "supporting",
               "frame": "rounded_card", "orientation": "landscape"}
              for w in ("slide", "pool", "raft", "river")]
    plan = _clean(_plan(photos=photos), "a slide, a pool, a raft and a river")
    assert len(plan.photos) == 4
    assert {p.frame for p in plan.photos} == {"rounded"}
    assert {p.orientation for p in plan.photos} == {"square"}
    one = _clean(_plan(photos=photos[:1]), "a slide")
    assert one.photos[0].frame == "rounded_card"  # a lone photo may be wide


def test_lido_max_photos_caps_the_plan_and_the_catalogue(monkeypatch):
    from app.lido_create import catalog
    from app.lido_create import plan as plan_module

    monkeypatch.setattr(catalog, "MAX_PHOTOS", 3)  # LIDO_MAX_PHOTOS=3
    monkeypatch.setattr(plan_module, "MAX_PHOTOS", 3)
    catalog.layouts.cache_clear()
    try:
        assert catalog.layouts() and max(lay.photos[1] for lay in catalog.layouts().values()) == 3
        assert "mosaic_four" not in catalog.layouts()  # a 4-photo layout is left out
        assert catalog.problems() == []  # the file itself is still valid
        photos = [{"from_brief": w, "subject": f"the {w}", "role": "supporting",
                   "frame": "rounded"} for w in ("slide", "pool", "raft", "river", "tube")]
        plan = plan_module._clean(_plan(photos=photos),
                                  "a slide, a pool, a raft, a river and a tube")
        assert len(plan.photos) == 3  # so at most 3 images are generated
    finally:
        catalog.layouts.cache_clear()


def test_each_draft_carries_its_own_bill_step_by_step(api, monkeypatch):
    from app import costs

    client, fake, _ = api
    fake.defect = "headline"  # a repair round, so every step is billed
    images = _FakeImages()
    _generating(monkeypatch, images)
    made = client.post("/v1/lido/drafts", json={"prompt": "Launch", "variations": 2}).json()
    inp, out = FAKE_TEXT_USAGE
    plan = costs.text_cost("gpt-4o-mini", inp, 0, out)  # the fixture's plan model
    design = costs.text_cost("gpt-6-astra", inp, 0, out)  # LLM_MODEL (no layout model set)
    photo = costs.image_cost("gpt-image-2.5-flare", 50, 0, FAKE_IMAGE_TOKENS)
    first, second = (d["cost"] for d in made)
    # the first variation: its plan, its draft, its repair, its one photo — nothing else
    assert first["byStepUsd"] == pytest.approx(
        {"plan": plan, "design": design, "repair": design, "photo": photo})
    assert first["totalUsd"] == pytest.approx(plan + 2 * design + photo)
    assert first["unknownCalls"] == 0 and len(first["calls"]) == 4
    # the second has no flaw (only the first draft call carries it): no repair
    assert set(second["byStepUsd"]) == {"plan", "design", "photo"}


def test_the_designer_s_shared_instructions_are_identical_on_every_call(api, monkeypatch):
    client, fake, _ = api
    seen: list[tuple[str, str, str | None]] = []
    real = fake.complete_json

    async def spy(*, system, user, schema, **kwargs):
        seen.append((schema.__name__, system, kwargs.get("cache_key")))
        return await real(system=system, user=user, schema=schema, **kwargs)

    fake.defect = "headline"  # a repair too: it shares the designer's instructions
    monkeypatch.setattr(fake, "complete_json", spy)
    client.post("/v1/lido/drafts", json={"prompt": "Launch", "variations": 2})
    design = [(s, k) for name, s, k in seen if name in ("BriefDesign", "BriefRepair")]
    assert len(design) == 3 and len({s for s, _ in design}) == 1  # byte-identical
    assert {k for _, k in design} == {"lido-design"}
    assert "EXAMPLE LAYOUTS" in design[0][0]  # the examples are in the cached part
    assert all("EXAMPLE LAYOUTS" not in call for call in fake.calls)  # not in the brief
    assert {k for name, _, k in seen if name == "DesignPlan"} == {"lido-plan"}


def test_the_reply_format_is_lean_and_reads_back_exactly():
    from pydantic import TypeAdapter

    from app.lido_create.kit import ElementOut, Gradient, to_element
    shape = Element(kind="shape", shape="rectangle", x=10.4, y=20, w=300, h=50,
                    color="accent", radius=12, opacity=0.5, bleed=True,
                    gradient=Gradient(style="linear", angle=180))
    text = Element(kind="text", x=70, y=80, w=900, h=0, text="Hi", text_type="headline",
                   size=96, effect="shadow", effect_color="soft")
    out = to_out(shape)
    assert out["x"] == 10 and "opacity" not in out  # whole pixels; rare settings grouped
    assert out["style"] == {"gradient": {"style": "linear", "angle": 180.0}, "opacity": 0.5}
    assert to_out(text)["effect"] == {"name": "shadow", "color": "soft"}
    adapter = TypeAdapter(ElementOut)
    for e in (shape, text):
        back = to_element(adapter.validate_python(to_out(e)))
        assert back.model_dump(exclude={"x"}) == e.model_dump(exclude={"x"})


def test_patch_edits_apply_against_the_numbering_sent():
    els = [Element(kind="shape", shape="circle", x=i, y=0, w=10, h=10) for i in range(4)]
    new = brief.ElementEdit.model_validate(
        {"action": "insert", "index": 2,
         "element": {"kind": "logo", "x": 0, "y": 0, "w": 110, "h": 89}})
    edits = [brief.ElementEdit(action="delete", index=0, element=None),
             brief.ElementEdit(action="delete", index=2, element=None), new,
             brief.ElementEdit(action="delete", index=9, element=None)]  # points nowhere
    out = brief.apply_edits(els, edits)
    assert [e.kind for e in out] == ["shape", "logo", "shape"]
    assert [e.x for e in out if e.kind == "shape"] == [1, 3]


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


# -- backdrops and contact icons -------------------------------------------------------


@pytest.mark.parametrize("style", ["split_half", "diagonal_split", "diagonal_bands",
                                   "corner_glow", "spotlight", "horizon_arc"])
def test_every_backdrop_expands_into_bleeding_backdrop_layers_with_text_areas(style):
    from app.lido_create.backdrops import Backdrop, brief_for, expand

    ex = expand(Backdrop(style=style, angle=50, split=0.95))  # out of range: clamped
    assert ex.layers and all(e.bleed and e.backdrop and e.kind == "shape" for e in ex.layers)
    assert ex.base is None or ex.base.end is not None  # a canvas gradient must end in a colour
    for palette in (None, PALETTES[0], PALETTES[5]):
        text = brief_for(ex, palette)
        assert "Text areas:" in text and "- the plain canvas" in text


def test_backdrop_layers_are_hidden_from_the_models_schema_and_cleared_on_its_elements():
    from app.adapters.openai_schema import response_format

    schema = json.dumps(response_format(brief.BriefDesign))
    assert '"backdrop"' not in schema and '"doodle"' not in schema


def test_a_photo_may_sit_on_the_backdrop_and_a_glow_has_no_edge_to_straddle():
    from app.lido_create.backdrops import Backdrop, expand
    from app.lido_create.check import seamless

    v = _variant()
    d = _recipe_design("fresh_promo", v)
    glow = expand(Backdrop(style="corner_glow"))
    assert all(seamless(e) for e in glow.layers)
    on_glow = d.model_copy(update={"background": glow.base,
                                   "elements": [*glow.layers, *d.elements]})
    assert not any("behind a photo" in e or "straddles" in e
                   for e in validate(on_glow, v, creative=True))


def test_the_icon_library_loads_clean_and_every_icon_draws_inside_its_box():
    from app.lido_create.doodles import doodle_path, info_icon, library, problems

    assert problems() == []
    assert len(library()) >= 10
    for kind in ("website", "phone", "email", "address"):
        assert info_icon(kind) is not None
    for name in library():
        path, pts = doodle_path(name, 80, 60, 4, seed=3)
        assert path.startswith("M ")
        assert all(-2 <= x <= 82 and -2 <= y <= 62 for x, y in pts), name


def test_arc_flags_packed_without_spaces_are_read_right():
    from app.lido_create.svgpath import flatten

    packed = flatten("M15 4a1.5 1.5 0 00-2.5-1.5l-9 9", strokes=True)
    spaced = flatten("M15 4a1.5 1.5 0 0 0 -2.5 -1.5l-9 9", strokes=True)
    assert packed == spaced and max(x for s in packed for x, _ in s) <= 16


def test_contact_icons_sit_beside_their_lines_without_adding_problems():
    from app.lido_create.decorate import add_contact_icons

    v = _variant()
    d = _recipe_design("fresh_promo", v)
    before = validate(d, v, creative=True)
    d2, added = add_contact_icons(d, v)
    assert added and len(validate(d2, v, creative=True)) <= len(before)
    for kind in added:
        i, text = next((i, e) for i, e in enumerate(d2.elements) if e.text_type == kind)
        icon = d2.elements[i + 1]
        assert icon.kind == "draw" and icon.doodle and icon.color == (text.color or "ink")
        assert icon.x + icon.w <= text_extent_x0(text, v) and abs(
            (icon.y + icon.h / 2) - (text.y + (text.size or 24) * (text.line_height or 1.3) / 2)) < 2


def text_extent_x0(e, v):
    from app.lido_create.check import text_extent
    return text_extent(e, v)[0]


def test_a_planned_backdrop_reaches_the_saved_draft(api):
    client, fake, _ = api
    fake.plan_extra = {"backdrop": {"style": "corner_glow", "side": "left"}}
    response = client.post("/v1/lido/drafts", json={"prompt": "Pizza night"})
    assert response.status_code == 200, response.text
    [draft] = response.json()
    assert "BACKDROP" in fake.calls[0] and "glows bleed in from" in fake.calls[0]
    assert "Text areas:" in fake.calls[0]
    assert draft["backdrop"]["style"] == "corner_glow"
    assert "doodles" not in draft and "doodles" not in draft["plan"]
    layers = list(draft["document"][0]["layers"].values())
    circles = [lr for lr in layers if lr["props"].get("shape") == "circle"
               and isinstance(lr["props"].get("color"), dict)
               and lr["props"]["color"].get("style") == "radial"]
    assert len(circles) >= 2  # the two corner glows
    assert isinstance(layers[0]["props"]["color"], dict)  # the canvas fade under them


def test_a_brief_with_a_price_cannot_rule_prices_out():
    from app.lido_create.plan import DesignPlan, _clean

    plan = DesignPlan(texts=[{"role": "headline", "text": "Pizza night"}], photos=[],
                      logo=True, exclude=["price", "logo"], moods=["playful_bright"],
                      layout="centre_stage", custom_layout=None, shapes=[], draw=[],
                      effects=[], gradient=None, photo_theme="food", notes="")
    assert "price" not in _clean(plan, "2 large pizzas for $19.99").exclude
    assert "price" in _clean(plan.model_copy(update={"exclude": ["price"]}), "no prices").exclude


@pytest.mark.parametrize("bullet", ["dot", "dash", "ring", "square", "diamond", "triangle",
                                    "check", "check_circle", "arrow_circle", "plus",
                                    "number", "bar", "check_ring", "check_square",
                                    "arrow_square", "plus_circle", "target",
                                    "diamond_outline", "number_ring", "glow_dot"])
def test_every_bullet_style_is_a_small_marker_centred_on_the_first_line(bullet):
    from app.lido_create.lists import expand_list

    v = _variant()
    els = expand_list(Element(kind="list", x=100, y=300, w=600, h=300, bullet=bullet,
                              items=["Fresh ingredients", "Free delivery", "Open late"],
                              size=26, color="ink"), v)
    items = [e for e in els if e.text_type == "item"]
    marks = [e for e in els if e.text_type != "item"]
    assert len(items) == 3 and marks
    for item in items:
        mine = [m for m in marks if abs(m.y + m.h / 2 - (item.y + 26 * 1.3 / 2)) < 2
                or m.text_type == "caption"]
        assert mine, f"no marker on {item.text!r}"
        first = item.size * item.line_height
        for m in (m for m in mine if m.kind != "text"):
            assert m.x + m.w < item.x  # left of its item
            assert max(m.w, m.h) <= 26 * 1.2  # a bullet supports the text
            assert abs(m.y + m.h / 2 - (item.y + first / 2)) < 1.5
    d = Design(recipe="t", theme="business", palette=v.palette.name, fonts=v.fonts.name,
               elements=els)
    assert not any("bullet marker" in e for e in validate(d, v))
    assert all(lr["props"]["path"] for lr in to_lido(d, v)[0]["layers"].values()
               if lr["type"]["resolvedName"] == "DrawLayer")


def test_solid_bullets_draw_their_glyph_in_the_hole_colour():
    from app.lido_create.lists import expand_list

    v = _variant()
    for bullet, glyph in (("check_circle", "tick"), ("arrow_circle", "chevron")):
        els = expand_list(Element(kind="list", x=100, y=300, w=600, h=200, bullet=bullet,
                                  items=["One", "Two"], size=26, color="on_accent"), v)
        drawn = [e for e in els if e.kind == "draw"]
        circles = [e for e in els if e.shape == "circle"]
        assert {e.doodle for e in drawn} == {glyph}
        assert {e.color for e in circles} == {"on_accent"} and {e.color for e in drawn} == {"accent"}


def test_outlined_bullets_are_a_thin_edge_filled_with_what_the_list_sits_on():
    from app.lido_create.lists import expand_list

    v = _variant()
    for bullet in ("check_ring", "target", "diamond_outline", "number_ring"):
        els = expand_list(Element(kind="list", x=100, y=300, w=600, h=200, bullet=bullet,
                                  items=["One", "Two"], size=26, color="ink"), v)
        edges = [e for e in els if e.stroke]
        assert len(edges) == 2 and all(e.color == "bg" and e.stroke == "accent"
                                       and e.stroke_width and e.stroke_width < 4
                                       for e in edges), bullet


def _faded(text_y: float, start_at: float = 36, angle: float = 180):
    from app.lido_create.ai import normalise
    from app.lido_create.kit import Gradient

    v = _variant()
    els = normalise([
        Element(kind="photo", x=0, y=0, w=1080, h=1080, clip="rect", bleed=True, subject="a room"),
        Element(kind="shape", shape="rectangle", x=-6, y=-4, w=1092, h=1088, color="bg",
                bleed=True, gradient=Gradient(style="linear", angle=angle, start="bg",
                                              end=None, start_at=start_at, end_at=100)),
        Element(kind="logo", x=485, y=40, w=110, h=89),
        Element(kind="text", text="Calm Living", text_type="headline", x=140, y=text_y, w=800,
                h=0, size=78, font="display", align="center", color="ink"),
        Element(kind="text", text="New collection", text_type="kicker", x=140, y=text_y + 110,
                w=800, h=0, size=26, font="body", align="center", color="ink"),
        Element(kind="text", text="Shop now", text_type="cta", x=140, y=text_y + 160,
                w=800, h=0, size=26, font="body", align="center", color="ink"),
    ], v)
    return Design(recipe="t", theme="business", palette=v.palette.name, fonts=v.fonts.name,
                  elements=els), v


def test_a_photo_fade_keeps_the_photo_visible_and_holds_text_in_its_solid_part():
    d, v = _faded(text_y=140)  # all text inside the solid top 36%
    errors = validate(d, v)
    assert not any("mostly hidden" in e or "sits on a photo" in e for e in errors), errors
    fade = to_lido(d, v)[0]["layers"]
    stops = next(lr["props"]["color"]["colors"] for lr in fade.values()
                 if isinstance(lr["props"].get("color"), dict))
    assert stops[0]["percent"] == 36 and stops[1]["color"].endswith(", 0)")  # fades out


def test_text_in_the_fading_part_of_a_photo_fade_is_caught():
    d, v = _faded(text_y=330)  # the lower lines reach into the fading part
    assert any("sits on a photo" in e for e in validate(d, v))


def test_the_designer_and_art_director_know_the_photo_fade():
    from app.lido_create.ai import SYSTEM
    from app.lido_create.catalog import layouts

    assert "Photo fade (scrim)" in SYSTEM and "{style linear" in SYSTEM
    assert layouts()["photo_fade"].fits(1)
