"""Font registry — resolves (family, weight, style) to a real font file.

Backs the layout engine (§1.6), the Skia exporter (§4.1) and the browser's @font-face
list. All three must agree on which file a text layer uses, so resolution happens here
and nowhere else.

Also carries the `embeddable` flag §4.1 requires for PDF export: a face that may not be
embedded is outlined to paths instead.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import uharfbuzz as hb
from fontTools.ttLib import TTFont

FONT_DIR = Path(__file__).resolve().parent.parent.parent / "assets_local" / "fonts"

# Used when a document names a family we do not have. Wide coverage, neutral shape.
FALLBACK_FAMILY = "Noto Sans"


@dataclass(frozen=True)
class FaceMetrics:
    units_per_em: int
    ascender: float      # font units
    descender: float     # font units, negative
    line_gap: float
    cap_height: float
    x_height: float

    def scaled(self, size: float) -> ScaledMetrics:
        k = size / self.units_per_em
        return ScaledMetrics(
            ascender=self.ascender * k,
            descender=self.descender * k,
            line_gap=self.line_gap * k,
            cap_height=self.cap_height * k,
            x_height=self.x_height * k,
            size=size,
        )


@dataclass(frozen=True)
class ScaledMetrics:
    ascender: float
    descender: float
    line_gap: float
    cap_height: float
    x_height: float
    size: float

    @property
    def natural_line_height(self) -> float:
        return self.ascender - self.descender + self.line_gap


@dataclass
class Face:
    key: str
    family: str
    weight: int
    style: str
    path: Path
    vibe: str
    embeddable: bool
    metrics: FaceMetrics
    _hb_font: hb.Font
    _lock: threading.Lock

    def hb_font_at(self, size: float) -> hb.Font:
        """HarfBuzz fonts are stateful (scale); guard mutation so shaping is thread-safe."""
        return self._hb_font


class FontRegistry:
    """Loads `catalog.json` produced by scripts/fetch_fonts.py."""

    def __init__(self, font_dir: Path | None = None):
        self.dir = Path(font_dir or FONT_DIR)
        self._faces: dict[str, Face] = {}
        self._by_family: dict[str, list[Face]] = {}
        self._catalog: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load_catalog()

    def _load_catalog(self) -> None:
        cat_path = self.dir / "catalog.json"
        if not cat_path.exists():
            raise RuntimeError(
                f"font catalog missing at {cat_path}. Run: python scripts/fetch_fonts.py"
            )
        self._catalog = json.loads(cat_path.read_text())

    # -- resolution -------------------------------------------------------------------

    @property
    def families(self) -> list[str]:
        return sorted({e["family"] for e in self._catalog.values()})

    def families_for_vibe(self, vibe: str) -> list[str]:
        return sorted({e["family"] for e in self._catalog.values() if e["vibe"] == vibe})

    def weights_for(self, family: str) -> list[int]:
        return sorted({e["weight"] for e in self._catalog.values()
                       if e["family"] == family and e["style"] == "normal"})

    def resolve_key(self, family: str, weight: int, style: str = "normal") -> str:
        """Exact face, else nearest weight in the family, else the fallback family.

        Returns a catalog key. Never raises — a missing family must degrade, not fail a
        render (§0.9 "a partial design always beats an error page").
        """
        candidates = [
            (k, e) for k, e in self._catalog.items()
            if e["family"] == family and e["style"] == style
        ]
        if not candidates and style == "italic":
            # Synthetic italic is not worth it; fall back to upright in the same family.
            candidates = [
                (k, e) for k, e in self._catalog.items()
                if e["family"] == family and e["style"] == "normal"
            ]
        if not candidates:
            if family != FALLBACK_FAMILY:
                return self.resolve_key(FALLBACK_FAMILY, weight, "normal")
            candidates = list(self._catalog.items())
        # Nearest weight; ties break heavier, which reads better for display type.
        key, _ = min(candidates, key=lambda kv: (abs(kv[1]["weight"] - weight),
                                                 -kv[1]["weight"]))
        return key

    def face(self, family: str, weight: int, style: str = "normal") -> Face:
        return self.face_by_key(self.resolve_key(family, weight, style))

    def face_by_key(self, key: str) -> Face:
        with self._lock:
            cached = self._faces.get(key)
            if cached is not None:
                return cached
        entry = self._catalog[key]
        path = self.dir / entry["file"]
        blob = hb.Blob.from_file_path(str(path))
        hb_face = hb.Face(blob)
        hb_font = hb.Font(hb_face)
        metrics = _read_metrics(path, hb_face.upem)
        face = Face(
            key=key,
            family=entry["family"],
            weight=entry["weight"],
            style=entry["style"],
            path=path,
            vibe=entry["vibe"],
            embeddable=entry.get("embeddable", True),
            metrics=metrics,
            _hb_font=hb_font,
            _lock=threading.Lock(),
        )
        with self._lock:
            self._faces.setdefault(key, face)
            self._by_family.setdefault(face.family, []).append(face)
        return face

    def css_face_list(self) -> list[dict]:
        """@font-face descriptors for the editor, so the browser previews the real face."""
        return [
            {
                "key": k,
                "family": e["family"],
                "weight": e["weight"],
                "style": e["style"],
                "url": f"/v1/fonts/{k}.ttf",
            }
            for k, e in sorted(self._catalog.items())
        ]


def _read_metrics(path: Path, upem: int) -> FaceMetrics:
    tt = TTFont(str(path), lazy=True)
    try:
        hhea = tt["hhea"]
        os2 = tt.get("OS/2")
        cap = getattr(os2, "sCapHeight", 0) or 0
        xh = getattr(os2, "sxHeight", 0) or 0
        # Some faces omit these; approximate from the typographic ascender.
        asc = getattr(os2, "sTypoAscender", 0) or hhea.ascent
        desc = getattr(os2, "sTypoDescender", 0) or hhea.descent
        gap = getattr(os2, "sTypoLineGap", 0) or hhea.lineGap
        return FaceMetrics(
            units_per_em=upem,
            ascender=float(hhea.ascent or asc),
            descender=float(hhea.descent or desc),
            line_gap=float(hhea.lineGap or gap),
            cap_height=float(cap or asc * 0.7),
            x_height=float(xh or asc * 0.52),
        )
    finally:
        tt.close()


@lru_cache(maxsize=1)
def get_registry() -> FontRegistry:
    return FontRegistry()
