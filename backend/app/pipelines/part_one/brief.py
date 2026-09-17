"""`brief.parse` — IMPLEMENTATION_PLAN §1.1.

Turns a messy human prompt (plus an optional brand kit) into a strict `DesignBrief`.
This is the only stage allowed to ask the user a question.

Three tiers, in order:
  1. one schema-constrained LLM call at temperature 0.2
  2. one repair round-trip with the validation errors appended
  3. a heuristic parser (regex for sizes, keyword map for kind)

Tier 3 is not dead code: it runs whenever no LLM is configured, and it is what keeps
the product alive when the model provider is down.
"""

from __future__ import annotations

import math
import re

import structlog

from app.adapters.base import AdapterError
from app.adapters.registry import llm as get_llm
from app.schema.brief import (
    KIND_DEFAULT_SIZE,
    BriefCanvas,
    ColorDirection,
    Contact,
    Copy,
    DesignBrief,
    LayoutHints,
    Typography,
)
from app.util.palette import complete_palette, order_palette, resolve_palette_words

log = structlog.get_logger(__name__)

SYSTEM_PROMPT = """\
You turn a short design request into a strict DesignBrief JSON object.

CANVAS SIZE
- Infer `canvas` from `kind` unless the user states a size. Defaults:
  story 1080x1920, post 1080x1350, square 1080x1080, poster 2480x3508,
  banner 1500x500, thumbnail 1280x720, ad 1200x628, flyer 1654x2339.
- If the user gives explicit pixel dimensions or a named aspect ratio, honour it exactly.
- `kind` and `canvas` must agree. "Poster" and "flyer" mean a PRINTED sheet; if the
  request is for a screen — a named aspect like 4:5 or 9:16, or a platform like
  Instagram, Facebook or LinkedIn — then `kind` is `post`, `story`, `ad` or `banner`
  however the user described it. A layout authored for A4 laid out on a 4:5 canvas has
  every vertical relationship wrong, so the word the user reached for must not override
  the shape they asked for.

COPY
- If the user supplied copy in quotes, use it VERBATIM in the matching field. Never
  paraphrase, re-case, shorten or "improve" the user's own words.
- If they supplied no copy, write it. A headline is at most 5 words and must be
  concrete. Do not write filler like "Your Text Here" or "Lorem ipsum".
- Leave a copy field null if that slot genuinely is not wanted. Do not invent a CTA for
  a design that is not selling anything.

OFFER, PRICE AND FINE PRINT
- A promotional request is mostly these fields, and they are NOT the headline. Split them
  out: `offer` is the deal itself ("Flat 50% Off", "Buy 1 Get 1"), `price` is a figure
  ("Rs 499", "from $29"), `badge` is the handful of characters that fit inside a stamp
  ("50% OFF", "SALE"), `terms` is validity and fine print ("*T&C apply. Valid till 30 Sep").
- `eventDetails` is date, time and venue on one line, for an opening, a class, a gig.
- `features` is the short bulleted list a design carries when it is selling several
  things at once — services, inclusions, menu items, package contents. Three to six
  entries, at most about 30 characters each. Leave it empty when the design has one
  message.
- `tags` is a SEPARATE, shorter list of keyword chips, one or two words each, at most
  about 16 characters — a technology stack, a skill set, an ingredient list, amenities, a
  set of hashtags. Up to eight entries. Do not mix these into `features`: "2+ years
  experience" is a feature, "Python" is a tag. A request naming both a set of full
  requirement lines and a set of short keywords needs both fields filled, not one merged
  list with everything the design asked to keep distinct rendered as the same line.
- Derive `badge` from the offer when the user gave one and no separate stamp text.
- `brandName` is whose design this is — the studio, clinic, shop or brand the user named
  ("Sunrise Yoga", "Patel Dental"). Copy it as they wrote it and do not invent one: a
  design captioned with a business that does not exist is worse than an unbranded one.

CONTACT DETAILS — TRANSCRIBE, NEVER WRITE
- Put every phone number, email address, website, street address and social handle the
  user gave into `copy.contact`, character for character as they typed it.
- NEVER invent one. A phone number nobody gave you is worse than no phone number: the
  design ships looking finished and the number is wrong. If the user gave none, leave
  every contact field null.
- A business design that names a phone number or a website almost always wants it shown.
  Do not decide it is clutter and drop it.

SUBJECT
- `subjectDescription` describes the one physical thing the design is about, phrased for
  an image generator ("a white and amber running shoe, three-quarter view").
- Assume the design HAS a subject. Almost every real request has one, even when the user
  never names it: a jewellery sale wants jewellery, a cafe opening wants coffee, a gym
  promo wants equipment, a Diwali greeting wants a diya. Infer the obvious physical
  thing the design is about and describe it concretely.
- Where the user names a category rather than an object, pick the single most
  photographable member of it ("a jewellery brand" -> "a gold necklace with a fine chain,
  arranged on dark velvet, three-quarter view").
- Set it to null ONLY when the user explicitly asks for text only, a quote card, a
  typographic treatment, or names no subject matter of any kind. A null subject cuts the
  design down to type on a flat colour, so do not choose it by default.
- If the design should show several of the thing — a range, a collection, three
  colourways, a menu — say so in the description ("three colourways of ..."). The layout
  corpus has multi-subject skeletons and this is how they get chosen.
- When the user names SEVERAL DIFFERENT things ("burgers, fries and shakes", "facial,
  manicure and massage"), put the first in `subjectDescription` and each of the others in
  `subjects`, one entry per thing, each phrased for an image generator the same way. Each
  entry becomes its own generated cutout, so a list of three arrives as three distinct
  objects instead of the same object printed three times. Leave `subjects` empty when the
  design is about one thing.

DENSITY
- Set `layoutHints.density` to "dense" when the request carries a lot to say — an offer
  plus features plus contact details, a menu, a services list, an event with times and a
  venue. Dense selects layouts built to hold that much copy; leaving it "balanced" selects
  a layout with three slots and the rest of the user's content is dropped on the floor.
- Use "sparse" only for a deliberately minimal design.

COLOUR WORDS
- When the user names colours, put them in `colorDirection.palette` as the words they
  used ("gold", "deep blue") or as hex if they gave hex. Do not translate a colour word
  into hex yourself and do not rank them — ordering is decided downstream.

COLOUR AND TYPE
- `colorDirection.mode` is "brand" only when a brand kit was provided, "from-prompt"
  when the user named colours, otherwise "auto".
- Pick `typography.vibe` from the design's tone: geometric (modern, tech, clean),
  humanist (friendly, editorial, approachable), serif-editorial (luxury, classic,
  magazine, and any festival, religious or ceremonial occasion — Diwali, Eid,
  Christmas, weddings — where display serifs carry the tone), display-bold (loud,
  sporty, promotional).

LANGUAGE
- Detect the language of the user's copy and set `language` to its BCP-47 tag. This
  drives font selection and text shaping, so getting it wrong breaks non-Latin scripts.

CLARIFICATION
- Set `needsClarification` ONLY when guessing wrong would waste real image-generation
  spend — essentially only when neither a canvas size nor a design kind can be inferred
  at all. At most one question, with 2-4 tappable options. In every other case, proceed
  with sensible defaults and let the user edit afterwards.
"""


