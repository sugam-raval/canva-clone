"""Palette curation for a generated design.

`_assign_colors` in `layout.py` can only pick from what the palette gives it, so the
palette is where a design's whole colour quality is decided — and an LLM asked for
"3-5 hex colours" reliably returns a set that is *plausible* and *flat*: three muted
mid-tones with no deep ground, no vivid accent, and nothing near-white to set type in.
That produces exactly the plain, washed-out look this module exists to fix.

The rule a designer actually follows for this kind of poster is a four-part structure,
and every palette leaving here has all four:

- **ground** — a deep, near-black-but-tinted field the page sits on. Deep grounds are
  what make an accent read as vivid; a mid-grey ground makes every accent look dusty.
- **accent** — one high-chroma colour, reserved. The lime on the green food poster, the
  red on the burger poster. Exactly one thing on the page gets it at full strength.
- **support** — a second, quieter colour a step off the accent, for secondary marks.
- **neutrals** — a near-white tinted with the design's own hue (never #FFFFFF flat) and
  a deep shade, so type has somewhere legible to go on any ground in the set.

`refine` keeps whatever of that the model already got right and manufactures the rest
from the model's own hue, so a good palette survives untouched and a weak one is
repaired rather than replaced. Only a palette with nothing usable in it at all falls
back to a curated preset.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

from app.util.color import (
    contrast_ratio,
    delta_e,
    parse_hex,
    relative_luminance,
    saturation,
    to_hex,
)

#: A ground darker than this reads as a real field rather than a mid-tone wash. Above
#: it, accents lose their punch and the design goes muddy — the single most common
#: failure in a model-written palette.
GROUND_MAX_LUMINANCE = 0.22

#: An accent below this chroma is a neutral wearing a hue, not an accent.
ACCENT_MIN_SATURATION = 0.45

BAND_MIN_CONTRAST = 1.35
"""How far the contact band must separate from the ground. A band is a tonal step, not
a panel — far below this it vanishes, far above it reads as a second page."""

#: The near-white and deep shade every palette ends with, as absolute HLS lightness.
TINT_LIGHTNESS = 0.94
SHADE_LIGHTNESS = 0.07


@dataclass(frozen=True)
class Preset:
    """A curated palette, in the order `refine` produces: ground, accent, support."""

    name: str
    ground: str
    accent: str
    support: str
    tags: tuple[str, ...]


#: Last-resort presets, one per broad subject family. These are only reached when the
#: model returned no usable colour at all — normally `refine` repairs the model's own
#: palette instead, because a preset cannot know that the brief was about mangoes.
PRESETS: tuple[Preset, ...] = (
    Preset("fresh-food", "#12170F", "#A8E063", "#4B8A2B",
           ("food", "restaurant", "menu", "organic", "fresh", "healthy", "salad")),
    Preset("hot-food", "#140A0A", "#E01F26", "#F2A93B",
           ("burger", "pizza", "grill", "spicy", "fast food", "bbq", "deal")),
    Preset("cafe-warm", "#1A1008", "#E8A33D", "#8C5A2B",
           ("coffee", "cafe", "bakery", "dessert", "warm", "cozy")),
    Preset("luxe-gold", "#0E0D0B", "#D4AF63", "#7A6134",
           ("luxury", "premium", "jewellery", "fashion", "gala", "elegant")),
    Preset("electric-tech", "#0A0E1A", "#3DDC97", "#3B6CF6",
           ("tech", "startup", "saas", "app", "fintech", "ai", "crypto")),
    Preset("sport-energy", "#0D0F12", "#F5E14C", "#1FA5E0",
           ("gym", "fitness", "sport", "training", "energy", "run")),
    Preset("sale-punch", "#101010", "#FF3B6B", "#FFC53D",
           ("sale", "discount", "offer", "black friday", "shopping", "promo")),
    Preset("calm-editorial", "#141A20", "#7FB4D9", "#C9A26B",
           ("business", "corporate", "hiring", "editorial", "finance", "clinic")),
)

#: Hue centres (degrees) for the descriptive names handed to the image model. A hex is
#: meaningless to a diffusion model; "deep charcoal with a lime accent" is not.
_HUE_NAMES: tuple[tuple[float, str], ...] = (
    (0, "red"), (18, "vermilion"), (35, "orange"), (48, "amber"), (58, "yellow"),
    (75, "lime"), (100, "green"), (150, "emerald"), (175, "teal"), (195, "cyan"),
    (215, "azure"), (235, "blue"), (255, "indigo"), (275, "violet"), (295, "purple"),
    (320, "magenta"), (340, "crimson"),
)


def _hls(color: str) -> tuple[float, float, float]:
    r, g, b = parse_hex(color)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)


def _from_hls(hue: float, lightness: float, sat: float) -> str:
    return to_hex(tuple(c * 255 for c in colorsys.hls_to_rgb(hue % 1.0, lightness, sat)))


def _at_lightness(color: str, lightness: float, *, sat_scale: float = 1.0) -> str:
    hue, _l, sat = _hls(color)
    return _from_hls(hue, lightness, min(1.0, sat * sat_scale))


def is_hex(value: str | None) -> bool:
    if not value or not isinstance(value, str) or not value.startswith("#"):
        return False
    body = value[1:]
    return len(body) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in body)


def color_name(color: str) -> str:
    """A short descriptive name — "deep charcoal", "vivid lime" — for image prompts."""
    hue, light, sat = _hls(color)
    if sat < 0.12:
        if light < 0.12:
            return "near-black"
        if light < 0.32:
            return "charcoal grey"
        if light < 0.62:
            return "mid grey"
        if light < 0.88:
            return "light grey"
        return "off-white"
    degrees = hue * 360
    family = min(_HUE_NAMES, key=lambda pair: min(
        abs(degrees - pair[0]), 360 - abs(degrees - pair[0])))[1]
    if light < 0.16:
        return f"near-black {family}"
    if light < 0.34:
        return f"deep {family}"
    if light > 0.82:
        return f"pale {family}"
    if sat > 0.65:
        return f"vivid {family}"
    return f"muted {family}"


def _chroma_score(color: str, ground: str) -> float:
    """How well `color` works as *the* accent on `ground`: vivid and visible."""
    return saturation(color) * min(contrast_ratio(ground, color) / 4.5, 1.6)


def _pick_ground(candidates: list[str]) -> str | None:
    """The darkest candidate, if any is dark enough to be a real ground."""
    dark = [c for c in candidates if relative_luminance(c) <= GROUND_MAX_LUMINANCE]
    if not dark:
        return None
    return min(dark, key=relative_luminance)


def _deepen(color: str) -> str:
    """Pull a colour down to a usable ground, keeping its hue and most of its chroma.

    A model that returns a mid-grey or a pastel as its first colour was describing the
    design's *hue family*, not its value — so the hue is what survives.
    """
    hue, _l, sat = _hls(color)
    return _from_hls(hue, 0.085, min(0.55, max(0.10, sat)))


def _derive_accent(ground: str, subject: str) -> str:
    """Manufacture a vivid accent for a ground that came with none.

    A near-neutral ground carries no hue to work from, so the subject's own words pick
    the preset whose accent belongs on it (a burger poster gets red, not whatever hue
    happened to survive rounding in a near-black). A ground with real hue instead gets
    a colour rotated well off it — far enough to read as a deliberate accent rather
    than a lighter version of the ground.
    """
    hue, _l, sat = _hls(ground)
    if sat < 0.15:
        return match_preset(subject).accent
    return _from_hls(hue + 0.42, 0.58, 0.82)


def match_preset(text: str) -> Preset:
    """The preset whose tags best match a subject/mood string."""
    haystack = (text or "").lower()
    best, best_hits = PRESETS[0], 0
    for preset in PRESETS:
        hits = sum(1 for tag in preset.tags if tag in haystack)
        if hits > best_hits:
            best, best_hits = preset, hits
    return best


def accent_of(palette: list[str]) -> str:
    """The reserved accent — the colour `decor` and the background prompt build on.

    `refine` puts it at index 1, so a refined palette is simply read, not re-scored:
    scoring again would let a brighter *support* colour quietly take the accent's job
    and undo the one decision the palette structure exists to make. Only a palette
    that never went through `refine` falls back to picking the most accent-like
    colour in it.
    """
    if len(palette) < 2:
        return palette[0] if palette else "#FFFFFF"
    ground, candidate = palette[0], palette[1]
    if saturation(candidate) >= ACCENT_MIN_SATURATION:
        return candidate
    return max(palette[1:], key=lambda c: _chroma_score(c, ground))


def tint_of(palette: list[str]) -> str:
    """The near-white. Type colour of last resort, and the light half of any duotone."""
    if not palette:
        return "#FFFFFF"
    return max(palette, key=relative_luminance)


def _with_neutrals(core: list[str], extras: list[str] | None = None) -> list[str]:
    """Close a ground/accent/support triple with the two neutrals every design needs."""
    ground, accent = core[0], core[1]
    # Tinted, never flat: a near-white carrying the design's own hue is what stops a
    # generated page reading as a slide deck.
    tint = _at_lightness(accent, TINT_LIGHTNESS, sat_scale=0.16)
    shade = _at_lightness(ground, SHADE_LIGHTNESS, sat_scale=0.8)

    ordered = [*core, tint, shade]
    # Anything else the model asked for is kept behind the structural five, so a
    # deliberate fifth colour is still available to `_assign_colors`.
    for color in extras or []:
        if color not in ordered and all(delta_e(color, other) > 12.0 for other in ordered):
            ordered.append(color)
    return ordered[:7]


def band_of(colors: list[str]) -> str:
    """A colour that reads as a distinct band against the ground.

    The contact band cannot simply take the palette's deepest shade: on the deep ground
    these designs are built on, that is the ground again a couple of percent darker and
    the band disappears. It has to be a deliberate step away from the ground in the
    direction there is room to move.
    """
    ground = colors[0] if colors else "#101418"
    dark = relative_luminance(ground) < 0.3
    # A fixed lightness is not enough on its own: a very dark, very desaturated ground
    # lifted to a fixed 0.19 still lands within a whisker of itself. So the step is
    # widened until the band actually separates from the ground it sits on.
    for offset in (0.0, 0.05, 0.10, 0.18):
        band = _at_lightness(ground, (0.19 + offset) if dark else (0.93 - offset),
                             sat_scale=1.1 if dark else 0.6)
        if contrast_ratio(ground, band) >= BAND_MIN_CONTRAST:
            return band
    return band


def refine(palette: list[str], subject: str = "") -> list[str]:
    """Repair a model-written palette into ground / accent / support / tint / shade.

    Returns at least five colours, ground first. Idempotent: a palette that already has
    the structure comes back with the same colours in the same roles.
    """
    clean: list[str] = []
    for color in palette or []:
        if not is_hex(color):
            continue
        normalised = to_hex(parse_hex(color))
        # Near-duplicates add nothing but crowd out the slots that matter.
        if all(delta_e(normalised, other) > 8.0 for other in clean):
            clean.append(normalised)

    if not clean:
        # Nothing usable came back at all. A preset already *is* the finished
        # structure, so its roles are taken as given rather than re-derived — scoring
        # them would only second-guess a palette that was curated on purpose.
        preset = match_preset(subject)
        return _with_neutrals([preset.ground, preset.accent, preset.support])

    ground = _pick_ground(clean) or _deepen(clean[0])
    rest = [c for c in clean if c != ground]

    accent = max(rest, key=lambda c: _chroma_score(c, ground)) if rest else ""
    if not accent or saturation(accent) < ACCENT_MIN_SATURATION:
        accent = _derive_accent(ground, subject)

    support = ""
    remaining = [c for c in rest if c != accent and delta_e(c, accent) > 22.0]
    if remaining:
        support = max(remaining, key=lambda c: _chroma_score(c, ground))
    if not support:
        # A quieter sibling of the accent: same hue family, darker and less saturated,
        # so it supports the accent instead of competing with it.
        hue, _l, sat = _hls(accent)
        support = _from_hls(hue - 0.06, 0.36, min(0.75, sat * 0.85))

    return _with_neutrals([ground, accent, support], extras=clean)
