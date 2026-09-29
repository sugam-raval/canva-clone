"""Template matching for the Lido.js (template) flow (docs/new_match_plan.md).

Offline: the LLM and the embedding model are replaced with fakes, so these pin the rules
— detail detection, the "holds every detail first" priority, the index cache — not any
model's taste.
"""

from __future__ import annotations

import json

import pytest

from app.adapters.base import AdapterError, LLMResult
from app.lido_corpus import match_index, matcher
from app.lido_corpus.details import details_in_text, template_details
from app.lido_corpus.fit import (
    ContentItem,
    TemplateFit,
    content_items,
    fit_template,
    quoted_lines,
    text_fits,
)
from app.lido_corpus.loader import DEFAULT_CORPUS_DIR, load_corpus, load_enriched
from app.lido_corpus.match_index import get_index
from app.lido_corpus.matcher import (
    DetailEvidence,
    RequestProfile,
    RequestProfileOutput,
    match_templates,
    profile_request,
    rank,
)

TEMPLATE_227 = DEFAULT_CORPUS_DIR / "template_227.json"


@pytest.fixture
def template_227():
    return load_enriched(TEMPLATE_227)


# -- details -----------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("Flat 30% off! Call 98765 43210 or visit www.sharmasweets.in",
     {"offer", "phone", "website"}),
    ("mail hr@acme.com", {"email"}),                           # email domain ≠ website
    ("walk-in 25 Oct, 10 AM at Baner Road, Pune 411045", {"date", "address"}),
    ("only ₹499", {"price"}),
    ("दिवाली पर 30% की छूट", {"offer"}),
    ("Grand opening of our new salon", set()),
    ("Since 2026, trusted", {"date"}),                          # a year is not a phone
    ("Offer valid till 25/10/2026", {"offer", "date"}),         # a date is not a phone
])
def test_details_in_text(text, expected):
    assert details_in_text(text) == expected


def test_template_details_reads_roles_and_sample_text():
    d = template_details(load_enriched(TEMPLATE_227).meta)
    # "Limited Happy Hours Promo" is an offer; the website slot is a contact slot.
    assert d.details == {"offer", "website"}
    assert d.contact_slots == ["website"]
    assert d.buttons == ["Get Yours!"]


# -- the priority rule (tiers, docs/slot_fit_match_plan.md §7) ------------------------


def _fit(held=(), dropped=(), must_keep_ok=True, coverage=None, contact=(), fit_cost=0.0,
         lines=0, leftover_other=0):
    return TemplateFit(dropped=list(dropped), must_keep_ok=must_keep_ok,
                       coverage=(1.0 if not dropped else 0.5) if coverage is None else coverage,
                       fit_cost=fit_cost, held_details=set(held),
                       leftover_contact=list(contact), lines=lines,
                       leftover_other=leftover_other)


def _profile(details=()):
    return RequestProfile(prompt="p", topic="t", details=set(details),
                          pattern_details=set(details), used_llm=False)


def test_template_holding_every_detail_beats_a_closer_topic():
    fits = {
        "close_topic": _fit({"website"}, ["phone"], must_keep_ok=False, contact=["website"]),
        "holds_all": _fit({"phone", "website"}),
    }
    topics = {"close_topic": 0.9, "holds_all": 0.1}
    r = rank(_profile({"phone", "website"}), fits, topics, list(fits))
    assert r.path == "holds_all"
    assert r.best.template_id == "holds_all"
    assert [c.tier for c in r.candidates] == ["A", "C"]      # a dropped must-keep is C
    assert r.candidates[1].missing == ["phone"]


def test_best_match_when_no_template_holds_everything():
    fits = {
        "sale": _fit({"offer", "website"}, ["phone"], False, 2 / 3),
        "food": _fit({"offer", "website"}, ["phone"], False, 2 / 3),
        "clinic": _fit({"phone", "website"}, ["offer"], False, 2 / 3),
    }
    topics = {"sale": 0.60, "food": 0.55, "clinic": 0.10}
    r = rank(_profile({"offer", "phone", "website"}), fits, topics, list(fits))
    assert r.path == "best_match"
    assert [c.template_id for c in r.candidates] == ["sale", "food", "clinic"]
    assert r.best.tier == "C"
    assert r.best.score == pytest.approx(0.5 * 0.60 + 0.4 * 2 / 3 + 0.1)


