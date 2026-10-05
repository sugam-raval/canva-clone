"""Step 1 of designing from a prompt: the ART DIRECTOR.

One fast LLM call reads the brief and writes a short design plan — what goes in (the
exact copy, how many photos and what each shows, logo or not), what must stay out
(prices, badges…), the mood, which Lido features fit that mood, and which layout from
the catalogue (library/layouts.yaml) to build — or a custom one. The designer
(`brief.py`) then builds exactly that plan, and the checks hold it to it.

The art director reads the mood map (library/moods.yaml) so users never need to know
feature names, and the last designs' fingerprints so it picks something different.
"""

from __future__ import annotations

import random
import re
from typing import Literal

import structlog
from pydantic import BaseModel

from app.lido_create import library
from app.lido_create.backdrops import STYLES as ENABLED_BACKDROPS
from app.lido_create.backdrops import Backdrop
from app.lido_create.backdrops import clean as clean_backdrop
from app.lido_create.catalog import CLIPS, MAX_PHOTOS, layout_menu, layouts, mood_guide, moods
from app.lido_create.check import CURRENCY
from app.lido_create.kit import (
    ENABLED_DRAW,
    ENABLED_EFFECTS,
    ENABLED_FRAMES,
    ENABLED_SHAPES,
    THEMES,
    default_photo_shape,
)
from app.lido_create.lists import MAX_ITEMS
from app.lido_create.models import describe, plan_call
from app.lido_create.shapes import frames

log = structlog.get_logger(__name__)

FREE_SHARE = 0.25  # this share of designs ignores the catalogue and invents a layout

TextRole = Literal["headline", "subhead", "kicker", "body", "item", "cta", "badge", "price",
                   "date", "caption", "website", "phone", "email", "address"]
Exclusion = Literal["price", "offer_badge", "discount", "promo_claims", "button",
                    "contact", "logo"]
ThemeName = Literal[tuple(t.name for t in THEMES)]  # type: ignore[valid-type]
MoodName = Literal[tuple(moods())]  # type: ignore[valid-type]


class PlanText(BaseModel):
    role: TextRole
    text: str


class PlanPhoto(BaseModel):
    from_brief: str  # the exact words in the brief that ask for this photo
    subject: str  # one sentence: exactly what this photo shows
    role: Literal["hero", "supporting"]
    frame: str  # a frame (library/frames.yaml) or a crop (library/crops.yaml)
    # the frame's shape on the canvas (a frame name keeps its own): photos start
    # rendering at it while the designer works, so the designer keeps to it
    orientation: Literal["square", "portrait", "landscape"] = "square"


WIDE_FRAME = 1.4  # w / h above which a frame is too wide for 3-4 photos to share a canvas

# w / h of each orientation: what the designer is asked for and photos are rendered at
ORIENTATION_ASPECT = {"square": 1.0, "portrait": 0.75, "landscape": 4 / 3}


class DesignPlan(BaseModel):
    texts: list[PlanText]
    photos: list[PlanPhoto]
    logo: bool
    exclude: list[Exclusion]
    moods: list[MoodName]
    layout: str  # a catalogue layout name, or "custom"
    custom_layout: str | None  # the structure in 1-2 sentences, when layout is "custom"
    shapes: list[str]  # Lido shape names that fit the mood
    draw: list[str]  # hand-drawn stroke presets that fit the mood (may be empty)
    effects: list[str]  # text effects that fit (may be empty)
    gradient: str | None  # how to use a gradient, or null for none
    photo_theme: ThemeName
    notes: str  # the art direction in 1-2 sentences: spacing, weight, attitude
    backdrop: Backdrop | None = None  # a layered gradient background, or null
    contact_icons: bool = True  # a small icon beside each website/phone/email/address


