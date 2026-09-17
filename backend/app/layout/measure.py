"""Text measurement and shaping — IMPLEMENTATION_PLAN §1.6 step 1.

HarfBuzz-shapes each text layer with the real font file and produces line breaks,
glyph advances and a tight ink bounding box. Per ADR 0001 this is the only text
shaper in the system: the browser renders the `PositionedGlyphRun`s produced here
rather than shaping for itself, which is how INV-3 is upheld.

Cached by (text, family, weight, style, size, letterSpacing, width, language, transform)
as §1.6/§6.5 require.
"""

from __future__ import annotations

import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field

import uharfbuzz as hb

from app.layout.fonts import Face, ScaledMetrics, get_registry
from app.renderer.transform import Rect
from app.schema.draw import PositionedGlyph, PositionedGlyphRun

# Scripts written right-to-left; HarfBuzz detects this itself, we only mirror alignment.
_RTL_LANGS = {"ar", "he", "fa", "ur", "yi", "dv", "ps"}

# Body copy at or above this many lines gets Knuth-Plass instead of greedy (§1.6).
KNUTH_PLASS_MIN_LINES = 3


@dataclass
class ShapedLine:
    text: str
    runs: list[PositionedGlyphRun]
    advance: float           # pen advance of the line
    ink_left: float          # ink bbox relative to the line's own origin (baseline at y=0)
    ink_right: float
    ink_top: float
    ink_bottom: float
    baseline_y: float = 0.0  # filled in by shape_block, relative to the block top

    @property
    def ink_width(self) -> float:
        return max(0.0, self.ink_right - self.ink_left)


@dataclass
class ShapedBlock:
    lines: list[ShapedLine] = field(default_factory=list)
    font_key: str = ""
    font_size: float = 0
    line_height_px: float = 0
    metrics: ScaledMetrics | None = None
    width: float = 0          # widest line advance
    height: float = 0         # total laid-out height (n_lines * line_height_px)
    ink: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    overflowed_width: bool = False   # a single unbreakable token exceeded the width

    @property
    def line_count(self) -> int:
        return len(self.lines)


def apply_transform(text: str, transform: str) -> str:
    """§1.3: uppercase is applied at render time, never baked into `content`."""
    if transform == "uppercase":
        return text.upper()
    if transform == "capitalize":
        return "".join(
            word[:1].upper() + word[1:] if word else word
            for word in _split_keep(text)
        )
    return text


def _split_keep(text: str) -> list[str]:
    out, buf = [], ""
    for ch in text:
        if ch.isspace():
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
        else:
            buf += ch
    if buf:
        out.append(buf)
    return out


# --------------------------------------------------------------------------------------
# Core shaping
# --------------------------------------------------------------------------------------


def _hb_language(lang: str) -> str:
    return (lang or "en").split("-")[0].lower()


def is_rtl(lang: str) -> bool:
    return _hb_language(lang) in _RTL_LANGS


def shape_line(
    text: str,
    face: Face,
    size: float,
    letter_spacing: float = 0.0,
    language: str = "en",
) -> ShapedLine:
    """Shape one line (no newlines). Positions are in px, baseline at y = 0, pen at x = 0.

    HarfBuzz is left at its default scale (= units per em) and converted to px here, so
    we keep full float precision instead of HarfBuzz's integer scaling.
    """
    hb_font = face.hb_font_at(size)
    buf = hb.Buffer()
    buf.add_str(text if text else "")
    buf.guess_segment_properties()
    if language:
        buf.language = _hb_language(language)
    hb.shape(hb_font, buf)

    upem = face.metrics.units_per_em
    k = size / upem

    glyphs: list[PositionedGlyph] = []
    pen = 0.0
    ink_left, ink_right = float("inf"), float("-inf")
    ink_top, ink_bottom = float("inf"), float("-inf")

    # An empty buffer never acquires a content type, so uharfbuzz hands back None rather
    # than an empty sequence. Text with nothing in it is not a rare case — a run of
    # spaces tokenizes to one whitespace token whose stripped form is "", and a layer the
    # user has cleared is empty too — and without this the whole solver dies on it.
    infos = buf.glyph_infos or []
    positions = buf.glyph_positions or []
    for idx, (info, pos) in enumerate(zip(infos, positions)):
        gx = pen + pos.x_offset * k
        gy = -pos.y_offset * k  # HarfBuzz y is up; canvas y is down
        cluster = info.cluster
        glyphs.append(
            PositionedGlyph(
                gid=info.codepoint,
                cluster=cluster,
                x=gx,
                y=gy,
                text=_cluster_text(text, infos, idx),
            )
        )
        try:
            ext = hb_font.get_glyph_extents(info.codepoint)
        except Exception:  # noqa: BLE001 - not all backends expose extents
            ext = None
        if ext is not None and ext.width and ext.height:
            x0 = gx + ext.x_bearing * k
            y0 = gy - ext.y_bearing * k
            x1 = x0 + ext.width * k
            y1 = y0 - ext.height * k
            ink_left = min(ink_left, x0, x1)
            ink_right = max(ink_right, x0, x1)
            ink_top = min(ink_top, y0, y1)
            ink_bottom = max(ink_bottom, y0, y1)

        pen = gx - pos.x_offset * k + pos.x_advance * k + letter_spacing

    # Letter spacing is inserted after every glyph; the trailing one is not part of the
    # line's visual width.
    advance = max(0.0, pen - letter_spacing) if glyphs else 0.0

    if ink_left == float("inf"):  # whitespace-only line has no ink
        ink_left = ink_right = 0.0
        ink_top = ink_bottom = 0.0

    run = PositionedGlyphRun(
        font_family=face.family,
        font_weight=face.weight,
        font_style=face.style,
        font_size=size,
        font_key=face.key,
        glyphs=glyphs,
        origin_x=0.0,
        origin_y=0.0,
        advance=advance,
        direction="rtl" if is_rtl(language) else "ltr",
    )
    return ShapedLine(
        text=text,
        runs=[run],
        advance=advance,
        ink_left=ink_left,
        ink_right=ink_right,
        ink_top=ink_top,
        ink_bottom=ink_bottom,
    )


