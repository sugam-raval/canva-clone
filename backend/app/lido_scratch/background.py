"""Art direction for the generated background.

The old prompt was whatever sentence the model happened to write, plus a safe-zone
clause. That is why generated pages looked plain: asked for "a background for a food
menu", an image model returns a photograph of a restaurant — a literal, evenly-detailed
scene with no graphic idea in it, no palette discipline and nothing for type to sit
against. The posters this pipeline is trying to match are not photographs at all. They
are *designed grounds*: a deep field, one torn brush sweep of the accent colour, a
halftone block in a corner, and a lot of deliberate emptiness.

So the model no longer writes the background prompt. It picks a `style` — a named
graphic treatment it can reason about — and everything else is assembled here from
parts that are known to work:

    recipe(style, palette)  +  motif  +  safe zone  +  quality tail
    negative(style)

The palette is injected by name *and* by hex ("deep charcoal green #12170F"), because a
diffusion model reads the name and ignores the hex, while the name alone drifts a whole
family away from the design's actual colours. Injecting the palette is also what keeps
the background, the type and the ornament looking like one design rather than three.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.lido_corpus.assets_ai import NEGATIVE_TEXT

from . import palette as pal

BackgroundStyle = Literal[
    "flat",
    "brush-grunge",
    "paint-splash",
    "gradient-glow",
    "duotone-texture",
    "geometric-shapes",
    "halftone-pop",
    "organic-blob",
    "luxury-marble",
    "neon-grid",
    "photo-scene",
    "studio-backdrop",
]


@dataclass(frozen=True)
class Recipe:
    """One background treatment. `template` is formatted with the palette's names."""

    summary: str
    """One line, shown to the design model as the menu it chooses from."""

    template: str
    negatives: str = ""
    photographic: bool = False
    """True when the result is a real photograph — the only case where a text scrim is
    still required, because a photo's local contrast cannot be predicted."""


#: The quality floor every prompt ends with. Two jobs: force *graphic design* output
#: rather than a stock photograph, and force the empty space a layout needs.
_QUALITY_TAIL = (
    "professional social media poster background artwork, high-end graphic design, "
    "crisp clean edges, rich deep contrast, deliberate composition, generous empty "
    "negative space for typography, premium print quality, 4k"
)

#: Applies to every style. The specific failure modes of a *background* — as opposed to
#: a photo of a subject — are clutter, mush, and an evenly-busy frame with nowhere to
#: put a headline.
_BASE_NEGATIVES = (
    "cluttered, busy, noisy, evenly detailed, low contrast, muddy colours, washed out, "
    "flat lighting, grainy, blurry, jpeg artifacts, amateur, clip art, stock photo "
    "collage, drop shadows, bevels, gradients banding"
)

