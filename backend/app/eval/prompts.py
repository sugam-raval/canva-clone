"""Evaluation prompt set — IMPLEMENTATION_PLAN §5.3.

§5.3 specifies 100 prompts across all kinds, plus 20 brand-kit prompts and 10
non-English. This is a representative subset covering every `kind`, both subject and
text-only briefs, three copy lengths per the §1.2 review requirement, and a
non-Latin-script set that exercises HarfBuzz shaping and font fallback.

Growing this to the full 130 is straightforward; the harness does not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalPrompt:
    id: str
    prompt: str
    kind: str
    tags: list[str] = field(default_factory=list)
    brand_kit: dict | None = None


SHORT_COPY = "short"
LONG_COPY = "long"

PROMPTS: list[EvalPrompt] = [
    # -- stories ---------------------------------------------------------------------
    EvalPrompt("story-01", 'Instagram story for a new running shoe, minimal and premium, '
               'headline "Run Lighter"', "story", ["subject", SHORT_COPY]),
    EvalPrompt("story-02", 'Story for an energy drink launch, bold and high contrast, '
               'headline "Go All Night" subhead "zero sugar, all lift" cta "Try it"',
               "story", ["subject"]),
    EvalPrompt("story-03", 'Story announcing a podcast episode, text only, editorial, '
               'headline "The Long Game" subhead "a conversation about patience, craft '
               'and the unglamorous middle years of building something that lasts"',
               "story", ["text-only", LONG_COPY]),
    EvalPrompt("story-04", 'Story for a skincare serum, clean and natural, headline '
               '"Quiet Skin"', "story", ["subject", SHORT_COPY]),
    EvalPrompt("story-05", 'Story for a sneaker drop, loud retro, headline "Back In '
               'Rotation" subhead "limited pairs, Friday 10am, online only"',
               "story", ["subject"]),

    # -- posts -----------------------------------------------------------------------
    EvalPrompt("post-01", 'Square sale post for wireless headphones, 50% off, loud',
               "post", ["subject", SHORT_COPY]),
    EvalPrompt("post-02", 'Editorial feed post about slow coffee, warm and natural, '
               'headline "The Twelve Minute Cup" body "we timed every stage of the '
               'pour, from bloom to final drawdown, and found that the difference '
               'between good and remarkable is almost entirely patience"',
               "post", ["subject", LONG_COPY]),
    EvalPrompt("post-03", 'A text only quote post, elegant serif, headline "Make it '
               'simple, but significant"', "post", ["text-only", SHORT_COPY]),
    EvalPrompt("post-04", 'Product card post for a ceramic mug, minimal, cta "Shop now"',
               "post", ["subject"]),
    EvalPrompt("post-05", 'Post announcing a hiring round for a design studio, playful, '
               'headline "We are hiring three designers"', "post", ["text-only"]),

    # -- posters ---------------------------------------------------------------------
    EvalPrompt("poster-01", 'Minimal gallery poster, lots of whitespace, no photo, '
               'headline "Form and Void"', "poster", ["text-only", SHORT_COPY]),
    EvalPrompt("poster-02", 'Gig poster for a jazz quartet, bold typographic, dark, '
               'headline "Midnight Sessions" subhead "four nights only"',
               "poster", ["subject"]),
    EvalPrompt("poster-03", 'Cinematic travel poster for the Norwegian fjords, '
               'photographic, headline "North"', "poster", ["subject", SHORT_COPY]),

    # -- banners ---------------------------------------------------------------------
    EvalPrompt("banner-01", 'LinkedIn banner 1500x500 for a fintech startup, clean tech '
               'feel, headline "Money that moves at your speed"', "banner", ["subject"]),
    EvalPrompt("banner-02", 'Website announcement banner, centred, text only, headline '
               '"Free shipping on every order this week"', "banner", ["text-only"]),

    # -- thumbnails ------------------------------------------------------------------
    EvalPrompt("thumb-01", 'Bold YouTube thumbnail about cheap flights to Japan, '
               'headline "I Flew For £43"', "thumbnail", ["subject", SHORT_COPY]),
    EvalPrompt("thumb-02", 'YouTube thumbnail for a keyboard review, high contrast, '
               'headline "This Changed My Typing"', "thumbnail", ["subject"]),

    # -- ads -------------------------------------------------------------------------
    EvalPrompt("ad-01", 'Facebook ad for a meal kit service, friendly, headline "Dinner, '
               'decided" subhead "five recipes a week, delivered Sunday" cta "Get 40% off"',
               "ad", ["subject"]),

    # -- flyers ----------------------------------------------------------------------
    EvalPrompt("flyer-01", 'Event flyer for a weekend farmers market, warm and natural, '
               'headline "Saturday Market" body "thirty local growers, bakers and makers '
               'from eight in the morning until two, every Saturday on the green, rain '
               'or shine, dogs welcome"', "flyer", ["subject", LONG_COPY]),

    # -- brand kit (§5.3 asks for a brand-kit subset) ----------------------------------
    EvalPrompt("brand-01", 'Story for our spring collection, headline "New Season"',
               "story", ["subject", "brand"],
               brand_kit={"palette": ["#101820", "#F2AA4C", "#FFFFFF"],
                          "fonts": [{"family": "Montserrat"}],
                          "tone": "confident, minimal"}),
    EvalPrompt("brand-02", 'Square post about our sustainability report, text only',
               "post", ["text-only", "brand"],
               brand_kit={"palette": ["#14532D", "#F0FDF4", "#BBF7D0"],
                          "fonts": [{"family": "Source Sans 3"}],
                          "tone": "plain, factual"}),

    # -- information-dense (offer + list + contact details in one request) -------------
    # These are the shape most real business requests arrive in, and the one the corpus
    # used to answer by dropping everything but the headline. Each carries facts that are
    # checkable in the output: a number that must appear character for character, a list
    # that must survive as separate lines, several distinct things to photograph.
    EvalPrompt("dense-01", 'Square post for Glow Salon, flat 50% off on facial, manicure '
               'and spa massage, starting Rs 499, call 98765 43210, visit glowsalon.com, '
               'cta "Book Now"', "post", ["subject", "dense", "offer", "contact", LONG_COPY]),
    EvalPrompt("dense-02", 'A4 flyer for Bright Dental Clinic, headline "Smile Brighter", '
               'checkup whitening and braces, upto 30% off, from Rs 999, open all week, '
               'call +91 22 4000 1234, email hi@smile.co.in, bright-dental.in',
               "flyer", ["subject", "dense", "offer", "contact", LONG_COPY]),
    EvalPrompt("dense-03", 'Sale post for wireless headphones, flat 50% off, only Rs 2499, '
               '30hr battery, active noise cancelling, 2 year warranty, call 98765 43210, '
               'headline "Sound Unleashed" cta "Shop now"',
               "post", ["subject", "dense", "offer", "contact"]),
    EvalPrompt("dense-04", 'Instagram post for a cafe menu showing a flat white, a '
               'cinnamon bun and a cold brew, warm and natural, headline "All Day", '
               'visit corner-cafe.co', "post", ["subject", "multi-subject", "dense"]),
    EvalPrompt("dense-05", 'Poster for a yoga studio opening, classes Monday to Friday '
               '7am and 6pm, first class free, 12 Mill Lane, call 07700 900123',
               "poster", ["subject", "dense", "contact", LONG_COPY]),

    # -- non-Latin (§5.3: 10 non-English prompts; shaping and font fallback) -----------
    EvalPrompt("i18n-01", 'Instagram story for a bakery, headline "Свежий хлеб каждый день"',
               "story", ["subject", "non-latin"]),
    EvalPrompt("i18n-02", 'Poster for a film festival, headline "Κινηματογράφος"',
               "poster", ["text-only", "non-latin"]),
    EvalPrompt("i18n-03", 'Square post for a language school, headline "Apprendre vite"',
               "post", ["text-only", "non-latin"]),
]


def by_tag(tag: str) -> list[EvalPrompt]:
    return [p for p in PROMPTS if tag in p.tags]
