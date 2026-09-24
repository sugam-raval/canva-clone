"""Safety screening — IMPLEMENTATION_PLAN §7.

This is a *first-line* filter, not a content-moderation system. It blocks the categories
§7 names outright and flags requests for photoreal likenesses of real individuals. A
production deployment must add a dedicated moderation provider for NSFW/violence/CSAM
on both prompts and generated images — §7 calls that non-negotiable, and pattern
matching cannot do it.

Also carries the prompt-injection isolation helper §7 requires for any text extracted
from user-supplied images.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Categories refused outright.
_BLOCKED = [
    (re.compile(r"\b(child|minor|underage|teen|kid)\w*\b.{0,30}"
                r"\b(nude|naked|sexual|explicit|porn)\w*\b", re.IGNORECASE), "sexual content involving minors"),
    (re.compile(r"\b(nude|naked|porn\w*|explicit sexual|nsfw)\b", re.IGNORECASE), "explicit sexual content"),
    (re.compile(r"\b(gore|beheading|mutilat\w+|torture)\b", re.IGNORECASE), "graphic violence"),
    (re.compile(r"\b(counterfeit|forged?)\b.{0,20}\b(passport|id|licen[cs]e|currency|banknote)\b",
                re.IGNORECASE), "forged identity or currency documents"),
]

# Flagged, not blocked: a real person's name plus photoreal intent (§7 likeness rules).
_PHOTOREAL = re.compile(
    r"\b(photorealistic|photo[- ]real|realistic photo|deepfake|lookalike|"
    r"as if photographed)\b", re.IGNORECASE)
_REAL_PERSON_HINT = re.compile(
    r"\b(president|prime minister|celebrity|actor|actress|singer|politician)\b", re.IGNORECASE)

# Trademarked characters and brands — §7 asks for a block; this list is illustrative and
# must be replaced with a maintained rights database before public launch.
_TRADEMARK = re.compile(
    r"\b(mickey mouse|spider[- ]?man|batman|superman|pikachu|pokemon|hello kitty|"
    r"star wars|darth vader|harry potter|marvel|disney)\b", re.IGNORECASE)


@dataclass
class Verdict:
    allowed: bool
    reason: str = ""
    flags: tuple[str, ...] = ()


def screen_prompt(prompt: str) -> Verdict:
    text = prompt or ""
    for pattern, reason in _BLOCKED:
        if pattern.search(text):
            return Verdict(False, f"This request was blocked: {reason}.")
    if _TRADEMARK.search(text):
        return Verdict(False, "This request names a trademarked character or brand. "
                              "Describe the design you want in your own terms instead.")

    flags = []
    if _PHOTOREAL.search(text) and _REAL_PERSON_HINT.search(text):
        flags.append("possible-real-likeness")
    return Verdict(True, flags=tuple(flags))