def test_no_details_means_closest_topic_minus_empty_contact_slots():
    fits = {"a": _fit(contact=["phone", "website"]), "b": _fit()}
    # a is 0.04 closer, but two unfilled contact slots cost 0.10.
    r = rank(_profile(), fits, {"a": 0.54, "b": 0.50}, list(fits))
    assert r.path == "holds_all"
    assert r.best.template_id == "b"
    assert r.candidates[1].empty_contact_slots == ["phone", "website"]


def test_fitting_every_line_beats_a_closer_topic_that_drops_one():
    """The pizza request: the closest template has no room for one line."""
    fits = {
        "restaurant": _fit(dropped=["Limited Time Offer"], coverage=0.86, lines=5),
        "generic": _fit(lines=5, fit_cost=0.2),
    }
    r = rank(_profile({"offer"}), fits, {"restaurant": 0.71, "generic": 0.50}, list(fits))
    assert r.best.template_id == "generic" and r.best.tier == "A"
    assert r.candidates[1].tier == "B"
    assert r.to_json()["candidates"][1]["droppedLines"] == ["Limited Time Offer"]


def test_spare_slots_count_against_a_template_only_when_the_user_wrote_the_copy():
    busy, lean = _fit(lines=2, leftover_other=6), _fit(lines=2)
    r = rank(_profile(), {"busy": busy, "lean": lean}, {"busy": 0.6, "lean": 0.5},
             ["busy", "lean"])
    assert r.best.template_id == "lean"          # 0.6 − 6·0.02 − 0.05 < 0.5
    free = {"busy": _fit(leftover_other=6), "lean": _fit()}
    r = rank(_profile(), free, {"busy": 0.6, "lean": 0.5}, ["busy", "lean"])
    assert r.best.template_id == "busy"          # no quoted lines: no spare-slot minus


def test_near_tie_goes_to_more_coverage():
    fits = {"x": _fit(dropped=["a"], coverage=0.70), "y": _fit(dropped=["b"], coverage=0.72)}
    # Same tier (B); x leads by less than the tie margin.
    topics = {"x": 0.36, "y": 0.34}
    r = rank(_profile(), fits, topics, list(fits))
    assert r.best.template_id == "y"


# -- the fit ---------------------------------------------------------------------------

PIZZA = """Create a vibrant promotional advertisement for a modern Italian restaurant.

Include the text:
“WEEKEND PIZZA FEST”
“BUY 1 GET 1 FREE”
“Freshly Baked • Extra Cheesy • Made Daily”
“Order Now”
“Limited Time Offer”

Make the design premium."""


def test_quoted_lines_are_found_in_order_without_duplicates():
    assert quoted_lines(PIZZA) == ["WEEKEND PIZZA FEST", "BUY 1 GET 1 FREE",
                                   "Freshly Baked • Extra Cheesy • Made Daily", "Order Now",
                                   "Limited Time Offer"]
    unquoted = "Diwali flyer. Include the text:\n- Happy Diwali\n- 20% off sweets\n\nWarm tones"
    assert quoted_lines(unquoted) == ["Happy Diwali", "20% off sweets"]
    assert quoted_lines('Say "Hi" and “Hi” again') == ["Hi"]
    # Prose right after a quoted list is not a requested line.
    assert quoted_lines("Include the text:\n“Sale”\n“Order Now”\nMake it bold.") == [
        "Sale", "Order Now"]


def test_content_items_guess_kinds_without_the_llm():
    items = {i.text: i for i in content_items(PIZZA, details_in_text(PIZZA))}
    assert {t: i.kind for t, i in items.items()} == {
        "WEEKEND PIZZA FEST": "headline", "BUY 1 GET 1 FREE": "offer",
        "Freshly Baked • Extra Cheesy • Made Daily": "tagline", "Order Now": "cta",
        "Limited Time Offer": "badge"}
    assert items["Freshly Baked • Extra Cheesy • Made Daily"].parts == (
        "Freshly Baked", "Extra Cheesy", "Made Daily")
    # The offer detail is carried by a quoted line, so no extra loose "offer" item.
    assert len(items) == 5


