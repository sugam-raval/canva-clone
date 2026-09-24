"""The Lido.js (template) flow: one LLM call fills template_227 from its own metadata.

Offline throughout — the LLM and both image adapters are replaced with recording fakes,
so these pin the pipeline's guarantees rather than any model's taste: which layers are
sent and filled, which adapter renders which image, what gets enforced after the model
answers, and what lands on disk.
"""

from __future__ import annotations

import io
import json

import pytest
from botocore.exceptions import EndpointConnectionError
from PIL import Image

from app.adapters.base import AdapterError, ImageResult, LLMResult
from app.adapters.stub_adapters import StubLLM
from app.config import get_settings
from app.lido_corpus import assets_ai, generate_ai, generated, match_index, matcher, textfit
from app.lido_corpus.generate_ai import (
    LidoLayerImagePrompt,
    LidoLayerTextFill,
    LidoTemplateFillOutput,
    LidoTextRepairOutput,
    build_user_message,
    check_text,
    image_targets,
    text_targets,
)
from app.lido_corpus.generated import public_url
from app.lido_corpus.loader import DEFAULT_CORPUS_DIR, load_corpus, load_enriched
from app.lido_corpus.model import LidoDocument
from app.lido_corpus.pipeline import generate_lido_design
from app.lido_corpus.retrieval import (
    NoReadyTemplateError,
    TemplateNotFoundError,
    choose_template,
    get_template,
    random_template,
    select_best_template,
)
from app.storage.assets import S3Backend

TEMPLATE = DEFAULT_CORPUS_DIR / "template_227.json"
LOGO = "210b6d7e-ed4c-46d8-b8df-672575c5d107"
KICKER = "14819dc3-ee3c-410d-ae88-ef2d6de07b2e"
ACCENT = "86279fff-8f09-48bd-94eb-c0e981c4a67d"
WEBSITE = "bab7c3c8-d0ce-468c-8faa-311e0d0563ee"
HEADLINE = "d151f974-b143-47fd-9b56-d64625400d89"
SUBJECT = "d73f71ae-32c9-4e72-ae99-94d780750314"
PROMO = "d835c471-0cb3-418d-901c-33f64b5c7140"

PROMPT = "Promo for my vegan smoothie bar, cheerful bright green and yellow branding"

GOOD_TEXT = {
    KICKER: "Craving Fresh?",
    ACCENT: "Sip Happy!",
    HEADLINE: "Vegan Sips",
    PROMO: "New Flavors Every Week",
    WEBSITE: "www.yourwebsite.com",
}
GOOD_PROMPTS = {
    "ROOT": "Diagonal two-panel background, lime-green panel left, pale wood right, "
            "centre left empty",
    SUBJECT: "Top-down green smoothie in a round bowl, transparent background, no backdrop",
}


def _output(text=None, prompts=None) -> LidoTemplateFillOutput:
    text = GOOD_TEXT if text is None else text
    prompts = GOOD_PROMPTS if prompts is None else prompts
    return LidoTemplateFillOutput(
        text_fills=[LidoLayerTextFill(layer_id=k, text=v) for k, v in text.items()],
        image_prompts=[LidoLayerImagePrompt(layer_id=k, prompt=v) for k, v in prompts.items()],
    )


class FakeLLM:
    """Answers each call with the next scripted item; an exception item is raised."""

    name = "fake:llm"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []

    async def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return LLMResult(parsed=answer, raw="", model="fake")


def _png(width: int, height: int, alpha: bool) -> bytes:
    img = Image.new("RGBA" if alpha else "RGB", (width, height),
                    (40, 200, 90, 0) if alpha else (40, 200, 90))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FakeImages:
    def __init__(self, alpha: bool, fail: bool = False):
        self.alpha, self.fail = alpha, fail
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise AdapterError("provider down")
        w, h = kwargs["width"], kwargs["height"]
        return ImageResult(data=_png(w, h, self.alpha), mime="image/png", width=w, height=h,
                           model="fake", has_alpha=self.alpha)


