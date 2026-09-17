"""ComposerOutput — IMPLEMENTATION_PLAN §1.3.

Deliberately small and hard to get wrong. The LLM does NOT invent coordinates; it
picks a skeleton, writes copy, chooses colour and fonts, and may nudge a frame by
at most +/-8%.
"""

from __future__ import annotations

from pydantic import Field

from .doc import Base


class FrameNudge(Base):
    dx: float = Field(default=0, ge=-0.08, le=0.08)
    dy: float = Field(default=0, ge=-0.08, le=0.08)
    dw: float = Field(default=0, ge=-0.08, le=0.08)
    dh: float = Field(default=0, ge=-0.08, le=0.08)


class SlotText(Base):
    content: str


class SlotImagePrompt(Base):
    prompt: str
    negative_prompt: str


class ComposerFont(Base):
    """A display face, a supporting face, and an optional script accent.

    One family for a whole design is what makes output look untyped: a display face set
    at caption size is unreadable, and a text face blown up to headline size is limp.
    `family` is the display face (headlines); `text_family` carries everything else.
    `script_family` is reserved for a short accent line set beside the headline — the
    "Summer" above "FASHION SALE" — and is never used for body copy.
    """

    family: str
    text_family: str | None = None
    script_family: str | None = None
    headline_weight: int = 700
    body_weight: int = 400

    def for_face(self, face: str | None) -> str:
        """Resolve a slot's requested face, degrading to one that exists."""
        if face == "script" and self.script_family:
            return self.script_family
        if face == "display":
            return self.family
        if face == "script":
            # No script in this pairing; the accent still has to be set in something,
            # and the display face reads as more deliberate than the body face.
            return self.family
        return self.text_family or self.family


class ComposerSlot(Base):
    slot_id: str
    include: bool = True
    text: SlotText | None = None
    color: str | None = None
    frame_nudge: FrameNudge | None = None
    image_prompt: SlotImagePrompt | None = None


class ComposerOutput(Base):
    template_id: str
    variant_id: str | None = None
    reason: str = Field(description="one line: why this skeleton fits the brief")
    palette: list[str] = Field(min_length=3, max_length=5)
    font: ComposerFont
    slots: list[ComposerSlot]


class RewrittenCopy(Base):
    """Output of `copy.rewrite` (§3.3) — all selected layers rewritten together."""

    layer_id: str
    content: str


class RewriteOutput(Base):
    layers: list[RewrittenCopy]
