"""Pick the best template for a request (docs/new_match_plan.md, extended by
docs/slot_fit_match_plan.md).

    1. details the user gave     patterns (`details.py`) + one small LLM double-check
    2. lines the user quoted     found by code (`fit.quoted_lines`); the same LLM call only
                                 labels each one's kind (headline, offer, cta, badge, …)
    3. English topic line        same LLM call (any input language → English, because the
                                 local embedding model only understands English)
    4. topic score               cosine(topic line, template card), stretched to 0..1
    5. slot fit                  `fit.fit_template`: the cheapest placement of every line
                                 and detail into a slot that accepts its kind and holds its
                                 exact text (max_chars / max_lines in the real font)
    6. priority rule (tiers)     A  nothing dropped: topic − fit cost − penalties
                                 B  every must-keep item placed (headline, offer, price,
                                    contact): 0.5·topic + 0.4·coverage + 0.1·fit − penalties
                                 C  the rest, same formula as B
       penalties: a contact slot the user left empty (its "www.yourwebsite.com" would
       ship), an offer slot with no offer to hold (the writer might invent one), and —
       when the user quoted exact lines — spare slots the writer has to invent copy for

Every step degrades instead of failing: no LLM → the raw request is the topic line, the
pattern details are used alone and line kinds are guessed; no embedding model → topic is
word overlap.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from app.adapters.registry import llm as get_llm
from app.config import get_settings

from .details import DETAILS, details_in_text
from .fit import KINDS, ContentItem, TemplateFit, content_items, fit_template, quoted_lines
from .loader import DEFAULT_CORPUS_DIR
from .match_index import IndexEntry, embed, embedder_name, get_index
from .model import LidoTemplateFile

log = structlog.get_logger(__name__)

# -- tunables (docs/slot_fit_match_plan.md §7; tune with `python scripts/lido_match.py test`) -------
TOPIC_WEIGHT = 0.5
COVERAGE_WEIGHT = 0.4
FIT_WEIGHT = 0.1
TIER_A_FIT_COST_WEIGHT = 0.2
EMPTY_CONTACT_PENALTY = 0.05
LEFTOVER_OFFER_PENALTY = 0.08
SPARE_SLOT_PENALTY = 0.02
BUSY_PENALTY = 0.05
# all-MiniLM-L6-v2 cosines: unrelated ≈ 0.0–0.15, clearly related ≈ 0.45–0.65.
COSINE_LOW = 0.10
COSINE_HIGH = 0.60
TIE_MARGIN = 0.02

Detail = Literal["phone", "email", "website", "address", "offer", "price", "date"]


# --------------------------------------------------------------------------------------
# Request profile
# --------------------------------------------------------------------------------------


class DetailEvidence(BaseModel):
    detail: Detail
    quote: str = Field(description="The exact words from the request that give this "
                                   "detail, copied character for character.")


class LineLabel(BaseModel):
    text: str = Field(description="One of the requested text lines, copied exactly.")
    kind: Literal[KINDS] = Field(description=(  # type: ignore[valid-type]
        "What the line is on the design: headline (the main title), tagline (a short "
        "supporting line or claim), offer (a deal or discount), price, cta (a call to "
        "action such as 'Order Now'), badge (a short urgency/label such as 'Limited Time "
        "Offer'), feature (one item of a list), body (a sentence or paragraph), brand (a "
        "business name), date, phone, email, website, address."))


class RequestProfileOutput(BaseModel):
    topic: str = Field(description=(
        "One short English line (max ~20 words) naming what the design is for: occasion or "
        "industry, product or service, and mood. Translate if the request is not English. "
        "No contact details, no prices."))
    details: list[DetailEvidence] = Field(description=(
        "Only details the request ACTUALLY gives with a real value, each with its exact "
        "quote: phone (a number), email (an address), website (a URL/domain), address (a "
        "street/area/city), offer (a specific discount or deal, e.g. '30% off', 'buy 1 get "
        "1'), price (an amount), date (a date or time). Not details: 'call us' without a "
        "number, 'apply today', 'book now', 'hiring', a list of services. Empty if none."))
    lines: list[LineLabel] = Field(default_factory=list, description=(
        "One entry per requested text line listed after the request (none if no lines "
        "are listed), labelling what each line is. Copy each line exactly."))


_SYSTEM = ("You read a design request and return an English topic line and the concrete "
           "details it provides. Be literal: never invent a detail that is not in the text.")


@dataclass
class RequestProfile:
    prompt: str
    topic: str
    details: set[str]
    pattern_details: set[str]
    used_llm: bool
    items: list[ContentItem] = field(default_factory=list)
    """Everything that has to find a slot: quoted lines and loose details."""

    @property
    def lines(self) -> list[str]:
        return [i.text for i in self.items if i.text is not None]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _verified(evidence: list[DetailEvidence], prompt: str) -> set[str]:
    """A detail the model adds counts only if its quote really is in the request — the
    model has claimed an "offer" for "Apply today" and for a plain list of services,
    which sent those requests to offer templates."""
    haystack = _norm(prompt)
    out = set()
    for ev in evidence:
        quote = _norm(ev.quote)
        if ev.detail in DETAILS and len(quote) >= 2 and quote in haystack:
            out.add(ev.detail)
    return out


_PROFILE_CACHE: OrderedDict[str, RequestProfile] = OrderedDict()
_PROFILE_CACHE_MAX = 256


async def profile_request(prompt: str, *, use_llm: bool = True) -> RequestProfile:
    key = hashlib.sha256(prompt.encode()).hexdigest()
    if use_llm and key in _PROFILE_CACHE:
        _PROFILE_CACHE.move_to_end(key)
        return _PROFILE_CACHE[key]

    pattern = details_in_text(prompt)
    topic, details, used = prompt.strip(), set(pattern), False
    lines = quoted_lines(prompt)
    labels: dict[str, str] = {}
    if use_llm:
        user = f'Design request:\n"""{prompt.strip()}"""'
        if lines:
            user += "\n\nRequested text lines:\n" + "\n".join(f"- {line}" for line in lines)
        try:
            result = await get_llm().complete_json(
                system=_SYSTEM, user=user,
                schema=RequestProfileOutput, model=get_settings().llm_model_fast,
                max_tokens=300 + 30 * len(lines))
            parsed = result.parsed
            if isinstance(parsed, RequestProfileOutput) and parsed.topic.strip():
                topic = parsed.topic.strip()
                details |= _verified(parsed.details, prompt)
                wanted = {line.lower() for line in lines}
                labels = {key: lab.kind for lab in parsed.lines
                          if (key := _norm(lab.text)) in wanted}
                used = True
        except Exception as exc:  # noqa: BLE001 — matching must never fail on this call
            log.warning("lido.match.profile_failed", error=str(exc))

    profile = RequestProfile(prompt=prompt, topic=topic, details=details,
                             pattern_details=pattern, used_llm=used,
                             items=content_items(prompt, details, labels))
    if used:
        _PROFILE_CACHE[key] = profile
        while len(_PROFILE_CACHE) > _PROFILE_CACHE_MAX:
            _PROFILE_CACHE.popitem(last=False)
    return profile


# --------------------------------------------------------------------------------------
# Scores
# --------------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(["a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "with", "by", "from", "our", "your", "my", "we", "is", "are", "this", "that", "it", "be", "as", "template", "post", "has", "text", "title", "tags"])


def _words(text: str) -> set[str]:
    out = set()
    for w in _WORD.findall(text.lower()):
        if w in _STOP or len(w) < 3:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)   # events → event
    return out


def _stretch(cos: float) -> float:
    return max(0.0, min(1.0, (cos - COSINE_LOW) / (COSINE_HIGH - COSINE_LOW)))


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def topic_scores(topic_vec: list[float] | None, topic: str,
                 entries: dict[str, IndexEntry]) -> dict[str, float]:
    if topic_vec is not None and all(e.embedding for e in entries.values()):
        return {tid: _stretch(_dot(topic_vec, e.embedding)) for tid, e in entries.items()}
    # Word-overlap fallback: share of the topic's words found on the card.
    q = _words(topic)
    if not q:
        return {tid: 0.0 for tid in entries}
    return {tid: min(1.0, len(q & _words(e.card)) / math.sqrt(len(q)) / 2)
            for tid, e in entries.items()}


@dataclass
class MatchCandidate:
    template_id: str
    topic: float
    details_score: float
    held: list[str]
    missing: list[str]
    empty_contact_slots: list[str]
    tier: Literal["A", "B", "C"] = "A"
    fit: TemplateFit = field(default_factory=TemplateFit)
    score: float = 0.0

    def to_json(self) -> dict:
        return {"templateId": self.template_id, "score": round(self.score, 4),
                "topic": round(self.topic, 4), "details": round(self.details_score, 4),
                "held": self.held, "missing": self.missing,
                "emptyContactSlots": self.empty_contact_slots, "tier": self.tier,
                "coverage": round(self.fit.coverage, 4),
                "placedLines": list(self.fit.placed.values()),
                "droppedLines": self.fit.dropped}


@dataclass
class MatchResult:
    path: Literal["holds_all", "best_match"]
    """holds_all: the pick places every line and detail the user gave."""
    topic_line: str
    request_details: list[str]
    used_llm: bool
    embedder: str
    candidates: list[MatchCandidate] = field(default_factory=list)
    """Every template, best first."""
    requested_lines: list[str] = field(default_factory=list)

    @property
    def best(self) -> MatchCandidate:
        return self.candidates[0]

    def to_json(self, top: int = 3) -> dict:
        return {"path": self.path, "tier": self.best.tier, "topicLine": self.topic_line,
                "requestDetails": self.request_details,
                "requestedLines": self.requested_lines, "usedLlm": self.used_llm,
                "embedder": self.embedder,
                "candidates": [c.to_json() for c in self.candidates[:top]]}


def _penalty(fit: TemplateFit) -> float:
    p = (EMPTY_CONTACT_PENALTY * len(fit.leftover_contact)
         + LEFTOVER_OFFER_PENALTY * fit.leftover_offer)
    if fit.lines:
        # The user wrote the copy; every spare slot is copy the writer has to invent.
        p += SPARE_SLOT_PENALTY * fit.leftover_other
        if fit.leftover_other > fit.lines:
            p += BUSY_PENALTY
    return p


def rank(profile: RequestProfile, fits: dict[str, TemplateFit],
         topics: dict[str, float], order: list[str], embedder: str = "") -> MatchResult:
    """The tier rule (docs/slot_fit_match_plan.md §7). `order` is corpus order, the final
    tie-breaker."""
    given = profile.details
    cands = []
    for tid in order:
        f = fits[tid]
        held = sorted(given & f.held_details)
        missing = sorted(given - f.held_details)
        topic = topics.get(tid, 0.0)
        if not f.dropped:
            tier: Literal["A", "B", "C"] = "A"
            score = topic - TIER_A_FIT_COST_WEIGHT * f.fit_cost
        else:
            tier = "B" if f.must_keep_ok else "C"
            score = (TOPIC_WEIGHT * topic + COVERAGE_WEIGHT * f.coverage
                     + FIT_WEIGHT * (1 - f.fit_cost))
        c = MatchCandidate(tid, topic, len(held) / len(given) if given else 1.0, held,
                           missing, list(f.leftover_contact), tier, f)
        c.score = score - _penalty(f)
        cands.append(c)

    def key(c: MatchCandidate):
        return (c.tier, -c.score)

    cands.sort(key=key)
    # Near-tie inside the leading tier: more coverage, then a cleaner fit, wins.
    if len(cands) > 1 and cands[0].tier == cands[1].tier \
            and cands[0].score - cands[1].score < TIE_MARGIN:
        a, b = cands[0], cands[1]
        if (b.fit.coverage, -b.fit.fit_cost, b.details_score) > \
                (a.fit.coverage, -a.fit.fit_cost, a.details_score):
            cands[0], cands[1] = b, a
    path: Literal["holds_all", "best_match"] = (
        "holds_all" if cands and not cands[0].fit.dropped else "best_match")
    return MatchResult(path=path, topic_line=profile.topic,
                       request_details=sorted(given), used_llm=profile.used_llm,
                       embedder=embedder, candidates=cands,
                       requested_lines=profile.lines)


def fit_all(templates: list[LidoTemplateFile],
            profile: RequestProfile) -> dict[str, TemplateFit]:
    return {t.meta.id: fit_template(t, profile.items, profile.details) for t in templates}


async def match_templates(templates: list[LidoTemplateFile], prompt: str, *,
                          corpus_dir: Path | str = DEFAULT_CORPUS_DIR,
                          use_llm: bool = True, catalog=None) -> MatchResult:
    """`catalog` (from `store.load_catalog`) supplies stored index entries and lets
    pgvector compute the similarities; without it the index is built in memory."""
    from .store import topic_similarities

    if catalog is not None:
        entries, from_db = catalog.entries, catalog.from_db
    else:
        entries, from_db = await get_index(templates, corpus_dir), False
    entries = {t.meta.id: entries[t.meta.id] for t in templates if t.meta.id in entries}
    profile = await profile_request(prompt, use_llm=use_llm)
    vectors = await embed([profile.topic])
    topic_vec = vectors[0] if vectors else None
    cosines = (await topic_similarities(entries, topic_vec, from_db=from_db)
               if topic_vec is not None else None)
    topics = ({tid: _stretch(c) for tid, c in cosines.items()} if cosines is not None
              else topic_scores(None, profile.topic, entries))
    embedder = (embedder_name() + (" (pgvector)" if from_db else "")
                if cosines is not None else "word-overlap")
    by_id = {t.meta.id: t for t in templates}
    fits = fit_all([by_id[tid] for tid in entries], profile)
    result = rank(profile, fits, topics, list(entries), embedder=embedder)
    best = result.best
    log.info("lido.match", path=result.path, tier=best.tier, picked=best.template_id,
             score=round(best.score, 3), topic=profile.topic,
             details=result.request_details, lines=len(result.requested_lines),
             dropped=best.fit.dropped)
    if best.tier != "A":
        # Corpus gap: no template holds this request cleanly (plan §9).
        log.info("lido.match.gap", topic=profile.topic, tier=best.tier,
                 kinds=[i.kind for i in profile.items],
                 lengths=[len(i.text) for i in profile.items if i.text],
                 dropped=best.fit.dropped)
    return result
