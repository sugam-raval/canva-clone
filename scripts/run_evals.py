#!/usr/bin/env python3
"""Run the evaluation suite — IMPLEMENTATION_PLAN §5.3.

    python scripts/run_evals.py                  # the whole suite
    python scripts/run_evals.py --tag text-only  # one slice
    python scripts/run_evals.py --limit 5        # a quick smoke run

Exits non-zero if any release gate fails, so it can gate a deploy.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import structlog
from app.db.session import dispose_engine
from app.eval.prompts import PROMPTS
from app.eval.runner import print_report, run_suite


async def main(args) -> int:
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if args.verbose else logging.INFO))

    prompts = PROMPTS
    if args.tag:
        prompts = [p for p in prompts if args.tag in p.tags]
    if args.kind:
        prompts = [p for p in prompts if p.kind == args.kind]
    if args.limit:
        prompts = prompts[: args.limit]
    if not prompts:
        print("no prompts matched that filter", file=sys.stderr)
        return 2

    report = await run_suite(
        prompts,
        user_email=args.user,
        concurrency=args.concurrency,
        out_dir=Path(args.out) if args.out else None,
    )
    print_report(report)
    await dispose_engine()
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="filter by prompt tag (subject, text-only, brand…)")
    parser.add_argument("--kind", help="filter by design kind (story, post, poster…)")
    parser.add_argument("--limit", type=int, help="run only the first N prompts")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--user", default="dev@localhost")
    parser.add_argument("--out", default="artifacts/evals",
                        help="directory for the JSON report")
    parser.add_argument("--verbose", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