def _user_message(prompt: str, brand_kit: dict | None, count: int) -> str:
    parts = [f"Design request:\n{prompt.strip()}"]
    if brand_kit:
        parts.append(
            "\nBrand kit (overrides palette, fonts and tone):\n"
            f"- palette: {brand_kit.get('palette')}\n"
            f"- fonts: {[f.get('family') for f in brand_kit.get('fonts', [])]}\n"
            f"- tone: {brand_kit.get('tone')}"
        )
    if count > 1:
        parts.append(f"\nThe user wants {count} layout variations of this same brief.")
    return "\n".join(parts)


async def parse_brief(prompt: str, *, brand_kit: dict | None = None,
                      count: int = 1) -> tuple[DesignBrief, int]:
    """Return (brief, cost_cents). Never raises — falls back to heuristics."""
    llm = get_llm()
    user = _user_message(prompt, brand_kit, count)
    worth_repairing = True

    try:
        result = await llm.complete_json(
            system=SYSTEM_PROMPT, user=user, schema=DesignBrief, temperature=0.2,
        )
        brief = _apply_brand_kit(result.parsed, brand_kit)
        return _sanitise(brief, prompt), result.cost_cents
    except AdapterError as exc:
        # An unrecoverable error (no key, refusal) will fail identically on retry.
        worth_repairing = exc.recoverable
        log.warning("brief.parse.llm_failed", error=str(exc), retrying=worth_repairing)

    # One repair round-trip, then heuristics.
    try:
        if not worth_repairing:
            raise AdapterError("skipping repair: first failure was unrecoverable",
                               recoverable=False)
        result = await llm.complete_json(
            system=SYSTEM_PROMPT,
            user=user + "\n\nYour previous reply could not be used. Return only a valid "
                        "DesignBrief object matching the schema exactly.",
            schema=DesignBrief, temperature=0.0,
        )
        brief = _apply_brand_kit(result.parsed, brand_kit)
        return _sanitise(brief, prompt), result.cost_cents
    except AdapterError as exc:
        log.warning("brief.parse.repair_failed", error=str(exc))

    log.info("brief.parse.heuristic_fallback")
    return _sanitise(_apply_brand_kit(heuristic_brief(prompt), brand_kit), prompt), 0


# --------------------------------------------------------------------------------------
# Heuristic parser (§1.1 tier 3)
# --------------------------------------------------------------------------------------

