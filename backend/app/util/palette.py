"""Turning colour *words* into a designed palette — IMPLEMENTATION_PLAN §1.1, §1.3.

Users name colours the way people talk: "gold and deep blue", "sage green", "off-white".
Two things then go wrong if those words are taken literally.

The first is vocabulary. The obvious move is the CSS keyword table, and it is a trap:
CSS `gold` is `#FFD700`, a saturated primary yellow that reads as a highlighter pen, and
CSS `darkblue` is `#00008B`, a pure-blue that no designer has ever specified. A prompt
asking for "elegant gold and deep blue" rendered through CSS keywords produces exactly
the poster a non-designer produces on their first attempt. `NAMED_COLORS` below is a
designer's vocabulary instead — metallics get their real muted chroma, "deep blue" lands
on a navy, and the qualifiers "deep", "light", "muted" and so on modify a base hue
rather than selecting a different keyword.

The second is ordering. `expand()` treats `palette[0]` as the canvas ground and the last
entry as the accent, but a user listing colours is not ranking them — "gold and deep
blue" means a gold accent on a blue ground, not a gold canvas. `order_palette` decides
which named colour is the ground from the design's mood and from the colours themselves,
which is the difference between a jewellery ad and a hazard sign.
"""

from __future__ import annotations

import re

from app.util.color import (
    adjust_lightness,
    chroma_of,
    contrast_ratio,
    delta_e,
    parse_hex,
    relative_luminance,
    saturation,
    to_hex,
)

__all__ = ["NAMED_COLORS", "complete_palette", "dedupe_palette", "order_palette",
           "resolve_color_word", "resolve_palette_words"]


# A designer's vocabulary, not the CSS keyword table. Where the two disagree the CSS
# value is the wrong one — see the module docstring.
NAMED_COLORS: dict[str, str] = {
    # neutrals
    "white": "#FFFFFF", "off-white": "#F7F4EF", "offwhite": "#F7F4EF",
    "ivory": "#F5EFE2", "cream": "#F3E9D6", "bone": "#EDE7DC", "eggshell": "#F2EDE4",
    "black": "#0B0B0D", "ink": "#101014", "charcoal": "#1E2024", "graphite": "#2A2D33",
    "grey": "#8A8F98", "gray": "#8A8F98", "silver": "#C6CBD2", "slate": "#47525E",
    "stone": "#B7B2A8", "sand": "#DFD3BE", "taupe": "#B4A899", "greige": "#D6CFC4",
    # metallics — the ones a literal table gets most wrong
    "gold": "#C9A227", "golden": "#C9A227", "old-gold": "#B08D2A",
    "antique-gold": "#A8842C", "champagne": "#E3CFA4", "brass": "#B5892F",
    "bronze": "#9C6B3C", "copper": "#B06A3B", "rose-gold": "#C98878",
    "platinum": "#D7D9DB", "pewter": "#8D9196", "gunmetal": "#3A4048",
    # blues
    "blue": "#2457C5", "navy": "#111E3C", "deep-blue": "#14264F", "midnight": "#0D1730",
    "royal-blue": "#1E3FA8", "cobalt": "#1B45C4", "sky-blue": "#7EB6E8",
    "powder-blue": "#BBD4E8", "teal": "#126F72", "petrol": "#12414C",
    "turquoise": "#1FA6A2", "cyan": "#22C7D6", "indigo": "#37339B",
    "denim": "#3A5F8A", "steel-blue": "#4C7796", "ice-blue": "#DCE9F2",
    # greens
    "green": "#2E7D4F", "emerald": "#0F7A52", "forest": "#1E4632", "forest-green": "#1E4632",
    "bottle-green": "#123B2B", "olive": "#6B6B32", "sage": "#9CAE93", "mint": "#A9DCC4",
    "moss": "#5C6B43", "lime": "#8FBF3F", "pine": "#1B3A2F", "eucalyptus": "#6F8F7C",
    # reds / pinks
    "red": "#C62B28", "crimson": "#A81F35", "scarlet": "#D33B27", "maroon": "#6B1D24",
    "burgundy": "#5C1A2B", "wine": "#5A1B2E", "oxblood": "#4A161C", "cherry": "#B2213A",
    "pink": "#E389A8", "blush": "#EBC3C1", "rose": "#D18A92", "fuchsia": "#C23D82",
    "magenta": "#B62B7A", "coral": "#E4705A", "salmon": "#E79480",
    # oranges / yellows / browns
    "orange": "#E0702A", "burnt-orange": "#B85A22", "amber": "#D99A28", "ochre": "#C08A2E",
    "mustard": "#C79A1E", "yellow": "#E8C22B", "butter": "#F0DFA0", "honey": "#D8A93C",
    "terracotta": "#B4623F", "rust": "#9E4A28", "brown": "#6B4A32", "chocolate": "#4A3123",
    "coffee": "#3D2C22", "caramel": "#9C6A3A", "tan": "#C49A6C", "khaki": "#B2A47C",
    # purples
    "purple": "#6B3FA0", "violet": "#7A45C4", "plum": "#5B2B4E", "aubergine": "#3A1F35",
    "lavender": "#C3B4E0", "lilac": "#CBB6DE", "mauve": "#A8859B", "grape": "#4C2A68",
}

