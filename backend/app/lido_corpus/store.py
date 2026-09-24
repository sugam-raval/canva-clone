"""Template catalog in Postgres (`lido_templates`, pgvector) — docs/new_match_plan.md Part A.

Source of truth for authoring stays the JSON files in `lidojs_templates/` (the enrich
script and code review work on files). This module mirrors them into the database:

    sync_templates()   files → lido_templates. For each template it computes the detail
                       slots, the English card and a fingerprint (hash of meta + model +
                       card format). Only templates whose fingerprint changed are
                       re-embedded; unchanged rows are left alone. Rows that came from a
                       file which no longer exists are deleted.
    load_catalog()     what the API uses per request: syncs (at most every
                       LIDO_TEMPLATE_SYNC_SECONDS), then returns every template document
                       plus its index entry (card, details, embedding) from the database.

If the database is unreachable, everything falls back to the files with in-memory
embeddings, so generation keeps working.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import repo
from app.db.session import session_scope

from .details import TemplateDetails, template_details
from .loader import DEFAULT_CORPUS_DIR, derive_meta, discover_templates, load_authored_corpus
from .match_index import IndexEntry, embed, embedder_name, fingerprint, template_card
from .model import LidoDocument, LidoTemplateFile

log = structlog.get_logger(__name__)


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    """Raw files with no `meta` block yet — not synced until enriched."""
    invalid_id: list[str] = field(default_factory=list)
    """Files with meta but not named `template_<number>.json` — `lido_templates.id` is
    a genuine integer (see `app.db.repo.template_db_id`), so there is nowhere else for
    it to come from. Never reaches `repo.upsert_template`; caught here instead, so one
    misnamed file can't take down every other template's sync (this runs on the API's
    hot path via `load_catalog`, not only after a CLI `--verify`)."""
    model: str = ""

    def summary(self) -> str:
        text = (f"{len(self.added)} added, {len(self.updated)} re-embedded, "
                f"{len(self.unchanged)} unchanged, {len(self.deleted)} deleted "
                f"(embedding model: {self.model})")
        if self.skipped:
            text += (f"; skipped {len(self.skipped)} file(s) with no metadata yet: "
                     + ", ".join(self.skipped) + " — run `make lido-add`")
        if self.invalid_id:
            text += (f"; skipped {len(self.invalid_id)} file(s) not named "
                     "template_<number>.json: " + ", ".join(self.invalid_id))
        return text


def _source_files(corpus_dir: Path | str) -> dict[str, str]:
    return {p.stem: p.name for p in discover_templates(corpus_dir)}


async def new_template_ids(corpus_dir: Path | str = DEFAULT_CORPUS_DIR) -> list[str]:
    """Template ids (file stems) that exist in `corpus_dir` but have no row yet in
    `lido_templates` — what `make lido-add` onboards. A file's id is always its file
    stem (see `loader.derive_meta`), whether or not it has a `meta` block yet, so this
    never needs to parse/validate the files themselves.

    With `LIDO_TEMPLATE_STORE=files` (no database), every file counts as new."""
    file_ids = {p.stem for p in discover_templates(corpus_dir)}
    if not use_database():
        return sorted(file_ids)
    async with session_scope() as session:
        stored = await repo.list_template_index(session)
    stored_app_ids = {repo.template_app_id(tid) for tid in stored}
    return sorted(file_ids - stored_app_ids)


async def _sync(session: AsyncSession, templates: list[LidoTemplateFile],
                files: dict[str, str], *, force: bool,
                only: set[str] | None = None) -> SyncReport:
    model = embedder_name()
    report = SyncReport(model=model)
    valid_templates: list[LidoTemplateFile] = []
    for t in templates:
        try:
            repo.template_db_id(t.meta.id)
        except ValueError:
            report.invalid_id.append(t.meta.id)
        else:
            valid_templates.append(t)
    templates = valid_templates
    stored = {repo.template_app_id(tid): row
             for tid, row in (await repo.list_template_index(session)).items()}
    if only is not None:
        # One template: touch only its row; never delete other templates' rows.
        templates = [t for t in templates if t.meta.id in only]
        stored = {tid: row for tid, row in stored.items() if tid in only}

    changed: list[tuple[LidoTemplateFile, str, TemplateDetails, str]] = []
    for t in templates:
        fp = fingerprint(t, model)
        row = stored.get(t.meta.id)
        fresh = (row and row["fingerprint"] == fp
                 and (row["has_embedding"] or model == "none"))
        if fresh and not force:
            report.unchanged.append(t.meta.id)
            continue
        d = template_details(t.meta)
        changed.append((t, fp, d, template_card(t, d)))
        (report.updated if row else report.added).append(t.meta.id)

    vectors = await embed([c[3] for c in changed]) if changed else None
    for i, (t, fp, d, card) in enumerate(changed):
        m = t.meta
        await repo.upsert_template(
            session, template_id=repo.template_db_id(m.id), name=m.name, kind=m.kind,
            aspect=m.aspect,
            tags=list(m.tags), description=m.description,
            document=[{"layers": {lid: layer.model_dump(mode="json", by_alias=False)
                                  for lid, layer in t.layers.items()},
                       "meta": m.model_dump(mode="json")}],
            card=card, details=d.to_json(), fingerprint=fp,
            embedding=vectors[i] if vectors else None,
            embedding_model=model if vectors else None,
            ready=bool(m.reference_note), source_file=files.get(m.id))

    ids = {t.meta.id for t in templates}
    gone = [tid for tid, row in stored.items() if tid not in ids and row["source_file"]]
    if gone:
        await repo.delete_templates(session, [repo.template_db_id(tid) for tid in gone])
    report.deleted = gone
    return report


async def sync_templates(corpus_dir: Path | str = DEFAULT_CORPUS_DIR, *,
                         force: bool = False,
                         only: list[str] | None = None) -> SyncReport:
    """Mirror the template files into `lido_templates`. Raises if the database is down.
    Files with no `meta` block yet are skipped (and listed in the report). `only`
    limits the sync to those template ids (a deleted file's row is removed too)."""
    templates, raw = load_authored_corpus(corpus_dir)
    wanted = set(only) if only else None
    if wanted is not None:
        raw = [name for name in raw if Path(name).stem in wanted]
    async with session_scope() as session:
        report = await _sync(session, templates, _source_files(corpus_dir), force=force,
                             only=wanted)
    report.skipped = raw
    if raw:
        log.warning("lido.templates.unenriched", files=raw,
                    hint="run `make lido-add` to draft their metadata and sync them")
    if report.added or report.updated or report.deleted:
        log.info("lido.templates.synced", summary=report.summary())
    return report


def _row_to_template(row: dict) -> LidoTemplateFile:
    doc = row["document"]
    obj = (json.loads(doc) if isinstance(doc, str) else doc)
    obj = obj[0] if isinstance(obj, list) else obj
    layers = LidoDocument.model_validate({"layers": obj["layers"]}).layers
    app_id = repo.template_app_id(row["id"])
    return LidoTemplateFile(layers=layers,
                            meta=derive_meta(app_id, layers, existing=obj.get("meta")))


def _row_to_entry(row: dict) -> IndexEntry:
    details = row["details"]
    details = json.loads(details) if isinstance(details, str) else details
    return IndexEntry(template_id=repo.template_app_id(row["id"]), fingerprint=row["fingerprint"],
                      card=row["card"], details=TemplateDetails.from_json(details or {}),
                      embedding=row["embedding"])


@dataclass
class Catalog:
    templates: list[LidoTemplateFile]
    entries: dict[str, IndexEntry]
    from_db: bool


_last_sync: dict[str, float] = {}


def use_database() -> bool:
    """`LIDO_TEMPLATE_STORE=db` (default) or `files` (no database at all — tests use it)."""
    return get_settings().lido_template_store == "db"


async def load_catalog(corpus_dir: Path | str = DEFAULT_CORPUS_DIR) -> Catalog:
    """Templates + index entries for matching and filling. Database first (synced from
    the files at most every LIDO_TEMPLATE_SYNC_SECONDS), files as the fallback."""
    key = str(Path(corpus_dir).resolve())
    ttl = get_settings().lido_template_sync_seconds
    if not use_database():
        from .match_index import get_index

        templates, _raw = load_authored_corpus(corpus_dir)
        return Catalog(templates, await get_index(templates, corpus_dir), from_db=False)
    try:
        if time.monotonic() - _last_sync.get(key, -1e9) >= ttl:
            await sync_templates(corpus_dir)
            _last_sync[key] = time.monotonic()
        async with session_scope() as session:
            rows = await repo.list_templates(session)
        # Only rows for templates that exist in this corpus folder (a test or a second
        # folder must not see another folder's templates).
        files = _source_files(corpus_dir)
        rows = [r for r in rows
                if repo.template_app_id(r["id"]) in files or not r["source_file"]]
        order = {tid: i for i, tid in enumerate(files)}
        rows.sort(key=lambda r: order.get(repo.template_app_id(r["id"]), len(order)))
        return Catalog([_row_to_template(r) for r in rows],
                       {repo.template_app_id(r["id"]): _row_to_entry(r) for r in rows},
                       from_db=True)
    except Exception as exc:  # noqa: BLE001 — DB down: fall back to the files
        log.warning("lido.templates.db_unavailable", error=str(exc))
        from .match_index import get_index

        templates, _raw = load_authored_corpus(corpus_dir)
        return Catalog(templates, await get_index(templates, corpus_dir), from_db=False)


async def topic_similarities(entries: dict[str, IndexEntry], vector: list[float],
                             *, from_db: bool) -> dict[str, float] | None:
    """Cosine similarity per template: by pgvector when the catalog came from the
    database, else in Python. None when any template lacks an embedding."""
    if not all(e.embedding for e in entries.values()):
        return None
    if from_db:
        try:
            async with session_scope() as session:
                sims = await repo.template_similarities(session, vector)
            sims_app = {repo.template_app_id(tid): sim for tid, sim in sims.items()}
            if all(tid in sims_app for tid in entries):
                return {tid: sims_app[tid] for tid in entries}
        except Exception as exc:  # noqa: BLE001
            log.warning("lido.templates.similarity_failed", error=str(exc))
    return {tid: sum(x * y for x, y in zip(vector, e.embedding, strict=False))
            for tid, e in entries.items()}


async def warm_catalog(corpus_dir: Path | str = DEFAULT_CORPUS_DIR) -> None:
    """At API startup: load the embedding model and sync the files into the database,
    so the first request is fast. Never raises."""
    try:
        catalog = await load_catalog(corpus_dir)
        log.info("lido.templates.warm", templates=len(catalog.templates),
                 database=catalog.from_db, model=embedder_name())
    except Exception as exc:  # noqa: BLE001
        log.warning("lido.templates.warm_failed", error=str(exc))