def test_a_detail_in_running_text_becomes_a_loose_item():
    prompt = 'Yoga classes. Call 98220 12345. Include "Stretch Daily"'
    items = content_items(prompt, details_in_text(prompt))
    assert [(i.kind, i.text) for i in items] == [("headline", "Stretch Daily"),
                                                 ("phone", None)]


def test_a_line_longer_than_any_slot_is_dropped_never_cut(template_227):
    long_line = "An unbelievably long headline that cannot possibly fit any box here"
    prompt = f'Food promo. Include “{long_line}” and “Order Now”'
    fit = fit_template(template_227, content_items(prompt, set()), set())
    assert fit.dropped == [long_line]
    assert long_line not in fit.placed.values()
    assert "Order Now" in fit.placed.values()
    assert not fit.must_keep_ok                  # it was the headline


def test_short_lines_all_find_a_slot_of_their_kind(template_227):
    prompt = 'Juice promo. Include “Fresh Juice”, “20% off today” and “Order Now”'
    fit = fit_template(template_227, content_items(prompt, {"offer"}), {"offer"})
    assert fit.dropped == [] and fit.coverage == 1.0
    roles = {s.layer_id: s.role for s in template_227.meta.slots}
    by_text = {text: roles[lid] for lid, text in fit.placed.items()}
    assert by_text["Fresh Juice"] == "headline"
    assert by_text["20% off today"] == "subhead"          # its sample is an offer
    assert by_text["Order Now"] == "label"                 # its sample is a button
    assert fit.leftover_contact == ["website"]


def test_an_optional_empty_contact_slot_is_hidden_and_can_take_a_short_line(template_227):
    for slot in template_227.meta.slots:
        if slot.role == "website":
            slot.optional = True
    no_lines = fit_template(template_227, [], set())
    assert no_lines.leftover_contact == [] and len(no_lines.hidden) == 1
    # Five short lines, four other slots: the fifth goes to the empty website slot.
    items = [ContentItem("headline", "Hot Deals", 3.0), ContentItem("badge", "Hurry!", 1.5),
             ContentItem("cta", "Order Now", 2.0), ContentItem("badge", "Limited", 1.5),
             ContentItem("badge", "Ends Sunday", 1.5)]
    fit = fit_template(template_227, items, set())
    website = next(s.layer_id for s in template_227.meta.slots if s.role == "website")
    assert website in fit.placed                 # reused rather than dropping a line


def test_a_split_line_is_placed_whole_or_not_at_all(template_227):
    # Three list rows but only one slot takes a feature: no lone fragment is placed.
    item = ContentItem("tagline", "x" * 60 + " • Hot • Fresh", 1.5,
                       parts=("x" * 60, "Hot", "Fresh"))
    fit = fit_template(template_227, [item], set())
    assert fit.placed == {} and fit.dropped == [item.text]


def test_text_fits_checks_the_real_limits(template_227):
    from app.lido_corpus.generate_ai import text_targets
    label = next(t for t in text_targets(template_227) if t.slot.role == "label")
    assert text_fits("Order Now", label)
    assert not text_fits("x" * (label.slot.max_chars * 2), label)


# -- request profile ---------------------------------------------------------------------


class FakeLLM:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    async def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.answer, Exception):
            raise self.answer
        return LLMResult(parsed=self.answer, raw="", model="fake")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(match_index, "_MEMORY", {})
    monkeypatch.setattr(matcher, "_PROFILE_CACHE", type(matcher._PROFILE_CACHE)())


async def test_profile_uses_llm_topic_and_adds_its_details(monkeypatch):
    llm = FakeLLM(RequestProfileOutput(topic="Diwali sweets sale", details=[
        DetailEvidence(detail="offer", quote="सेल"),
        DetailEvidence(detail="price", quote="₹99"),          # not in the request: ignored
    ]))
    monkeypatch.setattr(matcher, "get_llm", lambda: llm)
    p = await profile_request("दिवाली मिठाई सेल, call 98765 43210")
    assert p.used_llm and p.topic == "Diwali sweets sale"
    assert p.details == {"offer", "phone"}           # LLM offer + pattern phone
    assert llm.calls[0]["model"]                      # always the fast model