def _cluster_text(source: str, infos, idx: int) -> str:
    """Source characters this glyph came from, for the Konva backend to draw."""
    start = infos[idx].cluster
    end = infos[idx + 1].cluster if idx + 1 < len(infos) else len(source)
    if end < start:  # RTL buffers run backwards
        start, end = end, start
    return source[start:end]


# --------------------------------------------------------------------------------------
# Line breaking
# --------------------------------------------------------------------------------------


def _token_widths(
    tokens: list[str], face: Face, size: float, letter_spacing: float, language: str
) -> tuple[list[float], list[float]]:
    """Return (advance widths, visible widths).

    A token ending in a space still advances the pen, but its trailing space is not
    visible ink. Line-fitting must use the visible width for the last token on a line,
    otherwise a line wraps one word early whenever it ends flush with the frame.
    """
    advances, visible = [], []
    for token in tokens:
        advances.append(shape_line(token, face, size, letter_spacing, language).advance)
        stripped = token.rstrip()
        visible.append(
            advances[-1] if stripped == token
            else shape_line(stripped, face, size, letter_spacing, language).advance
        )
    return advances, visible


def _tokenize(paragraph: str) -> list[str]:
    """Split into breakable tokens. Break opportunities are spaces and after hyphens."""
    words: list[str] = []
    buf = ""
    for ch in paragraph:
        buf += ch
        if ch == " " or (ch == "-" and len(buf) > 1):
            words.append(buf)
            buf = ""
    if buf:
        words.append(buf)
    return words or [""]


def _greedy_break(
    widths: list[float], visible: list[float], max_width: float
) -> list[list[int]]:
    """First-fit wrap. A line is judged by its *visible* width, so a trailing space
    never pushes a word to the next line."""
    lines: list[list[int]] = []
    cur: list[int] = []
    cur_advance = 0.0
    for i, adv in enumerate(widths):
        if cur and cur_advance + visible[i] > max_width:
            lines.append(cur)
            cur, cur_advance = [i], adv
        else:
            cur.append(i)
            cur_advance += adv
    if cur:
        lines.append(cur)
    return lines


def _knuth_plass_break(
    widths: list[float], visible: list[float], max_width: float
) -> list[list[int]]:
    """Total-fit breaking: minimise the sum of cubed raggedness over all lines.

    Cheaper than the full algorithm (no hyphenation penalties or flagged breaks) but it
    gives the even rag that makes multi-line body copy look typeset rather than wrapped.
    """
    n = len(widths)
    if n == 0:
        return []
    # prefix[i] = total advance of tokens[0:i]
    prefix = [0.0]
    for w in widths:
        prefix.append(prefix[-1] + w)

    INF = float("inf")
    cost = [INF] * (n + 1)
    prev = [0] * (n + 1)
    cost[0] = 0.0

    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            # Visible width of tokens[i:j]: full advances except the last token, which
            # contributes only its ink so a trailing space costs nothing.
            line_w = (prefix[j - 1] - prefix[i]) + visible[j - 1]
            if line_w > max_width and j - i > 1:
                break  # any earlier i is only wider
            if cost[i] == INF:
                continue
            if line_w > max_width:
                penalty = (line_w - max_width) ** 3 * 1000  # unbreakable token: tolerate
            elif j == n:
                penalty = 0.0  # the last line may be short for free
            else:
                penalty = (max_width - line_w) ** 3
            if cost[i] + penalty < cost[j]:
                cost[j] = cost[i] + penalty
                prev[j] = i

    lines: list[list[int]] = []
    j = n
    while j > 0:
        i = prev[j]
        lines.append(list(range(i, j)))
        j = i
    lines.reverse()
    return lines