SYSTEM = f"""You are the ART DIRECTOR of a design studio. You read a client's brief for ONE
square social-media post template and write a short, precise DESIGN PLAN that a designer
will build. You do not place anything on the canvas — you decide WHAT and HOW.

DECIDE
1. texts — every piece of copy the brief asks for, word for word (fix obvious typos).
   Roles: headline (exactly one), subhead, kicker, body, item (one per list item — keep
   EVERY item the brief lists, up to 9, never trim the list),
   cta, badge, price, date, caption, website, phone, email, address. Keep it short: a
   template holds short lines. If the brief gives no headline, write one. Add a cta
   unless the brief rules buttons out. Add contact placeholders (www.yourwebsite.com)
   only if the brief asks for contact details.
2. photos — how many photos the brief really needs, 1 to {MAX_PHOTOS}. The default is ONE
   hero photo. Add a photo only for each further distinct thing the brief names to SHOW
   (three different things named = 3; "X and Y" = 2; before and after = 2; a list of
   five items = 4, the most). Never pad with extra mood shots, detail close-ups or "in
   use" photos the brief didn't ask for: one thing to show = 1 photo. More things than {MAX_PHOTOS} → {MAX_PHOTOS}
   (or 1 group shot). Each photo gets from_brief — the exact words copied from the brief
   that ask for it (the brief's own name for that thing, copied as written) — its own
   subject sentence (who or what, action, setting, light), a frame and an orientation
   (square | portrait | landscape — the shape that frame takes in your layout: a tall
   side column is portrait, a wide band landscape). With 3 or 4 photos they share the
   canvas: use square or portrait shapes and no wide frames (rounded_card, oval,
   brush_stroke, brush_swoosh) — four wide photos side by side are too small to read;
   lay them out as a grid, a stagger or a column. Exactly one photo is the
   hero, the rest supporting. A supporting photo whose words are not in the brief is
   removed.
3. logo — true unless the brief explicitly says no logo / no branding.
4. exclude — what the brief forbids or what would be wrong: "no prices" → price;
   "no offers/discounts/promotional claims" → offer_badge, discount, promo_claims;
   no contact info wanted → contact; "no logo" → logo; no call to action → button.
5. moods — 1 or 2 moods from the MOOD GUIDE. Moods are styles, not industries: choose by
   the FEELING the brief asks for (its adjectives, its tone, its audience), never by what
   the business sells — any business can use any mood. When the brief
   names no feeling, pick the one that best serves its goal and audience.
6. features — from the chosen moods: a frame per photo (from that mood's frames; give
   different photos different but related frames), shapes, draw strokes, effects and a
   gradient idea. Respect the mood's "avoid". Use names exactly as listed.
7. layout — a catalogue layout whose photo range includes YOUR photo count (check the
   numbers in brackets), that fits the brief, avoiding
   the recently used ones listed below; or "custom" with custom_layout describing a new
   structure in 1-2 sentences.
8. photo_theme — the closest theme ({", ".join(t.name for t in THEMES)}) for placeholder
   photos.
9. notes — 1-2 sentences of art direction (spacing, weight, attitude).
10. backdrop — a layered gradient background from the chosen mood's backdrops: style;
   side (split_half: left/right/top/bottom; diagonal_split and horizon_arc: top/bottom;
   corner_glow: left/right; spotlight: center/left/right/top/bottom); angle 10-30 (the
   tilt of diagonals, negative tilts the other way); split 0.35-0.65 (where the split,
   bands or arc sit); tone accent | soft. Most designs gain depth from one; use null for
   a plain canvas when the mood lists no backdrops or the brief wants it minimal.
11. contact_icons — true (a small icon beside each website/phone/email/address line)
   unless the brief asks for no icons.

LAYOUT CATALOGUE
{{menu}}

MOOD GUIDE
{{moods}}

NAMES YOU MAY USE (only these — anything else is not available)
frames: {", ".join(ENABLED_FRAMES) or "none"} | crops: {", ".join(CLIPS) or "none"}{
    " (cutout = a transparent subject with no frame, e.g. a product)" if "cutout" in CLIPS
    else ""}
shapes: {", ".join(ENABLED_SHAPES) or "none"}
draw: {", ".join(ENABLED_DRAW) or "none — leave draw empty"}
effects: {", ".join(ENABLED_EFFECTS) or "none — leave effects empty"}
backdrops: {"; ".join(f"{k} = {library.hint('backdrops', k)}" for k in ENABLED_BACKDROPS)
            or "none — backdrop is always null"}
"""


_WORD = re.compile(r"[a-z0-9]{3,}")


def _asked_for(quote: str, brief: str) -> bool:
    """Do the quoted words really appear in the brief? (Every word of 3+ letters must,
    so a paraphrase like "close-up of the cream being applied" doesn't pass.)"""
    words = _WORD.findall(quote.lower())
    have = set(_WORD.findall(brief.lower()))
    return bool(words) and all(w in have for w in words)