_KIND_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("story", ("story", "stories", "reel", "tiktok", "9:16", "vertical video")),
    ("thumbnail", ("thumbnail", "youtube", "16:9 thumb")),
    ("banner", ("banner", "header", "cover", "billboard", "leaderboard")),
    ("poster", ("poster", "print", "a3", "a2", "wall")),
    ("flyer", ("flyer", "leaflet", "handout", "a5")),
    ("ad", ("ad ", "advert", "advertisement", "campaign", "facebook ad", "google ad")),
    ("post", ("post", "instagram", "linkedin", "social", "feed", "square")),
]

_MOOD_KEYWORDS = {
    "minimal": ("minimal", "clean", "simple", "understated", "whitespace"),
    "premium": ("premium", "luxury", "elegant", "high-end", "sophisticated"),
    "bold": ("bold", "loud", "punchy", "striking", "dramatic"),
    "playful": ("playful", "fun", "quirky", "friendly", "cheerful"),
    "high-contrast": ("high contrast", "high-contrast", "stark"),
    "warm": ("warm", "cosy", "cozy", "inviting"),
    "dark": ("dark", "moody", "night", "noir"),
    "retro": ("retro", "vintage", "80s", "90s", "nostalgic"),
    "natural": ("natural", "organic", "earthy", "eco"),
    "tech": ("tech", "futuristic", "digital", "cyber"),
    # Festivals and ceremonies are a large share of real requests and none of the moods
    # above catch them, so they used to fall through to the "clean" default and take
    # geometric sans type. They want ceremonial typography and a rich ground.
    "festive": (
        "festival", "festive", "celebration", "celebrate", "greeting", "wishes",
        "diwali", "deepavali", "holi", "navratri", "dussehra", "dasara", "durga puja",
        "ganesh", "chaturthi", "janmashtami", "raksha bandhan", "rakhi", "pongal",
        "onam", "ugadi", "gudi padwa", "baisakhi", "lohri", "sankranti", "puja",
        "eid", "ramadan", "ramzan", "bakrid", "muharram", "hanukkah", "christmas",
        "xmas", "easter", "thanksgiving", "lunar new year", "new year", "nowruz",
        "wedding", "anniversary", "engagement", "shubh", "mangal",
    ),
}

# Checked in order, so the more specific mood wins over a generic one that happens to
# co-occur ("a clean, festive Diwali poster" is festive first).
_VIBE_FOR_MOOD = {
    "festive": "serif-editorial",
    "premium": "serif-editorial",
    "retro": "serif-editorial",
    "bold": "display-bold",
    "high-contrast": "display-bold",
    "playful": "humanist",
    "natural": "humanist",
}

# Phrases that explicitly rule out a photographic subject. Getting this wrong is
# expensive in both directions: a spurious subject spends money generating an image
# nobody asked for, a missing one leaves a hole in the layout.
_NO_SUBJECT_RE = re.compile(
    r"\b(?:no|without|zero)\s+(?:photo|photos|photograph\w*|image|images|imagery|"
    r"picture|pictures|product|subject)\b|\btext[\s-]?only\b|\btype[\s-]?only\b|"
    r"\btypographic\b|\bjust\s+text\b|\bquote\s+(?:card|post|graphic)\b",
    re.IGNORECASE)

_SQUARE_RE = re.compile(r"\bsquare\b|\b1\s*:\s*1\b", re.IGNORECASE)

_SIZE_RE = re.compile(r"(\d{2,5})\s*(?:x|×|by)\s*(\d{2,5})", re.IGNORECASE)
_RATIO_RE = re.compile(r"\b(\d{1,2})\s*:\s*(\d{1,2})\b")

# Quoted phrases, matched with the OPENING and CLOSING mark paired by style rather than
# any-quote-to-any-quote. A single shared character class (the previous approach) treats
# a right single quotation mark and a plain apostrophe as the same character, so
# "WE'RE HIRING!" — a contraction, not a quote — closes the match after two letters:
# "WE". Pairing straight-with-straight and curly-with-curly avoids that; each alternative
# still supports whichever quote character the user's editor produced. `findall` on this
# pattern returns one tuple per match with the phrase in whichever group fired, so callers
# use `_find_quoted` rather than the raw method.
_QUOTED_RE = re.compile(
    r'"([^"]{2,120})"|“([^”]{2,120})”|\'([^\']{2,120})\'|‘([^’]{2,120})’')


def _find_quoted(text: str) -> list[str]:
    return ["".join(groups) for groups in _QUOTED_RE.findall(text)]


# Labelled copy, e.g. `cta "Shop now"` or `headline: "Run Lighter"`. Users write this
# constantly, and dropping the label puts every quoted string into the headline. Quote
# pairing follows the same style-matched rule as `_QUOTED_RE` and for the same reason.
_LABELLED_COPY_RE = re.compile(
    r"\b(headline|header|title|heading|subhead|subtitle|subheading|body|paragraph|"
    r"cta|button|caption|tagline|label)\b\s*(?:is|=|:|reading|that says|saying)?\s*"
    r'(?:"([^"]{1,160})"|“([^”]{1,160})”|\'([^\']{1,160})\'|‘([^’]{1,160})’)',
    re.IGNORECASE)

