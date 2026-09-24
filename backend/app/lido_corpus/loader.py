"""Dynamic directory loader for Lido.js templates.

No template is ever named in code. `discover_templates()` globs `*.json` in a directory
at call time; add `template_6.json` tomorrow and it is in the corpus on the next call,
no import to edit. Metadata (`meta.slots`, `meta.canvas_size`, ...) is *recomputed from
the layers* every load, so it can never drift out of sync with the actual document — only
the human-authored fields (`name`, `kind`, `tags`, `description`) persist across runs,
because those can't be derived from geometry alone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .model import (
    ImageSpec,
    LidoDocument,
    LidoLayer,
    LidoTemplateFile,
    LidoTemplateMeta,
    SlotInfo,
    SlotRole,
)

DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[3] / "lidojs_templates"


def discover_templates(directory: Path | str = DEFAULT_CORPUS_DIR) -> list[Path]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.json") if not p.name.endswith(".meta.json"))


def _read_root_object(path: Path) -> dict:
    """Lido exports as `[{"layers": {...}, "meta": {...}?}]` — a one-element array."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        if not data:
            raise ValueError(f"{path}: empty array")
        return data[0]
    return data  # tolerate a bare object too


def _font_size(layer: LidoLayer) -> float | None:
    sizes = layer.props.get("fontSizes")
    if sizes:
        try:
            return float(sizes[0])
        except (TypeError, ValueError):
            pass
    return None


def _default_text(layer: LidoLayer) -> str | None:
    doc = layer.props.get("doc")
    if not isinstance(doc, dict):
        return None
    parts: list[str] = []
    for para in doc.get("content", []):
        for node in para.get("content", []):
            text = node.get("text")
            if text:
                parts.append(text)
    return " ".join(parts) or None


_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
_URL_RE = re.compile(r"^(https?://)?(www\.)?[\w-]+(\.[\w-]+)*\.[a-z]{2,}(/\S*)?$", re.IGNORECASE)
_PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,}$")

# Lido `type.type` values that carry free copy (not contact details, not a logo). An
# untyped TextLayer (`None`) is free copy too — many exports leave the type empty.
_FREE_TEXT_TYPES = {"bodyText", "title", "static", None}


def _contact_role_from_text(text: str | None) -> SlotRole | None:
    """An untyped or mistyped layer whose sample text *is* a contact detail — the
    export's type tag is often missing, and treating a website as free copy lets the
    fill model invent one."""
    t = (text or "").strip()
    if not t:
        return None
    if _EMAIL_RE.match(t):
        return "email"
    if _URL_RE.match(t) and " " not in t:
        return "website"
    if _PHONE_RE.match(t) and sum(c.isdigit() for c in t) >= 7:
        return "phone"
    return None


def _is_logo_frame(layer: LidoLayer) -> bool:
    """A FrameLayer is the brand logo when tagged so, or — for untyped exports — when
    its image is a logo asset. Treating a logo as a photo gets it regenerated."""
    if layer.type.type == "logo":
        return True
    url = ((layer.props.get("image") or {}).get("url") or "").lower()
    name = url.rsplit("/", 1)[-1]
    return "logo" in name


def _box_center(layer: LidoLayer) -> tuple[float, float] | None:
    pos, box = layer.props.get("position") or {}, layer.props.get("boxSize") or {}
    if not box.get("width") or not box.get("height"):
        return None
    return (float(pos.get("x", 0)) + float(box["width"]) / 2,
            float(pos.get("y", 0)) + float(box["height"]) / 2)


def _on_shape(layer: LidoLayer, layers: dict[str, LidoLayer]) -> bool:
    """True when the text's center sits on a ShapeLayer — a button or ribbon label."""
    c = _box_center(layer)
    if c is None:
        return False
    for other in layers.values():
        if other.type.resolvedName != "ShapeLayer":
            continue
        pos, box = other.props.get("position") or {}, other.props.get("boxSize") or {}
        x, y = float(pos.get("x", 0)), float(pos.get("y", 0))
        w, h = float(box.get("width") or 0), float(box.get("height") or 0)
        if x <= c[0] <= x + w and y <= c[1] <= y + h:
            return True
    return False


