#!/usr/bin/env python3
"""Seed the template corpus — IMPLEMENTATION_PLAN §1.2.

Validates every skeleton, embeds its description, and upserts it into `templates`.
Refuses to seed if validation finds an error: a broken skeleton in the corpus produces
broken designs for every user who retrieves it.

    python scripts/seed_templates.py [--rebuild-index]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.adapters.base import AdapterError
from app.adapters.registry import embedder as get_embedder
from app.db import repo
from app.db.session import dispose_engine, session_scope
from app.templates_corpus.skeletons import ALL_SKELETONS
from app.templates_corpus.validate import validate_corpus
from sqlalchemy import text


async def ensure_vector_dimension(session, dim: int) -> bool:
    """Make `templates.embedding` match the embedder's dimension.

    Swapping embedding models changes the vector width, and pgvector will reject inserts
    that do not match. Rather than fail the seed with an opaque error, reconcile the
    column — dropping any stored vectors, which are meaningless across models anyway.
    """
    row = (await session.execute(text("""
        select a.atttypmod from pg_attribute a
        join pg_class c on c.oid = a.attrelid
        where c.relname = 'templates' and a.attname = 'embedding'
    """))).first()
    current = int(row[0]) if row and row[0] and row[0] > 0 else None
    if current == dim:
        return False
    print(f"  reconciling templates.embedding: vector({current}) -> vector({dim})")
    await session.execute(text("drop index if exists templates_embedding_idx"))
    await session.execute(text(
        f"alter table templates alter column embedding type vector({dim}) using null"))
    return True


async def main(rebuild_index: bool) -> int:
    issues = validate_corpus(ALL_SKELETONS)
    errors = [i for i in issues if i.severity == "error"]
    for issue in [i for i in issues if i.severity == "warning"]:
        print(f"  warning  {issue.template_id}: [{issue.code}] {issue.message}")
    if errors:
        for issue in errors:
            print(f"  ERROR    {issue.template_id}/{issue.slot_id}: "
                  f"[{issue.code}] {issue.message}", file=sys.stderr)
        print(f"\nRefusing to seed: {len(errors)} validation error(s).", file=sys.stderr)
        return 1

    descriptions = [s.description for s in ALL_SKELETONS]
    try:
        embedder = get_embedder()
        embeddings: list = list(await embedder.embed(descriptions))
        dim = len(embeddings[0]) if embeddings else embedder.dim
        print(f"embedded {len(embeddings)} descriptions with {embedder.name} (dim={dim})")
        async with session_scope() as session:
            await ensure_vector_dimension(session, dim)
    except AdapterError as exc:
        print(f"  warning  embedding unavailable ({exc}); seeding without vectors — "
              f"retrieval falls back to quality ranking")
        embeddings = [None] * len(ALL_SKELETONS)

    async with session_scope() as session:
        for skeleton, embedding in zip(ALL_SKELETONS, embeddings):
            await repo.upsert_template(
                session,
                template_id=skeleton.id,
                name=skeleton.name,
                kind=skeleton.kind,
                aspect=skeleton.aspect,
                tags=list(skeleton.tags),
                skeleton=skeleton.model_dump(by_alias=True, exclude_none=True),
                description=skeleton.description,
                embedding=embedding,
            )
        total = await repo.count_templates(session)

    if rebuild_index and any(e is not None for e in embeddings):
        async with session_scope() as session:
            # ivfflat only becomes meaningful once rows exist, so it is built here
            # rather than in the initial schema.
            lists = max(1, min(100, total // 4))
            await session.execute(text("drop index if exists templates_embedding_idx"))
            await session.execute(text(
                f"create index templates_embedding_idx on templates "
                f"using ivfflat (embedding vector_cosine_ops) with (lists = {lists})"))
            print(f"rebuilt ivfflat index with lists={lists}")

    variants = sum(1 + len(s.variants) for s in ALL_SKELETONS)
    print(f"\nseeded {len(ALL_SKELETONS)} skeletons ({variants} with variants); "
          f"{total} templates in the database")
    await dispose_engine()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-index", action="store_true",
                        help="rebuild the ivfflat vector index after seeding")
    raise SystemExit(asyncio.run(main(parser.parse_args().rebuild_index)))