RECIPES: dict[str, Recipe] = {
    "flat": Recipe(
        summary="no image at all — the flat palette ground. Fast, and the right answer "
                "when a cutout subject and the ornament layer are already carrying the "
                "page",
        template="",
    ),
    "brush-grunge": Recipe(
        summary="a torn dry-brush sweep of the accent across a deep ground — the bold, "
                "high-energy poster look used for food, sale and sports posts",
        template=(
            "abstract graphic poster background: a deep solid {ground_name} ({ground}) "
            "field, with one bold hand-painted dry brush stroke of {accent_name} "
            "({accent}) sweeping across it, rough torn edges, visible bristle texture, "
            "a scatter of small paint specks at its edge, subtle {support_name} "
            "({support}) grunge scuff in one corner"
        ),
        negatives="smooth vector gradient, airbrush, glossy, photographic",
    ),
    "paint-splash": Recipe(
        summary="ink and paint splatter arcs on a dark ground — energetic, editorial, "
                "good for launches and youth brands",
        template=(
            "abstract graphic poster background: deep {ground_name} ({ground}) ground "
            "with a dynamic arc of {accent_name} ({accent}) ink splatter and paint "
            "droplets sweeping through one side, fine spray particles, crisp liquid "
            "edges, {support_name} ({support}) secondary splash far smaller"
        ),
        negatives="muddy blending, watercolour bleed, photographic",
    ),
    "gradient-glow": Recipe(
        summary="a deep gradient field with a soft light bloom and vignette — calm, "
                "modern, the safest ground for a lot of type",
        template=(
            "abstract gradient background: rich {ground_name} ({ground}) deepening to "
            "near-black at the edges, one soft diffused glow of {accent_name} "
            "({accent}) light blooming from one side, smooth luminous falloff, subtle "
            "film grain, strong vignette"
        ),
        negatives="hard edges, banding, visible shapes, text",
    ),
    "duotone-texture": Recipe(
        summary="a two-colour textured surface — concrete, paper or linen — quiet and "
                "expensive-looking under bold type",
        template=(
            "duotone textured surface background in {ground_name} ({ground}) and "
            "{support_name} ({support}): fine concrete and paper grain, soft directional "
            "light raking across it, faint {accent_name} ({accent}) tint in the "
            "highlights, uniform and calm"
        ),
        negatives="busy pattern, objects, props, photographic subject",
    ),
    "geometric-shapes": Recipe(
        summary="flat geometric composition — arcs, circles and bands pushed to the "
                "edges — modern, corporate, tech",
        template=(
            "flat vector geometric background: deep {ground_name} ({ground}) field with "
            "large simple {accent_name} ({accent}) arcs, circles and diagonal bands "
            "arranged along the edges of the frame, a few thin {support_name} "
            "({support}) line accents, perfectly flat colour, bauhaus poster geometry, "
            "wide open middle"
        ),
        negatives="3d render, shading, texture, photographic, crowded pattern",
    ),
    "halftone-pop": Recipe(
        summary="retro halftone dot gradients and comic-print texture — loud, playful, "
                "sale-poster energy",
        template=(
            "retro pop-art background: {ground_name} ({ground}) ground with large "
            "{accent_name} ({accent}) halftone dot gradients fading across two corners, "
            "screen-print misregistration texture, a single bold {support_name} "
            "({support}) diagonal band, vintage risograph feel"
        ),
        negatives="photographic, smooth gradient, 3d",
    ),
    "organic-blob": Recipe(
        summary="soft organic blob and wave shapes — friendly, contemporary, good for "
                "wellness, apps and pastel brands",
        template=(
            "modern abstract background: soft rounded organic blob and wave shapes in "
            "{accent_name} ({accent}) and {support_name} ({support}) drifting across a "
            "{ground_name} ({ground}) ground, flat matte colour, gentle overlap, large "
            "calm empty area in the middle"
        ),
        negatives="sharp edges, photographic, busy detail",
    ),
    "luxury-marble": Recipe(
        summary="marble, silk or deep velvet with metallic veining — premium, fashion, "
                "jewellery, invitations",
        template=(
            "luxury background: deep {ground_name} ({ground}) marble and soft silk "
            "drapery, delicate {accent_name} ({accent}) metallic veining catching the "
            "light, subtle {support_name} ({support}) shadow depth, refined and "
            "restrained, elegant negative space"
        ),
        negatives="gaudy, plastic, neon, busy veining",
    ),
    "neon-grid": Recipe(
        summary="a dark perspective grid with neon glow and light streaks — tech, "
                "gaming, crypto, product launches",
        template=(
            "dark tech background: {ground_name} ({ground}) space with a faint "
            "perspective wireframe grid, {accent_name} ({accent}) neon glow lines and "
            "soft light streaks along one edge, {support_name} ({support}) rim light, "
            "atmospheric haze, deep blacks"
        ),
        negatives="daylight, clutter, photographic people, text",
    ),
    "photo-scene": Recipe(
        summary="an actual photograph of a place or surface. Use only when the design "
                "genuinely needs a real setting behind it — it is the least designed "
                "of the options and always costs a scrim behind the type",
        template=(
            "editorial photograph of {motif}, shallow depth of field, soft directional "
            "light, muted {ground_name} ({ground}) tones, {accent_name} ({accent}) "
            "colour accents in the scene, uncluttered composition, wide empty area for "
            "text overlay"
        ),
        negatives="busy background, crowds, signage, harsh flash",
        photographic=True,
    ),
    "studio-backdrop": Recipe(
        summary="a seamless studio backdrop with a single spotlight — the neutral, "
                "product-shot ground for a cutout subject",
        template=(
            "seamless studio backdrop in {ground_name} ({ground}), one soft spotlight "
            "pooling in the centre and falling off to deep shadow at the edges, subtle "
            "{accent_name} ({accent}) rim light, smooth sweep floor, no props"
        ),
        negatives="props, furniture, people, clutter",
        photographic=True,
    ),
}

