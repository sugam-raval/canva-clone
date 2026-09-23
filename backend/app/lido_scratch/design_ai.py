"""Brief -> `DesignSpec`. The one LLM call that actually designs the page.

`app.lido_corpus.compose_ai` writes copy into a layout somebody else already made.
This writes the layout too, so the prompt has to carry the design judgement that a
template would otherwise have supplied: what dominates, where the eye goes, how much
air to leave. That is what `_system_prompt` is.

Same failure posture as the rest of the corpus (§1.3): never fail the request here.
With no LLM configured, `_mechanical_spec` lays the brief out on a standard poster
grid — plainer than what the model would do, but a real design.
"""

from __future__ import annotations

import re

from app.adapters.base import AdapterError
from app.adapters.registry import llm as get_llm
from app.schema.brief import DesignBrief

from . import background as background_mod
from .spec import DesignSpec, SpecBackground, SpecElement

#: Past this the page stops being a design and starts being a list. Raised from a
#: plainer default to leave room for a real feature/bullet list (job openings, menu
#: items, amenities) without starving the rest of the layout of its budget.
MAX_ELEMENTS = 18


def _system_prompt() -> str:
    return (
        "You are a senior graphic designer. Given a design brief, you design a complete "
        "single-page layout from scratch and return it as a structured spec.\n"
        "\n"
        "You are designing to the standard of a paid social media template — the kind "
        "with a deep colour field, a torn brush stroke of one vivid accent, a hero "
        "subject cut out and floating over it, a script line above a heavy condensed "
        "headline, a tracked-out sub-line under it, a roundel carrying the offer and a "
        "contact bar across the foot. Not a slide. Every mechanism that page is built "
        "from is available to you below; a plain centred stack of grey text on a "
        "photograph is a failure even when nothing about it is wrong.\n"
        "\n"
        "The brief is a starting point, not a content list. It will usually give you "
        "less copy than a finished page needs, and filling the gap is your job: a real "
        "design carries 4 to 14 elements, and one carrying two reads as unfinished "
        "whatever its proportions are.\n"
        "\n"
        "GEOMETRY. x, y and w are fractions of the canvas (0 = left/top edge, 1 = "
        "right/bottom edge), never pixels. Keep every element inside a margin of at "
        "least 0.06 on all four sides. Text height is computed for you from the wrapped "
        "line count — do not set h on a text element.\n"
        "\n"
        "TYPE SCALE. Pick a size class per element, not a pixel size. A page needs ONE "
        "dominant element: exactly one 'display' or 'title', and everything else at "
        "least two steps smaller. A design where the headline and the subhead are the "
        "same size reads as a list. Body copy stays at 'body' or 'caption'; phone, "
        "address and website go at 'caption' or 'micro' near the bottom.\n"
        "\n"
        "TYPE VOICE. Three things separate set type from typed text, and you control "
        "all three:\n"
        "  - `vibe` picks the whole page's font pairing — a display face, a text face "
        "and a script face. Choose it for the subject, not as a default.\n"
        "  - `font` on an element overrides which of the three it is set in. The move "
        "worth knowing: ONE short line set `font='script'` at 'heading' or 'title' "
        "directly above the headline ('Super Delicious' over 'FOOD MENU'). One line "
        "only — a second script line destroys the effect and the hierarchy with it. "
        "Everything else leaves `font` alone.\n"
        "  - `tracking` is letter spacing. A short uppercase line under the headline "
        "set `tracking='ultra'` is the classic spaced-out sub-line. Never on body "
        "copy, never on more than one line of the page. Roles carry sensible defaults, "
        "so you only set this when you want the effect deliberately.\n"
        "\n"
        "COMPOSITION. Do not centre everything by default — a left-aligned block with a "
        "strong ragged edge is usually stronger, and centring is a decision you make for "
        "a reason (a stamp, a title card, a formal invitation). Leave real empty space; "
        "crowding is the most common way these come out looking cheap. Group related "
        "lines tightly (headline and subhead almost touching) and separate unrelated "
        "groups generously — proximity is what tells the reader what belongs together.\n"
        "\n"
        "COLOUR. Return 3-5 palette hexes, and build them as a designer does: a DEEP "
        "ground first (near-black, tinted with the design's hue — a mid-grey or pastel "
        "ground is what makes a page look washed out), then ONE vivid high-chroma "
        "accent, then a quieter support colour. Reserve the accent for exactly one "
        "thing. Omit an element's colour unless you specifically want it off the "
        "default; a legible on-palette colour is chosen for you against whatever ends "
        "up behind that element.\n"
        "\n"
        "BACKGROUND. You choose `background.style`, not a prompt. The image prompt is "
        "written for you from the style's recipe and your own palette, so the ground "
        "always belongs to the same design as the type. The styles:\n"
        f"{background_mod.style_menu()}\n"
        "Set `background.safe_zone` to whichever side your text actually sits on — "
        "that side is held flat and empty for you. `background.motif` is optional and "
        "at most a few words: for a graphic style it only steers the shapes, and only "
        "for 'photo-scene' is it the picture itself. It names the design's SUBJECT "
        "or occasion ('a restaurant opening night', 'a loaded cheeseburger'), never "
        "the treatment — the treatment is `style`, and a motif like 'a warm abstract "
        "texture' tells the ground nothing it does not already know. Prefer a graphic "
        "style: a "
        "photograph behind type is the weakest of the options and forces a veil over "
        "the whole page to stay legible.\n"
        "\n"
        "ORNAMENT. `decor` is the layer of small marks that makes a page look made — "
        "an accent rule under the headline, a dot matrix in an empty corner, a solid "
        "panel bled off one edge, a band carrying the contact row. Pick 2-3 that suit "
        "the archetype (or leave it empty for the archetype's own defaults). You "
        "choose the marks; where they go is worked out against the finished layout.\n"
        "\n"
        "IMAGERY. Use a photo element only when the brief has a real subject to show. "
        "Every text element in your layout is drawn ON TOP OF the background — you "
        "are not choosing between text or image, you always get both, so design them "
        "to coexist:\n"
        "  - A 'photo' element in its own frame is cover-cropped into a rectangle or "
        "circle — good for a scene, a product on a surface, an establishing shot.\n"
        "  - Set cutout=true on a photo element for one specific case: a single "
        "subject (a person, an animal, a product, a mascot) meant to stand directly "
        "on the page with no visible edge or background of its own — it renders on a "
        "transparent background with no crop and no box. This is the single strongest "
        "move available to you: a hero cutout over a graphic ground, overlapping the "
        "type, is what the reference posters are built on. Use it whenever the brief "
        "has one clear subject; never for a scene or setting.\n"
        "  - A design can use more than one cutout when the brief actually has more "
        "than one subject — a product in two colourways, a duo of people, a mascot "
        "plus a small icon accent. Give each its own element with its own "
        "image_prompt and its own place in the composition; never repeat one prompt.\n"
        "  - Never ask an image prompt for text, lettering, logos, watermarks or UI — "
        "type is set as live text, never baked into a picture.\n"
        "\n"
        "ARCHETYPE. Commit to `layout_style` on purpose — it is what keeps every "
        "design from defaulting to the same centred stack. 'split-panel' in "
        "particular is built from pieces you already have: decor 'edge-block' lays "
        "the solid colour panel that carries the text, a photo or cutout fills the "
        "other half. No diagonal or custom shapes exist — only rect, circle and "
        "octagon — so build a strong composition from those, not from a shape you "
        "cannot actually have.\n"
        "\n"
        "FEATURES. When the brief lists several short, parallel items — job "
        "openings, menu items, services, amenities, included items — do not write "
        "them as one paragraph. Give EACH item its own text element with "
        "role='feature'; a bullet dot in that element's colour is added in front of "
        "it automatically, so write only the item's own text, no leading '-' or "
        "'•'. If the brief clearly implies a list like this but does not spell out "
        "the exact items (e.g. 'hiring poster for a tech startup' with no roles "
        "named), write plausible, specific ones yourself — real role or item names, "
        "not 'Feature 1'.\n"
        "\n"
        "ROLES. Two roles do more than label text. role='offer' is a short discount or "
        "deal ('SAVE 50%', '2 FOR 1') and gets a disc stamped behind it, so keep it to "
        "a few words. role='cta' gets a filled pill, so it should read as a button "
        "('ORDER NOW', 'BOOK A TABLE'). role='tagline' is the short tracked-out line "
        "under a headline.\n"
        "\n"
        "SAY IT ONCE. Every element earns its place by adding something the reader "
        "does not already have. A tagline, a subhead and an offer that all restate the "
        "same promotion are not three elements, they are one message printed three "
        "times, and the page reads as having nothing to say. If the brief gives you a "
        "single fact ('free coffee for the first 100 customers'), ONE element carries "
        "it and the others do different work: what it is, when it happens, why it is "
        "worth turning up for, what to do next. Never repeat a phrase from one element "
        "in another.\n"
        "\n"
        "FILL THE FRAME. Place elements across the whole canvas, not stacked from the "
        "top with the lower third left empty — a page whose content stops at y=0.6 "
        "looks unfinished no matter how good the top of it is. Either carry the "
        "composition to the bottom margin (a CTA, a contact line, a footer band) or "
        "put the empty space deliberately *inside* the composition where it separates "
        "two groups.\n"
        "\n"
        "COPY. You are writing this design's words, not transcribing the brief. A brief "
        "that gives you only a headline still needs a subhead or a supporting line to "
        "look designed rather than unfinished — write them, in the brief's voice, about "
        "the brief's actual subject. Never 'Lorem ipsum', never a placeholder name.\n"
        "\n"
        "The single exception is contact detail: phone, address, email and website "
        "each get their own role ('phone', 'address', 'email', 'website') and are "
        "transcribed exactly as the brief gives them, invented under no "
        "circumstances. If the brief has no phone number, the design has no phone "
        "number — omit the element. If it gives an email but not a phone, include "
        "only the email.\n"
        "\n"
        f"SCOPE. Between 4 and {MAX_ELEMENTS} elements. Two elements on a page is not a "
        "design; if you find yourself with that few, you have not written enough copy "
        "or have not used a shape or photo the composition wants."
    )