async def test_profile_falls_back_to_patterns_when_llm_fails(monkeypatch):
    monkeypatch.setattr(matcher, "get_llm", lambda: FakeLLM(AdapterError("down")))
    p = await profile_request("Yoga classes, call 98220 12345")
    assert not p.used_llm
    assert p.topic == "Yoga classes, call 98220 12345"
    assert p.details == {"phone"}


# -- the index ---------------------------------------------------------------------------


class FakeEmbedder:
    model_name = "fake-embedder"

    def __init__(self):
        self.batches: list[list[str]] = []

    async def embed(self, texts):
        self.batches.append(list(texts))
        # Deterministic unit vectors: "salon" cards point one way, everything else another.
        return [[1.0, 0.0] if "salon" in t.lower() else [0.0, 1.0] for t in texts]


async def test_in_memory_index_only_reembeds_changed_templates(tmp_path, monkeypatch):
    fake = FakeEmbedder()
    monkeypatch.setattr(match_index, "_embedder", lambda: fake)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "template_227.json").write_text(TEMPLATE_227.read_text())
    raw = json.loads(TEMPLATE_227.read_text())
    raw[0]["meta"]["name"] = "Salon Promo"
    raw[0]["meta"]["id"] = "template_b"
    (corpus / "template_b.json").write_text(json.dumps(raw))

    first = await get_index(load_corpus(corpus), corpus)
    assert len(fake.batches) == 1 and len(fake.batches[0]) == 2
    assert all(e.embedding for e in first.values())

    await get_index(load_corpus(corpus), corpus)             # nothing changed
    assert len(fake.batches) == 1

    raw[0]["meta"]["tags"] = ["salon", "hair"]              # any meta edit → re-embed
    (corpus / "template_b.json").write_text(json.dumps(raw))
    await get_index(load_corpus(corpus), corpus)
    assert len(fake.batches) == 2 and len(fake.batches[1]) == 1   # only template_b


async def test_match_templates_end_to_end_with_fakes(tmp_path, monkeypatch):
    monkeypatch.setattr(match_index, "_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(matcher, "get_llm", lambda: FakeLLM(
        RequestProfileOutput(topic="new hair salon opening", details=[])))
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "template_227.json").write_text(TEMPLATE_227.read_text())
    raw = json.loads(TEMPLATE_227.read_text())
    raw[0]["meta"].update(id="template_b", name="Salon Promo")
    (corpus / "template_b.json").write_text(json.dumps(raw))

    r = await match_templates(load_corpus(corpus), "Grand opening of our salon",
                              corpus_dir=corpus)
    assert r.best.template_id == "template_b"
    assert r.embedder == "fake-embedder" and r.used_llm
    assert r.to_json()["candidates"][0]["templateId"] == "template_b"


async def test_raw_file_without_meta_is_not_a_candidate_until_enriched(tmp_path):
    """A freshly dropped export has no name, tags or limits yet: it stays out of the
    catalog (and out of lido_templates) until `make lido-update` drafts its meta."""
    from app.lido_corpus.store import load_catalog

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "template_227.json").write_text(TEMPLATE_227.read_text())
    raw = json.loads(TEMPLATE_227.read_text())
    raw[0].pop("meta")
    (corpus / "template_new.json").write_text(json.dumps(raw))

    catalog = await load_catalog(corpus)
    assert [t.meta.id for t in catalog.templates] == ["template_227"]
    assert set(catalog.entries) == {"template_227"}