def _clean(plan: DesignPlan, brief: str = "") -> DesignPlan:
    """Drop names that don't exist and enforce the limits, so a slip by the model
    can't break the designer. With the `brief`, supporting photos the brief never
    asked for (padding) are dropped."""
    if brief and plan.photos:
        hero = next((p for p in plan.photos if p.role == "hero"), plan.photos[0])
        kept, seen = [], set()
        for p in [hero, *[q for q in plan.photos if q is not hero]]:
            key = " ".join(_WORD.findall(p.from_brief.lower()))
            # a quote listing several things ("before and after") may back several photos
            listing = bool(re.search(r",| and | & | or ", p.from_brief.lower()))
            if p is not hero and (not _asked_for(p.from_brief, brief)
                                  or (key in seen and not listing)):
                continue
            seen.add(key)
            kept.append(p)
        if len(kept) < len(plan.photos):
            log.info("lido.plan.padding_dropped", asked=len(plan.photos), kept=len(kept))
        plan.photos = kept
    known_frames = set(ENABLED_FRAMES) | set(CLIPS)  # what library/ switches on
    plan.photos = plan.photos[:MAX_PHOTOS] or plan.photos
    for p in plan.photos:
        if p.frame not in known_frames:
            p.frame = default_photo_shape()
    # PHOTO LIMIT: written for up to 4 photos; revisit for 5+ (see catalog.py)
    if len(plan.photos) >= 3:  # several photos share the canvas: none of them wide
        for p in plan.photos:
            frame = frames().get(p.frame)
            if frame is not None and frame.aspect > WIDE_FRAME:
                log.info("lido.plan.wide_frame_swapped", frame=p.frame, photos=len(plan.photos))
                p.frame = default_photo_shape()
            if p.orientation == "landscape":
                p.orientation = "square"
    if not any(p.role == "hero" for p in plan.photos) and plan.photos:
        plan.photos[0].role = "hero"
    plan.shapes = [s for s in plan.shapes if s in ENABLED_SHAPES]
    plan.draw = [d for d in plan.draw if d in ENABLED_DRAW]
    plan.effects = [e for e in plan.effects if e in ENABLED_EFFECTS]
    if brief and CURRENCY.search(brief) and "price" in plan.exclude:
        plan.exclude.remove("price")  # the brief gives a price: it can't rule prices out
    if plan.backdrop is not None:  # a style library/backdrops.yaml switched off: none
        plan.backdrop = (clean_backdrop(plan.backdrop)
                         if plan.backdrop.style in ENABLED_BACKDROPS else None)
    if plan.layout != "custom" and plan.layout not in layouts():
        plan.layout, plan.custom_layout = "custom", plan.custom_layout or plan.layout
    if any(t.role == "cta" for t in plan.texts) and "button" in plan.exclude:
        plan.exclude.remove("button")  # the brief asked for a call to action: keep it
    if not plan.logo and "logo" not in plan.exclude:
        plan.exclude.append("logo")
    if "logo" in plan.exclude:
        plan.logo = False
    items = [t for t in plan.texts if t.role == "item"]
    if len(items) > MAX_ITEMS:  # more than a post can hold: keep the first nine
        drop = {id(t) for t in items[MAX_ITEMS:]}
        plan.texts = [t for t in plan.texts if id(t) not in drop]
    if not any(t.role == "headline" for t in plan.texts) and plan.texts:
        plan.texts[0].role = "headline"
    return plan


_LIST_SUITS = {"list", "prices", "options", "services", "information", "collection",
               "catalogue", "steps", "process"}


def _best_fitting(plan: DesignPlan, prompt: str, avoid: list[str], rng: random.Random) -> str:
    """A catalogue layout for the plan's photo count, preferring ones whose `suits`
    words appear in the brief (and list-friendly ones when there is a list)."""
    words = set(_WORD.findall(prompt.lower()))
    has_list = sum(t.role == "item" for t in plan.texts) >= 4

    def score(name: str) -> tuple:
        lay = layouts()[name]
        hits = sum(1 for s in lay.suits if set(_WORD.findall(s.lower())) <= words)
        listy = has_list and bool(_LIST_SUITS & {s.lower() for s in lay.suits})
        return (name not in avoid, listy, hits, rng.random())

    fitting = [n for n, lay in layouts().items() if lay.fits(len(plan.photos))]
    return max(fitting, key=score) if fitting else "custom"


def fingerprint(plan: DesignPlan) -> str:
    """One notebook line: enough to tell the next design what to avoid."""
    feats = [f"frames {'/'.join(sorted({p.frame for p in plan.photos}))}"]
    if plan.gradient:
        feats.append("gradient")
    feats += plan.draw[:2] + plan.effects[:1]
    if plan.backdrop:
        feats.append(f"backdrop {plan.backdrop.style}")
    return f"{plan.layout} ({len(plan.photos)} photos; {', '.join(feats)})"


