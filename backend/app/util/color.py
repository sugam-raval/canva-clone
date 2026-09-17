"""Colour maths shared by the composer (§1.3) and harmonisation (§1.5).

Contrast is WCAG 2.1 relative luminance; perceptual distance is CIEDE2000-ish via
CIE76 in Lab, which is adequate for the "is this accent distinguishable" test in §1.5.1
and much cheaper than full CIEDE2000.
"""

from __future__ import annotations

import colorsys
import math

import numpy as np

RGB = tuple[int, int, int]


def parse_hex(value: str) -> RGB:
    text = (value or "#000000").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) < 6:
        return (0, 0, 0)
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, round(v))) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _linearise(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str | RGB) -> float:
    r, g, b = parse_hex(color) if isinstance(color, str) else color
    return 0.2126 * _linearise(r) + 0.7152 * _linearise(g) + 0.0722 * _linearise(b)


def contrast_ratio(a: str | RGB, b: str | RGB) -> float:
    """WCAG 2.1 contrast ratio, 1.0 (identical) to 21.0 (black on white)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def srgb_to_lab(rgb: RGB) -> tuple[float, float, float]:
    r, g, b = (_linearise(c) for c in rgb)
    # sRGB D65 -> XYZ
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + 16 / 116

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a: str | RGB, b: str | RGB) -> float:
    """CIE76 colour difference. Roughly: <2 imperceptible, >25 clearly distinct."""
    la = srgb_to_lab(parse_hex(a) if isinstance(a, str) else a)
    lb = srgb_to_lab(parse_hex(b) if isinstance(b, str) else b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(la, lb)))


def saturation(color: str | RGB) -> float:
    r, g, b = parse_hex(color) if isinstance(color, str) else color
    return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[1]


def adjust_lightness(color: str, factor: float) -> str:
    """factor > 1 lightens, < 1 darkens, preserving hue and saturation."""
    r, g, b = parse_hex(color)
    h, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    light = max(0.0, min(1.0, light * factor))
    return to_hex(tuple(c * 255 for c in colorsys.hls_to_rgb(h, light, sat)))


def best_contrast(background: str, candidates: list[str]) -> tuple[str, float]:
    """Pick the candidate with the highest contrast against `background`."""
    pool = [c for c in candidates if c and c.startswith("#")] or ["#FFFFFF", "#000000"]
    best = max(pool, key=lambda c: contrast_ratio(background, c))
    return best, contrast_ratio(background, best)


def readable_on(background: str, palette: list[str] | None = None,
                minimum: float = 4.5) -> str:
    """A colour that is legible on `background`.

    Prefers a palette colour that clears the threshold, so designs stay on-palette; only
    falls back to plain white or black when nothing in the palette is readable enough.
    """
    if palette:
        passing = [c for c in palette if contrast_ratio(background, c) >= minimum]
        if passing:
            return max(passing, key=lambda c: contrast_ratio(background, c))
    white, black = contrast_ratio(background, "#FFFFFF"), contrast_ratio(background, "#000000")
    return "#FFFFFF" if white >= black else "#000000"


# --------------------------------------------------------------------------------------
# Harmony
#
# `readable_on` maximises contrast ratio, which is colour-blind in the literal sense: on
# a saturated orange it will happily return a saturated green, because green clears the
# threshold. That is how a Diwali poster ends up with a green headline. Designers do not
# choose type colour that way — they take a tint or shade of the ground, a near-neutral,
# or a colour that is genuinely analogous or genuinely complementary, and they reserve
# chroma for accents. These helpers encode that.
# --------------------------------------------------------------------------------------

# Hue separations, in degrees. Inside ANALOGOUS the candidate shares the ground's family;
# beyond COMPLEMENTARY it is a deliberate opposition. The band between the two is the
# discordant middle.
#
# The analogous window is wide on purpose. Gold on maroon is 54 degrees apart and is one
# of the most reliable pairings there is — a narrower window classes it as a clash. What
# actually goes wrong sits around a quarter turn: orange against green (118), red against
# green (120). That is the band these numbers isolate.
ANALOGOUS_DEGREES = 60.0
COMPLEMENTARY_DEGREES = 140.0

# Below this chroma a colour reads as a neutral and sits against any hue.
NEUTRAL_CHROMA = 0.16


def hue_of(color: str | RGB) -> float:
    """Hue in degrees, 0..360."""
    r, g, b = parse_hex(color) if isinstance(color, str) else color
    return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360.0


def chroma_of(color: str | RGB) -> float:
    """How coloured this is, 0 (grey) to 1. HSV saturation scaled by value, so very dark
    saturated colours correctly read as near-neutral."""
    r, g, b = parse_hex(color) if isinstance(color, str) else color
    _, sat, value = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return sat * value


def hue_distance(a: float, b: float) -> float:
    """Shortest angular distance between two hues, 0..180."""
    delta = abs(a - b) % 360.0
    return 360.0 - delta if delta > 180.0 else delta


def harmony_score(candidate: str, background: str) -> float:
    """0..1 — how comfortably `candidate` sits on `background`, ignoring contrast.

    Neutrals score highest because they are unconditionally safe. Analogous and
    complementary hues score well. The band in between is what makes a design look
    accidental, and is scored down hard.
    """
    chroma = chroma_of(candidate)
    if chroma < NEUTRAL_CHROMA:
        # Neutrals are safe but unremarkable, so they score below a well-judged
        # chromatic pairing rather than above it — otherwise the safe grey wins every
        # comparison and every design drifts to greyscale. A neutral carrying a trace of
        # the ground's hue still beats flat #FFF or #000, which reads as a default.
        return 0.86 if chroma >= 0.02 else 0.80
    # A near-neutral ground imposes no hue of its own, so anything sits on it.
    if chroma_of(background) < NEUTRAL_CHROMA:
        return 0.9

    distance = hue_distance(hue_of(candidate), hue_of(background))
    if distance <= ANALOGOUS_DEGREES:
        base = 0.88
    elif distance >= COMPLEMENTARY_DEGREES:
        base = 0.78
    else:
        # Ramp down into the middle of the discordant band and back out, so the score
        # degrades smoothly instead of cliff-edging at the boundaries.
        span = COMPLEMENTARY_DEGREES - ANALOGOUS_DEGREES
        into = (distance - ANALOGOUS_DEGREES) / span
        base = 0.34 - 0.18 * math.sin(into * math.pi)

    # Two loud colours fight even when their hues are compatible.
    if chroma > 0.55 and chroma_of(background) > 0.55:
        base *= 0.8
    return max(0.0, min(1.0, base))


def tonal_candidates(background: str) -> list[str]:
    """Tints, shades and near-neutrals built from the background's own hue.

    This is the pool a designer works from first: cream on navy, charcoal on blush. The
    hue is inherited, so every entry is harmonious by construction.
    """
    hue = hue_of(background) / 360.0
    out: list[str] = []
    # Lightness ladder from near-black to near-white. The saturations are deliberately
    # not tiny: at 0.05 the ladder produces flat greys that are technically harmonious
    # and visually dead. Around 0.4 a light step becomes a cream or a blush — the tone
    # a designer actually reaches for.
    for lightness in (0.05, 0.12, 0.20, 0.84, 0.88, 0.93):
        for sat in (0.22, 0.68):
            out.append(to_hex(
                tuple(c * 255 for c in colorsys.hls_to_rgb(hue, lightness, sat))))
    out.extend(("#FFFFFF", "#000000"))
    # Dedupe, preserving order.
    return list(dict.fromkeys(out))


def harmonious_on(background: str, palette: list[str] | None = None,
                  minimum: float = 4.5, *, allow_chroma: bool = False) -> str:
    """A colour that is both legible on `background` and harmonious with it.

    Drop-in replacement for `readable_on` wherever the result is shown to a viewer.
    Candidates that fail `minimum` are discarded outright — legibility is not traded
    away — and the survivors are ranked by harmony first, contrast second.

    `allow_chroma` admits saturated palette colours; it is for accent-role text (a CTA
    label, an eyebrow) where a colour pop is the point. Body and headline text leave it
    off and end up on a tint, a shade or a neutral.
    """
    on_palette = {e for e in (palette or []) if e and e.startswith("#")}
    pool = list(tonal_candidates(background)) + sorted(on_palette)

    passing = [c for c in dict.fromkeys(pool) if contrast_ratio(background, c) >= minimum]
    if not passing:
        return readable_on(background, palette, minimum=minimum)

    def rank(candidate: str) -> float:
        harmony = harmony_score(candidate, background)
        if not allow_chroma:
            # Squaring widens the gap between "sits well" and "clashes" without banning
            # chroma outright: an analogous cream barely moves, a discordant green
            # collapses. Accent text skips this and competes on harmony alone.
            harmony *= harmony
        # Contrast beyond roughly 7:1 buys no more comfort, so it stops being a tiebreak.
        comfort = min(contrast_ratio(background, candidate) / 7.0, 1.0)
        # The palette was chosen for this design; a colour already in it beats an
        # equally harmonious tone invented here. Without this the ladder's safe neutrals
        # quietly displace every considered colour and designs drift toward grey.
        affinity = 0.28 if candidate in on_palette else 0.0
        return harmony + 0.25 * comfort + affinity

    return max(passing, key=rank)


def kmeans_palette(pixels: np.ndarray, k: int = 5, iterations: int = 12,
                   seed: int = 7) -> list[str]:
    """Dominant colours, clustered in Lab so the result matches what the eye groups.

    `pixels` is an (N, 3) uint8 RGB array. Returns hexes ordered by cluster population.
    """
    if pixels.size == 0:
        return []
    sample = pixels.reshape(-1, 3).astype(np.float64)
    if sample.shape[0] > 20000:
        rng = np.random.default_rng(seed)
        sample = sample[rng.choice(sample.shape[0], 20000, replace=False)]

    lab = np.array([srgb_to_lab((int(r), int(g), int(b))) for r, g, b in sample])

    rng = np.random.default_rng(seed)
    centres = lab[rng.choice(lab.shape[0], min(k, lab.shape[0]), replace=False)]
    labels = np.zeros(lab.shape[0], dtype=int)
    for _ in range(iterations):
        distances = ((lab[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        new_labels = distances.argmin(axis=1)
        if (new_labels == labels).all():
            break
        labels = new_labels
        for i in range(centres.shape[0]):
            member = lab[labels == i]
            if member.size:
                centres[i] = member.mean(axis=0)

    counts = np.bincount(labels, minlength=centres.shape[0])
    order = np.argsort(-counts)
    out = []
    for i in order:
        member = sample[labels == i]
        if member.size:
            out.append(to_hex(tuple(member.mean(axis=0))))
    return out


def ensure_distinct(accent: str, background: str, minimum_delta: float = 25.0) -> str:
    """§1.5.1: keep the accent hue but push its lightness until it is distinguishable
    from the background."""
    if delta_e(accent, background) >= minimum_delta:
        return accent
    bg_luminance = relative_luminance(background)
    for step in range(1, 9):
        factor = 1 + 0.14 * step if bg_luminance < 0.5 else 1 - 0.11 * step
        candidate = adjust_lightness(accent, factor)
        if delta_e(candidate, background) >= minimum_delta:
            return candidate
    return "#FFFFFF" if bg_luminance < 0.5 else "#111111"
