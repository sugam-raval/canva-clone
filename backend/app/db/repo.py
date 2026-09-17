"""Data access. Plain SQL against the schema in infra/initdb/001_schema.sql (§0.7).

Kept as explicit SQL rather than an ORM mapping so the queries in the plan — notably the
pgvector template retrieval in §1.2 — read exactly as specified.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schema.doc import DesignDoc


def _uuid() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------------------


async def ensure_user(session: AsyncSession, email: str) -> str:
    row = (await session.execute(
        text("insert into users (email) values (:email) "
             "on conflict (email) do update set email = excluded.email returning id"),
        {"email": email},
    )).first()
    return str(row[0])


# --------------------------------------------------------------------------------------
# Assets (§0.8)
# --------------------------------------------------------------------------------------


async def find_asset_by_gen_hash(session: AsyncSession, gen_hash: str) -> dict | None:
    row = (await session.execute(
        text("select id, storage_key, mime, width, height, has_alpha, bytes "
             "from assets where gen_hash = :h"),
        {"h": gen_hash},
    )).mappings().first()
    return dict(row) if row else None


async def insert_asset(
    session: AsyncSession, *, user_id: str | None, kind: str, storage_key: str, mime: str,
    width: int | None, height: int | None, has_alpha: bool, size_bytes: int,
    gen_hash: str | None, gen_params: dict | None,
) -> str:
    """Insert, or return the existing row if another worker won the race on gen_hash.

    The unique index on gen_hash is what makes §6.1's content-addressed cache free.
    """
    asset_id = _uuid()
    row = (await session.execute(
        text("""
            insert into assets (id, user_id, kind, storage_key, mime, width, height,
                                has_alpha, bytes, gen_hash, gen_params)
            values (:id, :user_id, :kind, :storage_key, :mime, :width, :height,
                    :has_alpha, :bytes, :gen_hash, cast(:gen_params as jsonb))
            on conflict (gen_hash) where gen_hash is not null do nothing
            returning id
        """),
        {
            "id": asset_id, "user_id": user_id, "kind": kind, "storage_key": storage_key,
            "mime": mime, "width": width, "height": height, "has_alpha": has_alpha,
            "bytes": size_bytes, "gen_hash": gen_hash,
            "gen_params": json.dumps(gen_params) if gen_params else None,
        },
    )).first()
    if row is not None:
        return str(row[0])
    existing = await find_asset_by_gen_hash(session, gen_hash) if gen_hash else None
    return str(existing["id"]) if existing else asset_id


async def get_asset(session: AsyncSession, asset_id: str) -> dict | None:
    try:
        uuid.UUID(asset_id)
    except (ValueError, AttributeError):
        return None
    row = (await session.execute(
        text("select id, user_id, kind, storage_key, mime, width, height, has_alpha, bytes "
             "from assets where id = :id"),
        {"id": asset_id},
    )).mappings().first()
    return dict(row) if row else None


async def get_assets(session: AsyncSession, asset_ids: list[str]) -> dict[str, dict]:
    valid = []
    for a in asset_ids:
        try:
            uuid.UUID(a)
            valid.append(a)
        except (ValueError, AttributeError):
            continue
    if not valid:
        return {}
    rows = (await session.execute(
        text("select id, storage_key, mime, width, height, has_alpha from assets "
             "where id = any(cast(:ids as uuid[]))"),
        {"ids": valid},
    )).mappings().all()
    return {str(r["id"]): dict(r) for r in rows}


# --------------------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------------------


async def insert_document(session: AsyncSession, doc: DesignDoc, user_id: str | None) -> str:
    payload = doc.model_dump(by_alias=True, exclude_none=True)
    await session.execute(
        text("""
            insert into documents (id, user_id, title, schema_version, doc, provenance)
            values (:id, :user_id, :title, :sv, cast(:doc as jsonb), cast(:prov as jsonb))
            on conflict (id) do update
              set doc = excluded.doc, title = excluded.title, updated_at = now()
        """),
        {
            "id": doc.id, "user_id": user_id, "title": doc.title,
            "sv": doc.schema_version, "doc": json.dumps(payload),
            "prov": json.dumps(payload.get("provenance", {"kind": "blank"})),
        },
    )
    return doc.id


async def update_document(session: AsyncSession, doc: DesignDoc) -> None:
    await session.execute(
        text("update documents set doc = cast(:doc as jsonb), title = :title, "
             "updated_at = now() where id = :id"),
        {
            "id": doc.id, "title": doc.title,
            "doc": json.dumps(doc.model_dump(by_alias=True, exclude_none=True)),
        },
    )


async def get_document(session: AsyncSession, doc_id: str) -> dict | None:
    try:
        uuid.UUID(doc_id)
    except (ValueError, AttributeError):
        return None
    row = (await session.execute(
        text("select id, user_id, title, doc, thumb_asset_id, updated_at, created_at "
             "from documents where id = :id"),
        {"id": doc_id},
    )).mappings().first()
    return dict(row) if row else None


async def list_documents(session: AsyncSession, user_id: str, limit: int = 50) -> list[dict]:
    rows = (await session.execute(
        text("select id, title, thumb_asset_id, updated_at, provenance from documents "
             "where user_id = :uid order by updated_at desc limit :lim"),
        {"uid": user_id, "lim": limit},
    )).mappings().all()
    return [dict(r) for r in rows]


async def set_document_thumb(session: AsyncSession, doc_id: str, asset_id: str) -> None:
    await session.execute(
        text("update documents set thumb_asset_id = cast(:a as uuid) where id = :id"),
        {"id": doc_id, "a": asset_id},
    )


async def delete_document(session: AsyncSession, doc_id: str, user_id: str) -> bool:
    result = await session.execute(
        text("delete from documents where id = :id and user_id = :uid"),
        {"id": doc_id, "uid": user_id},
    )
    return bool(result.rowcount)


# --------------------------------------------------------------------------------------
# Jobs and generation requests (§0.9)
# --------------------------------------------------------------------------------------


async def insert_job(session: AsyncSession, *, job_id: str, request_id: str, doc_id: str | None,
                     layer_id: str | None, job_type: str, payload: dict) -> None:
    await session.execute(
        text("""insert into jobs (id, request_id, doc_id, layer_id, type, input)
                values (:id, :rid, :did, :lid, :type, cast(:input as jsonb))
                on conflict (id) do nothing"""),
        {"id": job_id, "rid": request_id, "did": doc_id, "lid": layer_id,
         "type": job_type, "input": json.dumps(payload)},
    )


async def set_job_state(session: AsyncSession, job_id: str, state: str, *,
                        output: dict | None = None, error: str | None = None,
                        cost_cents: int = 0) -> None:
    await session.execute(
        text("""update jobs set state = :state,
                   output = coalesce(cast(:output as jsonb), output),
                   error = coalesce(:error, error),
                   cost_cents = cost_cents + :cost,
                   attempts = attempts + case when :state = 'running' then 1 else 0 end,
                   started_at = case when :state = 'running' then now() else started_at end,
                   finished_at = case when :state in ('done','failed','skipped')
                                      then now() else finished_at end
                 where id = :id"""),
        {"id": job_id, "state": state, "cost": cost_cents,
         "output": json.dumps(output) if output else None, "error": error},
    )


async def create_generation_request(session: AsyncSession, *, user_id: str,
                                    prompt: str) -> str:
    request_id = _uuid()
    await session.execute(
        text("insert into generation_requests (id, user_id, prompt) values (:id, :uid, :p)"),
        {"id": request_id, "uid": user_id, "p": prompt},
    )
    return request_id


async def update_generation_request(session: AsyncSession, request_id: str, **fields) -> None:
    allowed = {"brief", "chosen_template_id", "doc_id", "state", "cost_cents", "error"}
    sets, params = [], {"id": request_id}
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "brief":
            sets.append("brief = cast(:brief as jsonb)")
            params["brief"] = json.dumps(value)
        elif key == "cost_cents":
            sets.append("cost_cents = cost_cents + :cost")
            params["cost"] = int(value)
        else:
            sets.append(f"{key} = :{key}")
            params[key] = value
    if not sets:
        return
    await session.execute(
        text(f"update generation_requests set {', '.join(sets)}, updated_at = now() "
             f"where id = :id"),
        params,
    )


async def get_generation_request(session: AsyncSession, request_id: str) -> dict | None:
    row = (await session.execute(
        text("select id, prompt, brief, chosen_template_id, doc_id, state, error, cost_cents, "
             "created_at from generation_requests where id = :id"),
        {"id": request_id},
    )).mappings().first()
    if not row:
        return None
    out = dict(row)
    jobs = (await session.execute(
        text("select id, type, state, layer_id, error, cost_cents from jobs "
             "where request_id = :id order by created_at"),
        {"id": request_id},
    )).mappings().all()
    out["jobs"] = [dict(j) for j in jobs]
    return out


# --------------------------------------------------------------------------------------
# Cost ledger (§6.7)
# --------------------------------------------------------------------------------------


async def add_usage(session: AsyncSession, user_id: str, cost_cents: int) -> int:
    row = (await session.execute(
        text("""insert into usage_ledger (user_id, day, cost_cents, requests)
                values (:uid, current_date, :cost, 1)
                on conflict (user_id, day) do update
                  set cost_cents = usage_ledger.cost_cents + excluded.cost_cents,
                      requests = usage_ledger.requests + 1
                returning cost_cents"""),
        {"uid": user_id, "cost": cost_cents},
    )).first()
    return int(row[0]) if row else 0


async def usage_today(session: AsyncSession, user_id: str) -> dict[str, int]:
    row = (await session.execute(
        # current_date is evaluated by Postgres, so the ledger day always matches the
        # day the insert in add_usage() used, regardless of the app server's timezone.
        text("select cost_cents, requests from usage_ledger "
             "where user_id = :uid and day = current_date"),
        {"uid": user_id},
    )).mappings().first()
    return {"costCents": int(row["cost_cents"]), "requests": int(row["requests"])} if row \
        else {"costCents": 0, "requests": 0}


# --------------------------------------------------------------------------------------
# Templates (§1.2)
# --------------------------------------------------------------------------------------


async def upsert_template(session: AsyncSession, *, template_id: str, name: str, kind: str,
                          aspect: str, tags: list[str], skeleton: dict, description: str,
                          embedding: list[float] | None) -> None:
    await session.execute(
        text("""
            insert into templates (id, name, kind, aspect, tags, skeleton, description,
                                   embedding)
            values (:id, :name, :kind, :aspect, cast(:tags as text[]),
                    cast(:skeleton as jsonb), :description, cast(:emb as vector))
            on conflict (id) do update set
              name = excluded.name, kind = excluded.kind, aspect = excluded.aspect,
              tags = excluded.tags, skeleton = excluded.skeleton,
              description = excluded.description,
              embedding = coalesce(excluded.embedding, templates.embedding)
        """),
        {
            "id": template_id, "name": name, "kind": kind, "aspect": aspect,
            "tags": tags, "skeleton": json.dumps(skeleton), "description": description,
            "emb": _vector_literal(embedding),
        },
    )


def _vector_literal(embedding: list[float] | None) -> str | None:
    if not embedding:
        return None
    return "[" + ",".join(f"{v:.7f}" for v in embedding) + "]"


async def retrieve_templates(
    session: AsyncSession, *, kind: str, aspect: str, text_only: bool,
    embedding: list[float] | None, limit: int = 3, dense: bool = False,
) -> list[dict]:
    """§1.2: hard filters (kind, aspect), then vector similarity blended with
    quality_score and a text-only/subject preference.

    When the pair matches nothing, the aspect is kept and the kind is relaxed — see the
    comment on the fallback for why that order and not the other.

    The text-only split is a *preference*, not a hard filter. As a filter it collapses
    the candidate set to whatever exists in one corner of the corpus — for `post`/`4:5`
    that is a single type-only skeleton, and for `post`/`1:1` it is none at all, so every
    text-only square fell through to the relaxed-aspect fallback and came back with a
    layout authored for a different shape. `MISMATCH_PENALTY` is large enough that a
    matching template always outranks a mismatched one, and small enough that a
    mismatched template still beats returning nothing.

    Density is a second, weaker preference on the same pattern. A brief carrying an
    offer, a feature list and a phone number needs a skeleton with slots for them: given
    a three-slot layout, most of what the user asked for simply never reaches the canvas.
    Its penalty is deliberately smaller than the text-only one — it reorders candidates
    that are otherwise close, but a template the query genuinely matches still wins.
    """
    params: dict[str, Any] = {"kind": kind, "aspect": aspect, "lim": limit,
                              "text_only": text_only, "dense": dense}
    # cosine distance is in [0, 2]; the penalty has to dominate it to act as a preference.
    mismatch = "(case when (:text_only = ('text-only' = any(tags))) then 0.0 else 3.0 end)"
    density = "(case when (:dense = ('dense' = any(tags))) then 0.0 else 1.0 end)"
    if embedding:
        params["emb"] = _vector_literal(embedding)
        order = ("order by (embedding <=> cast(:emb as vector)) * 0.8 "
                 f"- quality_score * 0.2 + {mismatch} + {density}")
    else:
        order = (f"order by {mismatch} asc, {density} asc, quality_score desc, "
                 "usage_count desc")

    sql = f"""
        select id, name, kind, aspect, tags, skeleton, description, quality_score
        from templates
        where kind = :kind
          and aspect = :aspect
        {order}
        limit :lim
    """
    rows = (await session.execute(text(sql), params)).mappings().all()
    if rows:
        return [dict(r) for r in rows]

    # Nothing for this (kind, aspect). Relax the KIND before the aspect: a skeleton is
    # normalised to its own aspect family, so one authored for an A4 sheet and laid out
    # on a 4:5 canvas has every vertical relationship wrong — the type block that cleared
    # the subject no longer does, the footer band lands mid-canvas. A post layout at the
    # right shape is a design; a poster layout at the wrong shape is a bug with a
    # photograph in it, which is what a "4:5 promotional poster" used to return.
    #
    # Kind is a label for the occasion; aspect is the geometry. Keep the geometry.
    by_aspect = f"""
        select id, name, kind, aspect, tags, skeleton, description, quality_score
        from templates where aspect = :aspect {order} limit :lim
    """
    rows = (await session.execute(text(by_aspect), params)).mappings().all()
    if rows:
        return [dict(r) for r in rows]

    # No template in this shape at all — now the kind is the better of the two signals.
    fallback = f"""
        select id, name, kind, aspect, tags, skeleton, description, quality_score
        from templates where kind = :kind {order} limit :lim
    """
    rows = (await session.execute(text(fallback), params)).mappings().all()
    if rows:
        return [dict(r) for r in rows]

    rows = (await session.execute(
        text("select id, name, kind, aspect, tags, skeleton, description, quality_score "
             "from templates order by quality_score desc limit :lim"),
        {"lim": limit},
    )).mappings().all()
    return [dict(r) for r in rows]


async def record_template_feedback(session: AsyncSession, template_id: str,
                                   delta: float) -> None:
    """§1.2: quality_score is a bandit signal — exported unedited is positive, deleted
    quickly or heavily repositioned is negative."""
    await session.execute(
        text("""update templates
                set quality_score = greatest(0, least(1, quality_score + :d)),
                    usage_count = usage_count + 1
                where id = :id"""),
        {"id": template_id, "d": delta},
    )


async def count_templates(session: AsyncSession) -> int:
    row = (await session.execute(text("select count(*) from templates"))).first()
    return int(row[0]) if row else 0
