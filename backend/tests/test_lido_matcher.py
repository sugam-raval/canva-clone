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
from app.lido_corpus.details import TemplateDetails, details_in_text, template_details
from app.lido_corpus.loader import DEFAULT_CORPUS_DIR, load_corpus, load_enriched
from app.lido_corpus.match_index import IndexEntry, get_index
from app.lido_corpus.matcher import (
    DetailEvidence,
    RequestProfile,
    RequestProfileOutput,
    match_templates,
    profile_request,
    rank,
)

TEMPLATE_227 = DEFAULT_CORPUS_DIR / "template_227.json"


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


# -- the priority rule -------------------------------------------------------------------


def _entry(tid, details=(), contact=()):
    return IndexEntry(tid, "fp", f"card {tid}",
                      TemplateDetails(details=set(details), contact_slots=list(contact)),
                      None)


def _profile(details=()):
    return RequestProfile(prompt="p", topic="t", details=set(details),
                          pattern_details=set(details), used_llm=False)


def test_template_holding_every_detail_beats_a_closer_topic():
    entries = {
        "close_topic": _entry("close_topic", {"website"}, ["website"]),
        "holds_all": _entry("holds_all", {"phone", "website"}, ["phone", "website"]),
    }
    topics = {"close_topic": 0.9, "holds_all": 0.1}
    r = rank(_profile({"phone", "website"}), entries, topics, list(entries))
    assert r.path == "holds_all"
    assert r.best.template_id == "holds_all"
    assert r.candidates[1].missing == ["phone"]


def test_best_match_when_no_template_holds_everything():
    entries = {
        "sale": _entry("sale", {"offer", "website"}, ["website"]),
        "food": _entry("food", {"offer", "website"}, ["website"]),
        "clinic": _entry("clinic", {"phone", "website"}, ["phone", "website"]),
    }
    topics = {"sale": 0.60, "food": 0.55, "clinic": 0.10}
    r = rank(_profile({"offer", "phone", "website"}), entries, topics, list(entries))
    assert r.path == "best_match"
    assert [c.template_id for c in r.candidates] == ["sale", "food", "clinic"]
    # 0.6·0.60 + 0.4·(2/3)
    assert r.best.score == pytest.approx(0.6 * 0.60 + 0.4 * 2 / 3)


def test_no_details_means_closest_topic_minus_empty_contact_slots():
    entries = {
        "a": _entry("a", {"phone", "website"}, ["phone", "website"]),
        "b": _entry("b"),
    }
    # a is 0.04 closer, but two unfilled contact slots cost 0.10.
    r = rank(_profile(), entries, {"a": 0.54, "b": 0.50}, list(entries))
    assert r.path == "holds_all"
    assert r.best.template_id == "b"
    assert r.candidates[1].empty_contact_slots == ["phone", "website"]


def test_near_tie_goes_to_more_held_details():
    entries = {"x": _entry("x", {"offer"}), "y": _entry("y", {"offer", "phone"})}
    # Neither holds offer+phone+website; x leads by less than the tie margin.
    topics = {"x": 0.50, "y": 0.34}
    r = rank(_profile({"offer", "phone", "website"}), entries, topics, list(entries))
    assert r.path == "best_match"
    assert r.best.template_id == "y"


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
    no_meta = tmp_path / "template_raw.json"
    no_meta.write_text(json.dumps(raw))
    assert enrich._verify(no_meta)[0] == ["no meta block yet — run `make lido-meta`"]

    broken = json.loads(TEMPLATE_227.read_text())
    for slot in broken[0]["meta"]["slots"]:
        if slot["role"] == "photo":
            slot["image"] = None                 # sample photo would never be replaced
        if slot["role"] == "logo":
            slot["locked"] = False
    bad = tmp_path / "template_bad.json"
    bad.write_text(json.dumps(broken))
    errors, _ = enrich._verify(bad)
    assert any("no image spec" in e for e in errors)
    assert any("logo must be locked" in e for e in errors)
