"""Slot fit (docs/slot_fit_match_plan.md): can this template hold everything the user
asked for — every line they quoted, every detail they gave — without cutting any of it?

    request  → content items   every quoted line (with a kind and its exact text) plus
                               every detected detail no quoted line already carries
    template → slot fits       what each editable text slot accepts, and its real limits
                               (max_chars / max_lines, measured in the slot's own font)
    both     → TemplateFit     the cheapest placement of items into slots (an exact
                               search; the problem is ~5-10 items × ~5-10 slots), what was
                               dropped, and what is left over

The matcher ranks templates by the fit (tiers) and then topic; the fill step receives the
winning placement, so the user's lines land exactly where they were planned, unchanged.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from itertools import product

from .details import CONTACT_DETAILS, DETAILS, _is_button_text, details_in_text
from .generate_ai import TextTarget, text_targets
from .model import LidoTemplateFile
from .textfit import too_wide_words, wrap

KINDS: tuple[str, ...] = (
    "headline", "tagline", "offer", "price", "cta", "badge", "feature", "body", "brand",
    "date", "phone", "email", "website", "address",
)

# How bad losing an item is (plan §5). Weight 3 = must keep.
KIND_WEIGHT = {
    "headline": 3.0, "offer": 3.0, "price": 3.0,
    "phone": 3.0, "email": 3.0, "website": 3.0, "address": 3.0,
    "cta": 2.0, "date": 2.0,
    "tagline": 1.5, "badge": 1.5, "brand": 1.5,
    "feature": 1.0, "body": 1.0,
}
MUST_KEEP = 3.0
# A quoted line may run this far past `max_chars` when it still wraps into `max_lines`
# in the slot's real font (max_chars is an estimate; the measured wrap is the truth).
MAX_CHARS_TOLERANCE = 0.10
# Per weight unit: dropping an item always costs more than any placement (costs ≤ 0.7).
DROP_COST = 10.0
MAX_ITEMS = 12
MAX_SPLIT_VARIANTS = 2

_STRONG_OFFER = re.compile(
    r"\d+\s*%|%\s*off\b|\bbuy\s+\d+\s+get\b|\bbogo\b|\bflat\s+[₹$€£]?\s?\d|\bfree\b"
    r"|\b\d+\s*off\b|\bsale\b|\bdiscount|\bcashback\b|छूट|मुफ्त|सवलत|डिस्काउंट",
    re.IGNORECASE)
_URGENCY = re.compile(
    r"\blimited\b|\bhurry\b|\btoday only\b|\blast chance\b|\bends\b|\bwhile stocks?\b"
    r"|\bexclusive\b|\bdon'?t miss\b|\bonly this\b|\bfew (?:days|seats|spots)\b",
    re.IGNORECASE)
_SEPARATOR = re.compile(r"\s*[•|·]\s*")


# --------------------------------------------------------------------------------------
# Request side: content items
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentItem:
    kind: str
    text: str | None
    """The user's exact words; None for a detail given in running text (e.g. a phone
    number in a sentence), which only needs a slot of its kind — the writer copies it."""
    weight: float
    details: frozenset[str] = frozenset()
    parts: tuple[str, ...] = ()
    """Bullet-separated pieces ("Freshly Baked • Extra Cheesy"), placeable as list rows."""

    @property
    def verbatim(self) -> bool:
        return self.text is not None

    @property
    def label(self) -> str:
        return self.text if self.text is not None else self.kind


_QUOTE = re.compile(r"“([^”\n]{2,160})”|\"([^\"\n]{2,160})\"|«([^»\n]{2,160})»"
                    r"|„([^“”\n]{2,160})[“”]|‘([^’\n]{2,160})’")
_INCLUDE_BLOCK = re.compile(
    r"\b(?:include|add|use|with|show)\s+(?:the\s+)?(?:following\s+)?"
    r"(?:text|texts|copy|lines|wording|words)\s*:[ \t]*\n((?:[ \t]*\S[^\n]*\n?)+)",
    re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*–•·]|\d{1,2}[.)])?\s*")


def _norm(text: str) -> str:
    return " ".join(text.split())


def quoted_lines(prompt: str) -> list[str]:
    """Every line the user asked to appear as written: quoted text, plus unquoted lines
    listed under "Include the text:". In order, without duplicates."""
    found: list[str] = []
    for m in _QUOTE.finditer(prompt):
        found.append(next(g for g in m.groups() if g is not None))
    for block in _INCLUDE_BLOCK.finditer(prompt):
        rows = block.group(1).splitlines()
        if any(_QUOTE.search(raw) for raw in rows):
            continue          # a quoted list: its lines are taken above, the rest is prose
        for raw in rows:
            line = _BULLET.sub("", raw).strip().strip("\"“”'‘’")
            if 2 <= len(line) <= 160:
                found.append(line)
    out, seen = [], set()
    for line in found:
        line = _norm(line)
        key = line.lower()
        if line and key not in seen:
            seen.add(key)
            out.append(line)
    return out


def guess_kind(text: str) -> str | None:
    """Pattern kind of one quoted line; None when only its position can tell (the first
    such line is the headline). The request-profile LLM call overrides this."""
    d = details_in_text(text)
    for contact in ("email", "website", "phone"):
        if contact in d:
            return contact
    if _STRONG_OFFER.search(text):
        return "offer"
    if "price" in d:
        return "price"
    if _is_button_text(text):
        return "cta"
    if _URGENCY.search(text):
        return "badge"
    if "offer" in d:
        return "offer"
    if "address" in d and re.search(r"\d", text):
        return "address"
    if "date" in d and len(text) <= 40:
        return "date"
    return None


def content_items(prompt: str, details: set[str],
                  labels: dict[str, str] | None = None) -> list[ContentItem]:
    """The request as items. `labels` maps a quoted line (normalized, lower-case) to the
    kind the LLM gave it; lines it didn't label fall back to `guess_kind`."""
    labels = labels or {}
    lines = quoted_lines(prompt)
    kinds: list[str | None] = []
    for line in lines:
        k = labels.get(line.lower())
        kinds.append(k if k in KINDS else guess_kind(line))
    has_headline = "headline" in kinds
    items: list[ContentItem] = []
    for line, kind in zip(lines, kinds, strict=True):
        if kind is None:
            if not has_headline:
                kind, has_headline = "headline", True
            else:
                kind = "tagline" if len(line) <= 60 else "body"
        line_details = frozenset(details_in_text(line) | ({kind} & set(DETAILS)))
        weight = KIND_WEIGHT[kind]
        if line_details & (CONTACT_DETAILS | {"price"}):
            weight = max(weight, MUST_KEEP)
        parts = tuple(p for p in _SEPARATOR.split(line) if p.strip())
        items.append(ContentItem(kind, line, weight, line_details,
                                 parts if len(parts) > 1 else ()))
    covered = set().union(*(i.details for i in items)) if items else set()
    for d in sorted(details - covered):
        items.append(ContentItem(d, None, KIND_WEIGHT.get(d, 1.0), frozenset({d})))
    # Heaviest first; beyond MAX_ITEMS the lightest are dropped up front.
    items.sort(key=lambda i: -i.weight)
    return items[:MAX_ITEMS] if len(items) > MAX_ITEMS else items


