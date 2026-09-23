"""Measure how template copy actually sets in its box, using the layer's real font.

A characters-per-line estimate breaks on wide display faces: "Smoothie" is 8 letters
like "Healthy Food"'s "Healthy", but in Yeseva One at 50px it is ~40px wider and
overflows a 200px headline box that "Healthy" fits. So wrapping is simulated with real
glyph advances (Pillow + the font file) the way a browser wraps a fixed-width box.

Fonts are cached in `lidojs_templates/fonts/`, fetched once from the URL the Lido layer
itself carries or, failing that, from Google Fonts by family name. With no font file
available the measurement falls back to an average-advance estimate, so a missing font
degrades accuracy rather than failing a generation.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

import structlog
from PIL import ImageFont

from .loader import DEFAULT_CORPUS_DIR

log = structlog.get_logger(__name__)

FONT_CACHE_DIR = DEFAULT_CORPUS_DIR / "fonts"

# Fallback advance as a fraction of font size when no font file can be had.
_FALLBACK_ADVANCE = 0.5
_FALLBACK_ADVANCE_UPPERCASE = 0.6
# Pillow and the browser agree to about a pixel per line; keep that slack so copy that
# "just fits" here doesn't wrap in the editor. Not more: template_227's own "Healthy"
# genuinely sets at 196px in its 200px headline box.
_WIDTH_SAFETY = 0.99
_SAMPLE = "the quick brown fox jumps over the lazy dog"
_GOOGLE_CSS = "https://fonts.googleapis.com/css2?family={family}"
_TTF_URL_RE = re.compile(r"url\((https://[^)]+\.ttf)\)")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(family: str) -> str:
    return _SLUG_RE.sub("-", family.lower()).strip("-")


def family_name(css_family: str) -> str:
    """'Poppins, serif' -> 'Poppins'."""
    return css_family.split(",")[0].strip().strip("'\"")


def _download(url: str, dest: Path) -> bool:
    try:
        # No browser user agent on purpose: Google Fonts then serves TrueType, not woff2.
        with urllib.request.urlopen(url, timeout=10) as response:
            data = response.read()
    except OSError as exc:
        log.warning("lido.font.download_failed", url=url, error=str(exc))
        return False
    if not data.startswith((b"\x00\x01\x00\x00", b"true", b"OTTO")):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def _google_ttf_url(family: str) -> str | None:
    url = _GOOGLE_CSS.format(family=urllib.parse.quote_plus(family))
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            css = response.read().decode("utf-8", "replace")
    except OSError as exc:
        log.warning("lido.font.lookup_failed", family=family, error=str(exc))
        return None
    match = _TTF_URL_RE.search(css)
    return match.group(1) if match else None


def font_file(family: str, urls: tuple[str, ...] = ()) -> Path | None:
    """Local TTF for `family`, downloading it into the cache on first use. A failed
    download isn't remembered, so a network blip doesn't pin the estimate for good."""
    path = FONT_CACHE_DIR / f"{_slug(family)}.ttf"
    if path.is_file():
        return path
    for url in urls:
        if _download(url, path):
            break
    else:
        google = _google_ttf_url(family)
        if not (google and _download(google, path)):
            return None
    log.info("lido.font.cached", family=family, path=str(path))
    return path


@lru_cache(maxsize=256)
def _font(path: Path, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=max(1, round(size)))


def apply_transform(text: str, transform: str | None) -> str:
    if transform == "uppercase":
        return text.upper()
    if transform == "lowercase":
        return text.lower()
    if transform == "capitalize":
        return re.sub(r"(^|\s)(\S)", lambda m: m.group(1) + m.group(2).upper(), text)
    return text


class TextMeasure:
    """Width of a string as a given layer would render it, in canvas pixels."""

    def __init__(self, font_path: Path | None, size: float, transform: str | None,
                 letter_spacing_em: float = 0.0):
        self.font_path, self.size, self.transform = font_path, size, transform
        self.letter_spacing = letter_spacing_em * size

    @property
    def exact(self) -> bool:
        return self.font_path is not None

    def width(self, text: str) -> float:
        text = apply_transform(text, self.transform)
        if self.font_path is not None:
            base = _font(self.font_path, self.size).getlength(text)
        else:
            ratio = (_FALLBACK_ADVANCE_UPPERCASE if self.transform == "uppercase"
                     else _FALLBACK_ADVANCE)
            base = len(text) * self.size * ratio
        return base + self.letter_spacing * len(text)

    def average_chars_per_line(self, box_width: float) -> int:
        per_char = self.width(_SAMPLE) / len(_SAMPLE)
        return max(1, int(box_width * _WIDTH_SAFETY / per_char))


def wrap(text: str, measure: TextMeasure, box_width: float) -> list[str]:
    """Greedy word wrap, the way a browser sets a fixed-width text box."""
    limit = box_width * _WIDTH_SAFETY
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if not current or measure.width(candidate) <= limit:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def too_wide_words(text: str, measure: TextMeasure, box_width: float) -> list[str]:
    limit = box_width * _WIDTH_SAFETY
    return [w for w in text.split() if measure.width(w) > limit]
