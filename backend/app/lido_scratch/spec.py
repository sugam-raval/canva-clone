"""The intermediate design spec — what the LLM actually writes.

A Lido layer is a deeply nested thing: a ProseMirror `doc` tree, a webfont descriptor,
a clip path, parallel `colors`/`fontSizes` arrays that have to agree with the marks
inside `doc`. Asking a model to emit that directly spends most of its attention on
bookkeeping and still produces documents that fail to parse.

So the model writes this instead — flat, small, and impossible to get structurally
wrong — and `compile.py` mechanically expands it into real Lido JSON. Two rules keep
the model on ground it is good at:

- **Proportional geometry.** `x`/`y`/`w` are fractions of the canvas, never pixels, so
  the same spec lays out correctly at 1080x1080 and at 1500x500, and the model is
  reasoning about composition rather than arithmetic.
- **Size classes, not point sizes.** A model asked for `fontSize` returns 48 for a
  headline whatever the canvas is. `size: "display"` carries the intent; the compiler
  turns it into pixels against the actual canvas.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .background import BackgroundStyle

ElementKind = Literal["text", "photo", "shape"]

SafeZone = Literal["top", "bottom", "left", "right", "center", "none"]

TextRole = Literal[
    "headline", "subhead", "body", "label", "cta",
    "brand", "phone", "address", "website", "email", "feature",
    "offer", "tagline",
]

SizeClass = Literal["display", "title", "heading", "body", "caption", "micro"]

#: Size class -> fraction of the canvas's short edge. Ratios, not pixels, so the type
#: scale holds its proportions on a square post and on a wide banner alike.
SIZE_RATIO: dict[str, float] = {
    "display": 0.115,
    "title": 0.075,
    "heading": 0.050,
    "body": 0.032,
    "caption": 0.024,
    "micro": 0.019,
}

ShapeKind = Literal["rect", "circle", "octagon"]

DecorKind = Literal[
    "dot-grid", "corner-brackets", "accent-underline", "side-rule",
    "badge-ring", "cta-pill", "contact-bar", "frame-outline", "edge-block",
]

FontSlot = Literal["auto", "display", "text", "script"]

#: Letter-spacing as a fraction of the font size. The tracked-out, widely-spaced
#: sub-line under a heavy headline ("FOR THIS WEEKEND ONLY") is a whole typographic
#: register that is simply unreachable without this, and it is the single most common
#: mark of a professionally set poster versus a generated one.
TRACKING_EM: dict[str, float] = {
    "tight": -0.02,
    "normal": 0.0,
    "wide": 0.10,
    "ultra": 0.28,
}

#: Line height per size class. Display type set at 1.2 looks loose and uncomposed;
#: body copy set at 1.0 is unreadable. One number for the whole page cannot be right
#: for both, and the old single LINE_HEIGHT constant was tuned for neither.
LINE_HEIGHT_FOR: dict[str, float] = {
    "display": 0.94,
    "title": 1.00,
    "heading": 1.10,
    "body": 1.35,
    "caption": 1.35,
    "micro": 1.30,
}

#: Typographic defaults per role, applied wherever the model expressed no preference.
#: These encode the conventions the reference posters follow — a label or a call to
#: action is set small, uppercase and tracked out; a headline is set tight and large.
ROLE_DEFAULTS: dict[str, dict[str, str]] = {
    "headline": {"transform": "uppercase", "tracking": "tight"},
    "subhead": {"tracking": "normal"},
    "tagline": {"transform": "uppercase", "tracking": "ultra"},
    "label": {"transform": "uppercase", "tracking": "wide"},
    "cta": {"transform": "uppercase", "tracking": "wide"},
    "brand": {"transform": "uppercase", "tracking": "wide"},
    "offer": {"transform": "uppercase", "tracking": "wide"},
    "feature": {"tracking": "normal"},
    "phone": {"tracking": "normal"},
    "address": {"tracking": "normal"},
    "website": {"tracking": "normal"},
    "email": {"tracking": "normal"},
}

Align = Literal["start", "center", "end"]

TextTransform = Literal["none", "uppercase", "capitalize"]

Tracking = Literal["tight", "normal", "wide", "ultra"]


class SpecElement(BaseModel):
    """One thing on the page. `kind` decides which of the optional fields matter."""

    kind: ElementKind
    role: TextRole | None = Field(
        default=None, description="what this text is for; required when kind='text'")

    text: str | None = Field(
        default=None, description="the copy, for kind='text'. Use \\n for a deliberate "
                                  "line break; do not pad with spaces")
    image_prompt: str | None = Field(
        default=None, description="subject to generate, for kind='photo'. Describe the "
                                  "subject only — never ask for text, logos or UI")
    cutout: bool = Field(
        default=False,
        description="for kind='photo' only. True generates the subject on a "
                    "transparent background and places it as a floating cutout — no "
                    "crop, no frame, no colour box behind it — instead of a "
                    "cover-cropped photo in a rectangle/circle. Use for a hero "
                    "product, mascot, or person meant to sit directly on the page; "
                    "never for a scene or setting, which wants a normal cropped photo")
    shape: ShapeKind | None = Field(
        default=None, description="for kind='shape'")

    x: float = Field(default=0.08, ge=-0.5, le=1.5,
                     description="left edge as a fraction of canvas width")
    y: float = Field(default=0.08, ge=-0.5, le=1.5,
                     description="top edge as a fraction of canvas height")
    w: float = Field(default=0.84, gt=0, le=1.5,
                     description="width as a fraction of canvas width")
    h: float | None = Field(
        default=None, gt=0, le=1.5,
        description="height as a fraction of canvas height. Ignored for text, whose "
                    "height follows from its wrapped line count")

    size: SizeClass = Field(default="body", description="type scale step, for kind='text'")
    align: Align = "start"
    transform: TextTransform = "none"
    color: str | None = Field(
        default=None, description="hex like '#FFFFFF'. Omit to let the compiler pick a "
                                  "legible on-palette colour for the ground behind it")
    opacity: float = Field(default=1.0, ge=0, le=1)

    behind: bool = Field(
        default=False,
        description="draw beneath the text block — use for shapes acting as a scrim or "
                    "colour field rather than as an accent on top")

    font: FontSlot = Field(
        default="auto",
        description="which face of the pairing to set this in. 'auto' picks by size "
                    "(large = display face, small = text face). 'script' sets the line "
                    "in the pairing's handwritten/script face — use it for ONE short "
                    "accent line above or below the headline, never for body copy, "
                    "never for two lines at once")
    tracking: Tracking | None = Field(
        default=None,
        description="letter spacing. Omit to take the role's convention. 'ultra' on a "
                    "short uppercase line under a headline is the classic spaced-out "
                    "sub-line; never use it on more than one line, or on body copy")

    z: int | None = Field(
        default=None,
        description="internal draw-order override; leave unset. Ornament sets it.")


class SpecBackground(BaseModel):
    """The ground the whole page is drawn on.

    `style` is the design decision and `motif` is at most a hint: the prompt itself is
    assembled in `background.build_prompt` from the style's recipe and the design's own
    palette, so the ground always belongs to the same colour scheme as the type and the
    ornament. A free-text prompt written by the model used to produce a literal
    photograph of the subject — evenly detailed, off-palette, and impossible to set
    type on — which is the failure this structure exists to remove.
    """

    style: BackgroundStyle = Field(
        default="gradient-glow",
        description="the graphic treatment of the ground; see the STYLE menu in the "
                    "instructions")
    color: str = Field(default="#101418", description="hex; the flat ground, and what "
                                                      "shows while an image loads")
    motif: str | None = Field(
        default=None,
        description="optional subject hint, 2-6 words ('a loaded cheeseburger', 'a "
                    "mountain trail at dawn'). For a graphic style it only steers the "
                    "shapes and colour and is never drawn literally; for "
                    "'photo-scene' it IS the photograph, so describe a place or a "
                    "surface, never text or a logo")
    safe_zone: SafeZone = Field(
        default="none",
        description="which side of the frame your text elements sit on. That side is "
                    "held visually calm — flat, uninterrupted colour — and any detail "
                    "is pushed to the opposite side. Set it on every image style; "
                    "'none' only makes sense for style='flat'.")


class DesignSpec(BaseModel):
    """A complete design, before it becomes Lido JSON."""

    name: str = Field(description="2-4 words naming the design, e.g. 'Morning Roast Promo'")
    kind: str = Field(default="post", description="post, story, poster, banner, thumbnail, ad or flyer")
    width: int = Field(default=1080, ge=64, le=8000)
    height: int = Field(default=1080, ge=64, le=8000)

    vibe: Literal[
        "geometric", "humanist", "serif-editorial", "display-bold", "script",
        "impact", "corporate", "tech-modern", "luxury-serif", "casual-hand", "retro",
        "condensed-sport", "street-bold", "editorial-fat", "playful-fun",
    ] = Field(
        default="geometric",
        description="typographic voice; selects the font pairing. Match it to what "
                    "the brief actually is, not a default: 'impact' for gym/sale/"
                    "sports, 'corporate' for hiring/business/LinkedIn, 'tech-modern' "
                    "for startups/SaaS/fintech, 'luxury-serif' for fashion/jewellery/"
                    "premium, 'casual-hand' for personal/friendly notes, 'retro' for "
                    "vintage posters, 'script' for weddings/invitations, "
                    "'serif-editorial' for magazines/culture, 'display-bold' for "
                    "playful/youth brands, 'condensed-sport' for match days/events/"
                    "schedules, 'street-bold' for music/nightlife/streetwear, "
                    "'editorial-fat' for bold magazine covers, 'playful-fun' for "
                    "sweets/kids/party, 'geometric'/'humanist' as clean defaults.")
    layout_style: Literal[
        "hero-stack", "split-panel", "badge-center", "top-band", "corner-frame",
    ] = Field(
        default="hero-stack",
        description="the composition archetype, committed to up front so the page "
                    "doesn't default to the same centred stack every time:\n"
                    "  - hero-stack: text block stacked down one side or the top, a "
                    "photo or cutout filling the rest. The general-purpose default.\n"
                    "  - split-panel: the canvas divided into two blocks side by side "
                    "(or top/bottom on a tall canvas) — a solid colour panel with text "
                    "against a photo or cutout panel. Strong for ads, hiring posts, "
                    "product launches.\n"
                    "  - badge-center: everything centred, often inside or around a "
                    "circular or framed badge. For formal announcements, seals, "
                    "invitations, stamps.\n"
                    "  - top-band: a coloured band across the top or bottom carrying "
                    "the headline/brand, the rest of the canvas open for imagery. For "
                    "banners and simple announcements.\n"
                    "  - corner-frame: imagery fills the canvas, text confined to one "
                    "corner or edge on its own scrim. For photo-led posters.")
    palette: list[str] = Field(
        default_factory=list,
        description="3-5 hex colours, ordered ground first then accents")
    background: SpecBackground = Field(default_factory=SpecBackground)

    decor: list[DecorKind] = Field(
        default_factory=list,
        description="the ornament the page wears — the small graphic marks that make a "
                    "layout look designed rather than typed. Pick 2-3 that suit the "
                    "archetype; leave empty to take the archetype's own defaults. "
                    "Placement is worked out for you against the finished layout, so "
                    "you are choosing marks, not positions:\n"
                    "  - accent-underline: a short heavy rule under the headline\n"
                    "  - dot-grid: a small dot matrix in the empty corners\n"
                    "  - side-rule: a vertical bar down the left of the headline\n"
                    "  - corner-brackets: two opposed L-brackets implying a frame\n"
                    "  - frame-outline: a hairline border inset from the trim\n"
                    "  - edge-block: a solid colour panel bled off one edge behind the "
                    "text — this is what builds a split-panel or top-band\n"
                    "  - contact-bar: a band across the foot carrying the contact "
                    "lines, each with an icon chip\n"
                    "  - badge-ring: a disc stamped behind a role='offer' element\n"
                    "  - cta-pill: a filled pill behind the call to action\n"
                    "(badge-ring and cta-pill are added automatically whenever the "
                    "page actually has an offer or a CTA, so you need not list them.)")

    elements: list[SpecElement] = Field(
        default_factory=list,
        description="Every element on the page, in reading order (top of the page "
                    "first). A finished design has at least 4 and at most 14. If the "
                    "brief only gave you a headline, you still write the supporting "
                    "copy — a subhead, a CTA, a tagline — because a page carrying two "
                    "elements reads as unfinished, not as minimal.")

    def text_elements(self) -> list[SpecElement]:
        return [e for e in self.elements if e.kind == "text" and (e.text or "").strip()]
