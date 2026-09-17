"""`art.direct` — decide what this design's imagery and ornament are actually OF.

Runs once per request, between `brief.parse` and `compose.layout`. Its output fills the
`{{scene}}`, `{{texture}}`, `{{lighting}}`, `{{treatment}}` and `{{prop}}` placeholders
in the corpus's prompt templates, and chooses which motif each ornament family
contributes, so two requests never arrive at the same picture by way of the same
skeleton.

Two tiers, matching `brief.parse`:
  1. one schema-constrained LLM call
  2. a heuristic director — a domain table keyed off the words in the brief

Tier 2 is not a degraded mode. It is what runs with no API key, and it is still a large
improvement on what it replaces: "studio backdrop" for every design ever generated.
"""

from __future__ import annotations

import hashlib
import random
import re

import structlog

from app.adapters.base import AdapterError
from app.adapters.registry import llm as get_llm
from app.schema.art import ArtDirection, MotifChoice
from app.schema.brief import DesignBrief
from app.templates_corpus.ornament import MOTIF_FAMILIES

log = structlog.get_logger(__name__)

SYSTEM_PROMPT = """\
You are the art director for one generated design. You decide what its imagery is OF.
You do NOT decide layout, copy or colour — those are already settled.

SCENE
- `scene` is what a photographic background of this design shows: a real place and a
  real surface, lit. "a scratched walnut barber counter, shallow depth of field", not
  "a studio backdrop".
- It must not contain THE SUBJECT or any people: the subject is a separate layer
  composited on top, and a background that already has one ships the design with two.
- It is still a real, styled photograph. Name the surface, the material and what sits at
  the EDGES of the frame — the stone, the timber, the foliage, the cloth, the light
  falling across it — and say that the middle is left calm for what goes on top. An
  instruction to describe "an empty setting" is what produced backgrounds that were a
  flat wall with a gradient on it, and a cutout floating on a flat wall is the single
  biggest difference between this system's output and the reference work it is chasing.
- Make it specific to this request's trade, cuisine, occasion or culture. A dental
  clinic, a biryani restaurant and a sneaker drop must not share a background.
- Never name a mood word. An image model reads "festive" as a stock genre and answers
  with snowflakes and fir, so a Diwali design comes back decorated for Christmas.
  Write what it should LOOK like instead: "marigold and brass, warm glowing lamps".

TEXTURE
- `texture` is the flat, abstract alternative for designs built on a graphic ground
  rather than a photograph: a material grain or a soft field, with real tonal depth in
  it. No subject and no people, but not a flat colour either.

LIGHTING
- One clause: direction, quality and colour. "low warm tungsten raking from the left".

SUBJECT TREATMENT
- `subjectTreatment` says how the subject should be RENDERED — materials, finish,
  surface, condiment of the light on it. Do NOT give it an angle or a camera position:
  the layout owns those, and a layout showing three views of one product needs its three
  angles to stay different.

PROP
- One small secondary object that belongs beside the subject: a sprig, a leaf, a tool of
  the trade. It is a cutout, so do not mention any surface it rests on.

ORNAMENT
- Choose one motif per family that suits the occasion. Leave a family null when the
  design has no opinion and the layout's own choice should stand.
- frame: border (a ruled double frame), corners (corner flourishes), arch (an arch
  behind the subject), frame-rule (a single thin rule)
- rule: divider (an ornamental rule), chevrons, scallop
- band: garland (hanging blossoms), bunting (triangular flags)
- field: blob (organic colour shape), wave, stripes (diagonal bands), arc-band (a sweep)
- scatter: confetti, dots, rays (a starburst)
- seal: badge (a stamped seal), ribbon (a banner)
- `density` is 1 (almost none) to 5 (heavily decorated). Ceremonial and promotional work
  carries more; minimal, editorial and corporate work carries less.
"""


def _user_message(brief: DesignBrief) -> str:
    copy = brief.copy_text
    lines = [
        f"kind: {brief.kind}",
        f"subject: {brief.subject_description or 'none — a type-only design'}",
        f"mood: {', '.join(brief.mood) or 'clean'}",
        f"typography vibe: {brief.typography.vibe}",
        f"density: {brief.layout_hints.density}",
        f"language: {brief.language}",
    ]
    if brief.subjects:
        lines.append(f"further subjects: {brief.subjects}")
    said = [v for v in (copy.headline, copy.subhead, copy.offer, copy.body) if v]
    if said:
        lines.append("what the design says: " + " / ".join(said))
    return "\n".join(lines)


