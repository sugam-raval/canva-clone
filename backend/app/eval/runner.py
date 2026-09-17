"""Evaluation runner — IMPLEMENTATION_PLAN §5.3.

Runs the prompt set through the real Part One pipeline, measures every finished
document, and reports the release gates.

It calls the orchestrator directly rather than going over HTTP so that it measures the
pipeline rather than the web server, and so a failing run can be attached to a debugger.
Timings are captured from the progress events, which is exactly what the user perceives.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.adapters.registry import embedder as get_embedder
from app.db import repo
from app.db.session import session_scope
from app.eval.metrics import DocMetrics, aggregate, measure_document, summary_stats
from app.eval.prompts import PROMPTS, EvalPrompt
from app.layout.fonts import get_registry as get_font_registry
from app.pipelines.part_one.orchestrator import generate
from app.schema.doc import DesignDoc
from app.storage.resolver import resolve_for

log = structlog.get_logger(__name__)


class _Recorder:
    """Captures the timings and per-layer signals the metrics need."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.skeleton_seconds = 0.0
        self.complete_seconds = 0.0
        self.cost_cents = 0
        self.doc_ids: list[str] = []
        self.glyph_boxes: dict[str, float] = {}
        self.failures: list[str] = []

    async def __call__(self, event) -> None:
        elapsed = time.monotonic() - self.started
        kind = getattr(event, "t", "")
        if kind == "doc.skeleton":
            if not self.skeleton_seconds:
                self.skeleton_seconds = elapsed
            self.doc_ids.append(event.doc["id"])
        elif kind == "layer.patch":
            notes = (event.patch.get("meta") or {}).get("notes") or {}
            # The gate records how many retries it needed; anything that still shipped
            # with detected glyphs is leakage.
            if notes.get("glyphLeakageCoverage"):
                self.glyph_boxes[event.layer_id] = float(notes["glyphLeakageCoverage"])
        elif kind == "job.failed":
            self.failures.append(f"{event.type}: {event.reason}")
        elif kind == "request.done":
            self.complete_seconds = elapsed
            self.cost_cents = event.cost_cents
        elif kind == "request.failed":
            self.complete_seconds = elapsed
            self.failures.append(f"request: {event.reason}")


async def run_one(prompt: EvalPrompt, user_id: str) -> list[DocMetrics]:
    recorder = _Recorder()
    async with session_scope() as session:
        request_id = await repo.create_generation_request(
            session, user_id=user_id, prompt=prompt.prompt)
        try:
            await generate(
                session, prompt=prompt.prompt, user_id=user_id, request_id=request_id,
                count=1, brand_kit=prompt.brand_kit, emit=recorder,
                allow_clarification=False,
            )
        except Exception as exc:
            log.exception("eval.prompt_failed", prompt_id=prompt.id)
            recorder.failures.append(f"crash: {exc}")

    out: list[DocMetrics] = []
    async with session_scope() as session:
        for doc_id in recorder.doc_ids:
            row = await repo.get_document(session, doc_id)
            if row is None:
                continue
            doc = DesignDoc.model_validate(row["doc"])
            resolved = await resolve_for(session, doc)
            metrics = measure_document(
                doc, prompt_id=prompt.id, glyph_boxes=recorder.glyph_boxes,
                resolve_asset=resolved.url_resolver(), load_image=resolved.image_loader(),
            )
            metrics.skeleton_seconds = recorder.skeleton_seconds
            metrics.complete_seconds = recorder.complete_seconds
            metrics.cost_cents = recorder.cost_cents
            metrics.notes.extend(recorder.failures)
            out.append(metrics)

    if not out:
        # A prompt that produced nothing still has to count against the gates, or a
        # pipeline that fails everything would score a perfect run.
        failed = DocMetrics(doc_id="", prompt_id=prompt.id, schema_valid=False)
        failed.notes = recorder.failures or ["no document produced"]
        failed.skeleton_seconds = recorder.skeleton_seconds
        failed.complete_seconds = recorder.complete_seconds or (
            time.monotonic() - recorder.started)
        out.append(failed)
    return out