#: Where a design lands when nobody chose a style — the treatment that suits each
#: typographic voice. Never "flat": a flat ground is a deliberate choice, not a default.
DEFAULT_STYLE_FOR_VIBE: dict[str, str] = {
    "geometric": "geometric-shapes",
    "humanist": "gradient-glow",
    "serif-editorial": "duotone-texture",
    "display-bold": "halftone-pop",
    "script": "luxury-marble",
    "impact": "brush-grunge",
    "corporate": "geometric-shapes",
    "tech-modern": "neon-grid",
    "luxury-serif": "luxury-marble",
    "casual-hand": "paint-splash",
    "retro": "halftone-pop",
    "condensed-sport": "brush-grunge",
    "street-bold": "halftone-pop",
    "editorial-fat": "duotone-texture",
    "playful-fun": "organic-blob",
}

#: The safe zone is not just "less detail there" — it is "none of the accent there".
#: The accent is both the colour the ground is painted with and the colour the headline
#: is set in, so wherever the two meet the headline disappears into its own background.
#: A real page came back with the headline in accent gold sitting on the accent brush.
_ACCENT_EXCLUSION = ("no brush marks, no splashes and no accent colour at all may enter "
                     "that area — it stays flat ground colour edge to edge")

_SAFE_ZONE_HINT: dict[str, str] = {
    "top": "keep the top third completely empty — flat, uninterrupted colour for a "
           f"headline to sit on, {_ACCENT_EXCLUSION} — and push all detail into the "
           "lower two-thirds",
    "bottom": "keep the bottom third completely empty — flat, uninterrupted colour for "
              f"type, {_ACCENT_EXCLUSION} — and push all detail into the upper "
              "two-thirds",
    "left": "keep the left third completely empty — flat, uninterrupted colour for "
            f"type, {_ACCENT_EXCLUSION} — and push all detail to the right",
    "right": "keep the right third completely empty — flat, uninterrupted colour for "
             f"type, {_ACCENT_EXCLUSION} — and push all detail to the left",
    "center": "keep the centre of the frame completely empty — flat, uninterrupted "
              f"colour for type, {_ACCENT_EXCLUSION} — and hold all detail to the "
              "outer edges",
}


def recipe_for(style: str) -> Recipe:
    return RECIPES.get(style) or RECIPES["gradient-glow"]


def is_photographic(style: str) -> bool:
    """Whether text over this background needs a scrim to stay legible."""
    return recipe_for(style).photographic


def style_menu() -> str:
    """The style list as the design model sees it, so the prompt cannot drift from
    the recipes actually implemented here."""
    return "\n".join(f"  - {key}: {recipe.summary}" for key, recipe in RECIPES.items())


def _motif_clause(motif: str | None, photographic: bool) -> str:
    """How the brief's subject enters the background.

    In a graphic treatment the subject is a hint at most — a background that draws its
    subject competes with the cutout or photo element that is already showing it, and
    ends up as the second-best picture of the same thing. In a photographic treatment
    the subject *is* the image, so it goes into the template directly instead.
    """
    if photographic or not motif:
        return ""
    return (f" Abstractly evoke {motif} in the shapes and colour only — never draw it "
            f"literally, never show the object itself.")


def build_prompt(
    style: str,
    colors: list[str],
    *,
    motif: str | None = None,
    safe_zone: str = "none",
) -> str | None:
    """The finished image prompt, or None for a style that generates no image."""
    recipe = recipe_for(style)
    if not recipe.template:
        return None

    ground = colors[0] if colors else "#101418"
    accent = pal.accent_of(colors)
    support = colors[2] if len(colors) > 2 else accent

    body = recipe.template.format(
        ground=ground, accent=accent, support=support,
        ground_name=pal.color_name(ground),
        accent_name=pal.color_name(accent),
        support_name=pal.color_name(support),
        motif=motif or "a clean uncluttered surface",
    )

    parts = [body + "."]
    motif_clause = _motif_clause(motif, recipe.photographic)
    if motif_clause:
        parts.append(motif_clause.strip())
    hint = _SAFE_ZONE_HINT.get(safe_zone)
    if hint:
        parts.append(f"Composition: {hint}.")
    parts.append(_QUALITY_TAIL + ".")
    return " ".join(parts)


def negative_prompt(style: str) -> str:
    recipe = recipe_for(style)
    parts = [NEGATIVE_TEXT, _BASE_NEGATIVES]
    if recipe.negatives:
        parts.append(recipe.negatives)
    return ", ".join(parts)