async def direct_art(brief: DesignBrief, *, seed: int = 0) -> tuple[ArtDirection, int]:
    """Return (direction, cost_cents). Never raises — falls back to the heuristic."""
    try:
        result = await get_llm().complete_json(
            system=SYSTEM_PROMPT, user=_user_message(brief), schema=ArtDirection,
            temperature=0.7,
        )
        return _sanitise(result.parsed, brief, seed), result.cost_cents
    except AdapterError as exc:
        log.info("art.direct.llm_unavailable", error=str(exc))
    return heuristic_direction(brief, seed=seed), 0


# --------------------------------------------------------------------------------------
# Heuristic director
# --------------------------------------------------------------------------------------


class _Domain:
    """One trade's visual world: where its photographs are taken and what they hold."""

    __slots__ = ("density", "motifs", "props", "scenes", "textures", "treatment")

    def __init__(self, scenes: list[str], textures: list[str], treatment: str,
                 props: list[str], motifs: dict[str, tuple[str, ...]],
                 density: int = 3):
        self.scenes = scenes
        self.textures = textures
        self.treatment = treatment
        self.props = props
        self.motifs = motifs
        self.density = density


# Keyed by the words that actually appear in requests. Each domain carries several
# scenes because the point of this module is that two requests in the same trade still
# get different pictures — one is chosen per design from the request's own seed.
_DOMAINS: dict[tuple[str, ...], _Domain] = {
    ("restaurant", "cafe", "coffee", "bakery", "food", "pizza", "burger", "biryani",
     "kitchen", "dine", "menu", "catering", "sweets", "bar", "brunch"): _Domain(
        scenes=["a worn oak table top with soft window light and a drift of flour",
                "a dark slate counter with steam catching a low warm light",
                "a pale terrazzo counter under bright midday daylight"],
        textures=["coarse linen weave, warm and matte",
                  "a soft speckled paper grain in warm neutrals"],
        treatment="appetising, glistening, shallow depth of field, natural texture",
        props=["a sprig of fresh herbs", "a scatter of whole coffee beans",
               "a folded linen napkin"],
        motifs={"rule": ("scallop", "divider"), "field": ("blob", "wave"),
                "scatter": ("dots", "confetti"), "frame": ("frame-rule", "corners"),
                "band": ("bunting",), "seal": ("badge", "ribbon")}),

    ("salon", "spa", "beauty", "skincare", "cosmetic", "makeup", "nail", "facial",
     "hair", "massage", "wellness", "grooming", "barber"): _Domain(
        scenes=["a pale marble vanity top with soft diffused daylight",
                "a still pool of water on smooth stone, lit from directly above",
                "a folded cotton towel on brushed limestone in low morning light"],
        textures=["fine plaster grain in soft neutrals",
                  "a smooth satin sheen, gently graded"],
        treatment="dewy, soft-focus highlights, smooth matte finish, clean edges",
        props=["a single eucalyptus leaf", "a smooth river stone",
               "a small sprig of dried lavender"],
        motifs={"rule": ("divider", "scallop"), "field": ("wave", "arc-band"),
                "scatter": ("dots",), "frame": ("corners", "frame-rule"),
                "band": ("garland",), "seal": ("badge",)},
        density=2),

    ("gym", "fitness", "workout", "training", "crossfit", "yoga", "run", "sport",
     "athletic", "boxing", "cycle"): _Domain(
        scenes=["a scuffed concrete gym floor under hard directional light",
                "a dark rubber-matted floor with a single hard rim light",
                "an empty running track at low sun, long shadows"],
        textures=["raw concrete grain, cool and hard",
                  "a taut diagonal mesh, high contrast"],
        treatment="high-contrast, hard specular highlights, matte rubber and steel",
        props=["a coiled skipping rope", "a rolled exercise mat"],
        motifs={"rule": ("chevrons",), "field": ("stripes", "arc-band"),
                "scatter": ("rays",), "frame": ("frame-rule",),
                "band": ("bunting",), "seal": ("badge",)},
        density=4),

    ("tech", "software", "app", "saas", "startup", "fintech", "ai", "digital",
     "electronic", "gadget", "laptop", "phone", "headphone", "audio"): _Domain(
        scenes=["a dark brushed-aluminium surface with a cool blue rim light",
                "a seamless deep-charcoal sweep with a single cold gradient falloff",
                "a smoked-glass surface with soft cyan reflections"],
        textures=["a fine anodised metal grain, cool and even",
                  "a soft gradient mesh in cool tones"],
        treatment="crisp specular highlights, precise edges, matte and glass finishes",
        props=["a coiled braided cable", "a small matte black cube"],
        motifs={"rule": ("chevrons", "divider"), "field": ("stripes", "wave"),
                "scatter": ("dots",), "frame": ("frame-rule",),
                "band": ("bunting",), "seal": ("badge",)},
        density=2),

    ("fashion", "apparel", "clothing", "boutique", "sneaker", "shoe", "bag", "wear",
     "outfit", "style", "lookbook", "denim"): _Domain(
        scenes=["a seamless colour studio sweep, soft and even",
                "a rippled silk backdrop catching a single soft light",
                "a bare plaster wall with hard afternoon sun and a clean shadow edge"],
        textures=["a soft colour gradient sweep, flat and even",
                  "a fine woven twill grain"],
        treatment="crisp fabric texture, clean edges, soft falloff",
        props=["a folded silk ribbon", "a pair of round sunglasses"],
        motifs={"rule": ("divider", "chevrons"), "field": ("arc-band", "blob", "wave"),
                "scatter": ("confetti", "dots"), "frame": ("corners", "frame-rule"),
                "band": ("bunting",), "seal": ("badge", "ribbon")},
        density=3),

    ("jewel", "jewellery", "jewelry", "gold", "diamond", "silver", "watch", "luxury",
     "premium", "boutique-luxury"): _Domain(
        scenes=["deep folded velvet in shadow with one warm highlight",
                "polished black stone with a narrow band of warm reflected light",
                "brushed brass in low light, softly graded"],
        textures=["fine brushed-brass grain, warm and even",
                  "deep velvet pile, softly graded"],
        treatment="sparkling facets, deep contrast, polished metal, jewel highlights",
        props=["a single dried rose", "a length of fine gold chain"],
        motifs={"rule": ("divider",), "field": ("arc-band", "wave"), "scatter": ("dots",),
                "frame": ("border", "corners"), "band": ("garland",),
                "seal": ("badge", "ribbon")},
        density=3),

    ("clinic", "dental", "dentist", "doctor", "medical", "hospital", "health",
     "pharmacy", "care", "therapy", "vet"): _Domain(
        scenes=["a clean pale clinical surface under soft even daylight",
                "a frosted-glass partition with cool diffused light behind it",
                "a smooth white counter with a gentle blue-grey falloff"],
        textures=["a soft matte surface in cool pale tones",
                  "a fine even grain in clinical white"],
        treatment="clean, clinical, soft even highlights, matte surfaces",
        props=["a small green leaf", "a rolled white towel"],
        motifs={"rule": ("divider",), "field": ("wave", "blob"), "scatter": ("dots",),
                "frame": ("frame-rule",), "band": ("bunting",), "seal": ("badge",)},
        density=2),

    ("property", "estate", "realty", "interior", "furniture", "home", "architect",
     "construction", "decor", "apartment"): _Domain(
        scenes=["a bright minimal interior with light falling from a tall window",
                "a bare plastered wall with a long diagonal shadow",
                "a polished concrete floor in a wide empty room, soft daylight"],
        textures=["a fine plaster grain in warm neutrals",
                  "a soft concrete grain, cool and even"],
        treatment="architectural, soft ambient light, honest materials",
        props=["a small trailing plant", "a folded wool throw"],
        motifs={"rule": ("divider", "chevrons"), "field": ("wave", "stripes"),
                "scatter": ("dots",), "frame": ("frame-rule",), "band": ("bunting",),
                "seal": ("badge",)},
        density=2),

    ("school", "college", "course", "class", "academy", "education", "tuition",
     "learning", "workshop", "seminar", "exam", "university"): _Domain(
        scenes=["a clean desk surface under soft daylight from the left",
                "a dark chalkboard-green wall, evenly lit",
                "a pale birch tabletop with a wash of morning light"],
        textures=["a soft recycled paper grain",
                  "a fine chalk-dusted matte surface"],
        treatment="clear, evenly lit, honest matte materials",
        props=["a stack of two books", "a sharpened pencil"],
        motifs={"rule": ("chevrons", "scallop"), "field": ("blob", "stripes"),
                "scatter": ("confetti", "dots"), "frame": ("frame-rule", "corners"),
                "band": ("bunting",), "seal": ("badge",)},
        density=3),

    ("car", "auto", "bike", "motor", "vehicle", "garage", "scooter", "tyre",
     "service-centre"): _Domain(
        scenes=["wet asphalt under a hard low sun, long reflections",
                "a dim concrete garage with a single hard overhead light",
                "an empty road at dusk with haze and cool falloff"],
        textures=["a coarse asphalt grain, cool and dark",
                  "brushed steel grain with a hard sheen"],
        treatment="glossy lacquer, hard specular highlights, deep reflections",
        props=["a chrome wrench", "a coiled rubber hose"],
        motifs={"rule": ("chevrons",), "field": ("stripes",), "scatter": ("rays",),
                "frame": ("frame-rule",), "band": ("bunting",), "seal": ("badge",)},
        density=3),

    ("travel", "hotel", "resort", "tour", "holiday", "flight", "trip", "beach",
     "island", "adventure", "booking"): _Domain(
        scenes=["a wide sunlit horizon with soft haze, dune grass at the frame edge",
                "pale sand in low golden light, gently rippled",
                "a calm sea surface at dawn, softly graded"],
        textures=["a soft warm gradient wash, hazy",
                  "a fine sand grain in warm neutrals"],
        treatment="sunlit, warm golden highlights, airy and clear",
        props=["a single palm frond", "a small woven sun hat"],
        motifs={"rule": ("scallop", "divider"), "field": ("wave", "arc-band"),
                "scatter": ("dots",), "frame": ("corners", "frame-rule"),
                "band": ("bunting",), "seal": ("badge",)},
        density=3),

    ("wedding", "engagement", "anniversary", "puja", "diwali", "eid", "christmas",
     "festival", "greeting", "celebration", "navratri", "pongal", "onam", "ramadan",
     "temple", "ceremony", "invitation"): _Domain(
        scenes=["a deep indigo ground with warm lamp bokeh and drifting gold light",
                "hand-beaten brass catching low candlelight, softly graded",
                "deep maroon silk with gold thread catching a warm glow"],
        textures=["fine gold leaf flecks on a deep ground",
                  "an ornamental damask grain in gold on dark"],
        treatment="warm glowing light, gilded highlights, rich saturated colour",
        props=["a single marigold bloom", "a small brass bell"],
        motifs={"rule": ("divider",), "field": ("arc-band",), "scatter": ("confetti",),
                "frame": ("border", "arch", "corners"), "band": ("garland",),
                "seal": ("badge",)},
        density=5),

    ("sale", "discount", "offer", "deal", "shop", "store", "retail", "clearance",
     "promo", "black-friday"): _Domain(
        scenes=["a bold flat colour field with a soft corner vignette",
                "a smooth colour gradient sweep with a single soft highlight",
                "a crisp paper surface with a hard raking light"],
        textures=["a flat colour field with fine paper grain",
                  "bold diagonal colour banding, flat and even"],
        treatment="bright, punchy, hard-edged, high saturation",
        props=["a burst of paper confetti", "a curled price tag"],
        motifs={"rule": ("chevrons", "divider"), "field": ("stripes", "arc-band", "blob"),
                "scatter": ("rays", "confetti"), "frame": ("frame-rule",),
                "band": ("bunting",), "seal": ("badge", "ribbon")},
        density=4),
}

