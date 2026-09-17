# ADR 0001 — Python/FastAPI backend replacing the Node services

Status: accepted — 2026-09-11
Supersedes the stack choices in IMPLEMENTATION_PLAN.md §0.3 / §0.4 for the server side.

## Context

§0.3 specifies Node 20 + Fastify for `apps/api`, Node for `services/orchestrator`,
and Python only for `services/ml-gateway` + `services/workers`. The project owner
requires a single Python/FastAPI backend.

## Decision

Collapse `apps/api`, `apps/sync`, `apps/render`, `services/orchestrator`,
`services/ml-gateway` and `services/workers` into one Python package, `backend/app`,
with module boundaries that mirror the original service boundaries so they can be
split back out into separate processes without code changes:

| Plan component        | Here                        | Split-out path                |
|---|---|---|
| `apps/api`            | `app/api/`                  | already its own ASGI router set |
| `apps/sync`           | `app/sync/`                 | separate uvicorn app          |
| `apps/render`         | `app/renderer/`             | separate arq worker on `q.export` |
| `services/orchestrator` | `app/pipelines/`          | separate arq worker           |
| `services/ml-gateway` | `app/adapters/`             | separate FastAPI app          |
| `packages/doc-schema` | `app/schema/`               | pip package                   |
| `packages/layout-engine` | `app/layout/`            | pip package                   |
| `packages/renderer-core` | `app/renderer/core.py`   | pip package                   |

Substitutions, each chosen as the nearest Python equivalent:

| Plan | Here | Why |
|---|---|---|
| Zod + `zod-to-json-schema` | Pydantic v2 + `model_json_schema()` | same guarantee: one source of truth emitting the JSON Schema the LLM is constrained against |
| BullMQ (Redis) | `arq` (Redis, asyncio) | same Redis-backed per-queue model, native to the async runtime |
| Yjs + `y-websocket` | `pycrdt` (Y-CRDT Rust bindings) | wire-compatible with Yjs, so the browser still runs real `yjs` |
| Skia via `@napi-rs/canvas` | `skia-python` | the same Skia; additionally gives native PDF and SVG canvases, which §4.1 needs |
| `harfbuzzjs` | `uharfbuzz` | the same HarfBuzz build |
| `resvg` | Skia SVG canvas / cairosvg | adequate for v1 |

## Consequence for INV-3 (render parity) — the important one

§0.11 achieves parity by having browser and server import the *same* TypeScript
`renderer-core` and `layout-engine`. A Python backend breaks that, and
"reimplement the layout engine twice" is exactly the drift Appendix A.5 warns about.

We therefore change *where* the shared code lives rather than duplicating it:

**The server is the single source of truth for the draw list.** `toDrawList()` and
all HarfBuzz shaping run in Python only. The browser never computes glyph positions
for the authoritative document; it receives `DrawCommand[]` (including
`PositionedGlyphRun[]` with resolved glyph ids and advances) as JSON over
`GET /v1/docs/:id/drawlist` and feeds it to a thin Konva backend.

Both renderers therefore consume a byte-identical command list — a *stronger*
parity guarantee than sharing source, because there is only one implementation.

The cost is interactive latency: live text editing cannot round-trip to the server
per keystroke. So the client keeps a **preview-only** shaper (browser text metrics)
used during a gesture, and re-fetches the authoritative draw list on gesture end.
Preview shaping is never persisted and never exported. The golden-image SSIM test
of §5.2 compares the browser's render of the server's draw list against the server's
own raster, which is what INV-3 actually asks for.

## Alternatives rejected

- **Keep Node for api/render, Python only for ML** — matches the plan, rejected by
  the owner's requirement.
- **Port `layout-engine` to TS and call it from Python via a node subprocess** —
  reintroduces a Node runtime dependency and a per-call process boundary on the
  hottest path (§6.5 text measurement cache).