# --------------------------------------------------------------------------------------
# Block shaping, with cache
# --------------------------------------------------------------------------------------

_CACHE: OrderedDict[tuple, ShapedBlock] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 4096
_STATS = {"hits": 0, "misses": 0}


def cache_stats() -> dict[str, int]:
    return dict(_STATS, size=len(_CACHE))


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
        _STATS.update(hits=0, misses=0)


def shape_block(
    content: str,
    *,
    font_family: str,
    font_weight: int = 400,
    font_style: str = "normal",
    font_size: float = 16.0,
    line_height: float = 1.2,
    letter_spacing: float = 0.0,
    max_width: float = 1e9,
    language: str = "en",
    text_transform: str = "none",
) -> ShapedBlock:
    """Shape a full text block, wrapping to `max_width`. Result is cached."""
    key = (
        content, font_family, font_weight, font_style, round(font_size, 3),
        round(line_height, 4), round(letter_spacing, 3), round(max_width, 2),
        language, text_transform,
    )
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            _STATS["hits"] += 1
            return hit
    _STATS["misses"] += 1

    block = _shape_block_uncached(
        content, font_family, font_weight, font_style, font_size,
        line_height, letter_spacing, max_width, language, text_transform,
    )

    with _CACHE_LOCK:
        _CACHE[key] = block
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return block


def _shape_block_uncached(
    content: str, font_family: str, font_weight: int, font_style: str, font_size: float,
    line_height: float, letter_spacing: float, max_width: float, language: str,
    text_transform: str,
) -> ShapedBlock:
    registry = get_registry()
    face = registry.face(font_family, font_weight, font_style)
    text = apply_transform(content, text_transform)
    text = unicodedata.normalize("NFC", text)

    metrics = face.metrics.scaled(font_size)
    line_height_px = line_height * font_size

    shaped_lines: list[ShapedLine] = []
    overflowed = False

    for paragraph in text.split("\n"):
        if paragraph == "":
            shaped_lines.append(shape_line("", face, font_size, letter_spacing, language))
            continue
        tokens = _tokenize(paragraph)
        widths, visible = _token_widths(tokens, face, font_size, letter_spacing, language)

        single = shape_line(paragraph, face, font_size, letter_spacing, language)
        if single.advance <= max_width:
            shaped_lines.append(single)
            continue

        greedy = _greedy_break(widths, visible, max_width)
        if len(greedy) >= KNUTH_PLASS_MIN_LINES:
            groups = _knuth_plass_break(widths, visible, max_width)
        else:
            groups = greedy

        for group in groups:
            line_text = "".join(tokens[i] for i in group).rstrip()
            line = shape_line(line_text, face, font_size, letter_spacing, language)
            if line.advance > max_width + 0.5:
                overflowed = True
            shaped_lines.append(line)

    # Vertical placement: first baseline sits one ascender below the top of the block,
    # centred within the leading so `lineHeight` behaves like CSS.
    half_leading = (line_height_px - (metrics.ascender - metrics.descender)) / 2
    for i, line in enumerate(shaped_lines):
        line.baseline_y = i * line_height_px + half_leading + metrics.ascender

    width = max((line.advance for line in shaped_lines), default=0.0)
    height = len(shaped_lines) * line_height_px

    ink_x0 = min((line.ink_left for line in shaped_lines), default=0.0)
    ink_x1 = max((line.ink_right for line in shaped_lines), default=0.0)
    ink_y0 = min((line.baseline_y + line.ink_top for line in shaped_lines), default=0.0)
    ink_y1 = max((line.baseline_y + line.ink_bottom for line in shaped_lines), default=0.0)

    return ShapedBlock(
        lines=shaped_lines,
        font_key=face.key,
        font_size=font_size,
        line_height_px=line_height_px,
        metrics=metrics,
        width=width,
        height=height,
        ink=Rect(ink_x0, ink_y0, max(0.0, ink_x1 - ink_x0), max(0.0, ink_y1 - ink_y0)),
        overflowed_width=overflowed,
    )