# --------------------------------------------------------------------------------------
# Template side: what each slot accepts
# --------------------------------------------------------------------------------------

_BASE_ACCEPTS: dict[str, dict[str, float]] = {
    "headline": {"headline": 0.0, "brand": 0.3, "offer": 0.4, "price": 0.5,
                 "tagline": 0.6, "badge": 0.6},
    "subhead": {"tagline": 0.0, "offer": 0.2, "badge": 0.2, "body": 0.3, "price": 0.3,
                "date": 0.3, "brand": 0.3, "headline": 0.5},
    "body": {"tagline": 0.0, "body": 0.0, "feature": 0.3, "date": 0.3, "badge": 0.4,
             "price": 0.4, "offer": 0.5},
    "label": {"badge": 0.0, "cta": 0.2, "date": 0.2, "feature": 0.3, "tagline": 0.3,
              "price": 0.3, "brand": 0.3, "offer": 0.4},
}
_REUSE_ACCEPTS = {"badge": 0.5, "cta": 0.5}


@dataclass
class SlotFit:
    target: TextTarget
    accepts: dict[str, float]
    contact: str | None
    """The slot's contact role (website/phone/email/address), else None."""
    offer_like: bool
    """Its sample copy is an offer ("25% off"): left empty, the writer might invent one."""
    optional: bool

    @property
    def layer_id(self) -> str:
        return self.target.layer_id


def _list_groups(targets: list[TextTarget]) -> set[str]:
    """Layer ids in a list of parallel short slots — the rule of `details._list_items`."""
    groups: dict[tuple, list[str]] = {}
    for t in targets:
        s = t.slot
        if s.role in CONTACT_DETAILS or not s.default_text or len(s.default_text) > 40:
            continue
        pos = s.position or {}
        size = round(s.font_size or 0)
        for key in ((size, round(pos.get("x", 0) / 10)), (size, "row", round(pos.get("y", 0) / 10))):
            groups.setdefault(key, []).append(s.layer_id)
    return {lid for ids in groups.values() if len(ids) >= 3 for lid in ids}