@pytest.fixture
def fakes(monkeypatch):
    opaque, transparent = FakeImages(alpha=False), FakeImages(alpha=True)
    monkeypatch.setattr(assets_ai, "get_text_to_image", lambda: opaque)
    monkeypatch.setattr(assets_ai, "get_transparent_image", lambda: transparent)

    def install(*answers) -> FakeLLM:
        llm = FakeLLM(*answers)
        monkeypatch.setattr(generate_ai, "get_llm", lambda: llm)
        return llm

    return install, opaque, transparent


class FakeStore(S3Backend):
    """Stands in for MinIO: records uploads, or fails like an unreachable endpoint."""

    def __init__(self):
        self.bucket = "design-assets"
        self.puts: dict[str, tuple[bytes, str]] = {}
        self.fail = False

    def put(self, key, data, mime):
        if self.fail:
            raise EndpointConnectionError(endpoint_url="http://localhost:9010")
        self.puts[key] = (data, mime)


@pytest.fixture(autouse=True)
def store(monkeypatch):
    """No test ever uploads to the real object store."""
    fake = FakeStore()
    monkeypatch.setattr(generated, "get_backend", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def offline_matcher(monkeypatch):
    """Template matching never calls the real LLM or loads the embedding model in these
    tests: the request profile falls back to patterns and topic to word overlap."""
    monkeypatch.setattr(matcher, "get_llm", lambda: StubLLM())
    monkeypatch.setattr(match_index, "_embedder", lambda: None)
    monkeypatch.setattr(match_index, "_MEMORY", {})


@pytest.fixture(autouse=True)
def offline_fonts(monkeypatch):
    """Measure with whatever fonts are already cached; never download in a test."""
    monkeypatch.setattr(textfit, "_download", lambda url, dest: False)
    monkeypatch.setattr(textfit, "_google_ttf_url", lambda family: None)


@pytest.fixture
def template():
    return load_enriched(TEMPLATE)


def _target(template, layer_id):
    return next(t for t in text_targets(template) if t.layer_id == layer_id)


def _layer_text(document, layer_id) -> str:
    doc = document[0]["layers"][layer_id]["props"]["doc"]
    return " ".join(n["text"] for p in doc["content"] for n in p.get("content", []) if n["text"])


# -- metadata and selection --------------------------------------------------------------


def test_template_default_copy_fits_its_own_limits(template):
    """If the metadata's limits reject the copy the template was designed with, every
    generation would be squeezed by a wrong estimate."""
    for target in text_targets(template):
        assert check_text(target.slot.default_text, target) == [], target.slot.role


def test_default_copy_wraps_like_the_reference_render(template):
    def lines(layer_id):
        target = _target(template, layer_id)
        return textfit.wrap(target.slot.default_text, target.measure, target.box_width)

    assert lines(PROMO) == ["Limited", "Happy", "Hours", "Promo"]
    assert lines(HEADLINE) == ["Healthy", "Food"]
    assert lines(KICKER) == ["Healthy but", "Tasty Diet?"]
    assert lines(ACCENT) == ["Get Yours!"]


@pytest.mark.skipif(not (textfit.FONT_CACHE_DIR / "yeseva-one.ttf").is_file(),
                    reason="needs the cached Yeseva One font to measure exactly")
def test_a_wide_word_that_passes_a_letter_count_is_still_caught(template):
    """A real run wrote "Vegan smoothie": 8 letters like "Healthy", but in Yeseva One
    "Smoothie" is 239px and broke across lines in the 200px headline box."""
    headline = _target(template, HEADLINE)
    assert headline.measure.exact
    problems = check_text("Vegan smoothie", headline)
    assert problems and "smoothie" in problems[0]
    assert check_text("Fresh Sips", headline) == []


def test_css_text_transform_is_applied_before_measuring():
    assert textfit.apply_transform("buy one get", "capitalize") == "Buy One Get"
    assert textfit.apply_transform("buy one", "uppercase") == "BUY ONE"
    assert textfit.family_name("Poppins, serif") == "Poppins"


async def test_every_template_is_a_candidate_even_without_reference_note(tmp_path):
    """The old reference_note gate is gone: a raw export with no meta is still picked
    when it is the only template, and an empty corpus is the only error."""
    raw = json.loads(TEMPLATE.read_text())
    raw[0].pop("meta", None)
    (tmp_path / "unreviewed.json").write_text(json.dumps(raw))
    picked = await select_best_template(load_corpus(tmp_path), PROMPT, corpus_dir=tmp_path)
    assert picked.template.meta.id == "unreviewed"
    assert picked.match is not None

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(NoReadyTemplateError):
        await select_best_template(load_corpus(empty), PROMPT, corpus_dir=empty)


def _renamed(template, new_id, *, ready=True):
    """A distinct template object sharing template_227's layers, for exercising
    selection across >1 template without depending on which corpus files happen to
    exist on disk."""
    meta = template.meta.model_copy(update={
        "id": new_id, "reference_note": template.meta.reference_note if ready else None,
    })
    return template.model_copy(update={"meta": meta})


def test_get_template_picks_by_id_regardless_of_readiness(template):
    not_ready = _renamed(template, "template_999", ready=False)
    corpus = [template, not_ready]

    assert get_template(corpus, "template_227").template is template
    # An explicit pick isn't gated on meta.reference_note the way auto-scoring is.
    assert get_template(corpus, "template_999").template is not_ready

    with pytest.raises(TemplateNotFoundError):
        get_template(corpus, "does-not-exist")


def test_random_template_picks_from_the_whole_corpus_not_just_ready_ones(template):
    not_ready = _renamed(template, "template_999", ready=False)
    corpus = [template, not_ready]

    seen = {random_template(corpus).template.meta.id for _ in range(30)}
    assert seen == {"template_227", "template_999"}


async def test_choose_template_precedence(template, tmp_path):
    """template_id wins outright; then random; only then the automatic match."""
    other = _renamed(template, "template_other")
    corpus = [template, other]

    chosen = await choose_template(corpus, PROMPT, template_id="template_other",
                                   corpus_dir=tmp_path)
    assert chosen.template is other and chosen.match is None
    chosen = await choose_template(corpus, PROMPT, template_id="template_other",
                                   random_pick=True, corpus_dir=tmp_path)
    assert chosen.template is other
    auto = await choose_template(corpus, PROMPT, corpus_dir=tmp_path)
    assert auto.match is not None   # identical cards tie; corpus order decides
    assert auto.template.meta.id == "template_227"

    picks = set()
    for _ in range(30):
        picks.add((await choose_template(corpus, PROMPT, random_pick=True,
                                         corpus_dir=tmp_path)).template.meta.id)
    assert picks == {"template_227", "template_other"}


def test_locked_logo_is_never_a_target(template):
    assert LOGO not in {t.layer_id for t in text_targets(template)}
    assert {t.layer_id for t in image_targets(template)} == {"ROOT", SUBJECT}
    message = build_user_message(PROMPT, template, text_targets(template),
                                 image_targets(template))
    assert LOGO not in message
    assert KICKER in message and SUBJECT in message and '"approx_chars_per_line":' in message


# -- the single call ---------------------------------------------------------------------


async def test_one_call_fills_every_layer_and_saves(fakes, store, tmp_path):
    install, opaque, transparent = fakes
    llm = install(_output())

    result = await generate_lido_design(PROMPT)

    assert len(llm.calls) == 1
    # No reasoning_effort/model override — the primary fill call uses whatever
    # LLM_REASONING_EFFORT/LLM_MODEL are globally configured, same as any other call.
    assert "reasoning_effort" not in llm.calls[0]
    assert "model" not in llm.calls[0]
    assert llm.calls[0]["schema"] is LidoTemplateFillOutput
    assert PROMPT in llm.calls[0]["user"]

    for layer_id, text in GOOD_TEXT.items():
        assert _layer_text(result.document, layer_id) == text

    original = load_enriched(TEMPLATE).layers[LOGO].model_dump(mode="json")
    assert result.document[0]["layers"][LOGO] == original

    # Background opaque, subject a real alpha cutout — decided by the template's spec.
    assert [c["prompt"] for c in opaque.calls] == [GOOD_PROMPTS["ROOT"]]
    assert len(transparent.calls) == 1
    assert transparent.calls[0]["prompt"].startswith(GOOD_PROMPTS[SUBJECT])
    assert "transparent background" in transparent.calls[0]["prompt"]
    assert transparent.calls[0]["height"] == 1024  # subject box is taller than wide
    assert opaque.calls[0]["quality"] == "high"

    # Uploaded to the store's public prefix and referenced by a permanent URL; nothing
    # image-shaped is written next to the JSON.
    layers = result.document[0]["layers"]
    for layer_id, name in (("ROOT", "background"), (SUBJECT, SUBJECT)):
        key = f"public/lido-generated/{result.design_id}/{name}.png"
        url = layers[layer_id]["props"]["image"]["url"]
        assert url == result.image_fills[layer_id] == layers[layer_id]["props"]["image"]["thumb"]
        assert url.startswith("http") and url.endswith(f"/design-assets/{key}")
        assert store.puts[key][1] == "image/png"
    assert "X-Amz-Signature" not in url

    # Nothing is written to disk — the returned document is what the route persists to
    # `lido_generations` (see app.db.repo.upsert_lido_generation).
    assert list(tmp_path.iterdir()) == []

    meta = result.document[0]["meta"]
    assert meta["template_id"] == "template_227"
    assert meta["prompt"] == PROMPT and meta["name"] == "Vegan Sips"
    assert meta["reference_note"] is None
    assert meta["generation"]["image_prompts"] == GOOD_PROMPTS
    LidoDocument.model_validate({"layers": result.document[0]["layers"]})


async def test_generate_accepts_an_explicit_template_id(fakes, tmp_path):
    install, _, _ = fakes
    install(_output())

    result = await generate_lido_design(PROMPT, generate_images=False,
                                        template_id="template_227")

    assert result.template.meta.id == "template_227"


async def test_generate_rejects_an_unknown_template_id(fakes, tmp_path):
    install, _, _ = fakes
    install(_output())

    with pytest.raises(TemplateNotFoundError):
        await generate_lido_design(PROMPT, generate_images=False,
                                   template_id="does-not-exist")


async def test_generate_accepts_random_template(fakes, tmp_path):
    install, _, _ = fakes
    install(_output())

    # A single-template corpus copy, independent of whatever else the real corpus
    # happens to contain — this pins that random_template reaches choose_template, not
    # that the real corpus has exactly one entry (it doesn't, and that's fine: this
    # test just isn't the place to depend on it).
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "template_227.json").write_text(TEMPLATE.read_text())

    result = await generate_lido_design(PROMPT, generate_images=False,
                                        random_template=True, corpus_dir=corpus_dir)

    assert result.template.meta.id == "template_227"