# Contact details and offers, extracted mechanically. These are the parts of a prompt
# that must survive character for character, so they are pulled out by pattern rather
# than left to a model that will happily round a phone number or restyle a URL.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
_URL_RE = re.compile(
    r"\b(?:https?://|www\.)[^\s,;]+|\b[\w-]{2,}\.(?:com|co|in|net|org|io|shop|store|"
    r"co\.uk|com\.au)\b(?:/[^\s,;]*)?", re.IGNORECASE)
_SOCIAL_RE = re.compile(r"(?<![\w@])@[A-Za-z][\w.]{2,29}\b")
# Deliberately loose about separators and country codes, deliberately strict about
# length: 7-15 digits is the E.164 range, and anything shorter is a price or a year.
_PHONE_RE = re.compile(
    r"(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d[\d\s.-]{5,16}\d")
_PHONE_CUE_RE = re.compile(
    r"\b(?:call|phone|ph|tel|telephone|mobile|mob|contact|whatsapp|dial|ring)\b"
    r"[\s:.-]*(?:us|now|at|on)?[\s:.-]*", re.IGNORECASE)
_DISCOUNT_RE = re.compile(
    r"\b(?:flat\s+|upto\s+|up\s+to\s+|extra\s+)?\d{1,2}\s*%\s*(?:off|discount)?\b|"
    r"\bbuy\s*\d\s*get\s*\d\s*(?:free)?\b|\bbogo\b", re.IGNORECASE)
# Leading qualifiers that belong on the offer line but not inside a seal. Anchored at
# the start on purpose: "get" mid-phrase is load-bearing, and trimming it turns
# "buy 1 get 1" into "buy 1 1".
_BADGE_TRIM_RE = re.compile(
    r"^(?:flat|upto|up\s+to|extra|save)\s+|\s+discount$", re.IGNORECASE)
_PRICE_RE = re.compile(
    r"(?:(?:starting|from|only|just|at)\s+)?(?:rs\.?|inr|₹|\$|£|€)\s?\d[\d,]*"
    r"(?:\.\d{1,2})?(?:\s*(?:onwards|only|/-))?", re.IGNORECASE)

_COPY_FIELD_FOR_LABEL = {
    "headline": "headline", "header": "headline", "title": "headline",
    "heading": "headline", "tagline": "headline",
    "subhead": "subhead", "subtitle": "subhead", "subheading": "subhead",
    "body": "body", "paragraph": "body",
    "cta": "cta", "button": "cta",
    "caption": "caption", "label": "caption",
}


def heuristic_brief(prompt: str) -> DesignBrief:
    """Deterministic, no model. Deliberately conservative: it never invents copy."""
    text = prompt.lower()

    kind = "post"
    for candidate, keywords in _KIND_KEYWORDS:
        if any(k in text for k in keywords):
            kind = candidate
            break

    width, height, _dpi = KIND_DEFAULT_SIZE.get(kind, (1080, 1350, 72))
    if kind == "post" and _SQUARE_RE.search(prompt):
        width, height, _dpi = KIND_DEFAULT_SIZE["square"]
    explicit = _SIZE_RE.search(prompt)
    if explicit:
        width, height = int(explicit.group(1)), int(explicit.group(2))
    else:
        ratio = _RATIO_RE.search(prompt)
        if ratio:
            rw, rh = int(ratio.group(1)), int(ratio.group(2))
            if rw > 0 and rh > 0:
                base = 1080
                width, height = (base, round(base * rh / rw)) if rw <= rh \
                    else (round(base * rw / rh), base)

    moods = [name for name, keywords in _MOOD_KEYWORDS.items()
             if any(k in text for k in keywords)] or ["clean"]

    copy = _extract_copy(prompt)

    # Iterate the mapping, not the detected moods: the mapping is ordered by specificity
    # while `moods` is in keyword-table order, which would let "bold" outrank "festive".
    vibe = next((v for m, v in _VIBE_FOR_MOOD.items() if m in moods), "geometric")

    subject = _guess_subject(prompt)

    return DesignBrief(
        kind=kind,
        canvas=BriefCanvas(width=width, height=height),
        subjectDescription=subject,
        copy=copy,
        mood=moods[:3],
        colorDirection=ColorDirection(mode="auto"),
        typography=Typography(vibe=vibe),
        layoutHints=LayoutHints(density="balanced"),
        language="en",
    )