# Qualifiers modify a base hue instead of selecting a different keyword, so "deep teal",
# "soft teal" and "muted teal" all stay the same colour family.
_LIGHTNESS_QUALIFIERS: dict[str, float] = {
    "deep": 0.62, "dark": 0.62, "rich": 0.74, "midnight": 0.45, "jet": 0.35,
    "light": 1.38, "pale": 1.52, "soft": 1.28, "pastel": 1.55, "baby": 1.5,
    "bright": 1.12, "vivid": 1.05, "electric": 1.1, "neon": 1.15,
}
_CHROMA_QUALIFIERS: dict[str, float] = {
    "muted": 0.55, "dusty": 0.5, "washed": 0.45, "faded": 0.5, "soft": 0.78,
    "pastel": 0.5, "vivid": 1.45, "bright": 1.25, "electric": 1.6, "neon": 1.7,
    "rich": 1.18, "deep": 1.1,
}

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _normalise_hex(value: str) -> str | None:
    match = _HEX_RE.match(value.strip())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return f"#{digits.upper()}"


def _scale_chroma(color: str, factor: float) -> str:
    """Push a colour toward or away from its own grey, holding luminance."""
    if abs(factor - 1.0) < 1e-3:
        return color
    r, g, b = parse_hex(color)
    grey = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return to_hex(tuple(grey + (channel - grey) * factor for channel in (r, g, b)))


def resolve_color_word(word: str) -> str | None:
    """One colour word or phrase -> hex. Returns None when it names no colour.

    Hex passes through untouched; a phrase is read right to left, so the last colour
    noun is the base and everything before it is a qualifier ("deep muted teal").
    """
    raw = (word or "").strip().lower()
    if not raw:
        return None
    direct = _normalise_hex(raw)
    if direct:
        return direct

    tokens = [t for t in re.split(r"[\s_/]+", raw.replace("-", " ")) if t]
    if not tokens:
        return None

    # Try the longest hyphenated compound first: "rose gold" is not a kind of gold.
    base_index: int | None = None
    base: str | None = None
    for start in range(len(tokens)):
        compound = "-".join(tokens[start:])
        if compound in NAMED_COLORS:
            base, base_index = NAMED_COLORS[compound], start
            break
    if base is None:
        for index in range(len(tokens) - 1, -1, -1):
            token = tokens[index].rstrip("s")
            if token in NAMED_COLORS:
                base, base_index = NAMED_COLORS[token], index
                break
    if base is None or base_index is None:
        return None

    for qualifier in tokens[:base_index]:
        if qualifier in _CHROMA_QUALIFIERS:
            base = _scale_chroma(base, _CHROMA_QUALIFIERS[qualifier])
        if qualifier in _LIGHTNESS_QUALIFIERS:
            base = adjust_lightness(base, _LIGHTNESS_QUALIFIERS[qualifier])
    return base