async def test_over_limit_copy_gets_one_repair_call(fakes, tmp_path):
    install, _, _ = fakes
    too_long = {**GOOD_TEXT, HEADLINE: "Deliciously Refreshing Smoothies"}
    llm = install(
        _output(text=too_long),
        LidoTextRepairOutput(text_fills=[LidoLayerTextFill(layer_id=HEADLINE, text="Fresh Sips")]),
    )

    result = await generate_lido_design(PROMPT, generate_images=False)

    assert len(llm.calls) == 2
    assert llm.calls[1]["schema"] is LidoTextRepairOutput
    assert HEADLINE in llm.calls[1]["user"] and "Deliciously" in llm.calls[1]["user"]
    # The repair call is scoped to LLM_MODEL_FAST, not the primary model/effort — a
    # small, well-identified fix doesn't need the main reasoning budget.
    assert llm.calls[1]["model"] == get_settings().llm_model_fast
    assert "reasoning_effort" not in llm.calls[1]
    assert result.text_fills[HEADLINE] == "Fresh Sips"
    assert result.repaired == [HEADLINE] and result.clamped == []


async def test_failed_repair_falls_back_to_clamping(fakes, tmp_path, template):
    install, _, _ = fakes
    too_long = {**GOOD_TEXT, PROMO: "Limited Time Only Buy One Get One Free Today"}
    install(_output(text=too_long), AdapterError("boom", recoverable=False))

    result = await generate_lido_design(PROMPT, generate_images=False)

    promo = next(t for t in text_targets(template) if t.layer_id == PROMO)
    assert result.clamped == [PROMO]
    assert check_text(result.text_fills[PROMO], promo) == []
    assert result.text_fills[PROMO].startswith("Limited Time")