def _role_for(layer_id: str, layer: LidoLayer, headline_id: str | None,
              subhead_id: str | None, layers: dict[str, LidoLayer] | None = None) -> SlotRole:
    t = layer.type.type
    rn = layer.type.resolvedName
    if rn == "RootLayer":
        return "background"
    if rn == "FrameLayer" or rn == "ImageLayer":
        return "logo" if _is_logo_frame(layer) else "photo"
    if t == "logo":
        return "logo"
    if rn == "ShapeLayer":
        return "decoration"
    if rn != "TextLayer":
        return "decoration"
    # -- text: never "decoration"; every text layer is copy someone has to write --
    if t in ("phoneNumber", "phone"):
        return "phone"
    if t == "email":
        return "email"
    if t == "address":
        return "address"
    if t == "website":
        return "website"
    contact = _contact_role_from_text(layer.type.replacableText or _default_text(layer))
    if contact:
        return contact
    if layer_id == headline_id:
        return "headline"
    if layer_id == subhead_id:
        return "subhead"
    if t == "static" or (layers is not None and _on_shape(layer, layers)):
        return "label"
    return "body"


def _free_text_ids(layers: dict[str, LidoLayer]) -> list[str]:
    return [
        lid for lid, layer in layers.items()
        if lid != "ROOT" and layer.type.resolvedName == "TextLayer"
        and layer.type.type in _FREE_TEXT_TYPES
        and not _contact_role_from_text(layer.type.replacableText or _default_text(layer))
    ]


def _extract_slots(
    layers: dict[str, LidoLayer], existing_slots: dict[str, dict] | None = None
) -> list[SlotInfo]:
    """Recompute every slot's geometry-derived fields (`role`, `editable`,
    `default_text`, `font_size`, `position`, `box_size`) fresh from the layers, every
    call — those can never drift from the actual document. But `max_chars`, `max_lines`,
    `locked`, `image` and `notes` are human-authored judgment calls that geometry can't
    reconstruct, so when a previous `meta.slots` entry for the same `layer_id` set one,
    it's carried forward instead of being silently wiped by the auto-computed default.
    """
    existing_slots = existing_slots or {}
    # The headline is the largest free-copy text of any type — a big "static" title
    # (template_1825's "Corporate Event Planning") or an untyped one (template_831's
    # गणेश) is the headline, not a label or decoration. The subhead is the next largest
    # that isn't a fixed "static" label, so a small script accent or button text never
    # outranks real supporting copy. Stable sort: equal sizes keep layer order.
    free = _free_text_ids(layers)
    ranked = sorted(free, key=lambda lid: _font_size(layers[lid]) or 0, reverse=True)
    headline_id = ranked[0] if ranked else None
    subhead_id = next((lid for lid in ranked[1:] if layers[lid].type.type != "static"), None)

    slots: list[SlotInfo] = []
    for lid, layer in layers.items():
        if lid == "ROOT":
            continue
        role = _role_for(lid, layer, headline_id, subhead_id, layers)
        # Exports sometimes carry layout whitespace inside the text ("●\n      Haircut");
        # it renders as single spaces, so the default copy and its limits should too.
        raw_text = layer.type.replacableText or _default_text(layer)
        default_text = " ".join(raw_text.split()) if raw_text else None
        prior = existing_slots.get(lid) or {}
        image = prior.get("image")
        slots.append(SlotInfo(
            layer_id=lid,
            resolved_name=layer.type.resolvedName,
            role=role,
            # Every TextLayer is fair game to rewrite — these templates are scratch
            # layout material, not fixed branding. `fixedText`/"static" only tells us
            # this text has no placeholder-style default; it does not lock the layer.
            editable=layer.type.resolvedName == "TextLayer" and default_text is not None,
            default_text=default_text,
            max_chars=prior.get("max_chars") or (
                int(len(default_text) * 1.4) + 8 if default_text else None
            ),
            max_lines=prior.get("max_lines"),
            locked=bool(prior.get("locked", False)),
            font_size=_font_size(layer),
            position=layer.props.get("position"),
            box_size=layer.props.get("boxSize"),
            image=ImageSpec.model_validate(image) if image else None,
            notes=prior.get("notes"),
        ))
    return slots


