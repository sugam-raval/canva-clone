"""Harmonisation — IMPLEMENTATION_PLAN §1.5.

"Independently generated layers do not belong to the same photograph. These
deterministic passes make them look like they do. All CPU, all fast."

  §1.5.1 harmonize.palette      — extract the real palette from the generated background
  §1.5.2 harmonize.contrast     — guarantee every text layer is legible where it sits
  §1.5.3 harmonize.shadow       — ground cutouts against the background's light direction
  §1.5.4 harmonize.color-match  — match subject white balance to the background

§1.5.2 rasterises everything *below* each text layer at low resolution. That is only
possible because the renderer is shareable — which is exactly why §0.11 insists on it.
"""

from __future__ import annotations

import math

import numpy as np
import structlog

from app.renderer.core import to_draw_list
from app.renderer.skia_backend import render_surface, surface_to_numpy
from app.renderer.transform import world_bounds
from app.schema.doc import (
    Adjustments,
    Backdrop,
    DesignDoc,
    GradientStop,
    LinearGradient,
    ShadowEffect,
    ShapeLayer,
    TextLayer,
    walk,
)
from app.util.color import (
    contrast_ratio,
    delta_e,
    ensure_distinct,
    harmonious_on,
    kmeans_palette,
    parse_hex,
    readable_on,
    relative_luminance,
    srgb_to_lab,
    to_hex,
)

log = structlog.get_logger(__name__)

# §1.5.2 thresholds: WCAG AA for body, the large-text allowance for display type.
CONTRAST_BODY = 4.5
CONTRAST_DISPLAY = 3.0
DISPLAY_SIZE_PX = 32.0

# Width of the low-resolution probe render. Cheap and exact.
PROBE_WIDTH = 240

# Headroom demanded of a recoloured layer, above the threshold it must actually meet.
#
# Contrast is decided against the mean of a 240px probe, but §5.3 measures the finished
# render. Picking the *most harmonious* colour that merely clears the bar — rather than
# the highest-contrast one, as this used to — leaves choices sitting exactly on it, and
# the difference between the two measurements is then enough to drop one under.
CONTRAST_MARGIN = 1.12


def harmonize(doc: DesignDoc, *, resolve_asset=None, load_image=None) -> DesignDoc:
    """Run every harmonisation pass in order. Pure with respect to the input doc."""
    doc = doc.model_copy(deep=True)
    probe = _probe_render(doc, resolve_asset=resolve_asset, load_image=load_image)

    harmonize_palette(doc, probe)
    harmonize_color_match(doc, probe)
    harmonize_shadow(doc, probe)
    # Contrast runs last: it depends on the final palette and on the scrims the earlier
    # passes may have adjusted.
    harmonize_contrast(doc, resolve_asset=resolve_asset, load_image=load_image)
    return doc


# --------------------------------------------------------------------------------------
# Low-resolution probe
# --------------------------------------------------------------------------------------


class Probe:
    """A small raster of the document, used to sample what is actually behind things."""

    def __init__(self, pixels: np.ndarray | None, doc: DesignDoc):
        self.pixels = pixels
        self.doc = doc
        self.scale = (pixels.shape[1] / doc.canvas.width) if pixels is not None else 0.0

    @property
    def ok(self) -> bool:
        return self.pixels is not None and self.pixels.size > 0

    def region(self, x: float, y: float, w: float, h: float) -> np.ndarray | None:
        if not self.ok:
            return None
        px0 = max(0, int(x * self.scale))
        py0 = max(0, int(y * self.scale))
        px1 = min(self.pixels.shape[1], int((x + w) * self.scale))
        py1 = min(self.pixels.shape[0], int((y + h) * self.scale))
        if px1 <= px0 or py1 <= py0:
            return None
        return self.pixels[py0:py1, px0:px1, :3]