def _user_prompt(brief: DesignBrief) -> str:
    return (
        f"Brief: {brief.model_dump_json(by_alias=True, exclude_none=True)}\n"
        f"Canvas: {brief.canvas.width}x{brief.canvas.height} ({brief.kind}).\n"
        "Design this page. Use the canvas size given."
    )


def _mechanical_spec(brief: DesignBrief) -> DesignSpec:
    """No-LLM fallback: the brief's copy on a plain top-aligned poster grid."""
    copy = brief.copy_text
    contact = copy.contact
    ground = (brief.color_direction.palette or ["#101418"])[0]

    # (text, role, size) in reading order, skipping anything the brief has no value for.
    rows: list[tuple[str, str, str]] = []
    for value, role, size in (
        (copy.brand_name, "brand", "caption"),
        (copy.headline, "headline", "display"),
        (copy.subhead, "subhead", "heading"),
        (copy.body, "body", "body"),
        # `offer` gets its own role rather than being folded into the subhead, so the
        # fallback page still earns its roundel and its pill.
        (copy.offer, "offer", "body"),
        (copy.cta, "cta", "body"),
    ):
        if value and value.strip():
            rows.append((value.strip(), role, size))
    if not rows:
        rows.append((brief.subject_description or "Your headline here", "headline", "display"))

    elements: list[SpecElement] = []
    y = 0.10
    for text, role, size in rows:
        elements.append(SpecElement(
            kind="text", role=role, text=text, size=size, x=0.08, y=y, w=0.84,
            transform="uppercase" if role == "headline" else "none",
        ))
        y += 0.13 if size == "display" else 0.09

    for value, role in ((contact.phone, "phone"), (contact.address, "address"),
                        (contact.website, "website")):
        if value and value.strip():
            elements.append(SpecElement(
                kind="text", role=role, text=value.strip(), size="caption",
                x=0.08, y=min(y, 0.86), w=0.84,
            ))
            y += 0.05

    # Even with no LLM the page gets a designed ground: the vibe's own default
    # treatment, drawn from the brief's palette. The old fallback emitted a flat colour
    # whenever the brief named no subject, which is where "plain and undesigned" was
    # most visible of all.
    vibe = _VIBE_FOR.get(brief.typography.vibe, "geometric")
    background = SpecBackground(
        style=background_mod.DEFAULT_STYLE_FOR_VIBE.get(vibe, "gradient-glow"),
        color=ground,
        motif=brief.subject_description or None,
        # The mechanical grid always stacks its text from the top, so the top of the
        # frame is exactly where the background needs to stay calm.
        safe_zone="top",
    )

    return DesignSpec(
        name=(copy.headline or copy.brand_name or brief.kind).strip()[:40] or "Untitled",
        kind=brief.kind,
        width=brief.canvas.width,
        height=brief.canvas.height,
        vibe=vibe,
        palette=brief.color_direction.palette or [ground, "#FFFFFF"],
        background=background,
        elements=elements,
    )


