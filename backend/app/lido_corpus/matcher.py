"""Part B of docs/new_match_plan.md: pick the best template for a request.

    1. details the user gave     patterns (`details.py`) + one small LLM double-check
    2. English topic line        same LLM call (any input language → English, because the
                                 local embedding model only understands English)
    3. topic score               cosine(topic line, template card), stretched to 0..1
    4. details score             user details the template can hold ÷ user details given
    5. priority rule             templates holding EVERY user detail win, ranked by topic;
                                 if none does, best 0.6·topic + 0.4·details wins
       both paths subtract 0.05 per contact slot the user left empty (its placeholder
       "www.yourwebsite.com" would otherwise ship on the design)

Every step degrades instead of failing: no LLM → the raw request is the topic line and
the pattern details are used alone; no embedding model → topic is word overlap.
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
from .loader import DEFAULT_CORPUS_DIR
from .match_index import IndexEntry, embed, embedder_name, get_index
from .model import LidoTemplateFile

log = structlog.get_logger(__name__)

# -- tunables (docs/new_match_plan.md §6; tune with `python scripts/lido_match.py test`) -------------------
TOPIC_WEIGHT = 0.6
DETAILS_WEIGHT = 0.4
EMPTY_CONTACT_PENALTY = 0.05
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


_SYSTEM = ("You read a design request and return an English topic line and the concrete "
           "details it provides. Be literal: never invent a detail that is not in the text.")


@dataclass
class RequestProfile:
    prompt: str
    topic: str
    details: set[str]
    pattern_details: set[str]
    used_llm: bool


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
    if use_llm:
        try:
            result = await get_llm().complete_json(
                system=_SYSTEM, user=f'Design request:\n"""{prompt.strip()}"""',
                schema=RequestProfileOutput, model=get_settings().llm_model_fast,
                max_tokens=300)
            parsed = result.parsed
            if isinstance(parsed, RequestProfileOutput) and parsed.topic.strip():
                topic = parsed.topic.strip()
                details |= _verified(parsed.details, prompt)
                used = True
        except Exception as exc:  # noqa: BLE001 — matching must never fail on this call
            log.warning("lido.match.profile_failed", error=str(exc))

    profile = RequestProfile(prompt=prompt, topic=topic, details=details,
                             pattern_details=pattern, used_llm=used)
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
    score: float = 0.0

    def to_json(self) -> dict:
        return {"templateId": self.template_id, "score": round(self.score, 4),
                "topic": round(self.topic, 4), "details": round(self.details_score, 4),
                "held": self.held, "missing": self.missing,
                "emptyContactSlots": self.empty_contact_slots}


@dataclass
class MatchResult:
    path: Literal["holds_all", "best_match"]
    topic_line: str
    request_details: list[str]
    used_llm: bool
    embedder: str
    candidates: list[MatchCandidate] = field(default_factory=list)
    """Every template, best first."""

    @property
    def best(self) -> MatchCandidate:
        return self.candidates[0]

    def to_json(self, top: int = 3) -> dict:
        return {"path": self.path, "topicLine": self.topic_line,
                "requestDetails": self.request_details, "usedLlm": self.used_llm,
                "embedder": self.embedder,
                "candidates": [c.to_json() for c in self.candidates[:top]]}


def rank(profile: RequestProfile, entries: dict[str, IndexEntry],
         topics: dict[str, float], order: list[str], embedder: str = "") -> MatchResult:
    """The priority rule. `order` is corpus order, the final tie-breaker."""
    given = profile.details
    cands = []
    for tid in order:
        e = entries[tid]
        held = sorted(given & e.details.details)
        missing = sorted(given - e.details.details)
        details_score = len(held) / len(given) if given else 1.0
        empty = [c for c in e.details.contact_slots if c not in given]
        cands.append(MatchCandidate(tid, topics.get(tid, 0.0), details_score, held,
                                    missing, empty))

    holds_all = [c for c in cands if not c.missing]
    if holds_all:
        path: Literal["holds_all", "best_match"] = "holds_all"
        for c in cands:
            c.score = c.topic - EMPTY_CONTACT_PENALTY * len(c.empty_contact_slots)
        pool, rest = holds_all, [c for c in cands if c.missing]
    else:
        path = "best_match"
        for c in cands:
            c.score = (TOPIC_WEIGHT * c.topic + DETAILS_WEIGHT * c.details_score
                       - EMPTY_CONTACT_PENALTY * len(c.empty_contact_slots))
        pool, rest = cands, []

    def key(c: MatchCandidate):
        return -c.score

    pool.sort(key=key)
    # Near-tie: more of the user's details wins (plan §6 B5).
    if len(pool) > 1 and pool[0].score - pool[1].score < TIE_MARGIN \
            and pool[1].details_score > pool[0].details_score:
        pool[0], pool[1] = pool[1], pool[0]
    rest.sort(key=lambda c: (-c.details_score, -c.topic))
    return MatchResult(path=path, topic_line=profile.topic,
                       request_details=sorted(given), used_llm=profile.used_llm,
                       embedder=embedder, candidates=pool + rest)


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
    result = rank(profile, entries, topics, list(entries), embedder=embedder)
    log.info("lido.match", path=result.path, picked=result.best.template_id,
             score=round(result.best.score, 3), topic=profile.topic,
             details=result.request_details)
    return result