def _probe_render(doc: DesignDoc, *, resolve_asset=None, load_image=None,
                  up_to_index: int | None = None) -> Probe:
    """Render the document (or the layers below `up_to_index`) small."""
    if doc.canvas.width <= 0:
        return Probe(None, doc)
    subset = doc
    if up_to_index is not None:
        subset = doc.model_copy(update={"layers": doc.layers[:up_to_index]})
    scale = PROBE_WIDTH / doc.canvas.width
    try:
        draw_list = to_draw_list(subset, scale=scale, resolve_asset=resolve_asset)
        surface = render_surface(draw_list, load_image,
                                 opaque_background=doc.canvas.background)
        return Probe(surface_to_numpy(surface), doc)
    except Exception as exc:  # noqa: BLE001 - harmonisation must never fail the request
        log.warning("harmonize.probe_failed", error=str(exc))
        return Probe(None, doc)


# --------------------------------------------------------------------------------------
# §1.5.1 palette
# --------------------------------------------------------------------------------------


def harmonize_palette(doc: DesignDoc, probe: Probe) -> None:
    """Replace the composer's guessed palette with the one actually in the background.

    Skipped when the brief asked for brand colours — a brand palette is not negotiable.
    """
    provenance = doc.provenance
    brief = getattr(provenance, "brief", None) or {}
    mode = (brief.get("colorDirection") or {}).get("mode")
    if mode == "brand":
        return
    if not probe.ok:
        return

    background = next((layer for layer in doc.layers if layer.role == "background"), None)
    if background is None or getattr(background, "asset_id", "") == "":
        return   # nothing generated yet; the composer palette is all we have

    bounds = world_bounds(background)
    region = probe.region(bounds.x, bounds.y, bounds.w, bounds.h)
    if region is None or region.size == 0:
        return

    extracted = kmeans_palette(region.reshape(-1, 3), k=5)
    if len(extracted) < 2:
        return

    # Keep the composer's accent hue but make sure it stands off the new background
    # (§1.5.1: ΔE > 25).
    previous_accent = doc.palette[-1] if doc.palette else extracted[-1]
    dominant = extracted[0]
    accent = ensure_distinct(previous_accent, dominant, minimum_delta=25.0)

    doc.palette = [*extracted[:4], accent]
    doc.canvas.background = dominant
    log.info("harmonize.palette", extracted=extracted[:3], accent=accent)

    _reapply_palette_roles(doc, dominant, accent)


def _reapply_palette_roles(doc: DesignDoc, primary: str, accent: str) -> None:
    """Re-colour shape and text layers whose colour came from a palette role."""
    for layer, _ in walk(doc.layers):
        # "contact" belongs here with the CTA pill: a contact bar is an accent-filled
        # band, and leaving it on the pre-extraction accent while the pill moves to the
        # new one ships a design with two different accents in it.
        if isinstance(layer, ShapeLayer) and layer.role in ("cta", "decoration",
                                                            "contact"):
            if layer.gradient is not None:
                layer.gradient = LinearGradient(
                    angle=layer.gradient.angle,
                    stops=[GradientStop(offset=s.offset, color=primary, opacity=s.opacity)
                           for s in layer.gradient.stops],
                )
            elif layer.fill:
                layer.fill = accent


# --------------------------------------------------------------------------------------
# §1.5.2 contrast
# --------------------------------------------------------------------------------------



# Copy that is READ rather than labelled. A pill behind one of these reads as a chip of
# UI: it draws a hard edge around a line of prose, and a block of them ships as a stack
# of mismatched brown rectangles. A gradient scrim over the region is what a designer
# reaches for. The pill stays for the short, label-like roles it suits — a CTA on its
# lozenge, a price, a badge, a caption — where the edge is the point.
_SCRIM_ROLES = frozenset({"headline", "subhead", "body", "offer", "event", "terms"})


def _prefers_scrim(layer: TextLayer) -> bool:
    """A scrim, or a pill behind the text itself?

    Width used to decide this, and it was the wrong question: a headline set in a left
    column is not wide, takes the pill, and comes back looking labelled. What matters is
    whether the copy is read or scanned.
    """
    return layer.role in _SCRIM_ROLES or layer.font_size >= DISPLAY_SIZE_PX * 1.5