_DEFAULT_DOMAIN = _Domain(
    scenes=["a seamless studio sweep with soft directional light",
            "a bare plaster wall with a soft raking light and a clean shadow",
            "a smooth matte surface with an even gradient falloff"],
    textures=["a fine even paper grain", "a soft gradient wash, flat and even"],
    treatment="clean, softly lit, honest materials, crisp edges",
    props=["a small sprig of foliage", "a simple geometric block"],
    motifs={"rule": ("divider", "scallop", "chevrons"),
            "field": ("blob", "wave", "arc-band"), "scatter": ("dots", "confetti"),
            "frame": ("frame-rule", "corners"), "band": ("bunting", "garland"),
            "seal": ("badge", "ribbon")},
)

# Mood expansions, reused from the composer so the two stages agree about what a mood
# looks like rather than each inventing its own vocabulary.
_LIGHTING_FOR_MOOD: dict[str, str] = {
    "festive": "warm glowing lamplight from below, golden falloff",
    "premium": "a single soft key light, deep restrained shadow",
    "luxury": "a single soft key light, deep restrained shadow",
    "bold": "hard directional light, strong graphic shadow",
    "high-contrast": "hard directional light, strong graphic shadow",
    "playful": "bright even light, soft bounced fill",
    "retro": "warm faded film light, gentle bloom",
    "tech": "cool precise light with tight specular highlights",
    "natural": "soft daylight through a window, gentle shadow",
    "minimal": "flat even light, almost no shadow",
    "dark": "a single low-key source, deep falloff into shadow",
    "warm": "low golden light raking from the left",
    "clean": "soft even light, gentle shadow",
}