def _extract_copy(prompt: str) -> Copy:
    """Pull quoted copy out of a prompt, honouring explicit labels first.

    `cta "Shop now"` must land in `cta`, not in the headline; unlabelled quotes then
    fill the remaining slots in reading order.
    """
    copy = Copy()
    consumed: set[str] = set()
    for label, *groups in _LABELLED_COPY_RE.findall(prompt):
        phrase = "".join(groups)
        field = _COPY_FIELD_FOR_LABEL.get(label.lower())
        if field and getattr(copy, field) is None:
            setattr(copy, field, phrase.strip())
            consumed.add(phrase.strip())

    leftovers = [q.strip() for q in _find_quoted(prompt) if q.strip() not in consumed]
    for field in ("headline", "subhead", "cta"):
        if not leftovers:
            break
        if getattr(copy, field) is None:
            setattr(copy, field, leftovers.pop(0))

    # Offer and contact details are read off the unquoted prompt: users type these as
    # plain instructions ("50% off, call 98765 43210"), not as quoted copy.
    unquoted = _QUOTED_RE.sub(" ", prompt)
    copy.offer, copy.badge, copy.price = extract_offer(unquoted)
    copy.contact = extract_contact(unquoted)
    return copy


def extract_contact(prompt: str) -> Contact:
    """Pull contact details out of a prompt verbatim.

    Order matters: emails and URLs are consumed before phone numbers are looked for, or
    the digits inside "shop24.com" are read as a number to call.
    """
    remaining = prompt
    email = _EMAIL_RE.search(remaining)
    if email:
        remaining = remaining.replace(email.group(0), " ")

    website = None
    for match in _URL_RE.finditer(remaining):
        candidate = match.group(0).rstrip(".,;")
        website = candidate
        remaining = remaining.replace(match.group(0), " ")
        break

    social = _SOCIAL_RE.search(remaining)
    if social:
        remaining = remaining.replace(social.group(0), " ")

    phone = _find_phone(remaining)

    return Contact(
        phone=phone,
        email=email.group(0) if email else None,
        website=website,
        social=social.group(0) if social else None,
    )


def _find_phone(text: str) -> str | None:
    """A phone number, preferring one introduced by a cue word.

    Without the cue preference a prompt containing "50% off, valid till 30 09 2026" hands
    back the date. Digits are counted rather than characters because formatting varies
    wildly and length is the only reliable signal.
    """
    cued = _PHONE_CUE_RE.search(text)
    windows = []
    if cued:
        windows.append(text[cued.end():cued.end() + 40])
    windows.append(text)
    for window in windows:
        for match in _PHONE_RE.finditer(window):
            candidate = match.group(0).strip(" .-")
            if 7 <= sum(c.isdigit() for c in candidate) <= 15:
                return candidate
    return None


def extract_offer(prompt: str) -> tuple[str | None, str | None, str | None]:
    """(offer, badge, price) read straight off the prompt."""
    discount = _DISCOUNT_RE.search(prompt)
    offer = badge = None
    if discount:
        offer = " ".join(discount.group(0).split())
        # A seal holds a dozen characters, so it gets the discount itself rather than
        # the phrase around it: "flat 50% off" is an offer line, "50% OFF" is a stamp.
        core = _BADGE_TRIM_RE.sub("", offer).strip()
        badge = core.upper() if 0 < len(core) <= 12 else None

    price_match = _PRICE_RE.search(prompt)
    price = " ".join(price_match.group(0).split()).strip(" ,.;") if price_match else None
    # A price that is only the discount over again adds nothing.
    if price and offer and price.lower() in offer.lower():
        price = None
    return offer, badge, price


_STOPWORDS = {
    "a", "an", "the", "for", "with", "and", "or", "of", "to", "in", "on", "at", "by",
    "make", "create", "design", "generate", "build", "me", "my", "our", "please",
    "poster", "story", "post", "banner", "thumbnail", "flyer", "ad", "advert", "square",
    "instagram", "facebook", "linkedin", "youtube", "social", "media", "image", "picture",
    "that", "this", "some", "very", "really", "about", "showing", "featuring", "promoting",
}



# Aspect families the corpus authors PRINT layouts against. A poster or a flyer is an
# A-series sheet; nothing in the corpus draws one at 4:5.
_PRINT_ASPECT = 1 / 1.414
_SCREEN_KIND_FOR_RATIO: tuple[tuple[float, str], ...] = (
    (9 / 16, "story"),
    (4 / 5, "post"),
    (1.0, "post"),
    (16 / 9, "thumbnail"),
    (1.91, "ad"),
    (3.0, "banner"),
)