_VIBE_FOR = {
    "geometric": "geometric",
    "humanist": "humanist",
    "serif-editorial": "serif-editorial",
    "display-bold": "display-bold",
}


def _apply_verbatim_contact(spec: DesignSpec, brief: DesignBrief) -> None:
    """Carry `Contact` through untouched, and drop any contact element the brief has
    nothing for. Same rule as `compose_ai`: a paraphrased phone number does not ring,
    and an invented one is worse than none."""
    contact = brief.copy_text.contact
    by_role = {"phone": contact.phone, "address": contact.address,
               "website": contact.website, "email": contact.email}
    kept: list[SpecElement] = []
    for element in spec.elements:
        if element.kind != "text" or element.role not in by_role:
            kept.append(element)
            continue
        value = by_role[element.role]
        if value and value.strip():
            element.text = value.strip()
            kept.append(element)
    spec.elements = kept


def _backfill_image_prompts(spec: DesignSpec, brief: DesignBrief) -> None:
    """Give every photo element something to generate, or drop it.

    The model reliably decides *that* a design wants a photo and often forgets to say
    what of — leaving a frame that compiles to an empty image box. Each unprompted
    frame takes the next subject from the brief; when the brief names no subject at
    all there is nothing to show, and an empty frame is worse than no frame.
    """
    kept: list[SpecElement] = []
    subject_index = 0
    mood = " ".join(brief.mood) or "clean, professional"
    for element in spec.elements:
        if element.kind != "photo":
            kept.append(element)
            continue
        if not (element.image_prompt or "").strip():
            subject = brief.subject_at(subject_index)
            if subject is None:
                continue
            element.image_prompt = (
                f"{subject}, {mood} lighting, professional photography"
            )
        subject_index += 1
        kept.append(element)
    spec.elements = kept