def _covering_scrim(doc: DesignDoc, layer: TextLayer,
                    bounds) -> tuple[str, float] | None:
    """The colour and opacity of a scrim already sitting under `layer`, if one covers it.

    Only scrims inserted by this pass count, and only those painted below the layer:
    something drawn on top of the text is not what the text is sitting on.
    """
    if not _prefers_scrim(layer):
        return None
    try:
        position = doc.layers.index(layer)
    except ValueError:
        return None
    for other in doc.layers[:position]:
        if other.role != "overlay" or not other.visible:
            continue
        if other.meta.notes.get("insertedBy") != "harmonize.scrim":
            continue
        covered = world_bounds(other).intersection(bounds)
        if bounds.area <= 0 or covered.area / bounds.area < 0.85:
            continue
        stops = other.gradient.stops if other.gradient else []
        if not stops:
            continue
        # The same conservative reading `_insert_scrim` reports: the faintest point over
        # the text, not the gradient's peak.
        return stops[len(stops) // 2].color, weakest_scrim_opacity()
    return None


def harmonize_contrast(doc: DesignDoc, *, resolve_asset=None, load_image=None) -> None:
    """Guarantee every text layer is legible against what is actually behind it.

    Each layer is measured against a render of the layers *beneath* it only. Sampling
    the finished document instead would include the text's own pixels — and anything
    stacked above it — which biases the reading toward the text colour and reports
    comfortable contrast for copy that is in fact unreadable.
    """
    index = -1
    while True:
        index += 1
        if index >= len(doc.layers):
            break
        layer = doc.layers[index]
        if not isinstance(layer, TextLayer) or not layer.visible:
            continue

        probe = _probe_render(doc, resolve_asset=resolve_asset, load_image=load_image,
                              up_to_index=index)
        if not probe.ok:
            continue
        bounds = world_bounds(layer)
        region = probe.region(*_ink_box(bounds))
        if region is None or region.size == 0:
            continue

        mean_rgb = tuple(float(v) for v in region.reshape(-1, 3).mean(axis=0))
        behind = to_hex(mean_rgb)
        dark_ref, light_ref = _extremes(region)

        threshold = CONTRAST_DISPLAY if layer.font_size >= DISPLAY_SIZE_PX else CONTRAST_BODY

        # Outlined type is read by its outline. Judging the fill would recolour a navy
        # word with a gold keyline into a plain gold word, throwing away the treatment
        # the skeleton asked for in order to fix a problem the outline already solved.
        ink = layer.stroke.color if (layer.stroke and layer.stroke.width > 0) \
            else layer.color

        if _safe_everywhere(ink, dark_ref, light_ref, threshold):
            layer.meta.notes["contrastRatio"] = round(
                min(contrast_ratio(ink, dark_ref),
                    contrast_ratio(ink, light_ref)), 2)
            continue

        # 3. Pick a palette colour that is legible against the mean AND sits well
        #    with it. Ranking on contrast alone puts discordant colours on type.
        #    Accent-role copy may carry chroma; headlines and body take a tone. An offer
        #    line, a price and a badge belong with the CTA here: they are authored in the
        #    accent on purpose, and forcing them to a neutral is how a gold "FLAT 50% OFF"
        #    comes back as plain white text that no longer reads as the point of the design.
        candidate = harmonious_on(behind, doc.palette,
                                  minimum=threshold * CONTRAST_MARGIN,
                                  allow_chroma=layer.role in ("cta", "caption", "offer",
                                                              "price", "badge"))
        candidate_ratio = contrast_ratio(candidate, behind)
        if _safe_everywhere(candidate, dark_ref, light_ref, threshold):
            layer.color = candidate
            layer.meta.notes["contrastRatio"] = round(candidate_ratio, 2)
            layer.meta.notes["contrastFix"] = "recoloured"
            continue

        # 4. Busy region, or nothing in the palette is readable. Escalate.
        layer.color = candidate
        covering = _covering_scrim(doc, layer, bounds)
        if covering is not None:
            # A scrim laid down for the layer above already darkens this one's ground.
            # Without this check each line of a copy block earns its own pill, and a
            # headline and the subhead beneath it ship as two brown chips of different
            # widths — the single most obviously machine-made thing in the output.
            layer.meta.notes["contrastFix"] = "scrim"
            effective = _composite(behind, *covering)
        elif _prefers_scrim(layer):
            scrim_colour, scrim_opacity = _insert_scrim(doc, index, layer, behind)
            layer.meta.notes["contrastFix"] = "scrim"
            index += 1   # the scrim was inserted below this layer, shifting it up
            effective = _composite(behind, scrim_colour, scrim_opacity)
        else:
            _add_backdrop(layer, behind, doc)
            layer.meta.notes["contrastFix"] = "backdrop"
            effective = _composite(behind, layer.backdrop.color, layer.backdrop.opacity)

        # Record the ratio against what the text now actually sits on, not against the
        # artwork it no longer touches — §5.3 reads this note.
        final_ratio = contrast_ratio(layer.color, effective)
        if final_ratio < threshold:
            # The escalation did not get there. Fall back to plain black or white, which
            # always clears the threshold against a mid-tone.
            layer.color = readable_on(effective, None, minimum=threshold)
            final_ratio = contrast_ratio(layer.color, effective)
        layer.meta.notes["contrastRatio"] = round(final_ratio, 2)
        # §1.5.2: never silently ship failing contrast — the note above is what the eval
        # harness reads.
        log.info("harmonize.contrast", layer_id=layer.id,
                 fix=layer.meta.notes["contrastFix"],
                 ratio=layer.meta.notes["contrastRatio"])


# Fraction trimmed from each edge of a text frame before sampling what is behind it.
INK_INSET = 0.14


def _ink_box(bounds) -> tuple[float, float, float, float]:
    """The part of a text frame the glyphs actually occupy.

    Sampling the whole frame lets its boundary dominate: a CTA label's frame matches its
    pill exactly, so the pill's rounded corners and antialiased rim enter the sample as
    blended half-colours. Those blends are not anywhere the text sits, but they are
    extreme enough to own a percentile and force a backdrop onto type that was perfectly
    legible. Glyphs do not reach the frame edge, so neither should the probe.
    """
    dx, dy = bounds.w * INK_INSET, bounds.h * INK_INSET
    return (bounds.x + dx, bounds.y + dy,
            max(1.0, bounds.w - 2 * dx), max(1.0, bounds.h - 2 * dy))


def _safe_everywhere(colour: str, dark_ref: str, light_ref: str,
                     threshold: float) -> bool:
    """Readable against the darkest and lightest parts of a region, not just its average.

    This replaces a variance test. Variance answers "is this region busy", which is the
    wrong question twice over: a hard edge between two flat colours — type sitting across
    a vector shape, which is most of a flat-graphic design — scores as busy and gets a
    scrim it does not need, while a genuinely noisy photograph can average out to a
    mid-tone and score calm. What matters is whether one colour stays legible everywhere
    the glyphs actually land.
    """
    return (contrast_ratio(colour, dark_ref) >= threshold
            and contrast_ratio(colour, light_ref) >= threshold)


def _extremes(region: np.ndarray) -> tuple[str, str]:
    """Representative darkest and lightest colours of a region.

    Percentiles rather than min/max, so a handful of stray pixels — a specular highlight,
    a compression artefact — cannot force an unnecessary escalation.
    """
    flat = region.reshape(-1, 3).astype(np.float32)
    luminance = flat.mean(axis=1)
    low, high = np.percentile(luminance, [10.0, 90.0])
    dark = flat[luminance <= low]
    light = flat[luminance >= high]
    if dark.size == 0:
        dark = flat
    if light.size == 0:
        light = flat
    return to_hex(tuple(dark.mean(axis=0))), to_hex(tuple(light.mean(axis=0)))


def _composite(under: str, over: str, alpha: float) -> str:
    """Flatten a translucent scrim over the artwork, so contrast is measured against
    what the viewer actually sees behind the glyphs."""
    from app.util.color import parse_hex

    alpha = max(0.0, min(1.0, alpha))
    top = np.array(parse_hex(over), dtype=float)
    bottom = np.array(parse_hex(under), dtype=float)
    return to_hex(tuple(top * alpha + bottom * (1.0 - alpha)))


def _add_backdrop(layer: TextLayer, behind: str, doc: DesignDoc) -> bool:
    """A scrim pill behind the text itself. Cheapest escalation, keeps the layout."""
    if layer.backdrop is not None:
        return True
    dark_behind = relative_luminance(behind) < 0.5
    scrim = doc.palette[0] if doc.palette else ("#000000" if dark_behind else "#FFFFFF")
    if contrast_ratio(layer.color, scrim) < 3.0:
        scrim = "#000000" if relative_luminance(layer.color) > 0.5 else "#FFFFFF"
    layer.backdrop = Backdrop(color=scrim, opacity=0.72,
                              padding=max(8.0, layer.font_size * 0.28),
                              radius=max(4.0, layer.font_size * 0.18))
    return True


# Peak opacity of a legibility scrim, at the midpoint of its gradient.
SCRIM_OPACITY = 0.45

# Where the text sits inside the scrim band. `_insert_scrim` places the band at
# `bounds.y - 0.4h` with height `2h`, so the text occupies this span of it.
SCRIM_TEXT_SPAN = (0.2, 0.7)


def _insert_scrim(doc: DesignDoc, index: int, layer: TextLayer,
                  behind: str) -> tuple[str, float]:
    """A gradient overlay between the image and the text, for when a per-text backdrop
    would be visually heavier than darkening the whole region.

    Returns the colour and the opacity the *faintest* line of the text sits on, because
    the caller has to composite exactly that to know whether the escalation worked. The
    old guess used the palette's ground colour at the gradient's peak — but the scrim is
    painted flat black or white, and a headline's first line sits far up the ramp where
    the gradient is barely there. Recording the peak is what let harmonisation claim a
    comfortable ratio for a layer the renderer then drew at 1.8:1. Taking the minimum
    over the text's own span is conservative in the right direction: where it is not
    enough the caller escalates again, instead of shipping the claim.
    """
    dark = relative_luminance(behind) >= 0.5
    colour = "#000000" if dark else "#FFFFFF"
    bounds = world_bounds(layer)
    scrim = ShapeLayer(
        id=f"{layer.id}_scrim",
        name="Legibility scrim",
        role="overlay",
        shape="rect",
        frame=type(layer.frame)(x=0, y=max(0.0, bounds.y - bounds.h * 0.4),
                                w=doc.canvas.width,
                                h=min(doc.canvas.height, bounds.h * 2.0)),
        gradient=LinearGradient(angle=180, stops=[
            GradientStop(offset=0.0, color=colour, opacity=0.0),
            GradientStop(offset=0.5, color=colour, opacity=SCRIM_OPACITY),
            GradientStop(offset=1.0, color=colour, opacity=0.0),
        ]),
        constraints=type(layer.constraints)(horizontal="stretch", vertical="middle",
                                            priority=15, optional=True),
    )
    scrim.meta.notes["insertedBy"] = "harmonize.scrim"
    doc.layers.insert(index, scrim)
    return colour, weakest_scrim_opacity()


def weakest_scrim_opacity() -> float:
    """The gradient's opacity at whichever end of the text's span is further up the ramp.

    A three-stop ramp peaking at the middle falls off linearly to nothing at both ends,
    so the faintest point over the text is whichever edge of its span sits further from
    the peak.
    """
    start, end = SCRIM_TEXT_SPAN
    furthest = max(abs(start - 0.5), abs(end - 0.5))
    return SCRIM_OPACITY * max(0.0, 1.0 - furthest / 0.5)


# --------------------------------------------------------------------------------------
# §1.5.3 shadow
# --------------------------------------------------------------------------------------


def estimate_light_direction(probe: Probe) -> tuple[float, float]:
    """Dominant gradient of a heavily blurred luminance map.

    Returns a unit vector pointing from dark toward light — the direction the light is
    coming FROM, so a shadow is cast along its negation.
    """
    if not probe.ok:
        return (-0.7071, -0.7071)   # default: light from the upper left
    import cv2

    grey = cv2.cvtColor(probe.pixels[:, :, :3].astype(np.uint8), cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(grey, (0, 0), sigmaX=max(2.0, grey.shape[1] / 12))
    gx = float(cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3).mean())
    gy = float(cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3).mean())
    magnitude = math.hypot(gx, gy)
    if magnitude < 1e-4:
        return (-0.7071, -0.7071)
    return (gx / magnitude, gy / magnitude)