def resolve_palette_words(words: list[str] | None) -> list[str]:
    """Resolve a brief's colour list, dropping entries that name no colour."""
    out: list[str] = []
    for word in words or []:
        resolved = resolve_color_word(str(word))
        if resolved and resolved not in out:
            out.append(resolved)
    return out


# Moods whose ground is dark. A festive or premium design on a light ground throws away
# the one thing that makes gold read as gold.
_DARK_GROUND_MOODS = frozenset({
    "festive", "premium", "dark", "luxury", "elegant", "moody", "dramatic", "night",
    "noir", "cinematic", "tech", "bold",
})
_LIGHT_GROUND_MOODS = frozenset({
    "minimal", "clean", "airy", "fresh", "natural", "playful", "soft", "pastel",
})


def _is_metallic(color: str) -> bool:
    """Gold, brass, copper and friends: mid-luminance, warm, moderately chromatic.

    A metallic is an accent by nature — it has no body as a field colour, and a canvas
    filled with one looks like an error rather than a decision.
    """
    r, _g, b = parse_hex(color)
    luminance = relative_luminance(color)
    return 0.10 < luminance < 0.62 and r > b and chroma_of(color) > 0.12


def order_palette(palette: list[str], *, moods: list[str] | None = None,
                  prefer_dark: bool | None = None) -> list[str]:
    """Reorder a palette so index 0 is the ground and the last entry is the accent.

    The composer and the user both hand over colours in the order they thought of them,
    which is never the order `expand()` needs. Ground is chosen by mood first and by
    luminance spread second; the accent is the most chromatic colour that is not the
    ground; the rest sit between them in luminance order so `on-primary` has a
    mid-tone to reach for.
    """
    colors = [c for c in dict.fromkeys(palette) if _normalise_hex(c)]
    colors = [_normalise_hex(c) or c for c in colors]
    if len(colors) < 2:
        return colors

    mood_set = {m.strip().lower() for m in (moods or [])}
    if prefer_dark is None:
        if mood_set & _DARK_GROUND_MOODS and not mood_set & _LIGHT_GROUND_MOODS:
            prefer_dark = True
        elif mood_set & _LIGHT_GROUND_MOODS:
            prefer_dark = False

    # A metallic is never the ground while any non-metallic is available.
    grounds = [c for c in colors if not _is_metallic(c)] or list(colors)
    if prefer_dark is True:
        ground = min(grounds, key=relative_luminance)
    elif prefer_dark is False:
        ground = max(grounds, key=relative_luminance)
    else:
        # No steer from mood: take whichever extreme is furthest from the middle, which
        # is the colour most obviously intended as a field rather than a mark.
        darkest, lightest = (min(grounds, key=relative_luminance),
                             max(grounds, key=relative_luminance))
        ground = (darkest if abs(relative_luminance(darkest) - 0.35)
                  > abs(relative_luminance(lightest) - 0.35) else lightest)

    rest = [c for c in colors if c != ground]
    if not rest:
        return [ground]

    # The accent must be visible on the ground; a chromatic colour that disappears
    # against it is decoration the viewer never sees.
    def accent_score(color: str) -> float:
        legibility = min(contrast_ratio(color, ground) / 4.5, 1.0)
        return saturation(color) * (0.4 + 0.6 * legibility)

    accent = max(rest, key=accent_score)
    middles = sorted((c for c in rest if c != accent),
                     key=relative_luminance,
                     reverse=relative_luminance(ground) < 0.4)
    return [ground, *middles, accent]


