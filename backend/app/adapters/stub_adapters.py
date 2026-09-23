"""Deterministic offline adapters.

Two jobs:

  1. Let the whole pipeline run end to end with no API key, so the plumbing, the layout
     solver, the editor and export can be developed and tested without spending money
     or waiting on a GPU.
  2. Exercise the *degraded* paths on purpose. `StubLLM` refuses rather than inventing
     output, which forces the §1.1 heuristic brief parser and the §1.3 mechanical
     composer fallback to run — the paths that must work when the model is down.

Images are procedural but deterministic: the same prompt and seed always produce the
same pixels, so INV-2 holds exactly in stub mode.
"""

from __future__ import annotations

import colorsys
import hashlib
import io
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from app.adapters.base import AdapterError, ImageResult, TextBox


def _seed_from(prompt: str, seed: int) -> int:
    digest = hashlib.sha256(f"{prompt}|{seed}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _palette_from(prompt: str, seed: int, n: int = 3) -> list[tuple[int, int, int]]:
    rng = np.random.default_rng(_seed_from(prompt, seed))
    base_hue = float(rng.random())
    out = []
    for i in range(n):
        hue = (base_hue + i * 0.11) % 1.0
        sat = 0.35 + 0.4 * float(rng.random())
        val = 0.25 + 0.6 * (i / max(1, n - 1))
        r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    return out


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class StubTextToImage:
    """A plausible empty backdrop: vertical gradient plus soft light blobs, and — by
    construction — no glyphs, so the §1.4.6 gate always passes in stub mode."""

    name = "stub:gradient"

    async def generate(self, *, prompt: str, negative_prompt: str = "", width: int = 1024,
                       height: int = 1024, seed: int = 0, steps: int = 28,
                       cfg: float = 4.5, quality: str = "medium") -> ImageResult:
        rng = np.random.default_rng(_seed_from(prompt, seed))
        colours = _palette_from(prompt, seed, 3)
        top = np.array(colours[0], dtype=np.float32)
        bottom = np.array(colours[2], dtype=np.float32)

        ramp = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
        canvas = top[None, None, :] * (1 - ramp) + bottom[None, None, :] * ramp
        canvas = np.repeat(canvas, width, axis=1)

        # A couple of soft light pools, so harmonisation has a light direction to find.
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        for _ in range(2):
            cx, cy = float(rng.random()) * width, float(rng.random()) * height * 0.6
            radius = (0.25 + 0.3 * float(rng.random())) * max(width, height)
            falloff = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * radius ** 2)))
            canvas += falloff[:, :, None] * 46.0

        img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), "RGB")
        img = img.filter(ImageFilter.GaussianBlur(radius=max(width, height) / 400))
        return ImageResult(data=_png_bytes(img), mime="image/png", width=width,
                           height=height, model=self.name, has_alpha=False,
                           cost_cents=0, params={"seedSupported": True, "seed": seed})


class StubTransparentImage:
    """A rounded organic silhouette with a genuine soft alpha edge, so matting,
    trimming and shadow-grounding all have something real to operate on."""

    name = "stub:blob-alpha"

    async def generate(self, *, prompt: str, negative_prompt: str = "", width: int = 1024,
                       height: int = 1024, seed: int = 0, steps: int = 30,
                       cfg: float = 5.0, quality: str = "medium") -> ImageResult:
        rng = np.random.default_rng(_seed_from(prompt, seed))
        colours = _palette_from(prompt, seed, 3)
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        cx, cy = width / 2, height / 2
        rx, ry = width * 0.34, height * 0.34
        points = []
        for i in range(48):
            angle = 2 * math.pi * i / 48
            wobble = 1.0 + 0.16 * math.sin(angle * 3 + float(rng.random()) * 6)
            points.append((cx + math.cos(angle) * rx * wobble,
                           cy + math.sin(angle) * ry * wobble))
        draw.polygon(points, fill=colours[1] + (255,))

        # Soften the edge so the matte is not a hard cut.
        alpha = img.split()[-1].filter(ImageFilter.GaussianBlur(radius=max(2, width / 300)))
        img.putalpha(alpha)

        # A simple diagonal highlight, so colour matching has something to correct.
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(overlay).ellipse(
            [cx - rx * 0.7, cy - ry * 0.9, cx + rx * 0.1, cy - ry * 0.1],
            fill=(255, 255, 255, 46),
        )
        img = Image.alpha_composite(img, overlay)
        img.putalpha(alpha)

        return ImageResult(data=_png_bytes(img), mime="image/png", width=width,
                           height=height, model=self.name, has_alpha=True,
                           cost_cents=0, params={"seedSupported": True, "seed": seed})


class StubInpainter:
    name = "stub:inpaint"

    async def fill(self, image: bytes, mask: bytes, *, prompt: str = "",
                   negative_prompt: str = "") -> ImageResult:
        from app.adapters.local_adapters import OpenCVInpainter

        return await OpenCVInpainter().fill(image, mask, prompt=prompt,
                                            negative_prompt=negative_prompt)


class StubGlyphDetector:
    """Reports nothing. Only correct alongside stub image generation, which draws no
    glyphs; never select this when a real image model is in use."""

    name = "stub:no-glyphs"

    async def detect(self, image: bytes) -> list[TextBox]:
        return []


class HashEmbedder:
    """Deterministic hashed bag-of-words embedding.

    Good enough to make template retrieval *work* offline — similar descriptions land
    near each other — but it has no semantics, so retrieval quality with this embedder
    is not representative. Swap in the real embedder before judging layout choice.
    """

    name = "stub:hash-embedder"

    def __init__(self, dim: int = 1536):
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vector = np.zeros(self.dim, dtype=np.float32)
            tokens = [t for t in text.lower().replace(",", " ").split() if len(t) > 2]
            for token in tokens:
                digest = hashlib.sha1(token.encode()).digest()
                for k in range(4):
                    index = int.from_bytes(digest[k * 4:(k + 1) * 4], "big") % self.dim
                    vector[index] += 1.0
            norm = float(np.linalg.norm(vector))
            out.append((vector / norm).tolist() if norm else vector.tolist())
        return out


class StubLLM:
    """Refuses, deliberately.

    Returning plausible-looking fabricated JSON would hide the fact that no model is
    configured and would make offline output look better than it is. Refusing routes the
    caller to the heuristic brief parser (§1.1) and the mechanical composer fallback
    (§1.3), which are paths that must work in production anyway.
    """

    name = "stub:llm-unavailable"

    async def complete_json(self, *, system: str, user, schema, temperature: float = 0.2,
                            model: str | None = None, max_tokens: int = 4096,
                            reasoning_effort: str | None = None):
        raise AdapterError(
            "no LLM configured (set OPENAI_API_KEY); using the heuristic fallback",
            recoverable=False,
        )
