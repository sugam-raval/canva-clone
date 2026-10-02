#!/usr/bin/env python3
"""Move draft templates between the database (`lido_drafts`) and files.

    python scripts/lido_drafts.py import [--delete-local]       lidojs_templates/drafts/ → DB
    python scripts/lido_drafts.py export ID [--name template_N] [--force]   DB → corpus

import  moves the old file-based drafts (template_<n>.json, previews/template_<n>.png,
        template_<n>.info.json) into `lido_drafts`, keeping each one's creation time and
        its old name as info.importedFrom; previews are uploaded to the object store.
        Safe to rerun: a draft already imported is left as it is. Every draft is read
        back and compared before anything local is touched, and local files are only
        removed with --delete-local (and only when every draft checked out).
export  writes draft ID (`lido_drafts.id`) into the corpus as
        lidojs_templates/template_<n>.json and previews/template_<n>.png, ready for
        `make lido-add TEMPLATE=template_<n>`. The name is --name, else the one it was
        imported from when that is still free, else the first free template_<n> from
        90001 (the range kept for generated templates).

Needs the database schema (`make db-upgrade`) and the object store running.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import repo
from app.db.session import dispose_engine, session_scope
from app.lido_create import drafts
from app.lido_create.kit import CORPUS_DIR, PHOTO_CACHE

OLD_DRAFTS_DIR = CORPUS_DIR / "drafts"
TEMPLATE_NAME = re.compile(r"template_(\d+)")
FIRST_EXPORT_NUMBER = 90001  # generated templates live in their own range, clear of real ones
# kept as columns (or derived) rather than inside `info`
_NOT_INFO = ("id", "createdAt", "hasPreview", "previewUrl", "source", "prompt", "name",
             "fingerprint", "document")
# local leftovers of the file-based drafts that mean nothing once they are in the DB
_LEFTOVERS = ("overview.png", ".history.json", ".photo_cache.json")


def _created(info: dict, path: Path) -> datetime:
    if info.get("createdAt"):
        return datetime.fromisoformat(info["createdAt"])
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


async def import_drafts(folder: Path, delete_local: bool) -> int:
    paths = sorted(p for p in folder.glob("template_*.json")
                   if TEMPLATE_NAME.fullmatch(p.stem))
    if not paths:
        print(f"no drafts in {folder}/")
        return 0
    imported = skipped = 0
    checked: list[Path] = []
    problems: list[str] = []
    for path in paths:
        document = json.loads(path.read_text())
        if not document:  # an id claimed by a request that then failed: nothing to keep
            print(f"  {path.stem}: empty placeholder, nothing to import")
            checked.append(path)
            continue
        info_path = folder / f"{path.stem}.info.json"
        info = json.loads(info_path.read_text()) if info_path.is_file() else {}
        png = folder / "previews" / f"{path.stem}.png"

        async with session_scope() as s:
            draft_id = await repo.find_imported_draft(s, path.stem)
        fresh = draft_id is None
        if fresh:
            row = {"source": info.get("source") or "manual",
                   "prompt": info.get("prompt") or "", "name": info.get("name") or "",
                   "fingerprint": info.get("fingerprint"), "preview_url": None,
                   "info": {**{k: v for k, v in info.items() if k not in _NOT_INFO},
                            "importedFrom": path.stem},
                   "document": document, "created_at": _created(info, path)}
            async with session_scope() as s:
                draft_id = await repo.insert_lido_draft(s, **row)
            imported += 1
        else:
            skipped += 1
        async with session_scope() as s:
            stored = await repo.get_lido_draft(s, draft_id)
        if png.is_file() and stored and not stored["preview_url"]:
            url = await asyncio.to_thread(drafts.upload_preview, draft_id, png.read_bytes())
            if url:
                async with session_scope() as s:
                    await repo.set_lido_draft_preview(s, draft_id, url)
                stored["preview_url"] = url

        # read it back: the stored document must be the file, value for value
        if stored is None or stored["document"] != document:
            problems.append(f"{path.stem}: stored document differs from the file")
        elif png.is_file() and not stored["preview_url"]:
            problems.append(f"{path.stem}: preview upload failed (object store down?)")
        else:
            checked.append(path)
            print(f"  {path.stem} → id {draft_id}: "
                  f"{'imported' if fresh else 'already in the DB'}"
                  f"{'' if stored['preview_url'] else ' (no preview)'}")

    print(f"\n{imported} imported, {skipped} already there, {len(problems)} problem(s)")
    for p in problems:
        print(f"  ! {p}")
    if problems:
        print("nothing local was removed; fix the above and rerun")
        return 1
    if delete_local:
        _remove_local(folder, checked)
    else:
        print(f"local files kept; rerun with --delete-local to remove {folder}/")
    return 0


def _remove_local(folder: Path, checked: list[Path]) -> None:
    for path in checked:
        for p in (path, folder / f"{path.stem}.info.json",
                  folder / "previews" / f"{path.stem}.png"):
            p.unlink(missing_ok=True)
    old_cache = folder / PHOTO_CACHE.name
    if old_cache.is_file():  # the photo-size cache now lives beside the corpus
        if PHOTO_CACHE.is_file():
            old_cache.unlink()
        else:
            shutil.move(old_cache, PHOTO_CACHE)
    for name in _LEFTOVERS:
        (folder / name).unlink(missing_ok=True)
    for d in (folder / "previews", folder):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    left = [p.name for p in folder.rglob("*")] if folder.exists() else []
    print(f"removed the local drafts{'; left untouched: ' + ', '.join(left) if left else ''}")


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _taken() -> set[str]:
    return {p.stem for p in CORPUS_DIR.glob("template_*.json")}


def export_name(record: dict) -> str:
    """The name it was imported under when still free, else the first free one from
    FIRST_EXPORT_NUMBER."""
    taken = _taken()
    if (old := record.get("importedFrom")) and old not in taken:
        return old
    n = FIRST_EXPORT_NUMBER
    while f"template_{n}" in taken:
        n += 1
    return f"template_{n}"


async def export_draft(draft_id: int, name: str | None, force: bool) -> int:
    record = await drafts.get_draft(draft_id)
    if record is None:
        print(f"no draft with id {draft_id}", file=sys.stderr)
        return 1
    if name and not TEMPLATE_NAME.fullmatch(name):
        print(f"--name must be template_<number>, not {name!r}", file=sys.stderr)
        return 1
    name = name or export_name(record)
    out = CORPUS_DIR / f"{name}.json"
    if out.exists() and not force:
        print(f"{out} already exists (--force to overwrite)", file=sys.stderr)
        return 1
    out.write_text(json.dumps(record["document"], indent=2) + "\n")
    print(f"wrote {out}")
    if record.get("previewUrl"):
        png = CORPUS_DIR / "previews" / f"{name}.png"
        png.write_bytes(await asyncio.to_thread(_download, record["previewUrl"]))
        print(f"wrote {png}")
    print(f"draft {draft_id} exported as {name}; next: make lido-add TEMPLATE={name} KIND=post")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="move lidojs_templates/drafts/ into the database")
    imp.add_argument("--from", dest="folder", type=Path, default=OLD_DRAFTS_DIR)
    imp.add_argument("--delete-local", action="store_true",
                     help="remove the local files once every draft is verified in the DB")
    exp = sub.add_parser("export", help="write a draft into lidojs_templates/")
    exp.add_argument("id", type=int, help="the draft's id (lido_drafts.id)")
    exp.add_argument("--name", help="template_<n> to export it as (default: a free one)")
    exp.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args()

    async def run() -> int:
        try:
            if args.command == "import":
                return await import_drafts(args.folder, args.delete_local)
            return await export_draft(args.id, args.name, args.force)
        finally:
            await dispose_engine()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
