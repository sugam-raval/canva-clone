"""Building blocks of the template index (docs/new_match_plan.md Part A).

For every template: which details it has a slot for (`details.py`), a short English
"card" describing it, a fingerprint, and the card's embedding from the local
sentence-transformer set in `SENTENCE_TRANSFORMER_MODEL`.

These are stored in Postgres by `store.py` (`lido_templates`, pgvector). `get_index` here
is the in-memory version, used when the database is unavailable or switched off
(`LIDO_TEMPLATE_STORE=files`).

WHAT IS EMBEDDED — the card (`template_card`), built from:
  meta.name, meta.kind, meta.description, meta.tags, the sample text of every text slot
  (by role), the detected detail slots, buttons, list size and photo count.
WHEN IT IS RE-EMBEDDED — whenever `fingerprint` changes: it hashes the WHOLE `meta`
  block (so any metadata edit, and any layer text change, which changes the recomputed
  meta), the embedding model name and CARD_VERSION. No manual re-index is needed.

Without `sentence-transformers` installed, entries have no embedding and the matcher
falls back to word overlap between the topic line and the card.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import structlog

from app.adapters.base import AdapterError
from app.config import get_settings

from .details import TemplateDetails, template_details
from .loader import DEFAULT_CORPUS_DIR
from .model import LidoTemplateFile

log = structlog.get_logger(__name__)

CARD_VERSION = 1
"""Bump when `template_card` changes, so every cached embedding is rebuilt."""



@dataclass
class IndexEntry:
    template_id: str
    fingerprint: str
    card: str
    details: TemplateDetails
    embedding: list[float] | None


# --------------------------------------------------------------------------------------
# Embedder — the local model only, never the hash fallback (which has no meaning)
# --------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _embedder():
    from app.adapters.embedding_adapters import SentenceTransformerEmbedder

    if not SentenceTransformerEmbedder.available():
        log.warning("lido.match.no_embedder",
                    reason="sentence-transformers not installed; topic falls back to "
                           "word overlap. Install the backend's [embed] extra.")
        return None
    return SentenceTransformerEmbedder(get_settings().sentence_transformer_model)


def embedder_name() -> str:
    emb = _embedder()
    return emb.model_name if emb is not None else "none"


async def embed(texts: list[str]) -> list[list[float]] | None:
    emb = _embedder()
    if emb is None or not texts:
        return None
    try:
        return await emb.embed(texts)
    except AdapterError as exc:
        log.warning("lido.match.embed_failed", error=str(exc))
        return None


# --------------------------------------------------------------------------------------
# The card
# --------------------------------------------------------------------------------------

_DETAIL_WORDS = {
    "phone": "a phone number", "email": "an email address", "website": "a website",
    "address": "an address", "offer": "an offer or discount", "price": "a price",
    "date": "a date or time",
}


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def template_card(template: LidoTemplateFile, details: TemplateDetails) -> str:
    """A few plain English sentences about what the template is and holds. Built from the
    metadata AND the real sample copy, so weak metadata is partly corrected by the text
    the design actually shows."""
    meta = template.meta
    by_role: dict[str, list[str]] = {}
    for s in meta.slots:
        if s.resolved_name == "TextLayer" and s.default_text:
            by_role.setdefault(s.role, []).append(_clean(s.default_text))

    parts = []
    head = meta.name or meta.id
    parts.append(f"{head}: {meta.kind} template.")
    if meta.description:
        parts.append(_clean(meta.description))
    title = " ".join(by_role.get("headline", []) + by_role.get("subhead", []))
    if title:
        parts.append(f"Title: {title}.")
    other = [t for role in ("body", "label") for t in by_role.get(role, [])]
    if other:
        parts.append("Text: " + "; ".join(other[:10]) + ".")
    has = [_DETAIL_WORDS[d] for d in sorted(details.details)]
    if details.buttons:
        has.append("a button (" + ", ".join(details.buttons) + ")")
    if details.list_items:
        has.append(f"a list of {details.list_items} items")
    if details.photos:
        has.append(f"{details.photos} photo{'s' if details.photos > 1 else ''}")
    if has:
        parts.append("Has " + ", ".join(has) + ".")
    if meta.tags:
        parts.append("Tags: " + ", ".join(meta.tags) + ".")
    return " ".join(parts)


def fingerprint(template: LidoTemplateFile, model: str) -> str:
    payload = json.dumps({"v": CARD_VERSION, "model": model,
                          "meta": template.meta.model_dump(mode="json")},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------------------
# Load / build / save
# --------------------------------------------------------------------------------------

_MEMORY: dict[str, dict[str, IndexEntry]] = {}


async def get_index(templates: list[LidoTemplateFile],
                    corpus_dir: Path | str = DEFAULT_CORPUS_DIR, *,
                    force: bool = False) -> dict[str, IndexEntry]:
    """In-memory index entries for exactly these templates, rebuilding only what changed
    since the last call (kept per corpus folder for the life of the process)."""
    key = str(Path(corpus_dir).resolve())
    model = embedder_name()
    cached = {} if force else _MEMORY.get(key, {})
    wanted = {t.meta.id: (t, fingerprint(t, model)) for t in templates}
    entries: dict[str, IndexEntry] = {}
    stale: list[tuple[LidoTemplateFile, str]] = []
    for tid, (t, fp) in wanted.items():
        hit = cached.get(tid)
        if hit and hit.fingerprint == fp and (hit.embedding or model == "none"):
            entries[tid] = hit
        else:
            stale.append((t, fp))

    if stale:
        built = []
        for t, fp in stale:
            d = template_details(t.meta)
            built.append(IndexEntry(t.meta.id, fp, template_card(t, d), d, None))
        vectors = await embed([e.card for e in built])
        for e, v in zip(built, vectors or [None] * len(built)):
            e.embedding = v
            entries[e.template_id] = e
        log.info("lido.match.index_built", rebuilt=len(built), total=len(entries),
                 model=model)
    _MEMORY[key] = entries
    return entries