async def test_invented_website_is_reverted_but_a_given_one_is_kept(fakes, tmp_path):
    install, _, _ = fakes
    invented = {**GOOD_TEXT, WEBSITE: "www.freshsips.com"}

    install(_output(text=invented))
    result = await generate_lido_design(PROMPT, generate_images=False)
    assert result.text_fills[WEBSITE] == "www.yourwebsite.com"

    install(_output(text=invented))
    result = await generate_lido_design(f"{PROMPT}. Our site is freshsips.com",
                                        generate_images=False)
    assert result.text_fills[WEBSITE] == "www.freshsips.com"


async def test_missing_answers_fall_back_to_template_defaults(fakes, tmp_path, template):
    install, _, transparent = fakes
    install(_output(text={HEADLINE: "Vegan Sips"}, prompts={"ROOT": GOOD_PROMPTS["ROOT"]}))

    result = await generate_lido_design(PROMPT)

    assert result.text_fills[KICKER] == "Healthy but Tasty Diet?"
    reference = template.meta.slots[[s.layer_id for s in template.meta.slots].index(SUBJECT)]
    assert result.image_prompts[SUBJECT] == reference.image.prompt
    assert transparent.calls[0]["prompt"].startswith(reference.image.prompt)


async def test_recoverable_llm_failure_is_retried_once(fakes, tmp_path):
    install, _, _ = fakes
    llm = install(AdapterError("truncated", recoverable=True), _output())

    result = await generate_lido_design(PROMPT, generate_images=False)

    assert len(llm.calls) == 2
    assert result.text_fills[HEADLINE] == "Vegan Sips"