def coerce_kind_to_canvas(kind: str, width: int, height: int) -> str:
    """Keep `kind` and `canvas` telling the same story.

    `kind` chooses a template family and `canvas` fixes the geometry, and when they
    disagree the geometry wins — a skeleton is normalised to ITS aspect, so one authored
    for an A4 sheet laid out on a 4:5 canvas has every vertical relationship wrong.

    The request this exists for said "4:5 vertical Instagram/Facebook promotional
    poster". The word "poster" set `kind`, the ratio set the canvas, retrieval hard-filters
    on both, and `poster` x `4:5` matches nothing in the corpus — so it fell through to
    the relaxed-aspect fallback and returned a print poster: a full-bleed photograph with
    three text slots, onto which an offer, a date, a brand name and a tagline could not
    be placed at all. The design never had a chance to be right.

    Only print kinds are moved, and only when the canvas is plainly a screen: a genuine
    A4 poster keeps its family.
    """
    if kind not in ("poster", "flyer"):
        return kind
    ratio = width / max(1, height)
    # Near enough to an A-series sheet: leave it alone.
    if abs(math.log(ratio / _PRINT_ASPECT)) < 0.08:
        return kind
    nearest = min(_SCREEN_KIND_FOR_RATIO, key=lambda pair: abs(math.log(pair[0] / ratio)))
    log.info("brief.parse.kind_follows_canvas", was=kind, now=nearest[1],
             width=width, height=height)
    return nearest[1]



# The business the design is for. Users name it in one of a very small number of ways,
# and all of them are explicit — this never guesses a brand out of ordinary prose,
# because a design captioned with a business that does not exist is worse than an
# unbranded one.
_BRAND_RE = re.compile(
    r"\b(?:called|named|for|brand[:\s]|business[:\s]|studio[:\s]|company[:\s])\s*"
    r"[\"\u201c\u2018']([^\"\u201d\u2019']{2,48})[\"\u201d\u2019']",
    re.IGNORECASE)
_BRAND_BARE_RE = re.compile(
    r"\b(?:called|named)\s+((?:[A-Z][\w&.'-]*\s*){2,6})", re.UNICODE)

_MONTH = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*")
_DATE_RE = re.compile(
    r"(?:"
    r"\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH + r"\.?(?:\s+\d{2,4})?"
    r"|" + _MONTH + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?,?(?:\s+\d{2,4})?"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r")", re.IGNORECASE)
# The words that make a date an *event* line rather than a passing mention.
_EVENT_LEAD_RE = re.compile(
    r"\b(opening|launch(?:ing)?|grand opening|starts?|starting|begins?|from|on|date|"
    r"event|show|sale|workshop|class|screening|doors)\b[^.\n]{0,40}$",
    re.IGNORECASE)


def extract_brand_name(prompt: str) -> str | None:
    """The business name, as the user wrote it."""
    match = _BRAND_RE.search(prompt)
    if match:
        return " ".join(match.group(1).split())
    bare = _BRAND_BARE_RE.search(prompt)
    if bare:
        return " ".join(bare.group(1).split())
    return None


def extract_event_line(prompt: str) -> str | None:
    """A dated line — "Opening Date: 23 September 2026" — as one string.

    Only a date introduced by an occasion word is taken. Dates turn up in prompts for
    other reasons ("a 90s poster", "valid till 30 Sep"), and lifting one of those into
    the event slot puts a wrong date on a finished design.
    """
    for match in _DATE_RE.finditer(prompt):
        before = prompt[max(0, match.start() - 60):match.start()]
        if not _EVENT_LEAD_RE.search(before):
            continue
        # Carry the label with it when there is one: "Opening Date: 23 September 2026"
        # reads as an event line, "23 September 2026" reads as a stray number.
        label = re.search(r"([A-Za-z][A-Za-z ]{2,24}?)\s*[:\u2014-]\s*$", before)
        date = " ".join(match.group(0).split())
        if label:
            return f"{label.group(1).strip()}: {date}"
        return date
    return None


# Where a prompt says, in so many words, what the picture is of. A long request is
# mostly instructions — format, palette, mood, copy — and reading the first few nouns off
# the top of it returns the instructions: "premium grand opening promotional modern
# motorcycle-themed restaurant called" was a real subject description, and it is what the
# image generator was paid to draw.
# Two to ten whole words, commas allowed, never running past a sentence end. Matched as
# words rather than as a character budget so a phrase cannot be cut off mid-word — an
# image prompt ending "a cool industrial restauran" is worse than no phrase at all.
_PHRASE = r"((?:[\w'&-]+[ ,]+){1,9}[\w'&-]+)"
_HERO_RE = re.compile(
    _PHRASE + r"\s+as the (?:main|hero|primary|star|central)\b", re.IGNORECASE)
_SUBJECT_MARKER_RE = re.compile(
    r"\b(?:featuring|feature|features|showing|shows|show|displaying|display|"
    r"hero shot of|photograph of|photo of|image of|shot of|close-?up of)\s+"
    + _PHRASE, re.IGNORECASE)

# Words that open a subject phrase without being part of it.
_SUBJECT_LEAD = {
    "feature", "features", "featuring", "show", "shows", "showing", "display",
    "displaying", "add", "include", "including", "a", "an", "the", "some", "image",
    "photo", "photograph", "picture", "shot", "of", "with", "off", "closeup",
}


def _clean_subject_phrase(phrase: str) -> str | None:
    """Trim a matched phrase down to the thing itself."""
    words = phrase.replace("\u2019", "'").split()
    while words and words[0].strip(",").lower() in _SUBJECT_LEAD:
        words.pop(0)
    while words and words[-1].strip(",").lower() in _SUBJECT_LEAD:
        words.pop()
    if not words:
        return None
    return " ".join(words[:10]).strip(" ,-")