#: Roles never removed as a duplicate. A contact line is user data transcribed
#: verbatim, and the headline is the page — neither is ever the copy to throw away.
_NEVER_DEDUPED = ("phone", "address", "website", "email", "headline")

MIN_TEXT_AFTER_DEDUPE = 3
"""Never dedupe a page down past this. Below it the cure is worse than the repetition."""


def _normalised(text: str) -> str:
    """Lowercase words only — punctuation, case and spacing removed.

    'FREE FOR THE FIRST 100 CUSTOMERS!' and 'Free for the first 100 customers' are the
    same sentence, and a comparison that cannot see that catches nothing real.
    """
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _dedupe_copy(spec: DesignSpec) -> None:
    """Drop any text element that says what another one already said.

    Asked for a tagline, a subhead, an offer and a CTA about one promotion, the model
    writes the promotion four times — a real page came back carrying 'FIRST 100
    CUSTOMERS', 'Be One of the First 100', and 'FREE FOR THE FIRST 100 CUSTOMERS!'
    stacked on top of each other. Each line is fine; together they are one message
    printed three times, which reads as a page with nothing to say.

    A line goes when its words are wholly contained in another line's, since the longer
    line already carries everything the shorter one told the reader. Two lines that
    merely share a word or two are left alone — echoing a key phrase is writing, not
    repetition.
    """
    texts = [e for e in spec.elements
             if e.kind == "text" and (e.text or "").strip()]
    tokens = {id(e): set(_normalised(e.text or "").split()) for e in texts}
    budget = len(texts) - MIN_TEXT_AFTER_DEDUPE
    if budget <= 0:
        return

    dropped: set[int] = set()
    for index, element in enumerate(texts):
        if budget <= 0:
            break
        if element.role in _NEVER_DEDUPED or len(tokens[id(element)]) < 2:
            continue
        for other_index, other in enumerate(texts):
            if other is element or id(other) in dropped:
                continue
            if not tokens[id(element)] <= tokens[id(other)]:
                continue
            # Identical wording on both sides leaves nothing to choose between them on
            # information, so the one that reads first wins and the echo below it goes.
            if len(tokens[id(element)]) < len(tokens[id(other)]) or other_index < index:
                dropped.add(id(element))
                budget -= 1
                break

    if dropped:
        spec.elements = [e for e in spec.elements if id(e) not in dropped]