def _accepts(target: TextTarget, in_list: bool) -> tuple[dict[str, float], bool]:
    slot = target.slot
    if slot.role in CONTACT_DETAILS:
        return {slot.role: 0.0}, False
    sample = slot.default_text or ""
    found = details_in_text(sample)
    acc = dict(_BASE_ACCEPTS.get(slot.role, {"tagline": 0.3, "body": 0.3, "badge": 0.3}))
    if slot.role == "label" and _is_button_text(sample):
        acc = {"cta": 0.0, "badge": 0.4}
    offer_like = bool(_STRONG_OFFER.search(sample)) or "offer" in found
    if offer_like:
        acc.update(offer=0.0, badge=min(acc.get("badge", 1.0), 0.2), price=0.2)
    for d in found & {"phone", "email", "website", "address", "price", "date"}:
        acc[d] = 0.0
    if in_list:
        acc["feature"] = 0.0
    return acc, offer_like


_SLOT_CACHE: dict[tuple[str, str], list[SlotFit]] = {}


def slot_fits(template: LidoTemplateFile) -> list[SlotFit]:
    """Every fillable text slot with what it accepts. Cached per template version, since
    building the measures touches font files."""
    meta = template.meta
    key = (meta.id, hashlib.sha256(meta.model_dump_json().encode()).hexdigest()[:16])
    hit = _SLOT_CACHE.get(key)
    if hit is not None:
        return hit
    targets = text_targets(template)
    listed = _list_groups(targets)
    out = []
    for t in targets:
        acc, offer_like = _accepts(t, t.layer_id in listed)
        out.append(SlotFit(t, acc, t.slot.role if t.slot.role in CONTACT_DETAILS else None,
                           offer_like, bool(t.slot.optional)))
    if len(_SLOT_CACHE) > 512:
        _SLOT_CACHE.clear()
    _SLOT_CACHE[key] = out
    return out


def text_fits(text: str, target: TextTarget) -> bool:
    """True when the user's exact `text` sets in this slot without being cut: within
    `max_chars` (or at most MAX_CHARS_TOLERANCE past it when the real font says it still
    wraps into `max_lines`), no word wider than the box, no more than `max_lines` lines."""
    text = _norm(text)
    slot, measure = target.slot, target.measure
    if slot.max_chars and len(text) > slot.max_chars:
        measured = measure is not None and measure.exact and slot.max_lines
        if not measured or len(text) > slot.max_chars * (1 + MAX_CHARS_TOLERANCE):
            return False
    if measure is not None and target.box_width:
        if too_wide_words(text, measure, target.box_width):
            return False
        if slot.max_lines and len(wrap(text, measure, target.box_width)) > slot.max_lines:
            return False
    return True


# --------------------------------------------------------------------------------------
# The fit
# --------------------------------------------------------------------------------------


@dataclass
class TemplateFit:
    placed: dict[str, str] = field(default_factory=dict)
    """layer_id → the user's exact line, locked for the fill step."""
    reserved: dict[str, str] = field(default_factory=dict)
    """layer_id → detail kind for a detail with no exact line (the writer fills it)."""
    hidden: list[str] = field(default_factory=list)
    """Optional contact slots with no user value: emptied instead of showing a placeholder."""
    dropped: list[str] = field(default_factory=list)
    """Lines (or detail kinds) that have no slot here."""
    coverage: float = 1.0
    must_keep_ok: bool = True
    fit_cost: float = 0.0
    held_details: set[str] = field(default_factory=set)
    leftover_contact: list[str] = field(default_factory=list)
    """Contact roles of unfilled, non-optional contact slots: their placeholder ships."""
    leftover_offer: int = 0
    leftover_other: int = 0
    lines: int = 0
    """How many exact lines the user asked for."""

    def to_json(self) -> dict:
        return {"placed": self.placed, "hidden": self.hidden, "dropped": self.dropped,
                "coverage": round(self.coverage, 4), "fitCost": round(self.fit_cost, 4)}


def _expand(items: list[ContentItem]) -> list[list[tuple[int, ContentItem]]]:
    """Variants of the item list: each splittable line whole or as its parts. Each
    entry is (index of the original item, item to place)."""
    splittable = [i for i, it in enumerate(items) if it.parts][:MAX_SPLIT_VARIANTS]
    variants = []
    for choice in product((False, True), repeat=len(splittable)):
        split = {i for i, s in zip(splittable, choice, strict=True) if s}
        rows: list[tuple[int, ContentItem]] = []
        for i, it in enumerate(items):
            if i in split:
                w = it.weight / len(it.parts)
                rows += [(i, ContentItem("feature", p, w, frozenset(details_in_text(p))))
                         for p in it.parts]
            else:
                rows.append((i, it))
        variants.append(rows)
    return variants