async def run_suite(prompts: list[EvalPrompt] | None = None, *, user_email: str,
                    concurrency: int = 2, out_dir: Path | None = None) -> dict:
    prompts = prompts or PROMPTS

    # §6.8: the API warms model weights at startup. Without the same warm-up here the
    # first prompt pays an ~18 s sentence-transformer load and lands in p95, reporting a
    # cold-start number no user ever experiences.
    warm_started = time.monotonic()
    get_font_registry()
    warm = getattr(get_embedder(), "warm", None)
    if warm is not None:
        warm()
    log.info("eval.warmup", seconds=round(time.monotonic() - warm_started, 2))

    async with session_scope() as session:
        user_id = await repo.ensure_user(session, user_email)

    semaphore = asyncio.Semaphore(concurrency)
    results: list[DocMetrics] = []

    async def run(prompt: EvalPrompt) -> None:
        async with semaphore:
            started = time.monotonic()
            metrics = await run_one(prompt, user_id)
            results.extend(metrics)
            worst = min((m.worst_contrast for m in metrics), default=0)
            log.info("eval.prompt_done", prompt_id=prompt.id,
                     seconds=round(time.monotonic() - started, 2),
                     valid=all(m.schema_valid for m in metrics),
                     overflow=sum(m.overflowing_text_layers for m in metrics),
                     collisions=sum(m.colliding_pairs for m in metrics),
                     worst_contrast=round(worst, 2))

    await asyncio.gather(*(run(prompt) for prompt in prompts))

    gates = aggregate(results)
    report = {
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "prompts": len(prompts),
        "summary": summary_stats(results),
        "gates": [
            {"name": g.name, "value": round(g.value, 4), "comparator": g.comparator,
             "threshold": g.threshold, "passed": g.passed}
            for g in gates
        ],
        "passed": all(g.passed for g in gates),
        "documents": [asdict(m) for m in results],
    }

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = out_dir / f"eval-{stamp}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        report["reportPath"] = str(path)
    return report


def print_report(report: dict) -> None:
    summary = report["summary"]
    print()
    print("=" * 68)
    print(f"  Eval — {report['prompts']} prompts, {summary['documents']} documents")
    print("=" * 68)
    for gate in report["gates"]:
        mark = "PASS" if gate["passed"] else "FAIL"
        unit = "s" if gate["name"].endswith("_seconds") else ""
        value = f"{gate['value']:.2f}{unit}" if unit else f"{gate['value']:.3f}"
        print(f"  {mark}  {gate['name']:24} {value:>9}   "
              f"({gate['comparator']} {gate['threshold']})")
    print("-" * 68)
    print(f"  time to skeleton   p50 {summary['p50SkeletonSeconds']:.2f}s  "
          f"p95 {summary['p95SkeletonSeconds']:.2f}s")
    print(f"  time to complete   p50 {summary['p50CompleteSeconds']:.2f}s  "
          f"p95 {summary['p95CompleteSeconds']:.2f}s")
    print(f"  cost               mean {summary['meanCostCents']:.2f}c  "
          f"total {summary['totalCostCents']}c")
    print(f"  degraded layers    {summary['degradedLayers']}")
    print(f"  templates used     {len(summary['templatesUsed'])}")
    print(f"  worst contrast     {summary['worstContrast']}:1")

    problems = [d for d in report["documents"] if d["notes"]]
    if problems:
        print("-" * 68)
        print("  Findings:")
        for doc in problems[:12]:
            for note in doc["notes"][:3]:
                print(f"    {doc['prompt_id']}: {note}")
    print("=" * 68)
    print(f"  {'ALL GATES PASSED' if report['passed'] else 'GATES FAILED'}")
    if report.get("reportPath"):
        print(f"  report: {report['reportPath']}")
    print()
