"""Data access for the Lido.js (template) flow. Plain SQL against
infra/initdb/001_schema.sql (templates + vectors) and 002_lido_generations.sql (history).
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _vector_literal(embedding: list[float] | None) -> str | None:
    if embedding is None:
        return None
    return "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"


_TEMPLATE_ID_RE = re.compile(r"^template_(\d+)$")


def template_db_id(app_id: str) -> int:
    """`lido_templates.id` (and `lido_generations.template_id`, its foreign key) is a
    genuine SQL integer — the template's own id, not a surrogate. The rest of the app
    identifies a template by its file stem (e.g. "template_10091"), so every template
    file must be named `template_<number>.json` for this to have anywhere to come from.
    Raises ValueError with a clear message otherwise, so a misnamed file fails during
    `make lido-add`/verify, not as an opaque database error."""
    m = _TEMPLATE_ID_RE.match(app_id)
    if not m:
        raise ValueError(f"template id {app_id!r} is not of the form 'template_<number>' "
                         "— lido_templates.id is a genuine integer, so the file must be "
                         "named template_<number>.json")
    return int(m.group(1))


def template_app_id(db_id: int) -> str:
    """The reverse of `template_db_id`."""
    return f"template_{db_id}"


# --------------------------------------------------------------------------------------
# Templates (lido_templates) — the template catalog and its embeddings (pgvector)
# --------------------------------------------------------------------------------------


async def list_template_index(session: AsyncSession) -> dict[int, dict]:
    """id → fingerprint/model/source_file for every stored template (no documents)."""
    rows = (await session.execute(text(
        "select id, fingerprint, embedding_model, source_file, "
        "embedding is not null as has_embedding from lido_templates"
    ))).mappings().all()
    return {r["id"]: dict(r) for r in rows}


async def upsert_template(session: AsyncSession, *, template_id: int, name: str,
                          kind: str, aspect: str, tags: list[str], description: str,
                          document: list[dict], card: str, details: dict,
                          fingerprint: str, embedding: list[float] | None,
                          embedding_model: str | None, ready: bool,
                          source_file: str | None) -> None:
    await session.execute(
        text("""
            insert into lido_templates
                (id, name, kind, aspect, tags, description, document, card, details,
                 fingerprint, embedding, embedding_model, ready, source_file, updated_at)
            values (:id, :name, :kind, :aspect, :tags, :description,
                    cast(:document as jsonb), :card, cast(:details as jsonb),
                    :fingerprint, cast(:embedding as vector), :embedding_model, :ready,
                    :source_file, now())
            on conflict (id) do update set
                name = excluded.name, kind = excluded.kind, aspect = excluded.aspect,
                tags = excluded.tags, description = excluded.description,
                document = excluded.document, card = excluded.card,
                details = excluded.details, fingerprint = excluded.fingerprint,
                embedding = excluded.embedding, embedding_model = excluded.embedding_model,
                ready = excluded.ready, source_file = excluded.source_file,
                updated_at = now()
        """),
        {"id": template_id, "name": name, "kind": kind, "aspect": aspect, "tags": tags,
         "description": description, "document": json.dumps(document, ensure_ascii=False),
         "card": card, "details": json.dumps(details), "fingerprint": fingerprint,
         "embedding": _vector_literal(embedding), "embedding_model": embedding_model,
         "ready": ready, "source_file": source_file},
    )


async def delete_templates(session: AsyncSession, template_ids: list[int]) -> int:
    if not template_ids:
        return 0
    result = await session.execute(
        text("delete from lido_templates where id = any(:ids)"), {"ids": template_ids})
    return result.rowcount or 0


async def list_templates(session: AsyncSession) -> list[dict]:
    """Every stored template with its document, card, details and embedding."""
    rows = (await session.execute(text("""
        select id, name, kind, aspect, tags, description, document, card, details,
               fingerprint, embedding::text as embedding, embedding_model, ready,
               source_file, updated_at
        from lido_templates order by id
    """))).mappings().all()
    out = []
    for r in rows:
        row = dict(r)
        emb = row.pop("embedding")
        row["embedding"] = json.loads(emb) if emb else None
        out.append(row)
    return out


async def template_similarities(session: AsyncSession,
                                embedding: list[float]) -> dict[int, float]:
    """Cosine similarity of every stored template's embedding to `embedding`, computed
    by pgvector (`<=>` is cosine distance)."""
    rows = (await session.execute(
        text("select id, 1 - (embedding <=> cast(:q as vector)) as cos "
             "from lido_templates where embedding is not null"),
        {"q": _vector_literal(embedding)},
    )).mappings().all()
    return {r["id"]: float(r["cos"]) for r in rows}


# --------------------------------------------------------------------------------------
# Generation history (lido_generations)
# --------------------------------------------------------------------------------------


async def upsert_lido_generation(session: AsyncSession, *, design_id: str,
                                 document: list[dict] | dict, meta: dict[str, Any],
                                 path: str | None = None) -> None:
    """`design_id` becomes `design_key` — the row's public slug, generated before this
    row exists (it also names the design's uploaded images' object-store path), kept
    distinct from the table's own sequential `id`. `meta` is the saved design's own
    `meta` block, which already carries name/kind/aspect/prompt/canvas_size/
    background_image_url/template_id (the app-level "template_NNN" form).

    A `template_id` that doesn't resolve to a real template (an old record pointing at
    one that's since been deleted, or just not of the expected form) is stored as null
    rather than failing the save — the generation record must never be lost over its
    template link alone."""
    app_template_id = meta.get("template_id")
    db_template_id = None
    if app_template_id:
        try:
            db_template_id = template_db_id(app_template_id)
        except ValueError:
            pass
    await session.execute(
        text("""
            insert into lido_generations
                (design_key, template_id, name, kind, aspect, prompt, canvas_size,
                 thumbnail_url, document, path)
            values (:design_key, :template_id, :name, :kind, :aspect, :prompt,
                    cast(:canvas_size as jsonb), :thumbnail_url,
                    cast(:document as jsonb), :path)
            on conflict (design_key) do update set
                template_id = excluded.template_id,
                name = excluded.name, kind = excluded.kind, aspect = excluded.aspect,
                prompt = excluded.prompt, canvas_size = excluded.canvas_size,
                thumbnail_url = excluded.thumbnail_url, document = excluded.document,
                path = excluded.path
        """),
        {
            "design_key": design_id,
            "template_id": db_template_id,
            "name": meta.get("name") or "",
            "kind": meta.get("kind") or "post",
            "aspect": meta.get("aspect") or "1:1",
            "prompt": meta.get("prompt") or "",
            "canvas_size": json.dumps(meta.get("canvas_size") or {}),
            "thumbnail_url": meta.get("background_image_url"),
            "document": json.dumps(document),
            "path": path,
        },
    )


def _generation_row(row) -> dict:
    """`design_key` -> `id` (the public identifier), `template_id` back to its
    app-level "template_NNN" form (or None)."""
    out = dict(row)
    out["id"] = out.pop("design_key")
    if out["template_id"] is not None:
        out["template_id"] = template_app_id(out["template_id"])
    return out


async def list_lido_generations(session: AsyncSession, *, limit: int = 50,
                                offset: int = 0) -> list[dict]:
    """Summary fields only (no `document`); use `get_lido_generation` to reopen one."""
    rows = (await session.execute(
        text("""
            select design_key, template_id, name, kind, aspect, prompt, canvas_size,
                   thumbnail_url, path, created_at
            from lido_generations
            order by created_at desc
            limit :limit offset :offset
        """),
        {"limit": limit, "offset": offset},
    )).mappings().all()
    return [_generation_row(r) for r in rows]


async def get_lido_generation(session: AsyncSession, design_id: str) -> dict | None:
    row = (await session.execute(
        text("""
            select design_key, template_id, name, kind, aspect, prompt, canvas_size,
                   thumbnail_url, document, path, created_at
            from lido_generations where design_key = :id
        """),
        {"id": design_id},
    )).mappings().first()
    return _generation_row(row) if row else None