def _costs(rows: list[tuple[int, ContentItem]], slots: list[SlotFit],
           given: set[str]) -> list[list[float | None]]:
    table = []
    for _, it in rows:
        row: list[float | None] = []
        for s in slots:
            acc = s.accepts
            if (s.contact and s.optional and s.contact not in given
                    and it.kind in _REUSE_ACCEPTS):
                acc = {**acc, **_REUSE_ACCEPTS}
            cost = acc.get(it.kind)
            if cost is not None and it.verbatim and not text_fits(it.text, s.target):
                cost = None
            row.append(cost)
        table.append(row)
    return table


def _solve(weights: list[float], table: list[list[float | None]]) -> tuple[float, list[int | None]]:
    """Exact min-cost placement (each slot used at most once; an item may be dropped at
    DROP_COST × weight). Memoized search over (item, used slots)."""
    n = len(weights)
    memo: dict[tuple[int, int], tuple[float, tuple]] = {}

    def best(i: int, used: int) -> tuple[float, tuple]:
        if i == n:
            return 0.0, ()
        key = (i, used)
        if key in memo:
            return memo[key]
        cost, rest = best(i + 1, used)
        result = (cost + DROP_COST * weights[i], (None,) + rest)
        for j, c in enumerate(table[i]):
            if c is None or used >> j & 1:
                continue
            sub, tail = best(i + 1, used | 1 << j)
            if sub + c < result[0]:
                result = (sub + c, (j,) + tail)
        memo[key] = result
        return result

    total, picks = best(0, 0)
    return total, list(picks)


def _unsplit_partial(items: list[ContentItem], rows: list[tuple[int, ContentItem]],
                     picks: list[int | None], table: list[list[float | None]]) -> float:
    """A split line goes in whole or not at all: "Made Daily" alone, without "Freshly
    Baked • Extra Cheesy", is not what the user wrote. Unplaces the parts of a partly
    placed split line (in `picks`) and returns the extra cost of doing so."""
    extra = 0.0
    for orig, it in enumerate(items):
        if not it.parts:
            continue
        mine = [r for r, (o, part) in enumerate(rows) if o == orig and part is not it]
        placed = [r for r in mine if picks[r] is not None]
        if mine and 0 < len(placed) < len(mine):
            for r in placed:
                extra += DROP_COST * rows[r][1].weight - (table[r][picks[r]] or 0.0)
                picks[r] = None
    return extra


def fit_template(template: LidoTemplateFile, items: list[ContentItem],
                 given: set[str]) -> TemplateFit:
    slots = slot_fits(template)
    best: tuple[float, list, list, list] = (float("inf"), [], [], [])
    for rows in _expand(items):
        table = _costs(rows, slots, given)
        total, picks = _solve([it.weight for _, it in rows], table)
        total += _unsplit_partial(items, rows, picks, table)
        if total < best[0]:
            best = (total, rows, picks, table)
    _, rows, picks, table = best

    fit = TemplateFit(lines=sum(1 for it in items if it.verbatim))
    used: set[int] = set()
    placed_weight = [0.0] * len(items)
    cost_sum = cost_weight = 0.0
    for r, ((orig, it), j) in enumerate(zip(rows, picks, strict=True)):
        if j is None:
            label = items[orig].label
            if label not in fit.dropped:
                fit.dropped.append(label)
            continue
        used.add(j)
        slot = slots[j]
        placed_weight[orig] += it.weight
        cost_sum += (table[r][j] or 0.0) * it.weight
        cost_weight += it.weight
        if it.verbatim:
            fit.placed[slot.layer_id] = _norm(it.text)
        else:
            fit.reserved[slot.layer_id] = it.kind
        fit.held_details |= set(it.details)

    total_weight = sum(it.weight for it in items)
    fit.coverage = sum(placed_weight) / total_weight if total_weight else 1.0
    fit.must_keep_ok = all(placed_weight[i] >= it.weight - 1e-9
                           for i, it in enumerate(items) if it.weight >= MUST_KEEP)
    fit.fit_cost = cost_sum / cost_weight if cost_weight else 0.0
    for j, s in enumerate(slots):
        if j in used:
            continue
        if s.contact:
            if s.contact in given:
                continue                      # the writer repeats the user's value
            if s.optional:
                fit.hidden.append(s.layer_id)
            else:
                fit.leftover_contact.append(s.contact)
        elif s.offer_like and "offer" not in given:
            fit.leftover_offer += 1
        else:
            fit.leftover_other += 1
    return fit