def _enrich_script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "enrich_lido_templates.py"
    spec = importlib.util.spec_from_file_location("enrich_lido_templates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_passes_a_complete_template_and_blocks_broken_ones(tmp_path):
    """`make lido-meta` / `lido-sync` run this; an error stops the database sync."""
    enrich = _enrich_script()
    good = tmp_path / "template_227.json"
    good.write_text(TEMPLATE_227.read_text())
    errors, _warnings = enrich._verify(good)
    assert errors == []

    raw = json.loads(TEMPLATE_227.read_text())
    raw[0].pop("meta")
    no_meta = tmp_path / "template_1.json"
    no_meta.write_text(json.dumps(raw))
    assert enrich._verify(no_meta)[0] == ["no meta block yet — run `make lido-meta`"]

    broken = json.loads(TEMPLATE_227.read_text())
    for slot in broken[0]["meta"]["slots"]:
        if slot["role"] == "photo":
            slot["image"] = None                 # sample photo would never be replaced
        if slot["role"] == "logo":
            slot["locked"] = False
    bad = tmp_path / "template_2.json"
    bad.write_text(json.dumps(broken))
    errors, _ = enrich._verify(bad)
    assert any("no image spec" in e for e in errors)
    assert any("logo must be locked" in e for e in errors)


def test_verify_rejects_a_filename_that_is_not_template_number(tmp_path):
    """lido_templates.id is a genuine integer, taken from the file name."""
    enrich = _enrich_script()
    misnamed = tmp_path / "template_my-design.json"
    misnamed.write_text(TEMPLATE_227.read_text())
    errors, _warnings = enrich._verify(misnamed)
    expected = ("file name 'template_my-design.json' is not of the form "
               "'template_<number>.json' — lido_templates.id is a genuine "
               "integer, so rename the file")
    assert errors == [expected]


# -- new_template_ids / `make lido-add` -----------------------------------------------


def _lido_match_script():
    import importlib.util
    from pathlib import Path as _Path

    path = _Path(__file__).resolve().parents[2] / "scripts" / "lido_match.py"
    spec = importlib.util.spec_from_file_location("lido_match", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_new_template_ids_in_files_mode_is_every_file(tmp_path):
    """No database (the default in tests, via the autouse fixture): everything on disk
    counts as new, since nothing is ever persisted."""
    from app.lido_corpus.store import new_template_ids

    (tmp_path / "template_a.json").write_text(TEMPLATE_227.read_text())
    (tmp_path / "template_b.json").write_text(TEMPLATE_227.read_text())
    assert await new_template_ids(tmp_path) == ["template_a", "template_b"]


async def test_new_template_ids_in_db_mode_excludes_stored_rows(tmp_path, monkeypatch):
    """`lido_templates.id` is a genuine integer (see app.db.repo.template_db_id) — a
    stored row's id, e.g. 1, means the file `template_1.json`."""
    from app.config import get_settings
    from app.lido_corpus import store

    monkeypatch.setattr(get_settings(), "lido_template_store", "db")
    (tmp_path / "template_1.json").write_text(TEMPLATE_227.read_text())
    (tmp_path / "template_2.json").write_text(TEMPLATE_227.read_text())

    class FakeScope:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(store, "session_scope", FakeScope)

    async def fake_list_template_index(_session):
        return {1: {}}                            # template_1 is already stored

    monkeypatch.setattr(store.repo, "list_template_index", fake_list_template_index)
    assert await store.new_template_ids(tmp_path) == ["template_2"]


class _FakeSyncReport:
    def __init__(self, ids):
        self.ids = ids

    def summary(self):
        return f"synced: {', '.join(self.ids)}"


async def test_cmd_add_rejects_an_unknown_template(tmp_path, capsys):
    lm = _lido_match_script()
    (tmp_path / "template_a.json").write_text(TEMPLATE_227.read_text())
    args = lm.argparse.Namespace(dir=tmp_path, template=["template_nope"])
    assert await lm.cmd_add(args) == 1
    assert "no such file" in capsys.readouterr().out


async def test_cmd_add_leaves_an_already_tracked_template_untouched(tmp_path, monkeypatch, capsys):
    lm = _lido_match_script()
    (tmp_path / "template_a.json").write_text(TEMPLATE_227.read_text())

    monkeypatch.setattr(lm, "new_template_ids", lambda _dir: _async([]))
    calls = []
    monkeypatch.setattr(lm, "sync_templates",
                        lambda *a, **k: calls.append((a, k)) or _async(_FakeSyncReport([])))

    args = lm.argparse.Namespace(dir=tmp_path, template=["template_a"])
    assert await lm.cmd_add(args) == 0
    out = capsys.readouterr().out
    assert "already in the database, nothing to do: template_a" in out
    assert calls == []                       # sync_templates was never called


async def test_cmd_add_batch_skips_a_broken_file_but_still_adds_the_good_one(
        tmp_path, monkeypatch, capsys):
    """A file that fails to parse (or fails verification) must not stop the rest of the
    batch, and must not be counted in what gets synced."""
    lm = _lido_match_script()
    good = tmp_path / "template_1.json"
    good.write_text(TEMPLATE_227.read_text())
    bad = tmp_path / "template_2.json"
    bad.write_text("")                        # unreadable — used to crash the whole batch

    monkeypatch.setattr(lm, "new_template_ids",
                        lambda _dir: _async(["template_2", "template_1"]))
    calls = []
    monkeypatch.setattr(lm, "sync_templates",
                        lambda _dir, only: calls.append(only) or _async(_FakeSyncReport(only)))

    args = lm.argparse.Namespace(dir=tmp_path, template=None)
    assert await lm.cmd_add(args) == 1        # non-zero: something was skipped
    out = capsys.readouterr().out
    assert "FAIL  template_2.json" in out
    assert "OK    template_1.json" in out
    assert calls == [["template_1"]]          # only the good one was synced


async def test_cmd_add_drafts_only_when_verification_first_fails(tmp_path, monkeypatch):
    """A template that already verifies cleanly is synced as-is — no model call. `lm`'s
    own `import enrich_lido_templates as enrich` (inside `cmd_add`) resolves to the same
    cached `sys.modules` entry as this import, once either has run once in the process,
    so patching this module object is enough to observe (or forbid) `cmd_add`'s calls
    into it."""
    import sys
    from pathlib import Path

    lm = _lido_match_script()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import enrich_lido_templates as enrich

    complete = tmp_path / "template_1.json"
    complete.write_text(TEMPLATE_227.read_text())

    monkeypatch.setattr(lm, "new_template_ids", lambda _dir: _async(["template_1"]))
    monkeypatch.setattr(lm, "sync_templates",
                        lambda _dir, only: _async(_FakeSyncReport(only)))

    async def _fail_if_called(*_a, **_k):
        raise AssertionError("draft should not run for an already-complete template")

    monkeypatch.setattr(enrich, "_enrich_file_in_place_async", _fail_if_called)

    args = lm.argparse.Namespace(dir=tmp_path, template=None)
    assert await lm.cmd_add(args) == 0


def _async(value):
    async def _coro(*_a, **_k):
        return value
    return _coro()


async def test_sync_skips_a_misnamed_template_instead_of_crashing(tmp_path, monkeypatch):
    """`lido_templates.id` is a genuine integer, so a template not named
    template_<number>.json can never reach the database — but it must be skipped and
    reported, not raise. `_sync` runs on the API's hot path (`load_catalog`), so a
    misnamed file must never be able to break every other template's sync."""
    from app.config import get_settings
    from app.lido_corpus import store

    monkeypatch.setattr(get_settings(), "lido_template_store", "db")
    (tmp_path / "template_227.json").write_text(TEMPLATE_227.read_text())
    raw = json.loads(TEMPLATE_227.read_text())
    raw[0]["meta"]["id"] = "not_a_number"
    (tmp_path / "template_not_a_number.json").write_text(json.dumps(raw))

    class FakeScope:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(store, "session_scope", FakeScope)

    async def fake_list_template_index(_session):
        return {}

    upserted = []

    async def fake_upsert_template(_session, **kwargs):
        upserted.append(kwargs["template_id"])

    monkeypatch.setattr(store.repo, "list_template_index", fake_list_template_index)
    monkeypatch.setattr(store.repo, "upsert_template", fake_upsert_template)
    monkeypatch.setattr(store, "embed", lambda texts: _async([[0.0] * 384 for _ in texts]))

    templates = load_corpus(tmp_path)
    async with FakeScope() as session:
        report = await store._sync(session, templates, store._source_files(tmp_path), force=False)

    assert report.invalid_id == ["template_not_a_number"]
    assert upserted == [227]                  # the well-named template still synced
