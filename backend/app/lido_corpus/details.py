"""Which *details* a request gives and which a template has a slot for (docs/new_match_plan.md §5).

A detail is one of seven concrete things a user can hand us and would be upset to lose:
a phone number, an email, a website, an address, an offer, a price, a date/time. The same
patterns run over the user's request and over each template's text slots, so "the
template can hold what the user gave" is a plain set comparison.

Patterns are deliberately simple and predictable. The request side is double-checked by
one small LLM call in `matcher.py` (an offer written in Hindi, an address with no street
word); the template side also trusts slot roles, which `loader._role_for` computes from
both the export's type tag and the sample text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import LidoTemplateMeta, SlotInfo

DETAILS: tuple[str, ...] = ("phone", "email", "website", "address", "offer", "price", "date")
CONTACT_DETAILS = frozenset({"phone", "email", "website", "address"})

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_WEBSITE = re.compile(
    r"(?:https?://|www\.)[^\s,;]+"
    r"|\b[\w-]+\.(?:com|in|org|net|co|io|shop|store|biz|info|app|online|site)(?:\.[a-z]{2})?\b",
    re.IGNORECASE)
# Digits with the separators people actually type; at least 7 digits (checked below) so
# "50%", "2026" or "10 AM" never count. No "/" so dates like 25/10/2026 are not phones.
_PHONE = re.compile(r"(?<![\w/])\+?\d[\d\s().-]{5,}\d(?![\w/])")
_OFFER = re.compile(
    r"\d+\s*%|%\s*off\b|\b(?:off|sale|discount|promo|promotion|offer|deal|deals|free|flat|"
    r"bogo|cashback|coupon|clearance|save)\b|buy\s+\d+\s+get"
    r"|छूट|ऑफर|सेल|मुफ्त|सवलत|ऑफ़र|डिस्काउंट",
    re.IGNORECASE)
_PRICE = re.compile(
    r"[₹$€£]\s?\d|\b(?:rs\.?|inr|usd|eur)\s?\d|\d\s?(?:rs\.?|/-)|\bprices?\b|\bonly\s+[₹$]?\d"
    r"|\bstarting\s+(?:at|from)\s+[₹$]?\d|रु\.?\s?\d|रुपये",
    re.IGNORECASE)
_MONTH = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*")
_DATE = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\b|\b{_MONTH}\s+\d{{1,2}}\b"
    r"|\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"
    r"|\b20\d{2}\b|\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b",
    re.IGNORECASE)
_ADDRESS = re.compile(
    r"\b(?:road|rd\.|street|st\.|lane|nagar|sector|floor|building|bldg|plaza|tower|"
    r"apartment|colony|chowk|marg|society|opp\.|opposite|near)\b|\b\d{6}\b"
    r"|रोड|मार्ग|नगर|चौक",
    re.IGNORECASE)

# Slot notes are NOT read for details: they describe neighbours and intent ("the
# service or offer name", "paired with the phone number"), which mislabels slots. Real
# offer slots show it in their sample text ("50% off", "Happy Hours Promo").

_ACTION = re.compile(
    r"^\W*(?:book|order|call|contact|apply|shop|buy|get|visit|join|register|sign|learn|"
    r"try|download|subscribe|enroll|enrol|reserve|claim|start|grab|explore|discover)\b",
    re.IGNORECASE)


def details_in_text(text: str | None) -> set[str]:
    """Every detail a free piece of text contains."""
    if not text:
        return set()
    found: set[str] = set()
    rest = text
    if _EMAIL.search(rest):
        found.add("email")
        rest = _EMAIL.sub(" ", rest)          # an email's domain is not a website
    if _WEBSITE.search(rest):
        found.add("website")
        rest = _WEBSITE.sub(" ", rest)
    for m in _PHONE.finditer(rest):
        if sum(c.isdigit() for c in m.group()) >= 7:
            found.add("phone")
            break
    if _OFFER.search(rest):
        found.add("offer")
    if _PRICE.search(rest):
        found.add("price")
    if _DATE.search(rest):
        found.add("date")
    if _ADDRESS.search(rest):
        found.add("address")
    return found


def _slot_details(slot: SlotInfo) -> set[str]:
    if slot.role in CONTACT_DETAILS:
        return {slot.role}
    # Includes a contact detail inside free copy ("call 98765 43210 today").
    return details_in_text(slot.default_text)


@dataclass
class TemplateDetails:
    details: set[str] = field(default_factory=set)
    """Every detail this template has a slot for."""
    contact_slots: list[str] = field(default_factory=list)
    """One entry per contact slot (e.g. ["website", "phone"]), for the empty-slot minus."""
    buttons: list[str] = field(default_factory=list)
    list_items: int = 0
    photos: int = 0

    def to_json(self) -> dict:
        return {"details": sorted(self.details), "contact_slots": self.contact_slots,
                "buttons": self.buttons, "list_items": self.list_items,
                "photos": self.photos}

    @classmethod
    def from_json(cls, data: dict) -> TemplateDetails:
        return cls(details=set(data.get("details", [])),
                   contact_slots=list(data.get("contact_slots", [])),
                   buttons=list(data.get("buttons", [])),
                   list_items=int(data.get("list_items", 0)),
                   photos=int(data.get("photos", 0)))


def _list_items(slots: list[SlotInfo]) -> int:
    """Largest group of parallel text slots: same font size, same left edge, short text.
    Bullets, job titles and a row of feature labels all count."""
    groups: dict[tuple, int] = {}
    for s in slots:
        if s.resolved_name != "TextLayer" or s.role in CONTACT_DETAILS or not s.default_text:
            continue
        if len(s.default_text) > 40:
            continue
        pos = s.position or {}
        by_column = (round(s.font_size or 0), round(pos.get("x", 0) / 10))
        by_row = (round(s.font_size or 0), "row", round(pos.get("y", 0) / 10))
        for key in (by_column, by_row):
            groups[key] = groups.get(key, 0) + 1
    best = max(groups.values(), default=0)
    return best if best >= 3 else 0


_SINGLE_WORD_ACTIONS = frozenset({
    "book", "order", "call", "contact", "apply", "shop", "buy", "register", "subscribe",
    "enroll", "enrol", "reserve", "join", "visit", "download"})


def _is_button_text(text: str | None) -> bool:
    """A short call to action. A lone "get" is a lead-in word ("get" + "50% off"), not a
    button, so one-word text counts only for unambiguous action verbs."""
    words = (text or "").split()
    if not words or len(words) > 4 or not _ACTION.match(text or ""):
        return False
    return len(words) > 1 or words[0].strip("!.").lower() in _SINGLE_WORD_ACTIONS


def template_details(meta: LidoTemplateMeta) -> TemplateDetails:
    out = TemplateDetails()
    text_slots = [s for s in meta.slots if s.resolved_name == "TextLayer" and s.editable]
    for s in text_slots:
        found = _slot_details(s)
        out.details |= found
        if s.role in CONTACT_DETAILS:
            out.contact_slots.append(s.role)
        if s.role == "label" and _is_button_text(s.default_text):
            out.buttons.append(" ".join(s.default_text.split()))
    out.list_items = _list_items(text_slots)
    out.photos = sum(1 for s in meta.slots
                     if s.role == "photo" and s.image is not None and s.image.generate)
    return out