def harmonize_shadow(doc: DesignDoc, probe: Probe) -> None:
    """Cutouts float unless grounded (§1.5.3)."""
    light_x, light_y = estimate_light_direction(probe)
    background_luminance = 0.5
    if probe.ok:
        background_luminance = float(probe.pixels[:, :, :3].mean() / 255.0)

    for layer in doc.layers:
        if layer.type != "image" or layer.role not in ("subject", "object", "logo"):
            continue
        if not layer.has_alpha:
            continue

        height = max(1.0, layer.frame.h)
        blur = 0.06 * height
        # Darker backgrounds take a lighter shadow, or it disappears into the ground.
        opacity = 0.25 + 0.15 * min(1.0, background_luminance * 1.4)
        offset = 0.05 * height

        shadow = ShadowEffect(
            dx=round(-light_x * offset, 2),
            dy=round(-light_y * offset + 0.02 * height, 2),
            blur=round(blur, 2),
            color="#000000",
            opacity=round(min(0.4, opacity), 3),
        )
        layer.effects = [e for e in layer.effects if e.kind != "shadow"] + [shadow]
        layer.meta.notes["lightDirection"] = [round(light_x, 3), round(light_y, 3)]


# --------------------------------------------------------------------------------------
# §1.5.4 colour match
# --------------------------------------------------------------------------------------


