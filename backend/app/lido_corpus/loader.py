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


def _role_for(layer_id: str, layer: LidoLayer, headline_id: str | None,
              subhead_id: str | None) -> SlotRole:
    t = layer.type.type
    rn = layer.type.resolvedName
    if rn == "RootLayer":
        return "background"
    if t == "logo":
        return "logo"
    if t == "static":
        return "label"
    if t == "phoneNumber":
        return "phone"
    if t == "address":
        return "address"
    if t == "website":
        return "website"
    if t == "bodyText":
        if layer_id == headline_id:
            return "headline"
        if layer_id == subhead_id:
            return "subhead"
        return "body"
    if rn == "FrameLayer":
        return "photo"
    if rn == "ShapeLayer":
        return "decoration"
    return "decoration"


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
    body_text_ids = [
        lid for lid, layer in layers.items()
        if lid != "ROOT" and layer.type.type == "bodyText"
    ]
    # Rank bodyText layers by font size (largest first) so a template with several
    # untagged text blocks still gets a sane headline/subhead/body split.
    ranked = sorted(body_text_ids, key=lambda lid: _font_size(layers[lid]) or 0, reverse=True)
    headline_id = ranked[0] if ranked else None
    subhead_id = ranked[1] if len(ranked) > 1 else None

    slots: list[SlotInfo] = []
    for lid, layer in layers.items():
        if lid == "ROOT":
            continue
        role = _role_for(lid, layer, headline_id, subhead_id)
        default_text = layer.type.replacableText or _default_text(layer)
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


def enrich_file_in_place(path: Path) -> LidoTemplateFile:
    """Recompute `meta` from the current layers and write it back into the file,
    preserving `name`/`kind`/`tags`/`description` if a human already set them."""
    template = load_enriched(path)
    out = [{
        "layers": json.loads(json.dumps(
            {lid: layer.model_dump(mode="json", by_alias=False) for lid, layer in template.layers.items()}
        )),
        "meta": template.meta.model_dump(mode="json"),
    }]
    with path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return template


def enrich_corpus_in_place(directory: Path | str = DEFAULT_CORPUS_DIR) -> list[LidoTemplateFile]:
    return [enrich_file_in_place(p) for p in discover_templates(directory)]
