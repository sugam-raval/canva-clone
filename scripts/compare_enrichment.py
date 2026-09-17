#!/usr/bin/env python3
"""Compare LLM vs rule-based template enrichment.

Demonstrates the difference between using the LLM for intelligent metadata
generation vs. the fast rule-based approach.

    python scripts/compare_enrichment.py
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from app.lido_corpus.loader import (
    DEFAULT_CORPUS_DIR,
    _read_root_object,
    _extract_slots,
    _aspect,
    _describe,
)
from app.lido_corpus.model import LidoDocument


async def _enrich_with_llm_direct(template_id: str, layers: dict, existing: dict | None = None):
    """Enrich using LLM."""
    from app.adapters.registry import llm as get_llm
    from pydantic import BaseModel, Field

    class TemplateMetadataSchema(BaseModel):
        name: str = Field(description="A short, descriptive name for the template")
        kind: str = Field(description="Design kind: post, story, poster, banner, thumbnail, ad, or flyer")
        description: str = Field(description="A one-sentence description")
        tags: list[str] = Field(description="2-3 relevant tags")

    root = layers["ROOT"]
    box = root.props.get("boxSize", {"width": 0, "height": 0})
    w, h = box.get("width", 0), box.get("height", 0)
    slots = _extract_slots(layers)

    def _slot_summary(slots):
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

    slot_summary = _slot_summary(slots)
    system_prompt = """You are an expert at analyzing design templates and generating descriptive metadata."""
    user_prompt = f"""Analyze this Lido.js template and generate metadata.

Template: {template_id}
Canvas: {int(w)}x{int(h)} ({_aspect(w, h)})

Slots:
{slot_summary}

Generate appropriate metadata."""

    llm = get_llm()
    llm_result = await llm.complete_json(
        system=system_prompt,
        user=user_prompt,
        schema=TemplateMetadataSchema,
    )
    result = llm_result.parsed

    from app.lido_corpus.model import LidoTemplateMeta
    return LidoTemplateMeta(
        id=template_id,
        name=(result.name or "").strip(),
        kind=(result.kind or "post").strip(),
        aspect=_aspect(w, h) if w and h else "1:1",
        tags=result.tags or [],
        description=(result.description or "").strip(),
        canvas_size={"width": w, "height": h},
        background_image_url=(root.props.get("image") or {}).get("url"),
        slots=slots,
    )


def _enrich_with_rules(template_id: str, layers: dict, existing: dict | None = None):
    """Enrich using rule-based approach."""
    from app.lido_corpus.model import LidoTemplateMeta

    existing = existing or {}
    root = layers["ROOT"]
    box = root.props.get("boxSize", {"width": 0, "height": 0})
    w, h = box.get("width", 0), box.get("height", 0)
    slots = _extract_slots(layers)

    return LidoTemplateMeta(
        id=template_id,
        name=existing.get("name", ""),
        kind=existing.get("kind", "post"),
        aspect=_aspect(w, h) if w and h else "1:1",
        tags=existing.get("tags", []),
        description=existing.get("description") or _describe(slots),
        canvas_size={"width": w, "height": h},
        background_image_url=(root.props.get("image") or {}).get("url"),
        slots=slots,
    )


async def main():
    print("\n" + "=" * 75)
    print("COMPARISON: LLM vs Rule-Based Template Enrichment")
    print("=" * 75)

    # Load a template without meta
    template_path = DEFAULT_CORPUS_DIR / "template_3.json"
    obj = _read_root_object(template_path)
    doc = LidoDocument.model_validate({"layers": obj["layers"]})

    # Rule-based enrichment
    print("\n📋 RULE-BASED ENRICHMENT (Fast, Offline, No API Calls)")
    print("-" * 75)
    rule_meta = _enrich_with_rules("template_3", doc.layers)
    print(f"  Name:        {rule_meta.name!r}")
    print(f"  Kind:        {rule_meta.kind!r}")
    print(f"  Description: {rule_meta.description!r}")
    print(f"  Tags:        {rule_meta.tags}")

    # LLM enrichment
    print("\n🤖 LLM ENRICHMENT (Smart, Context-Aware, Uses OpenAI)")
    print("-" * 75)
    try:
        llm_meta = await _enrich_with_llm_direct("template_3", doc.layers)
        print(f"  Name:        {llm_meta.name!r}")
        print(f"  Kind:        {llm_meta.kind!r}")
        print(f"  Description: {llm_meta.description!r}")
        print(f"  Tags:        {llm_meta.tags}")
    except Exception as exc:
        print(f"  ⚠️  LLM unavailable: {exc}")
        print(f"  Falling back to rule-based...")

    print("\n" + "=" * 75)
    print("SUMMARY")
    print("=" * 75)
    print("""
Rule-Based (--no-llm):
  ✓ Fast (instant, no network)
  ✓ Works offline
  ✓ Generic description from role analysis
  ✗ Empty name, generic template kind

LLM-Based (default):
  ✓ Intelligent template names
  ✓ Context-aware descriptions
  ✓ Relevant, contextual tags
  ✓ Smart kind inference
  ✗ Requires OpenAI API key
  ✗ Slightly slower

USAGE:
  make lido-enrich-llm   # Use LLM (smart metadata)
  make lido-enrich-rule  # Use rule-based (fast, offline)
  make lido-enrich       # Auto-select (LLM if available)
""")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    asyncio.run(main())