def _guess_subject(prompt: str) -> str | None:
    """Pull the concrete noun phrase out of the prompt, minus instruction words.

    Returns None rather than a bad guess: a wrong subject spends real money on an image
    of the wrong thing, whereas None yields a clean text-only design the user can build on.

    A phrase the prompt explicitly marks as the subject — "feature X", "X as the main
    hero" — beats the leading-nouns heuristic every time, and a long, carefully written
    request almost always contains one. The heuristic stays as the fallback for the short
    prompts it was written for ("summer fashion sale").
    """
    if _NO_SUBJECT_RE.search(prompt):
        # The user asked for no photograph; retrieval filters on this, so respect it.
        return None
    stripped = _QUOTED_RE.sub(" ", prompt)

    for pattern in (_HERO_RE, _SUBJECT_MARKER_RE):
        match = pattern.search(stripped)
        if not match:
            continue
        cleaned = _clean_subject_phrase(match.group(1))
        if cleaned and len(cleaned.split()) >= 2:
            return cleaned

    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z\-']+", stripped)
             if w.lower() not in _STOPWORDS and len(w) > 2]
    if len(words) < 2:
        return None
    return " ".join(words[:8])


# --------------------------------------------------------------------------------------
# Post-processing
# --------------------------------------------------------------------------------------


def _apply_brand_kit(brief: DesignBrief, brand_kit: dict | None) -> DesignBrief:
    """§1.1: 'Brand kit, when present, overrides palette/fonts/tone.'"""
    if not brand_kit:
        return brief
    palette = brand_kit.get("palette") or []
    if palette:
        brief.color_direction = ColorDirection(mode="brand", palette=list(palette))
    fonts = brand_kit.get("fonts") or []
    if fonts:
        family = fonts[0].get("family") if isinstance(fonts[0], dict) else str(fonts[0])
        if family:
            brief.typography.family_hint = family
    return brief


def _sanitise(brief: DesignBrief, original_prompt: str) -> DesignBrief:
    """Clamp anything the model could get wrong in a way that would cost money."""
    # Canvas: keep within something renderable and non-degenerate.
    brief.canvas.width = max(64, min(20000, int(brief.canvas.width)))
    brief.canvas.height = max(64, min(20000, int(brief.canvas.height)))

    # A single clarifying question, maximum (§1.1).
    if brief.needs_clarification is not None:
        options = brief.needs_clarification.options[:4]
        if len(options) < 2:
            brief.needs_clarification = None
        else:
            brief.needs_clarification.options = options

    # Verbatim-copy guard: if the user quoted copy, the brief must contain it unchanged.
    #
    # A quoted phrase the model didn't paraphrase away usually landed in a field this
    # guard doesn't scan directly — `offer`, `price`, `badge`, a `features` entry, a
    # contact field — so `present` has to check everywhere a genuine transcription could
    # be, not just the five headline-shaped fields. And when every headline-shaped field
    # is already filled, that means the phrase found its way in somewhere else, not that
    # it was dropped — overwriting an already-correct field with it would be the guard
    # inventing a new failure instead of catching one.
    quoted = _find_quoted(original_prompt)
    if quoted:
        copy = brief.copy_text
        present = {
            (v or "").strip().lower()
            for v in (
                copy.headline, copy.subhead, copy.body, copy.cta, copy.caption,
                copy.offer, copy.price, copy.badge, copy.terms, copy.event_details,
                copy.brand_name, copy.contact.phone, copy.contact.email,
                copy.contact.website, copy.contact.address, copy.contact.social,
                *copy.features, *copy.tags,
            )
            if v
        }
        empty_slots = [f for f in ("headline", "subhead", "body", "cta", "caption")
                      if not getattr(copy, f)]
        for phrase in quoted:
            norm = phrase.strip().lower()
            if not norm or norm in present:
                continue
            if not empty_slots:
                # Nowhere left to safely put this phrase without overwriting a field
                # that already holds something else.
                log.info("brief.parse.unmatched_quoted_copy", phrase=phrase)
                continue
            field = empty_slots.pop(0)
            setattr(copy, field, phrase.strip())
            present.add(norm)
            log.info("brief.parse.restored_verbatim_copy", phrase=phrase, field=field)

    brief.mood = [m.strip().lower() for m in brief.mood if m.strip()][:4]

    # Colour words -> a designed palette, in ground-first order. Left alone, "gold and
    # deep blue" reaches the composer as two words that it resolves through the CSS
    # keyword table, and the design ships on a highlighter-yellow ground. See
    # `app.util.palette` for why the obvious table is the wrong one.
    if brief.color_direction.palette:
        resolved = resolve_palette_words(list(brief.color_direction.palette))
        if resolved:
            ordered = order_palette(resolved, moods=brief.mood)
            # Users name two colours far more often than three, and a two-colour palette
            # leaves supporting copy with nowhere to go but the accent.
            brief.color_direction.palette = complete_palette(ordered, moods=brief.mood)
        elif brief.color_direction.mode == "from-prompt":
            # The words named no colour at all; better to let the composer choose than
            # to carry nonsense into the palette.
            brief.color_direction = ColorDirection(mode="auto")

    brief.kind = coerce_kind_to_canvas(brief.kind, brief.canvas.width,
                                       brief.canvas.height)

    _ensure_subject(brief, original_prompt)
    _restore_details(brief, original_prompt)
    _set_density(brief)
    return brief