def _domain_for(text: str) -> _Domain:
    """The best-matching trade, or the default.

    Scored by how many of a domain's keywords appear rather than by first hit: a request
    for "a gym cafe" names both, and the one it says more about should win.
    """
    words = set(re.findall(r"[a-z]+", text.lower()))
    best, best_score = _DEFAULT_DOMAIN, 0
    for keywords, domain in _DOMAINS.items():
        score = sum(1 for k in keywords if k in words or any(k in w for w in words))
        if score > best_score:
            best, best_score = domain, score
    return best


def _brief_text(brief: DesignBrief) -> str:
    copy = brief.copy_text
    parts = [brief.subject_description or "", " ".join(brief.subjects),
             " ".join(brief.mood), copy.headline or "", copy.subhead or "",
             copy.offer or "", copy.body or "", " ".join(copy.features)]
    return " ".join(p for p in parts if p)


def heuristic_direction(brief: DesignBrief, *, seed: int = 0) -> ArtDirection:
    """Deterministic, no model — and deliberately varied.

    The seed comes from the request, so two identical prompts a minute apart are
    directed differently while one document always regenerates to the same picture.
    """
    text = _brief_text(brief)
    domain = _domain_for(text)
    rng = random.Random(seed)

    lighting = next((_LIGHTING_FOR_MOOD[m] for m in brief.mood
                     if m in _LIGHTING_FOR_MOOD), _LIGHTING_FOR_MOOD["clean"])

    density = domain.density
    if brief.layout_hints.density == "sparse":
        density = max(1, density - 2)
    elif brief.layout_hints.density == "dense":
        density = min(5, density + 1)

    motifs = MotifChoice.model_validate(
        {family: _pick_motif(family, domain, rng) for family in MOTIF_FAMILIES})

    return ArtDirection(
        scene=rng.choice(domain.scenes),
        texture=rng.choice(domain.textures),
        lighting=lighting,
        subjectTreatment=domain.treatment,
        prop=rng.choice(domain.props),
        motifs=motifs,
        density=density,
        reason="heuristic: matched on the trade named in the brief",
    )