#: Words that name a *treatment* rather than a subject. A motif built only from these
#: is the model restating the style it already picked in `background.style`.
_STYLE_WORDS = frozenset((
    "abstract", "background", "backdrop", "blob", "brush", "colour", "color",
    "geometric", "glow", "gradient", "grunge", "halftone", "marble", "neon", "paint",
    "pattern", "shape", "shapes", "splash", "stroke", "texture", "textured", "warm",
    "cool", "dark", "light", "soft", "bold", "modern", "clean", "elegant", "vibrant",
    "a", "an", "the", "and", "with", "of", "in", "on",
))


def _is_style_restatement(motif: str) -> bool:
    """True when every word in the motif describes the treatment, not the subject."""
    words = [w for w in _normalised(motif).split() if w]
    return bool(words) and all(word in _STYLE_WORDS for word in words)


def _backfill_background_motif(spec: DesignSpec, brief: DesignBrief) -> None:
    """Point the ground at what the design is actually about.

    The motif is what ties a generated background to the occasion — the opening of a
    restaurant wants a ground built out of that, not a gradient that would have served
    a dentist equally well. Two things stop that happening on their own: the model
    leaves the field blank, or it fills it with the treatment it already chose ("a warm
    abstract brush texture"), which tells the ground nothing it did not already know
    from `background.style`. Both are replaced by the brief's real subject, and for a
    graphic style it still only steers shape and colour (`background._motif_clause`)
    rather than being drawn literally.
    """
    if spec.background.style == "flat":
        return
    motif = (spec.background.motif or "").strip()
    if motif and not _is_style_restatement(motif):
        return
    hint = (brief.subject_description or spec.name or "").strip()
    if hint:
        spec.background.motif = hint[:80]


def _backfill_features(spec: DesignSpec, brief: DesignBrief) -> None:
    """Make sure every explicit bullet point in the brief actually appears.

    The model is told to give each list item its own `role='feature'` element, but a
    brief's `features`/`tags` are the one part of this pipeline that is genuinely
    user-authored data (a menu, a set of job openings) rather than something the
    model is free to phrase — so if it dropped or merged any of them into a
    paragraph, they are added back explicitly rather than trusted to have survived.
    """
    # `tags` deliberately excluded: those are short keyword chips (a tech stack, a
    # hashtag row), not sequential list items, and turning them into bulleted rows
    # duplicated real content with junk like a literal "hiring" or "career" bullet.
    items = list(brief.copy_text.features)
    if not items:
        return
    existing = {e.text.strip().lower() for e in spec.elements
               if e.kind == "text" and e.role == "feature" and e.text}
    missing = [item for item in items if item.strip().lower() not in existing]
    if not missing:
        return
    start_y = 0.5
    if spec.text_elements():
        start_y = max((e.y for e in spec.elements if e.kind == "text"), default=0.5) + 0.08
    for i, item in enumerate(missing):
        spec.elements.append(SpecElement(
            kind="text", role="feature", text=item.strip(), size="body",
            x=0.12, y=min(0.9, start_y + i * 0.07), w=0.76,
        ))


async def design_spec(brief: DesignBrief) -> tuple[DesignSpec, bool]:
    """Returns the spec and whether an LLM produced it (False => mechanical fallback)."""
    try:
        result = await get_llm().complete_json(
            system=_system_prompt(), user=_user_prompt(brief), schema=DesignSpec,
            temperature=0.7, max_tokens=8192,
        )
        spec = result.parsed
    except (AdapterError, ValueError):
        spec = _mechanical_spec(brief)
        _apply_verbatim_contact(spec, brief)
        _backfill_image_prompts(spec, brief)
        _backfill_features(spec, brief)
        _backfill_background_motif(spec, brief)
        _dedupe_copy(spec)
        return spec, False

    # The model is free with the canvas; the brief is not a suggestion.
    spec.width, spec.height = brief.canvas.width, brief.canvas.height
    spec.elements = spec.elements[:MAX_ELEMENTS]
    if not spec.text_elements():
        spec.elements = _mechanical_spec(brief).elements
    _apply_verbatim_contact(spec, brief)
    _backfill_image_prompts(spec, brief)
    _backfill_features(spec, brief)
    _backfill_background_motif(spec, brief)
    # Last, so it sees the backfilled features too: a bullet that merely restates the
    # subhead is the same repetition arriving by another door.
    _dedupe_copy(spec)
    return spec, True