async def make_plan(prompt: str, *, recent: list[str], avoid_layouts: list[str] | None = None,
                    free: bool | None = None, rng: random.Random | None = None) -> DesignPlan:
    """The art director's plan for `prompt`. `recent` are fingerprints of the latest
    designs (the notebook); `avoid_layouts` the layouts other variations of this same
    request already took; `free` forces (or forbids) inventing a custom layout."""
    from app.adapters.registry import llm as get_llm
    from app.lido_create.brief import _ask

    rng = rng or random.Random()
    free = rng.random() < FREE_SHARE if free is None else free
    system = SYSTEM.replace("{menu}", layout_menu()).replace("{moods}", mood_guide())
    avoid = list(dict.fromkeys((avoid_layouts or []) + [r.split(" ")[0] for r in recent]))
    user = (f'CLIENT BRIEF:\n"""\n{prompt.strip()}\n"""\n\n'
            + ("Recently made (choose something different):\n- " + "\n- ".join(recent)
               + "\n\n" if recent else "")
            + (f"Layouts already taken by other versions of this request: "
               f"{', '.join(avoid_layouts)}.\n\n" if avoid_layouts else "")
            + ("FREE DESIGN: do NOT use the catalogue — set layout to \"custom\" and invent a "
               "fresh structure in custom_layout that suits this brief.\n\n" if free
               else f"Prefer a catalogue layout not in: {', '.join(avoid) or 'none'}.\n\n")
            + "Write the design plan.")
    options = plan_call()
    reply = await _ask(get_llm(), system=system, user=user, schema=DesignPlan,
                       temperature=0.8, max_tokens=6000, **options)
    plan = _clean(reply.parsed, prompt)
    if free:
        plan.layout = "custom"
    elif plan.layout != "custom" and not layouts()[plan.layout].fits(len(plan.photos)):
        # the model picked a layout for a different photo count: swap in one that fits
        log.info("lido.plan.layout_swapped", picked=plan.layout, photos=len(plan.photos))
        plan.layout = _best_fitting(plan, prompt, avoid, rng)
    log.info("lido.plan", layout=plan.layout, photos=len(plan.photos), moods=plan.moods,
             logo=plan.logo, exclude=plan.exclude, model=describe(options))
    return plan


def plan_brief(plan: DesignPlan) -> str:
    """The plan as the designer reads it."""
    lay = layouts().get(plan.layout)
    structure = (f"{plan.layout}: {lay.idea}" if lay else
                 f"custom: {plan.custom_layout or 'invent a structure that suits the brief'}")
    mood_lines = []
    for name in plan.moods:
        m = moods()[name]
        mood_lines.append(f"{name} — feel: {m.feel}; avoid: {m.avoid}")
    photos = "\n".join(
        f"  {i}. {p.role}: {p.subject} — frame: {p.frame}"
        + ("" if p.frame in frames() else
           f", {p.orientation} (w/h about {ORIENTATION_ASPECT[p.orientation]:.2f})")
        for i, p in enumerate(plan.photos, 1))
    texts = "\n".join(f"  - {t.role}: {t.text!r}" for t in plan.texts if t.role != "item")
    items = [t.text for t in plan.texts if t.role == "item"]
    if items:
        n = len(items)
        shape = ("one column" if n <= 4 else "2 columns of 3" if n <= 6
                 else "3 columns of 3 (or 2 columns if the area is narrow)")
        texts += (f"\n  - list of {n} items — put ALL of them in ONE list element "
                  f"(it lays them out as {shape}): {items!r}")
    feats = [f"shapes: {', '.join(plan.shapes)}" if plan.shapes else "",
             f"hand-drawn: {', '.join(plan.draw)}" if plan.draw else "",
             f"text effects: {', '.join(plan.effects)}" if plan.effects else "",
             f"gradient: {plan.gradient}" if plan.gradient else ""]
    return (
        "DESIGN PLAN (from the art director — build exactly this)\n"
        f"- Layout: {structure}\n"
        f"- Photos: exactly {len(plan.photos)}, each in its frame (frame = the photo's "
        f"`frame` field when it is a frame name, otherwise its `clip`) and with its "
        f"shape (its picture is already being made at that shape):\n{photos}\n"
        f"- Text, use these exact words (roles map to text_type; price/date → badge, "
        f"subhead → body):\n{texts}\n"
        f"- Logo: {'one small logo' if plan.logo else 'NONE — no logo element at all'}\n"
        f"- Mood: {'; '.join(mood_lines)}\n"
        f"- Features to use: {'; '.join(f for f in feats if f) or 'your choice'}\n"
        f"- Do NOT add: {', '.join(plan.exclude) or 'nothing excluded'}\n"
        f"- Art direction: {plan.notes}"
        + ("\n- Contact icons: a small icon is added beside each website/phone/email/"
           "address line — leave about 50px free to the left of those lines"
           if plan.contact_icons else ""))
