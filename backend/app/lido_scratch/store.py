"""Persist generated designs to `lido_generated/`.

Kept separate from `lidojs_templates/` on purpose: that directory is the hand-curated
corpus the retrieval flow searches, and mixing machine output into it would quietly
change what every corpus request matches against. Same on-disk shape though — a
`[{"layers": ..., "meta": ...}]` array — so a generated design that turns out well can
be promoted into the corpus by moving the file, and `app.lido_corpus.loader` reads it
with no special casing.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.lido_corpus.loader import DEFAULT_CORPUS_DIR, derive_meta
from app.lido_corpus.model import LidoDocument

GENERATED_DIR = DEFAULT_CORPUS_DIR.parent / "lido_generated"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _slug(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:40] or "design"


def new_id(name: str) -> str:
    return f"{_slug(name)}-{uuid.uuid4().hex[:8]}"


def build_document(design_id: str, layers: dict[str, dict], *, name: str, kind: str,
                   prompt: str, tags: list[str], description: str) -> list[dict]:
    """The `[{layers, meta}]` array as written to disk and returned to the client.

    `meta` is derived by the corpus loader rather than assembled here, so a scratch
    design describes its slots in exactly the same terms a corpus template does.
    """
    document = LidoDocument.model_validate({"layers": layers})
    meta = derive_meta(design_id, document.layers, existing={
        "name": name, "kind": kind, "tags": tags, "description": description,
    })
    payload = meta.model_dump(mode="json")
    payload["source"] = "scratch"
    payload["prompt"] = prompt
    payload["generated_at"] = datetime.now(UTC).isoformat()
    return [{"layers": layers, "meta": payload}]


def save(design_id: str, document: list[dict], directory: Path | None = None) -> Path:
    directory = directory or GENERATED_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{design_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)
    return path


def load(design_id: str, directory: Path | None = None) -> list[dict] | None:
    # `design_id` arrives from a URL path segment, so it is matched against the shape
    # `new_id` produces rather than trusted as a filename.
    if not _ID_RE.match(design_id):
        return None
    path = (directory or GENERATED_DIR) / f"{design_id}.json"
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def listing(directory: Path | None = None) -> list[dict]:
    """Every saved design's `meta`, newest first. Unreadable files are skipped rather
    than failing the listing — one bad file must not hide the rest of the gallery."""
    directory = directory or GENERATED_DIR
    if not directory.is_dir():
        return []
    out: list[tuple[float, dict]] = []
    for path in directory.glob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            meta = (data[0] if isinstance(data, list) else data).get("meta") or {}
        except (json.JSONDecodeError, OSError, IndexError, AttributeError):
            continue
        meta.setdefault("id", path.stem)
        out.append((path.stat().st_mtime, meta))
    return [meta for _mtime, meta in sorted(out, key=lambda pair: pair[0], reverse=True)]