def _aspect(w: float, h: float) -> str:
    from math import gcd
    iw, ih = round(w), round(h)
    g = gcd(iw, ih) or 1
    return f"{iw // g}:{ih // g}"


def _describe(slots: list[SlotInfo]) -> str:
    present = {s.role for s in slots}
    labels = {
        "headline": "a headline", "subhead": "a subheading", "body": "body copy",
        "phone": "a phone number", "address": "an address", "website": "a website",
        "logo": "a logo", "photo": "a photo frame", "decoration": "decorative shapes",
    }
    parts = [labels[r] for r in
              ["headline", "subhead", "body", "phone", "address", "website", "logo", "photo"]
              if r in present]
    n_photos = sum(1 for s in slots if s.role == "photo")
    n_decor = sum(1 for s in slots if s.role == "decoration")
    if n_photos > 1:
        parts = [p for p in parts if p != "a photo frame"] + [f"{n_photos} photo frames"]
    if n_decor:
        parts.append(f"{n_decor} decorative shape{'s' if n_decor > 1 else ''}")
    body = ", ".join(parts[:-1]) + (" and " + parts[-1] if len(parts) > 1 else (parts[0] if parts else ""))
    return f"Template with {body}." if body else "Template."


def derive_meta(template_id: str, layers: dict[str, LidoLayer],
                 existing: dict | None = None) -> LidoTemplateMeta:
    root = layers["ROOT"]
    box = root.props.get("boxSize", {"width": 0, "height": 0})
    w, h = box.get("width", 0), box.get("height", 0)
    existing = existing or {}
    existing_slots_by_id = {
        s["layer_id"]: s for s in existing.get("slots", []) if s.get("layer_id")
    }
    slots = _extract_slots(layers, existing_slots_by_id)
    existing_background = existing.get("background")
    return LidoTemplateMeta(
        id=template_id,
        name=existing.get("name", ""),
        kind=existing.get("kind", "post"),
        aspect=_aspect(w, h) if w and h else "1:1",
        tags=existing.get("tags", []),
        description=existing.get("description") or _describe(slots),
        canvas_size={"width": w, "height": h},
        background_image_url=(root.props.get("image") or {}).get("url"),
        background=ImageSpec.model_validate(existing_background) if existing_background else None,
        text_layer_count=sum(1 for s in slots if s.resolved_name == "TextLayer"),
        reference_note=existing.get("reference_note"),
        slots=slots,
    )


def load_enriched(path: Path) -> LidoTemplateFile:
    obj = _read_root_object(path)
    doc = LidoDocument.model_validate({"layers": obj["layers"]})
    meta = derive_meta(path.stem, doc.layers, existing=obj.get("meta"))
    return LidoTemplateFile(layers=doc.layers, meta=meta)


def load_corpus(directory: Path | str = DEFAULT_CORPUS_DIR) -> list[LidoTemplateFile]:
    return [load_enriched(p) for p in discover_templates(directory)]


def load_authored_corpus(directory: Path | str = DEFAULT_CORPUS_DIR
                         ) -> tuple[list[LidoTemplateFile], list[str]]:
    """Templates whose file has a `meta` block, plus the names of raw files that don't.

    A raw export dropped into the folder has no metadata yet (no name, tags, limits,
    image specs), so it is never a match candidate until the enrich script has drafted
    its `meta` — see `make lido-meta` / `make lido-add`."""
    ready, raw = [], []
    for path in discover_templates(directory):
        try:
            has_meta = bool(_read_root_object(path).get("meta"))
        except (OSError, ValueError):
            has_meta = False
        if has_meta:
            ready.append(load_enriched(path))
        else:
            raw.append(path.name)
    return ready, raw
