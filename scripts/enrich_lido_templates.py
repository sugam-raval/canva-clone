#!/usr/bin/env python3
"""Enrich Lido.js templates with intelligent `meta` — companion to `app.lido_corpus`.

Every template in `lidojs_templates/` is loaded fresh at request time (see
`app/lido_corpus/loader.py`), so this script is never required for the pipeline to work.
It exists purely as a convenience: drop a raw Lido export (just `{"layers": {...}}`, no
`meta` block) into the directory, run this script, and get a human-readable `meta` block
written back into the file — so you can inspect slots/roles/description without starting
the API.

By default, uses an LLM (if available via OPENAI_API_KEY) to generate intelligent metadata:
smart template names, inferred kinds (poster/story/banner), and descriptions that understand
the design's purpose. Falls back to rule-based generation if the LLM is unavailable.

Default behavior only touches templates that have NO `meta` block yet. A template that
already has one (even a partial, human-edited one) is left alone, because `name`, `kind`,
`tags` and `description` are treated as human-authored. Pass --force to recompute for
all templates (still preserves non-empty existing name/kind/tags/description values).

    python scripts/enrich_lido_templates.py              # only templates missing meta, uses LLM
    python scripts/enrich_lido_templates.py --force       # recompute for all templates
    python scripts/enrich_lido_templates.py --no-llm      # use rule-based enrichment instead
    python scripts/enrich_lido_templates.py --dir path/to/templates
    python scripts/enrich_lido_templates.py --check       # exit 1 if missing meta, don't write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.adapters.registry import llm as get_llm
from app.lido_corpus.loader import (
    DEFAULT_CORPUS_DIR,
    _aspect,
    _describe,
    _extract_slots,
    _read_root_object,
    derive_meta,
    discover_templates,
)
from app.lido_corpus.model import ImageSpec, LidoDocument, LidoTemplateMeta


class TemplateMetadataSchema(BaseModel):
    """Schema for LLM to generate intelligent template metadata."""
    name: str = Field(description="A short, descriptive name for the template (2-4 words)")
    kind: str = Field(
        description="The most suitable design kind: post, story, poster, banner, thumbnail, ad, or flyer"
    )
    description: str = Field(description="A one-sentence description of what this template is for")
    tags: list[str] = Field(description="2-3 relevant tags for the template")


def _slot_summary(slots) -> str:
    """Describe slots for LLM prompting."""
    by_role = {}
    for s in slots:
        role = s.role
        if role not in by_role:
            by_role[role] = []
        by_role[role].append(s.default_text[:30] if s.default_text else "(empty)")

    parts = []
    for role in ["headline", "subhead", "body", "phone", "address", "website", "logo", "photo"]:
        if role in by_role:
            texts = ", ".join(f'"{t}"' for t in by_role[role])
            parts.append(f"- {role}: {texts}")
    return "\n".join(parts) if parts else "(no editable slots)"


async def _enrich_with_llm(template_id: str, layers: dict, existing: dict | None = None) -> LidoTemplateMeta:
    """Use LLM to generate intelligent template metadata."""
    existing = existing or {}
    root = layers["ROOT"]
    box = root.props.get("boxSize", {"width": 0, "height": 0})
    w, h = box.get("width", 0), box.get("height", 0)
    existing_slots_by_id = {
        s["layer_id"]: s for s in existing.get("slots", []) if s.get("layer_id")
    }
    slots = _extract_slots(layers, existing_slots_by_id)
    existing_background = existing.get("background")

    # If human already set these, keep them
    existing_name = existing.get("name", "").strip()
    existing_kind = existing.get("kind", "").strip()
    existing_desc = existing.get("description", "").strip()
    existing_tags = existing.get("tags", [])

    slot_summary = _slot_summary(slots)
    system_prompt = """You are an expert at analyzing design templates and generating descriptive metadata."""
    user_prompt = f"""Analyze this Lido.js template and generate metadata for it.

Template ID: {template_id}
Canvas size: {int(w)}x{int(h)} ({_aspect(w, h)})

Editable slots in the design:
{slot_summary}