def harmonize_color_match(doc: DesignDoc, probe: Probe) -> None:
    """Match each subject's white balance to the background's mid-tones.

    Written into `ImageLayer.adjust` — non-destructive, so the user can undo it in the
    inspector. Clamped to +/-0.15 as §1.5.4 requires.
    """
    if not probe.ok:
        return
    background = next((layer for layer in doc.layers if layer.role == "background"), None)
    if background is None:
        return
    bg_bounds = world_bounds(background)
    bg_region = probe.region(bg_bounds.x, bg_bounds.y, bg_bounds.w, bg_bounds.h)
    if bg_region is None or bg_region.size == 0:
        return

    flat = bg_region.reshape(-1, 3).astype(np.float32)
    luminance = flat.mean(axis=1)
    midtones = flat[(luminance > 60) & (luminance < 200)]
    if midtones.shape[0] < 32:
        midtones = flat
    bg_lab = srgb_to_lab(tuple(int(v) for v in midtones.mean(axis=0)))

    for layer in doc.layers:
        if layer.type != "image" or layer.role not in ("subject", "object"):
            continue
        bounds = world_bounds(layer)
        region = probe.region(bounds.x, bounds.y, bounds.w, bounds.h)
        if region is None or region.size == 0:
            continue
        subject_lab = srgb_to_lab(tuple(int(v) for v in region.reshape(-1, 3).mean(axis=0)))

        # b* is the blue-yellow axis: positive means warmer.
        temperature = max(-0.15, min(0.15, (bg_lab[2] - subject_lab[2]) / 100.0))
        # a* and b* magnitude difference approximates a chroma difference.
        bg_chroma = math.hypot(bg_lab[1], bg_lab[2])
        subject_chroma = math.hypot(subject_lab[1], subject_lab[2])
        saturation_delta = max(-0.15, min(0.15, (bg_chroma - subject_chroma) / 120.0))

        if abs(temperature) < 0.01 and abs(saturation_delta) < 0.01:
            continue
        adjust = layer.adjust or Adjustments()
        adjust.temperature = round(temperature, 3)
        adjust.saturation = round(saturation_delta, 3)
        layer.adjust = adjust
        layer.meta.notes["colorMatched"] = True


def palette_distance(a: str, b: str) -> float:
    return delta_e(parse_hex(a), parse_hex(b))