async def test_no_llm_is_an_error_not_an_unchanged_template(monkeypatch, tmp_path):
    monkeypatch.setattr(generate_ai, "get_llm", lambda: StubLLM())
    with pytest.raises(AdapterError):
        await generate_lido_design(PROMPT)
    assert not list(tmp_path.glob("*.json"))


# -- images ------------------------------------------------------------------------------


async def test_generate_images_false_leaves_template_images(fakes, tmp_path, template):
    install, opaque, transparent = fakes
    install(_output())

    result = await generate_lido_design(PROMPT, generate_images=False)

    assert opaque.calls == [] and transparent.calls == []
    assert result.image_fills == {} and result.image_failures == []
    layers = result.document[0]["layers"]
    assert layers["ROOT"]["props"]["image"]["url"] == template.meta.background_image_url


async def test_one_failed_image_keeps_its_original_and_is_reported(fakes, monkeypatch,
                                                                   tmp_path, template):
    install, _, _ = fakes
    monkeypatch.setattr(assets_ai, "get_transparent_image", lambda: FakeImages(True, fail=True))
    install(_output())

    result = await generate_lido_design(PROMPT)

    assert result.image_failures == [SUBJECT]
    assert set(result.image_fills) == {"ROOT"}
    original = template.layers[SUBJECT].props["image"]["url"]
    assert result.document[0]["layers"][SUBJECT]["props"]["image"]["url"] == original


async def test_failed_upload_keeps_template_images_and_is_reported(fakes, store, tmp_path,
                                                                  template):
    install, _, _ = fakes
    store.fail = True
    install(_output())

    result = await generate_lido_design(PROMPT)

    assert sorted(result.image_failures) == sorted(["ROOT", SUBJECT])
    assert result.image_fills == {}
    layers = result.document[0]["layers"]
    assert layers["ROOT"]["props"]["image"]["url"] == template.meta.background_image_url


def test_public_url_never_expires(monkeypatch, store):
    key = "public/lido-generated/tpl-x-1234abcd/background.png"
    settings = get_settings()
    monkeypatch.setattr(settings, "s3_public_base_url", None)
    monkeypatch.setattr(settings, "s3_endpoint_url", "http://localhost:9010")
    assert public_url(store, key) == f"http://localhost:9010/design-assets/{key}"

    monkeypatch.setattr(settings, "s3_public_base_url", "https://cdn.example.com/assets/")
    assert public_url(store, key) == f"https://cdn.example.com/assets/{key}"

    class LocalStore:  # the fallback when MinIO is down: a permanent API route
        def url(self, key, ttl):
            return f"/v1/assets/raw/{key}"

    assert public_url(LocalStore(), key) == f"/v1/assets/raw/{key}"
