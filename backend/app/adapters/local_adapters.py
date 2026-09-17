"""CPU-only local adapters. No GPU required (Appendix B: self-host only the cheap models).

  * `RembgMatting`     — u2net via onnxruntime, if the `localml` extra is installed
  * `GrabCutMatting`   — OpenCV fallback, no model download
  * `OpenCVGlyphDetector` — MSER-based text *detection* for the §1.4.6 glyph gate
  * `OpenCVInpainter`  — Telea fill, the cheap tier §2.7/§3.3 call for uniform regions
  * `LanczosUpscaler`  — Lanczos + unsharp; §1.4.4's Real-ESRGAN needs a GPU
"""

from __future__ import annotations

import io
import threading

import cv2
import numpy as np
from PIL import Image

from app.adapters.base import AdapterError, ImageResult, TextBox


def _to_bgr(data: bytes) -> np.ndarray:
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise AdapterError("could not decode image", recoverable=False)
    return image


def _to_rgba(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as img:
        return np.array(img.convert("RGBA"))


def _png(array: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", array)
    if not ok:
        raise AdapterError("could not encode PNG")
    return buf.tobytes()


# --------------------------------------------------------------------------------------
# Matting
# --------------------------------------------------------------------------------------


class RembgMatting:
    """u2net through onnxruntime. Downloads ~176 MB of weights on first use."""

    name = "local:rembg-u2net"
    _session = None
    _lock = threading.Lock()

    @classmethod
    def available(cls) -> bool:
        try:
            import rembg  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_session(self):
        with self._lock:
            if RembgMatting._session is None:
                from rembg import new_session

                RembgMatting._session = new_session("u2net")
            return RembgMatting._session

    async def infer(self, image: bytes) -> bytes:
        import asyncio

        from rembg import remove

        def run() -> bytes:
            cut = remove(image, session=self._get_session())
            with Image.open(io.BytesIO(cut)) as img:
                alpha = img.convert("RGBA").split()[-1]
                buf = io.BytesIO()
                alpha.save(buf, format="PNG")
                return buf.getvalue()

        return await asyncio.to_thread(run)


class GrabCutMatting:
    """OpenCV GrabCut seeded from a centre rectangle.

    Crude next to a learned matter, but it needs no weights and no GPU, and it exists so
    the remove-background path always has *something* behind it rather than failing.
    """

    name = "local:grabcut"

    async def infer(self, image: bytes) -> bytes:
        import asyncio

        def run() -> bytes:
            bgr = _to_bgr(image)
            h, w = bgr.shape[:2]
            mask = np.zeros((h, w), np.uint8)
            bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
            inset_x, inset_y = int(w * 0.06), int(h * 0.06)
            rect = (inset_x, inset_y, w - 2 * inset_x, h - 2 * inset_y)
            try:
                cv2.grabCut(bgr, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
            except cv2.error as exc:
                raise AdapterError(f"grabcut failed: {exc}") from exc
            alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0)
            alpha = alpha.astype(np.uint8)
            alpha = cv2.GaussianBlur(alpha, (5, 5), 0)
            return _png(alpha)

        return await asyncio.to_thread(run)


def refine_alpha(rgb: bytes, alpha_png: bytes, *, band_ratio: float = 0.004) -> bytes:
    """§1.4.2 `refine_alpha`: trimap band -> feather -> colour decontamination -> despeckle.

    Appendix A.2 names skipped colour decontamination as the defect that "reads as cheap
    AI instantly": without it, band pixels keep a fringe of the removed background.
    """
    bgr = _to_bgr(rgb)
    alpha = cv2.imdecode(np.frombuffer(alpha_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if alpha is None:
        raise AdapterError("could not decode alpha matte", recoverable=False)
    if alpha.shape[:2] != bgr.shape[:2]:
        alpha = cv2.resize(alpha, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_LINEAR)

    h, w = alpha.shape
    a = alpha.astype(np.float32) / 255.0

    # 1. Confident foreground / background, everything else is the unknown band.
    fg = (a > 0.95).astype(np.uint8)
    bg = (a < 0.05).astype(np.uint8)
    band_px = max(2, int(band_ratio * min(w, h)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (band_px * 2 + 1,) * 2)
    unknown = ((cv2.dilate(fg, kernel) > 0) & (cv2.dilate(bg, kernel) > 0))

    # 2. Feather the band so the edge is not a hard staircase.
    blurred = cv2.GaussianBlur(a, (0, 0), sigmaX=max(0.6, band_px / 2))
    a = np.where(unknown, blurred, a)

    # 3. Colour decontamination: F = (I - (1-a)B) / a, with B sampled from a local
    #    background ring around the subject.
    rgb_f = bgr.astype(np.float32)
    ring = cv2.dilate(bg, kernel) & (~fg.astype(bool)).astype(np.uint8)
    if ring.sum() > 32:
        bg_colour = rgb_f[ring.astype(bool)].mean(axis=0)
    else:
        border = np.concatenate([rgb_f[0], rgb_f[-1], rgb_f[:, 0], rgb_f[:, -1]])
        bg_colour = border.mean(axis=0)
    band = unknown & (a > 0.02)
    if band.any():
        a3 = np.clip(a[band][:, None], 0.05, 1.0)
        estimate = (rgb_f[band] - (1.0 - a3) * bg_colour[None, :]) / a3
        rgb_f[band] = np.clip(estimate, 0, 255)

    # 4. Despeckle: drop alpha islands under 0.05% of the bounding box.
    solid = (a > 0.5).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid, connectivity=8)
    if count > 1:
        min_area = max(16.0, 0.0005 * float(solid.sum() or (h * w)))
        for label in range(1, count):
            if stats[label, cv2.CC_STAT_AREA] < min_area:
                a[labels == label] = 0.0

    out = np.dstack([rgb_f.astype(np.uint8), (np.clip(a, 0, 1) * 255).astype(np.uint8)])
    return _png(out)


def compose_rgba(rgb: bytes, alpha_png: bytes) -> bytes:
    bgr = _to_bgr(rgb)
    alpha = cv2.imdecode(np.frombuffer(alpha_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if alpha.shape[:2] != bgr.shape[:2]:
        alpha = cv2.resize(alpha, (bgr.shape[1], bgr.shape[0]))
    return _png(np.dstack([bgr, alpha]))


def trim_transparent_border(rgba_png: bytes) -> tuple[bytes, int, int]:
    """Crop to the tight alpha bbox and report the new natural size (§1.4.2)."""
    rgba = _to_rgba(rgba_png)
    alpha = rgba[:, :, 3]
    coords = cv2.findNonZero((alpha > 4).astype(np.uint8))
    if coords is None:
        return rgba_png, rgba.shape[1], rgba.shape[0]
    x, y, w, h = cv2.boundingRect(coords)
    cropped = rgba[y:y + h, x:x + w]
    buf = io.BytesIO()
    Image.fromarray(cropped, "RGBA").save(buf, format="PNG")
    return buf.getvalue(), w, h


def alpha_centroid(rgba_png: bytes) -> tuple[float, float]:
    """Centre of mass of the alpha channel, normalised. §1.6 step 5 aligns subjects by
    this rather than by frame centre."""
    rgba = _to_rgba(rgba_png)
    alpha = rgba[:, :, 3].astype(np.float32)
    total = alpha.sum()
    if total <= 0:
        return 0.5, 0.5
    ys, xs = np.nonzero(alpha)
    weights = alpha[ys, xs]
    return (float((xs * weights).sum() / total / rgba.shape[1]),
            float((ys * weights).sum() / total / rgba.shape[0]))


# --------------------------------------------------------------------------------------
# Glyph detection — the §1.4.6 gate that enforces INV-1
# --------------------------------------------------------------------------------------


class OpenCVGlyphDetector:
    """Gradient + morphology text detection for the §1.4.6 glyph gate.

    Detection only, never recognition — the gate asks "is there text-like structure
    here", not "what does it say".

    The discriminating signal is **edge transitions per scanline**. Text is a run of
    vertical strokes, so a horizontal scanline through a word crosses many edges
    (measured: 20-64 for real copy); a smooth gradient crosses none and an object
    silhouette crosses about four. Density and aspect ratio alone do not separate
    those cases, which is why this is the primary filter.

    Tuned to over-report rather than under-report: a false positive costs one re-roll,
    a false negative ships baked-in text the user can never fix (Appendix A.1).
    """

    name = "local:opencv-gradient"

    # A scanline through real copy crosses this many stroke edges at minimum.
    MIN_TRANSITIONS = 8
    # Text packs edges densely (measured 0.51-0.62 of the box); an object's silhouette
    # arc is sparse (0.05-0.13). The floor sits well below the text range on purpose.
    MIN_EDGE_DENSITY = 0.18
    MAX_EDGE_DENSITY = 0.85
    # A text line is several marks of consistent height sitting on a baseline.
    MIN_MARKS = 2
    MAX_HEIGHT_VARIATION = 0.85

    async def detect(self, image: bytes) -> list[TextBox]:
        import asyncio

        return await asyncio.to_thread(self._detect_sync, image)

    @staticmethod
    def _load_flattened(data: bytes) -> np.ndarray | None:
        """Decode to BGR, compositing any alpha over neutral grey.

        Dropping the alpha channel instead would turn a cutout's transparent surround
        black, manufacturing a hard silhouette edge that reads as text to any
        gradient-based detector.
        """
        raw = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
        if raw is None:
            return None
        if raw.ndim == 2:
            return cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
        if raw.shape[2] == 4:
            alpha = raw[:, :, 3:4].astype(np.float32) / 255.0
            return (raw[:, :, :3].astype(np.float32) * alpha
                    + 128.0 * (1.0 - alpha)).astype(np.uint8)
        return raw[:, :, :3]

    def _detect_sync(self, image: bytes) -> list[TextBox]:
        bgr = self._load_flattened(image)
        if bgr is None:
            raise AdapterError("could not decode image", recoverable=False)
        h, w = bgr.shape[:2]
        # Work at a fixed scale so every threshold means the same thing on any input.
        scale = 900.0 / max(h, w)
        if scale < 1.0:
            bgr = cv2.resize(bgr, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_AREA)
        sh, sw = bgr.shape[:2]

        grey = cv2.GaussianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (3, 3), 0)
        gx = cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3)
        edges = (cv2.magnitude(gx, gy) > 60).astype(np.uint8) * 255

        # Close along x to join glyphs into words and lines, then open to drop specks.
        closed = cv2.morphologyEx(
            edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (19, 3)))
        closed = cv2.morphologyEx(
            closed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)))
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        boxes: list[TextBox] = []
        for contour in contours:
            x, y, bw, bh = cv2.boundingRect(contour)
            if bw < 12 or bh < 7:
                continue
            if (bw * bh) / float(sw * sh) > 0.45:   # the whole frame is not a word
                continue
            if bw / float(bh) < 0.7:                # text lines are wider than tall
                continue

            roi = edges[y:y + bh, x:x + bw] > 0
            density = float(roi.mean())
            if not (self.MIN_EDGE_DENSITY < density < self.MAX_EDGE_DENSITY):
                continue

            transitions = np.abs(np.diff(roi.astype(np.int8), axis=1)).sum(axis=1)
            nonzero = transitions[transitions > 0]
            median_transitions = float(np.median(nonzero)) if nonzero.size else 0.0
            if median_transitions < self.MIN_TRANSITIONS:
                continue

            n_cc, _, stats, _ = cv2.connectedComponentsWithStats(
                roi.astype(np.uint8), connectivity=8)
            heights = [stats[i, cv2.CC_STAT_HEIGHT] for i in range(1, n_cc)
                       if stats[i, cv2.CC_STAT_AREA] >= 4]
            if len(heights) < self.MIN_MARKS:
                continue
            median_h = float(np.median(heights))
            if median_h <= 0:
                continue
            if float(np.std(heights) / median_h) > self.MAX_HEIGHT_VARIATION:
                continue
            if not (0.25 < median_h / float(bh) <= 1.05):
                continue

            boxes.append(TextBox(
                x=x / sw, y=y / sh, w=bw / sw, h=bh / sh,
                score=min(1.0, median_transitions / 20.0),
            ))
        return boxes


# --------------------------------------------------------------------------------------
# Inpainting and upscaling
# --------------------------------------------------------------------------------------


class OpenCVInpainter:
    """Telea fill. Cheap and seamless on uniform regions; do not expect it to invent
    structure. §2.7 recommends exactly this tier where the background is flat."""

    name = "local:opencv-telea"

    async def fill(self, image: bytes, mask: bytes, *, prompt: str = "",
                   negative_prompt: str = "") -> ImageResult:
        import asyncio

        def run() -> ImageResult:
            bgr = _to_bgr(image)
            m = cv2.imdecode(np.frombuffer(mask, np.uint8), cv2.IMREAD_GRAYSCALE)
            if m is None:
                raise AdapterError("could not decode mask", recoverable=False)
            if m.shape[:2] != bgr.shape[:2]:
                m = cv2.resize(m, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
            # §2.7: dilate before filling, or a ghost ring of the removed object remains.
            radius = max(3, int(0.004 * min(bgr.shape[:2])))
            m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                        (radius * 2 + 1,) * 2))
            filled = cv2.inpaint(bgr, (m > 127).astype(np.uint8), radius, cv2.INPAINT_TELEA)
            return ImageResult(data=_png(filled), mime="image/png",
                               width=filled.shape[1], height=filled.shape[0],
                               model=self.name, cost_cents=0)

        return await asyncio.to_thread(run)


class LanczosUpscaler:
    """§1.4.4 wants a Real-ESRGAN-class model; that needs a GPU. Lanczos plus a mild
    unsharp mask is the honest CPU substitute — it will not hallucinate detail."""

    name = "local:lanczos"

    async def upscale(self, image: bytes, scale: int = 2) -> ImageResult:
        import asyncio

        def run() -> ImageResult:
            with Image.open(io.BytesIO(image)) as img:
                mode = "RGBA" if img.mode in ("RGBA", "LA", "PA") else "RGB"
                img = img.convert(mode)
                out = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
                array = np.array(out)
                rgb = array[:, :, :3].astype(np.float32)
                blur = cv2.GaussianBlur(rgb, (0, 0), 1.2)
                sharp = np.clip(rgb + 0.45 * (rgb - blur), 0, 255).astype(np.uint8)
                array[:, :, :3] = sharp
                buf = io.BytesIO()
                Image.fromarray(array, mode).save(buf, format="PNG")
                return ImageResult(data=buf.getvalue(), mime="image/png",
                                   width=out.width, height=out.height,
                                   model=self.name, has_alpha=(mode == "RGBA"),
                                   cost_cents=0)

        return await asyncio.to_thread(run)
