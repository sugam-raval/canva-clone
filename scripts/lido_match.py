#!/usr/bin/env python3
"""Lido.js template matching tools (docs/new_match_plan.md).

    python scripts/lido_match.py index            # sync lidojs_templates/*.json → lido_templates (DB)
    python scripts/lido_match.py index --force    # re-embed every template
    python scripts/lido_match.py index --template template_300   # just this one
    python scripts/lido_match.py show "request"   # explain which template a request would get
    python scripts/lido_match.py test             # run the test requests and print accuracy
    python scripts/lido_match.py test --no-llm    # same, without the small LLM call

The API also syncs by itself (at startup and every LIDO_TEMPLATE_SYNC_SECONDS), re-embedding
only templates whose metadata changed, so `index` is only needed to force it or to look at
the cards. With LIDO_TEMPLATE_STORE=files (or the database down) everything runs in memory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.lido_corpus.loader import DEFAULT_CORPUS_DIR
from app.lido_corpus.match_index import embedder_name
from app.lido_corpus.matcher import MatchResult, match_templates
from app.lido_corpus.store import load_catalog, sync_templates, use_database

CASES = Path(__file__).resolve().parent.parent / "backend/app/lido_corpus/match_cases.jsonl"


def _print_result(prompt: str, r: MatchResult, top: int = 3) -> None:
    path = ("holds every detail" if r.path == "holds_all"
            else "best match (no template holds every detail)")
    print(f"\nRequest : {prompt}")
    print(f"Topic   : {r.topic_line}   ({'LLM' if r.used_llm else 'no LLM'}, {r.embedder})")
    print(f"Details : {', '.join(r.request_details) or 'none'}")
    print(f"Path    : {path}")
    for i, c in enumerate(r.candidates[:top], 1):
        extra = []
        if c.missing:
            extra.append("no slot for " + ", ".join(c.missing))
        if c.empty_contact_slots:
            extra.append("placeholder " + ", ".join(c.empty_contact_slots))
        print(f"  {i}. {c.template_id:<16} score {c.score:5.2f}  topic {c.topic:4.2f}  "
              f"details {c.details_score:4.2f}  {'; '.join(extra)}")


async def cmd_index(args) -> int:
    only = args.template or None
    if only:
        from app.lido_corpus.loader import discover_templates

        missing = set(only) - {p.stem for p in discover_templates(args.dir)}
        if missing:
            print(f"template(s) not found in {args.dir}: {', '.join(sorted(missing))}")
            return 1
    if use_database():
        report = await sync_templates(args.dir, force=args.force, only=only)
        print(f"lido_templates: {report.summary()}")
        if report.skipped:
            return 1
    catalog = await load_catalog(args.dir)
    where = "Postgres lido_templates (pgvector)" if catalog.from_db else "memory (no database)"
    print(f"{len(catalog.templates)} template(s) in {where}, embedder: {embedder_name()}")
    for tid, e in catalog.entries.items():
        if only and tid not in only:
            continue
        print(f"\n[{tid}] details={sorted(e.details.details) or '-'} "
              f"embedding={'yes' if e.embedding else 'no'}\n  {e.card}")
    return 0


async def cmd_show(args) -> int:
    catalog = await load_catalog(args.dir)
    r = await match_templates(catalog.templates, args.prompt, corpus_dir=args.dir,
                              use_llm=not args.no_llm, catalog=catalog)
    _print_result(args.prompt, r, top=args.top)
    return 0


async def cmd_test(args) -> int:
    catalog = await load_catalog(args.dir)
    templates = catalog.templates
    ids = {t.meta.id for t in templates}
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    top1 = top3 = counted = 0
    misses = []
    for case in cases:
        ok = [t for t in case["acceptable"] if t in ids]
        if not ok:
            continue                                   # template not in this corpus
        counted += 1
        r = await match_templates(templates, case["prompt"], corpus_dir=args.dir,
                                  use_llm=not args.no_llm, catalog=catalog)
        picks = [c.template_id for c in r.candidates]
        if picks[0] in ok:
            top1 += 1
        else:
            misses.append((case, r))
        if set(picks[:3]) & set(ok):
            top3 += 1
    for case, r in misses:
        print(f"\nMISS — expected {case['acceptable']}")
        _print_result(case["prompt"], r)
    if not counted:
        print("no test case matches a template in this corpus")
        return 1
    print(f"\n{counted} cases · first pick right {top1}/{counted} ({100 * top1 / counted:.0f}%)"
          f" · right answer in top 3 {top3}/{counted} ({100 * top3 / counted:.0f}%)"
          f" · embedder {embedder_name()} · {'no LLM' if args.no_llm else 'LLM on'}")
    return 0 if top1 / counted >= 0.85 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_CORPUS_DIR)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index")
    p.add_argument("--force", action="store_true")
    p.add_argument("--template", action="append", default=None, metavar="NAME",
                   help="only this template (file stem); repeat for several")
    p = sub.add_parser("show")
    p.add_argument("prompt")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--no-llm", action="store_true")
    p = sub.add_parser("test")
    p.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()
    return asyncio.run({"index": cmd_index, "show": cmd_show, "test": cmd_test}[args.cmd](args))


if __name__ == "__main__":
    raise SystemExit(main())