def _restore_details(brief: DesignBrief, original_prompt: str) -> None:
    """Put back the offer and contact details the model dropped or rewrote.

    The system prompt tells the model to transcribe these verbatim and the model does not
    reliably do it: a number gets summarised away as clutter, a URL gets tidied into
    "our website", a discount gets folded into the headline. All three are silent
    failures — the design still looks finished, it just cannot be acted on. So the
    prompt is re-read here and anything the model left empty is filled from it.

    Only empty fields are filled. Where the model did produce a value it is kept, on the
    grounds that it had the whole request in view and the regex has one line of it.
    """
    copy = brief.copy_text

    found = extract_contact(original_prompt)
    for field in ("phone", "email", "website", "social"):
        if getattr(copy.contact, field) is None and getattr(found, field) is not None:
            setattr(copy.contact, field, getattr(found, field))
            log.info("brief.parse.restored_contact", field=field)

    # A number the model invented is worse than none, and the only way to tell an
    # invented one from a transcribed one is whether its digits are in the prompt.
    prompt_digits = re.sub(r"\D", "", original_prompt)
    if copy.contact.phone:
        digits = re.sub(r"\D", "", copy.contact.phone)
        if digits and digits not in prompt_digits:
            log.info("brief.parse.dropped_invented_phone")
            copy.contact.phone = None

    if not copy.brand_name:
        brand = extract_brand_name(original_prompt)
        if brand:
            copy.brand_name = brand
            log.info("brief.parse.restored_brand_name", brand=brand)

    if not copy.event_details:
        event = extract_event_line(original_prompt)
        if event:
            copy.event_details = event
            log.info("brief.parse.restored_event", event_line=event)

    offer, badge, price = extract_offer(_QUOTED_RE.sub(" ", original_prompt))
    if not copy.offer and offer:
        copy.offer = offer
    if not copy.badge and badge:
        copy.badge = badge
    if not copy.price and price:
        copy.price = price

    copy.features = [" ".join(f.split()) for f in copy.features if f and f.strip()][:6]
    copy.tags = [" ".join(t.split()) for t in copy.tags if t and t.strip()][:8]


def _set_density(brief: DesignBrief) -> None:
    """Escalate to a dense layout when the brief plainly carries more than a sparse one
    can hold.

    Density is a hard-ish filter at retrieval, so a brief with an offer, four features
    and a phone number that still says "balanced" gets a three-slot layout and most of
    what the user asked for never reaches the canvas.
    """
    if brief.layout_hints.density == "sparse":
        # A deliberate choice. Honour it even when there is a lot of copy.
        return
    # Measured against the core three roles every layout already has. What makes a brief
    # dense is the material *beyond* a headline, a subhead and a button: an offer, a
    # price, a list, a phone number.
    # `badge` is excluded: it is derived from the offer, and counting both would read a
    # single discount as two pieces of content.
    extras = set(brief.copy_text.filled_roles()) & {
        "offer", "price", "terms", "feature", "event", "contact", "body"}
    if len(extras) >= 2 or len(brief.copy_text.features) >= 3:
        brief.layout_hints.density = "dense"


def _ensure_subject(brief: DesignBrief, original_prompt: str) -> None:
    """Backstop the model's single most consequential omission.

    A null `subjectDescription` is not a neutral default: `template.retrieve` treats it
    as a hard filter, so the design is cut down to whichever type-only skeleton exists
    for that kind and aspect — one layout, no imagery, no ornament. The model reaches for
    null whenever the prompt names a business rather than an object ("a jewellery
    brand", "a cafe"), which is most real prompts.

    So a missing subject is only honoured when the prompt actually asks for one to be
    missing. Otherwise the heuristic subject stands in: an approximate subject produces a
    design the user can regenerate one layer of, whereas a missing one produces a design
    they have to start over.
    """
    if brief.subject_description and brief.subject_description.strip():
        return
    if _NO_SUBJECT_RE.search(original_prompt):
        brief.subject_description = None
        return

    guessed = _guess_subject(original_prompt)
    if not guessed:
        return
    # Phrase it for an image generator rather than handing over prompt fragments.
    brief.subject_description = f"{guessed}, photographed as a single clear object"
    log.info("brief.parse.subject_inferred", subject=brief.subject_description)