def _pick_motif(family: str, domain: _Domain, rng: random.Random) -> str:
    """One of the motifs this trade is happy with, chosen for this request.

    A domain lists every member of a family it accepts, so variety comes from a real
    choice rather than from overruling the trade: a ceremony lists only `garland` for its
    band because bunting on a wedding invitation is simply wrong, while a retail promo
    lists three fields because any of them would do and sameness is the bigger risk.
    """
    return rng.choice(domain.motifs.get(family) or MOTIF_FAMILIES[family])


def seed_from(*parts: str) -> int:
    """A stable 32-bit seed from any identifying strings (a request id, a prompt)."""
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:4], "big")


# --------------------------------------------------------------------------------------
# Sanitising
# --------------------------------------------------------------------------------------

# Words that name a stock genre to an image model rather than a tone to a designer. The
# composer scrubs these out of prompts; a direction carrying one would simply reintroduce
# it on the next substitution, so it is caught here too.
_GENRE_WORDS = re.compile(r"\b(festive|festival|holiday|seasonal)\b", re.IGNORECASE)

# A scene must be empty. These are the ways a model puts something in it anyway.
_POPULATED = re.compile(r"\b(person|people|man|woman|model|hand|hands|face|crowd)\b",
                        re.IGNORECASE)


def _sanitise(direction: ArtDirection, brief: DesignBrief, seed: int) -> ArtDirection:
    """Repair the direction rather than failing the request."""
    fallback = heuristic_direction(brief, seed=seed)

    direction.scene = _clean_scene(direction.scene) or fallback.scene
    direction.texture = _clean_scene(direction.texture) or fallback.texture
    direction.lighting = " ".join(direction.lighting.split()) or fallback.lighting
    direction.subject_treatment = (" ".join(direction.subject_treatment.split())
                                   or fallback.subject_treatment)
    direction.prop = " ".join(direction.prop.split()) or fallback.prop

    # Motifs need no repair here: `MotifChoice` constrains each family to the members
    # the renderer has builders for, so a model that invents one fails validation and the
    # stage degrades to the heuristic director rather than shipping a slot that renders
    # to an empty path. `motif_assignment` re-checks membership before substituting, for
    # the case of a direction built by hand.
    return direction


def _clean_scene(scene: str) -> str:
    """Strip genre words and drop any clause that populates the frame."""
    scene = _GENRE_WORDS.sub("ornamental", scene)
    clauses = [c.strip() for c in scene.split(",")]
    kept = [c for c in clauses if c and not _POPULATED.search(c)]
    return " ".join(", ".join(kept).split())
