"""Server-side renderer and exporter — IMPLEMENTATION_PLAN §0.11 and §4.1.

Consumes the draw list produced by `renderer/core.py`. Text is drawn from the glyph ids
HarfBuzz produced, with the same static font file the layout engine measured, which is
what makes server output match the browser (INV-3).

Outputs PNG, JPEG, PDF (vector, live text, embedded fonts) and SVG.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import skia
import structlog

from app.layout.fonts import get_registry
from app.renderer.svgpath import parse_svg_path
from app.schema.draw import DrawList

log = structlog.get_logger(__name__)

ImageLoader = Callable[[str, str], bytes | None]  # (asset_id, asset_url) -> encoded bytes

_CAP = {
    "butt": skia.Paint.kButt_Cap,
    "round": skia.Paint.kRound_Cap,
    "square": skia.Paint.kSquare_Cap,
}

_JOIN = {
    "miter": skia.Paint.kMiter_Join,
    "round": skia.Paint.kRound_Join,
    "bevel": skia.Paint.kBevel_Join,
}

_BLEND = {
    "normal": skia.BlendMode.kSrcOver,
    "multiply": skia.BlendMode.kMultiply,
    "screen": skia.BlendMode.kScreen,
    "overlay": skia.BlendMode.kOverlay,
    "soft-light": skia.BlendMode.kSoftLight,
    "darken": skia.BlendMode.kDarken,
    "lighten": skia.BlendMode.kLighten,
    "color-dodge": skia.BlendMode.kColorDodge,
    "difference": skia.BlendMode.kDifference,
}


def parse_color(value: str | None, default: int = 0) -> int:
    """'#RRGGBB' / '#RRGGBBAA' / 'transparent' -> Skia ARGB int."""
    if not value or value in ("transparent", "none"):
        return default
    text = value.lstrip("#")
    if len(text) == 6:
        r, g, b = (int(text[i:i + 2], 16) for i in (0, 2, 4))
        return skia.ColorSetARGB(255, r, g, b)
    if len(text) == 8:
        r, g, b, a = (int(text[i:i + 2], 16) for i in (0, 2, 4, 6))
        return skia.ColorSetARGB(a, r, g, b)
    return default


# --------------------------------------------------------------------------------------
# Non-destructive colour adjustments (§0.5 Adjustments, applied at render time)
# --------------------------------------------------------------------------------------

_LUM = (0.2126, 0.7152, 0.0722)


def _identity() -> np.ndarray:
    m = np.zeros((5, 5), dtype=np.float64)
    np.fill_diagonal(m, 1.0)
    return m


def adjustment_matrix(adjust: dict[str, float] | None) -> list[float] | None:
    """Compose brightness/contrast/saturation/temperature/hue into one 4x5 colour matrix."""
    if not adjust:
        return None
    brightness = float(adjust.get("brightness", 0) or 0)
    contrast = float(adjust.get("contrast", 0) or 0)
    saturation = float(adjust.get("saturation", 0) or 0)
    temperature = float(adjust.get("temperature", 0) or 0)
    hue = float(adjust.get("hueRotate", adjust.get("hue_rotate", 0)) or 0)
    if not any((brightness, contrast, saturation, temperature, hue)):
        return None

    m = _identity()

    if saturation:
        s = 1.0 + saturation
        lr, lg, lb = _LUM
        sat = _identity()
        sat[0, :3] = [lr + s * (1 - lr), lg * (1 - s), lb * (1 - s)]
        sat[1, :3] = [lr * (1 - s), lg + s * (1 - lg), lb * (1 - s)]
        sat[2, :3] = [lr * (1 - s), lg * (1 - s), lb + s * (1 - lb)]
        m = sat @ m

    if hue:
        rad = math.radians(hue)
        cos, sin = math.cos(rad), math.sin(rad)
        lr, lg, lb = _LUM
        rot = _identity()
        rot[0, :3] = [lr + cos * (1 - lr) - sin * lr,
                      lg - cos * lg - sin * lg,
                      lb - cos * lb + sin * (1 - lb)]
        rot[1, :3] = [lr - cos * lr + sin * 0.143,
                      lg + cos * (1 - lg) + sin * 0.140,
                      lb - cos * lb - sin * 0.283]
        rot[2, :3] = [lr - cos * lr - sin * (1 - lr),
                      lg - cos * lg + sin * lg,
                      lb + cos * (1 - lb) + sin * lb]
        m = rot @ m

    if contrast:
        k = 1.0 + contrast
        con = _identity()
        for i in range(3):
            con[i, i] = k
            con[i, 4] = 0.5 * (1 - k)
        m = con @ m

    if temperature:
        # Warm pushes red up and blue down; cool the reverse. Clamped by the schema
        # to +/-1, and harmonisation only ever writes +/-0.15 (§1.5.4).
        warm = _identity()
        warm[0, 4] = 0.12 * temperature
        warm[2, 4] = -0.12 * temperature
        m = warm @ m

    if brightness:
        bri = _identity()
        for i in range(3):
            bri[i, 4] = brightness
        m = bri @ m

    return [float(v) for v in m[:4, :].reshape(-1)]


# --------------------------------------------------------------------------------------
# Effects
# --------------------------------------------------------------------------------------


def _effect_filter(effects: list[dict]) -> Any | None:
    """Chain layer effects into a single Skia image filter."""
    current = None
    for effect in effects:
        kind = effect.get("kind")
        if kind == "shadow":
            # Skia takes a blur sigma; a CSS-style blur radius is ~2 sigma.
            sigma = max(0.0, float(effect.get("blur", 0))) / 2.0
            colour = parse_color(effect.get("color", "#000000"))
            alpha = int(max(0.0, min(1.0, float(effect.get("opacity", 1)))) * 255)
            colour = skia.ColorSetA(colour, alpha)
            current = skia.ImageFilters.DropShadow(
                float(effect.get("dx", 0)), float(effect.get("dy", 0)),
                sigma, sigma, colour, current,
            )
        elif kind == "blur":
            sigma = max(0.0, float(effect.get("radius", 0))) / 2.0
            current = skia.ImageFilters.Blur(sigma, sigma, current)
        elif kind == "glow":
            sigma = max(0.0, float(effect.get("radius", 0))) / 2.0
            colour = parse_color(effect.get("color", "#FFFFFF"))
            alpha = int(max(0.0, min(1.0, float(effect.get("opacity", 1)))) * 255)
            current = skia.ImageFilters.DropShadow(
                0.0, 0.0, sigma, sigma, skia.ColorSetA(colour, alpha), current,
            )
        elif kind == "stroke":
            width = max(0.0, float(effect.get("width", 0)))
            if width > 0:
                colour = parse_color(effect.get("color", "#000000"))
                # Dilate the alpha, tint it, and draw it behind the layer content.
                outline = skia.ImageFilters.Dilate(width, width, current)
                outline = skia.ImageFilters.ColorFilter(
                    skia.ColorFilters.Blend(colour, skia.BlendMode.kSrcIn), outline
                )
                current = skia.ImageFilters.Merge([outline, current])
    return current


# --------------------------------------------------------------------------------------
# Renderer
# --------------------------------------------------------------------------------------


@dataclass
class RenderStats:
    images_drawn: int = 0
    images_missing: int = 0
    glyphs_drawn: int = 0
    paths_drawn: int = 0
    placeholders_drawn: int = 0


class SkiaDrawListRenderer:
    """Executes a `DrawList` onto any Skia canvas (raster surface, PDF page, SVG)."""

    def __init__(self, load_image: ImageLoader | None = None):
        self._load_image = load_image
        self._image_cache: dict[str, skia.Image | None] = {}
        self._typeface_cache: dict[str, skia.Typeface] = {}
        self.stats = RenderStats()

    # -- resources --------------------------------------------------------------------

    def typeface(self, font_key: str) -> skia.Typeface:
        cached = self._typeface_cache.get(font_key)
        if cached is not None:
            return cached
        registry = get_registry()
        try:
            face = registry.face_by_key(font_key)
            typeface = skia.Typeface.MakeFromFile(str(face.path))
        except Exception:  # noqa: BLE001 - a missing face must not fail the render
            typeface = None
        if typeface is None:
            typeface = skia.Typeface.MakeDefault()
        self._typeface_cache[font_key] = typeface
        return typeface

    def image(self, asset_id: str, asset_url: str) -> skia.Image | None:
        key = asset_id or asset_url
        if key in self._image_cache:
            return self._image_cache[key]
        data = None
        if self._load_image is not None:
            try:
                data = self._load_image(asset_id, asset_url)
            except Exception:  # noqa: BLE001
                data = None
        image = skia.Image.MakeFromEncoded(skia.Data.MakeWithCopy(data)) if data else None
        self._image_cache[key] = image
        return image

    # -- execution --------------------------------------------------------------------

    def draw(self, canvas: skia.Canvas, draw_list: DrawList) -> RenderStats:
        restore_depth: list[int] = []

        for cmd in draw_list.commands:
            op = cmd.op
            if op == "clear":
                colour = parse_color(cmd.color, skia.ColorTRANSPARENT)
                canvas.clear(colour)

            elif op == "saveTransform":
                depth = 1
                canvas.save()
                m = cmd.matrix
                canvas.concat(skia.Matrix.MakeAll(m.a, m.c, m.e, m.b, m.d, m.f, 0, 0, 1))
                filters = _effect_filter(cmd.effects) if cmd.effects else None
                needs_layer = (
                    cmd.opacity < 0.999 or cmd.blend != "normal" or filters is not None
                )
                if needs_layer:
                    paint = skia.Paint()
                    paint.setAlphaf(max(0.0, min(1.0, cmd.opacity)))
                    paint.setBlendMode(_BLEND.get(cmd.blend, skia.BlendMode.kSrcOver))
                    if filters is not None:
                        paint.setImageFilter(filters)
                    canvas.saveLayer(None, paint)
                    depth += 1
                if cmd.clip is not None:
                    canvas.clipRect(
                        skia.Rect.MakeXYWH(cmd.clip.x, cmd.clip.y, cmd.clip.w, cmd.clip.h),
                        skia.ClipOp.kIntersect, True,
                    )
                restore_depth.append(depth)

            elif op == "restore":
                depth = restore_depth.pop() if restore_depth else 1
                for _ in range(depth):
                    canvas.restore()

            elif op == "placeholder":
                paint = skia.Paint(Color=parse_color(cmd.color), AntiAlias=True)
                rect = skia.Rect.MakeXYWH(cmd.dest.x, cmd.dest.y, cmd.dest.w, cmd.dest.h)
                if cmd.clip_path:
                    canvas.save()
                    self._clip_to(canvas, cmd.clip_path)
                    canvas.drawRect(rect, paint)
                    canvas.restore()
                elif cmd.radius > 0:
                    canvas.drawRoundRect(rect, cmd.radius, cmd.radius, paint)
                else:
                    canvas.drawRect(rect, paint)
                self.stats.placeholders_drawn += 1

            elif op == "image":
                self._draw_image(canvas, cmd)

            elif op == "path":
                self._draw_path(canvas, cmd)

            elif op == "textRun":
                self._draw_text(canvas, cmd)

        while restore_depth:
            for _ in range(restore_depth.pop()):
                canvas.restore()
        return self.stats

    @staticmethod
    def _clip_to(canvas: skia.Canvas, clip_path: str) -> None:
        """Clip to a mask silhouette. A path we cannot parse must not silently blank the
        layer, so a parse failure leaves the clip alone and the image draws square."""
        try:
            canvas.clipPath(parse_svg_path(clip_path), skia.ClipOp.kIntersect, True)
        except Exception:  # noqa: BLE001 - drawing square beats not drawing
            log.warning("render.mask_unparseable", path=clip_path[:80])

    def _draw_image(self, canvas: skia.Canvas, cmd: Any) -> None:
        image = self.image(cmd.asset_id, cmd.asset_url)
        dest = skia.Rect.MakeXYWH(cmd.dest.x, cmd.dest.y, cmd.dest.w, cmd.dest.h)
        if image is None:
            self.stats.images_missing += 1
            return
        paint = skia.Paint(AntiAlias=True)
        paint.setAlphaf(max(0.0, min(1.0, cmd.opacity)))
        paint.setBlendMode(_BLEND.get(cmd.blend, skia.BlendMode.kSrcOver))
        matrix = adjustment_matrix(
            cmd.adjust.model_dump(by_alias=True) if cmd.adjust is not None else None
        )
        if matrix is not None:
            paint.setColorFilter(skia.ColorFilters.Matrix(matrix))

        src = (
            skia.Rect.MakeXYWH(cmd.crop.x, cmd.crop.y, cmd.crop.w, cmd.crop.h)
            if cmd.crop is not None
            else skia.Rect.MakeWH(image.width(), image.height())
        )
        sampling = skia.SamplingOptions(skia.CubicResampler.Mitchell())
        clipped = bool(cmd.clip_path)
        if clipped:
            canvas.save()
            self._clip_to(canvas, cmd.clip_path)
        canvas.drawImageRect(image, src, dest, sampling, paint,
                             skia.Canvas.kStrict_SrcRectConstraint)
        if clipped:
            canvas.restore()
        self.stats.images_drawn += 1

    def _draw_path(self, canvas: skia.Canvas, cmd: Any) -> None:
        try:
            path = parse_svg_path(cmd.d)
        except Exception:  # noqa: BLE001
            return
        if cmd.gradient:
            paint = skia.Paint(AntiAlias=True)
            shader = self._gradient_shader(cmd.gradient, path.getBounds())
            if shader is not None:
                paint.setShader(shader)
                canvas.drawPath(path, paint)
        elif cmd.fill and cmd.fill not in ("none", "transparent"):
            paint = skia.Paint(AntiAlias=True, Color=parse_color(cmd.fill),
                               Style=skia.Paint.kFill_Style)
            canvas.drawPath(path, paint)

        if cmd.stroke and cmd.stroke_width > 0:
            paint = skia.Paint(AntiAlias=True, Color=parse_color(cmd.stroke),
                               Style=skia.Paint.kStroke_Style,
                               StrokeWidth=cmd.stroke_width)
            paint.setStrokeCap(_CAP.get(cmd.cap, skia.Paint.kButt_Cap))
            paint.setStrokeJoin(_JOIN.get(cmd.join, skia.Paint.kMiter_Join))
            if cmd.dash:
                paint.setPathEffect(skia.DashPathEffect.Make(list(cmd.dash), 0.0))
            canvas.drawPath(path, paint)
        self.stats.paths_drawn += 1

    @staticmethod
    def _gradient_shader(gradient: dict, bounds: skia.Rect) -> Any | None:
        stops = gradient.get("stops") or []
        if len(stops) < 2:
            return None
        angle = math.radians(float(gradient.get("angle", 90)))
        cx, cy = bounds.centerX(), bounds.centerY()
        # The ramp has to span the box along its OWN direction. Sizing it by
        # max(width, height) instead makes a wide, short shape cover only the middle
        # slice of the ramp — a 1080x272 scrim spans 25% of it, so every stop lands near
        # the midpoint and the "gradient" renders as a flat band with two hard edges.
        ux, uy = math.cos(angle - math.pi / 2), math.sin(angle - math.pi / 2)
        half = (bounds.width() * abs(ux) + bounds.height() * abs(uy)) / 2
        dx, dy = ux * half, uy * half
        colours, positions = [], []
        for stop in stops:
            colour = parse_color(stop.get("color", "#000000"))
            alpha = int(max(0.0, min(1.0, float(stop.get("opacity", 1)))) * 255)
            colours.append(skia.ColorSetA(colour, alpha))
            positions.append(float(stop.get("offset", 0)))
        return skia.GradientShader.MakeLinear(
            points=[skia.Point(cx - dx, cy - dy), skia.Point(cx + dx, cy + dy)],
            colors=colours, positions=positions,
        )

    def _draw_text(self, canvas: skia.Canvas, cmd: Any) -> None:
        fill = skia.Paint(AntiAlias=True, Color=parse_color(cmd.color))
        stroke = None
        if cmd.stroke_color and cmd.stroke_width > 0:
            stroke = skia.Paint(AntiAlias=True, Color=parse_color(cmd.stroke_color),
                                Style=skia.Paint.kStroke_Style,
                                StrokeWidth=cmd.stroke_width)

        for run in cmd.runs:
            if not run.glyphs:
                continue
            font = skia.Font(self.typeface(run.font_key), run.font_size)
            font.setSubpixel(True)
            font.setEdging(skia.Font.Edging.kAntiAlias)
            gids = [g.gid for g in run.glyphs]
            points = [
                skia.Point(run.origin_x + g.x, run.origin_y + g.y) for g in run.glyphs
            ]
            blob = skia.TextBlob.MakeFromPosText(
                struct.pack(f"<{len(gids)}H", *gids), points, font,
                skia.TextEncoding.kGlyphID,
            )
            if blob is None:
                continue
            if stroke is not None:
                canvas.drawTextBlob(blob, 0, 0, stroke)
            canvas.drawTextBlob(blob, 0, 0, fill)
            self.stats.glyphs_drawn += len(gids)


# --------------------------------------------------------------------------------------
# Output formats (§4.1)
# --------------------------------------------------------------------------------------


def render_surface(draw_list: DrawList, load_image: ImageLoader | None = None,
                   *, opaque_background: str | None = None) -> skia.Surface:
    surface = skia.Surface(max(1, draw_list.width), max(1, draw_list.height))
    canvas = surface.getCanvas()
    if opaque_background:
        canvas.clear(parse_color(opaque_background, skia.ColorWHITE))
    SkiaDrawListRenderer(load_image).draw(canvas, draw_list)
    return surface


def render_png(draw_list: DrawList, load_image: ImageLoader | None = None) -> bytes:
    surface = render_surface(draw_list, load_image)
    image = surface.makeImageSnapshot()
    return bytes(image.encodeToData(skia.EncodedImageFormat.kPNG, 100))


def render_jpeg(draw_list: DrawList, load_image: ImageLoader | None = None,
                quality: int = 90) -> bytes:
    # JPEG has no alpha; composite onto white so transparency does not turn black.
    surface = render_surface(draw_list, load_image, opaque_background="#FFFFFF")
    image = surface.makeImageSnapshot()
    return bytes(image.encodeToData(skia.EncodedImageFormat.kJPEG, quality))


def render_webp(draw_list: DrawList, load_image: ImageLoader | None = None,
                quality: int = 88) -> bytes:
    surface = render_surface(draw_list, load_image)
    image = surface.makeImageSnapshot()
    return bytes(image.encodeToData(skia.EncodedImageFormat.kWEBP, quality))


def render_pdf(draw_list: DrawList, load_image: ImageLoader | None = None,
               *, title: str = "Design", dpi: int = 72) -> bytes:
    """Vector PDF with live, embedded-font text — §4.1 explicitly forbids rasterising
    the page. Drawing from glyph ids means Skia embeds a subset of the real face."""
    stream = skia.DynamicMemoryWStream()
    metadata = skia.PDF.Metadata()
    metadata.fTitle = title
    metadata.fCreator = "AI Layered Design Generator"
    metadata.fRasterDPI = float(dpi)
    document = skia.PDF.MakeDocument(stream, metadata)
    # PDF user units are points (1/72 inch); scale so the page is physically correct.
    k = 72.0 / max(1, dpi)
    canvas = document.beginPage(draw_list.width * k, draw_list.height * k)
    canvas.scale(k, k)
    SkiaDrawListRenderer(load_image).draw(canvas, draw_list)
    document.endPage()
    document.close()
    return bytes(stream.detachAsData())


def render_svg(draw_list: DrawList, load_image: ImageLoader | None = None) -> bytes:
    stream = skia.DynamicMemoryWStream()
    bounds = skia.Rect.MakeWH(draw_list.width, draw_list.height)
    canvas = skia.SVGCanvas.Make(bounds, stream)
    SkiaDrawListRenderer(load_image).draw(canvas, draw_list)
    del canvas  # flushes the SVG document
    return bytes(stream.detachAsData())


def surface_to_numpy(surface: skia.Surface) -> np.ndarray:
    """Return the surface as an **RGBA** array.

    Skia's raster surfaces are BGRA on this platform, so reading one straight into numpy
    hands back channel-swapped pixels. Everything downstream — palette extraction,
    contrast measurement and colour matching in §1.5 — treats the array as RGB, so the
    conversion must happen here rather than at each call site.
    """
    image = surface.makeImageSnapshot()
    return np.array(image.convert(colorType=skia.kRGBA_8888_ColorType,
                                  alphaType=skia.kUnpremul_AlphaType))


def encode_png_bytes(array: np.ndarray) -> bytes:
    image = skia.Image.fromarray(array)
    return bytes(image.encodeToData(skia.EncodedImageFormat.kPNG, 100))


def decode_image(data: bytes) -> skia.Image | None:
    return skia.Image.MakeFromEncoded(skia.Data.MakeWithCopy(data))


def image_to_png(image: skia.Image) -> bytes:
    return bytes(image.encodeToData(skia.EncodedImageFormat.kPNG, 100))