Generate appropriate metadata:
- name: A short, descriptive name (2-4 words, e.g. "Product Showcase", "Restaurant Menu")
- kind: The most suitable design kind: post, story, poster, banner, thumbnail, ad, or flyer
- description: A one-sentence description of what this template is for
- tags: 2-3 relevant tags (e.g. business, contact, modern)"""

    try:
        llm = get_llm()
        llm_result = await llm.complete_json(
            system=system_prompt,
            user=user_prompt,
            schema=TemplateMetadataSchema,
        )
        result = llm_result.parsed
        llm_name = (result.name or "").strip()
        llm_kind = (result.kind or "post").strip()
        llm_desc = (result.description or "").strip()
        llm_tags = result.tags or []
    except Exception as exc:  # noqa: BLE001
        print(f"    (LLM unavailable: {exc}; falling back to rule-based)")
        llm_name = llm_kind = llm_desc = ""
        llm_tags = []

    # Use LLM if available, otherwise fall back to rule-based; preserve existing if non-empty
    name = existing_name or llm_name or ""
    kind = existing_kind or llm_kind or "post"
    description = existing_desc or llm_desc or _describe(slots)
    tags = existing_tags or llm_tags or []

    return LidoTemplateMeta(
        id=template_id,
        name=name,
        kind=kind,
        aspect=_aspect(w, h) if w and h else "1:1",
        tags=tags,
        description=description,
        canvas_size={"width": w, "height": h},
        background_image_url=(root.props.get("image") or {}).get("url"),
        background=ImageSpec.model_validate(existing_background) if existing_background else None,
        text_layer_count=sum(1 for s in slots if s.resolved_name == "TextLayer"),
        reference_note=existing.get("reference_note"),
        slots=slots,
    )


def _enrich_file_in_place(path: Path, use_llm: bool = True) -> LidoTemplateMeta:
    """Recompute metadata and write it back, preserving human-authored fields."""
    obj = _read_root_object(path)
    doc = LidoDocument.model_validate({"layers": obj["layers"]})

    if use_llm:
        meta = asyncio.run(_enrich_with_llm(path.stem, doc.layers, existing=obj.get("meta")))
    else:
        # Fallback: rule-based (same merge behavior as the API's own loader)
        meta = derive_meta(path.stem, doc.layers, existing=obj.get("meta"))

    out = [{
        "layers": json.loads(json.dumps(
            {lid: layer.model_dump(mode="json", by_alias=False) for lid, layer in doc.layers.items()}
        )),
        "meta": meta.model_dump(mode="json"),
    }]
    with path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return meta


def _has_meta(path: Path) -> bool:
    try:
        obj = _read_root_object(path)
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        raise ValueError(f"could not read {path.name}: {exc}") from exc
    return bool(obj.get("meta"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_CORPUS_DIR,
                        help=f"template directory (default: {DEFAULT_CORPUS_DIR})")
    parser.add_argument("--force", action="store_true",
                        help="recompute meta for every template, not just ones missing it")
    parser.add_argument("--check", action="store_true",
                        help="don't write anything; exit 1 if any template is missing meta")
    parser.add_argument("--no-llm", action="store_true",
                        help="use rule-based enrichment instead of LLM")
    args = parser.parse_args()

    paths = discover_templates(args.dir)
    if not paths:
        print(f"no templates found in {args.dir}")
        return 0

    missing: list[Path] = []
    errors: list[tuple[Path, str]] = []
    for path in paths:
        try:
            if not _has_meta(path):
                missing.append(path)
        except ValueError as exc:
            errors.append((path, str(exc)))

    if errors:
        for path, message in errors:
            print(f"  ERROR    {path.name}: {message}", file=sys.stderr)

    if args.check:
        if missing:
            print(f"{len(missing)} template(s) missing meta: " + ", ".join(p.name for p in missing))
            return 1
        print(f"all {len(paths)} template(s) have meta")
        return 1 if errors else 0

    targets = paths if args.force else missing
    enriched: list[Path] = []
    for path in targets:
        try:
            meta = _enrich_file_in_place(path, use_llm=not args.no_llm)
            enriched.append(path)
            status = f"name={meta.name!r}, kind={meta.kind}" if meta.name else f"kind={meta.kind}"
            print(f"  enriched {path.name:<25} {status}")
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            errors.append((path, str(exc)))
            print(f"  ERROR    {path.name}: {exc}", file=sys.stderr)

    skipped = [p for p in paths if p not in targets]
    for path in skipped:
        print(f"  skipped  {path.name} (already has meta)")

    print(f"\n{len(enriched)} enriched, {len(skipped)} skipped, {len(errors)} error(s) "
          f"— {len(paths)} template(s) total in {args.dir}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