# A palette shorter than this cannot express a ground, a mid-tone and an accent, which is
# the minimum a layout needs: something to sit on, something to read as, something to
# point with.
MIN_PALETTE = 3


def complete_palette(palette: list[str], *, moods: list[str] | None = None) -> list[str]:
    """Extend an under-length palette with tones derived from the ones already in it.

    Users name two colours far more often than three — "gold and deep blue", "black and
    white" — and a two-colour palette leaves every layout with nothing between its ground
    and its accent, so supporting copy has to be set in either the background colour or
    the accent. The colours added here are derived from the ground rather than invented,
    so the result still reads as the palette that was asked for: a warm ground gets a warm
    off-white, a cool one gets a cool one.

    Assumes `order_palette` ordering (ground first, accent last) and preserves it.
    """
    colors = [c for c in dict.fromkeys(palette) if _normalise_hex(c)]
    colors = [_normalise_hex(c) or c for c in colors]
    if len(colors) >= MIN_PALETTE:
        return colors
    if not colors:
        return colors

    ground = colors[0]
    accent = colors[-1] if len(colors) > 1 else None
    dark_ground = relative_luminance(ground) < 0.35

    while len(colors) < MIN_PALETTE:
        mid = _mid_tone(ground, accent, dark_ground, avoid=colors)
        # Insert before the accent so the accent stays last.
        colors.insert(len(colors) - 1 if len(colors) > 1 else 1, mid)
    return colors


def _mix(a: str, b: str, t: float) -> str:
    """Blend two colours in sRGB. Crude, and right for tints and shades."""
    ar, ag, ab = parse_hex(a)
    br, bg, bb = parse_hex(b)
    return to_hex((ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t))


def _mid_tone(ground: str, accent: str | None, dark_ground: bool,
              *, avoid: list[str]) -> str:
    """A tint or shade of the ground that keeps a trace of its hue.

    Mixing toward white or black rather than scaling lightness is what preserves the
    hue: scaling a navy up by enough to read as a light colour clips every channel and
    lands on pure white, which belongs to no palette in particular. A cream mixed out of
    the navy still looks like it came from this design.
    """
    target = "#FFFFFF" if dark_ground else "#0B0B0D"
    for ratio in (0.88, 0.94, 0.78, 0.97):
        candidate = _mix(ground, target, ratio)
        if contrast_ratio(candidate, ground) >= 4.5 and candidate not in avoid:
            return candidate
    if accent is not None:
        fallback = _mix(accent, target, 0.7)
        if fallback not in avoid:
            return fallback
    return target if target not in avoid else _mix(ground, target, 0.6)


# CIE76 distance below which two palette entries are the same colour as far as a viewer
# is concerned. `delta_e`'s own docstring puts "clearly distinct" at 25; this is set
# lower so genuinely close but intentional pairs (a ground and its own deeper shade)
# survive, and only the near-duplicates go.
MIN_PALETTE_DELTA = 12.0


def dedupe_palette(palette: list[str]) -> list[str]:
    """Drop entries that are perceptually the same colour as one already kept.

    A palette of five is worth having only if it contains five colours. A model asked for
    three-to-five hexes will happily return `#17212F`, `#1A2635` and `#1A232C` — three
    navies no viewer can tell apart — and every role the layout resolves against that
    palette then lands on effectively the same colour, so the design reads as two colours
    with a broken accent rather than as five.

    The first and last entries are load-bearing (`expand()` reads them as the ground and
    the accent) so both survive; it is the middle that gets thinned.
    """
    colors = [c for c in dict.fromkeys(palette) if _normalise_hex(c)]
    colors = [_normalise_hex(c) or c for c in colors]
    if len(colors) <= 2:
        return colors

    ground, accent, middles = colors[0], colors[-1], colors[1:-1]
    kept = [ground]
    for color in middles:
        if all(delta_e(color, other) >= MIN_PALETTE_DELTA for other in [*kept, accent]):
            kept.append(color)
    kept.append(accent)
    return kept
