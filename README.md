# AI Layered Design Generator

A prompt becomes a **real multi-layer design document** — live text, transparent
subjects, shapes, effects — every layer independently editable. Nothing is ever
flattened into a picture of a design.

Implements **Part One** of [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)
(prompt → editable composition). Part Two (decomposing a flat image back into layers)
is deliberately out of scope for this build.

---

## The three invariants

Everything here exists to hold these. They are enforced mechanically, not by convention.

| | Invariant | How it is enforced |
|---|---|---|
| **INV-1** | Text is text, never pixels | The schema validator rejects any text layer carrying a raster adapter; the §1.4.6 **glyph gate** re-rolls and then inpaints any generated image containing detectable lettering |
| **INV-2** | Every generated asset is reproducible | Each image layer stores its full `GenerationParams`; assets are content-addressed by `gen_hash`, so identical parameters return identical bytes |
| **INV-3** | Canvas and export are the same picture | One `toDrawList()` on the server. The browser does not compute geometry or shape text — it replays the server's `DrawCommand[]`, glyph ids and all (see [ADR 0001](docs/adr/0001-python-backend.md)) |

---

## Quick start

Requires Python 3.11+, Node 20+, and Docker.

```bash
make setup     # deps, fonts, containers, template corpus  (~5 min, downloads ~1 GB)
make dev       # API on :8000, editor on :5173
```

Open <http://localhost:5173>, type a prompt, press **Generate**.

It works with **no API key** — stub adapters produce procedural images and the
heuristic brief parser takes over — so you can exercise the whole pipeline offline.
For real designs, add a key:

```bash
echo "OPENAI_API_KEY=sk-..." >> backend/.env
```

`GET /v1/health` reports which implementation each capability resolved to.

### If `make setup` fails

| Symptom | Cause and fix |
|---|---|
| `ENOSPC ... watch` on `make web` | inotify instances exhausted. `sudo sysctl -w fs.inotify.max_user_instances=512`, or run `VITE_USE_POLLING=1 npm run dev` |
| Port 5442 in use | Another Postgres. Change the host port in `infra/docker-compose.yml` and `DATABASE_URL` |
| `uv` installs into the wrong environment | An active conda env takes precedence. The Makefile pins `VIRTUAL_ENV` and `--python` to avoid this |

---

## How a prompt becomes a document

```
 prompt
   │
   ├─ 1.1  brief.parse        LLM (schema-constrained) → heuristic fallback
   ├─ 1.2  art.direct         what the imagery is OF  ─┐ both need only the brief,
   ├─ 1.2  template.retrieve  hard filters + pgvector  ┘ so they run concurrently
   ├─ 1.3  compose.layout     LLM picks skeleton + writes copy; expand() does all geometry
   │
   ├───────► doc.skeleton emitted  ◄── p95 0.3s. The user sees the layout immediately.
   │
   ├─ 1.4  assets             background first, then subjects in parallel
   │                          every generated raster passes the glyph gate
   ├─ 1.5  harmonise          palette · contrast · shadow · colour-match  (all CPU)
   ├─ 1.6  layout.solve       measure → autofit → margins → collisions → optical → snap
   └─ 1.7  assemble           validate, persist, thumbnail
```

**The LLM never invents coordinates.** It chooses a hand-designed skeleton and fills
slots; `expand()` turns normalised slots into pixels deterministically. That is where
layout quality comes from — a curated corpus beats a smarter model.

**The layout does not decide the picture.** A skeleton owns *composition* — which region
stays empty, which angle a subject is seen from, whether a slot is a cutout. It used to
own *subject matter* too: every background prompt in the corpus read "studio backdrop,
soft directional light", so a barber shop, a dental clinic and a sneaker drop were
photographed on the same grey sweep. `art.direct` splits the two. Once per request it
decides the scene, the light, how the subject is rendered and which motif each ornament
family contributes, and the corpus's prompts are now composition with `{{scene}}`,
`{{lighting}}` and `{{treatment}}` holes in them.

So a Diwali greeting is shot on gold leaf over a deep ground under warm lamplight with a
garland across the top; a gym promo on scuffed concrete under hard light with chevrons
and a starburst — **through the same skeleton**. Variety is bounded by the trade rather
than random: a family the trade has one right answer for (a ceremony's garland) gets it
every time, and only the families it has no view on vary between requests. It works with
no API key — a domain table keyed off the words in the brief directs it offline.

**Everything in the request reaches the canvas.** A real business request is rarely one
headline: it carries an offer, a price, a list of services, a phone number and a
website, and often several different things to photograph. Each of those is a field on
the brief and a slot role in the corpus, so "flat 50% off on facial, manicure and spa,
call 98765 43210" produces a discount seal, three distinct generated cutouts, three
feature lines and a contact strip — rather than a headline over one photograph.

Contact details are the one thing never written, only transcribed. Phone numbers,
emails and URLs are pulled out of the prompt by pattern, restored after the model runs
if it dropped them, discarded if the model invented digits that were not in the prompt,
and dropped rather than truncated when they do not fit. A design whose number does not
ring is worse than one with no number on it — it ships looking finished.

---

## Architecture

```
backend/app/
  schema/          DesignDoc, DrawList, brief, template, events  — the contract
  layout/          HarfBuzz shaping, measurement cache, the layout solver
  renderer/        toDrawList (pure) + Skia backend → PNG/JPEG/WebP/PDF/SVG
  adapters/        every model behind a swappable interface (§0.3)
  pipelines/       the Part One orchestrator and per-layer AI operations
  templates_corpus/ the skeleton corpus, its DSL and its validator
  eval/            the §5.3 harness and release gates
  api/             FastAPI routes + WebSocket progress
frontend/src/
  editor/          Konva renderer that replays the server's draw list
  components/      layer panel, inspector
```

### Choices worth knowing about

- **Python everywhere.** The plan specifies Node for the API and orchestrator;
  this is one FastAPI process, with module boundaries that mirror the original
  service split so they can be pulled apart unchanged. See
  [ADR 0001](docs/adr/0001-python-backend.md), which also explains how INV-3 is
  preserved — and in fact strengthened — by that change.
- **Local embeddings.** Template retrieval runs on every request, so it uses
  `sentence-transformers/all-MiniLM-L6-v2` on CPU rather than a hosted embedding
  API: no network hop in the latency budget, no per-request cost. The vector column
  follows the model's dimension and `seed_templates.py` reconciles it if you swap models.
- **Model weights are warmed at startup.** The first sentence-transformer load takes
  ~18 s; paying it on a user's first request would blow the 3 s skeleton budget.

---

## Editing

The editor knows nothing about which pipeline produced a document — it only knows
`DesignDoc`. Select on canvas or in the layer panel, then:

- drag, resize and rotate; arrow keys nudge (shift = 10px)
- double-click text to edit; the solver re-runs on commit, never per keystroke
- **Regenerate** an image layer with a new seed, or **Remove background** to matte it
- **Rewrite** copy with an instruction — selected layers are rewritten together so
  headline and subhead stay one voice
- **Resize** to another format; constraints reflow the layout into a new document
- **Export** PNG/JPEG/WebP/SVG, or **PDF with live text and embedded fonts** — not a
  rasterised page

---

## Testing and evaluation

```bash
make check   # ruff + tsc + 108 tests
make eval    # the §5.3 suite; exits non-zero if any release gate fails
```

The eval runs 24 prompts across all seven design kinds — subject and text-only,
three copy lengths, brand-kit and non-Latin — through the real pipeline and measures
what the user actually receives:

```
  PASS  schema_validity              1.000   (>= 1.0)
  PASS  text_overflow_rate           0.000   (<= 0.0)
  PASS  collision_rate               0.000   (<= 0.02)
  PASS  contrast_pass_rate           1.000   (>= 0.98)
  PASS  safe_margin_pass_rate        1.000   (>= 0.98)
  PASS  glyph_leakage_rate           0.000   (<= 0.01)
  PASS  copy_length_pass_rate        1.000   (>= 0.98)
  PASS  editable_text_rate           1.000   (>= 1.0)
  PASS  p95_skeleton_seconds         0.29s   (<= 3.0)
  PASS  p95_complete_seconds         1.68s   (<= 25.0)
```

Timings above are with stub adapters; real image generation dominates
`p95_complete_seconds` (the 25 s gate is sized for that).

---

## Status against the plan

**Built and verified**

- §0.5–0.6 schema, migrations, coordinate system · §1.1–1.3 brief, retrieval, composer
- §1.4 asset workers incl. the glyph gate · §1.5 harmonisation · §1.6 layout solver
- §0.11 / §4.1 draw list and Skia export (PNG/JPEG/WebP/PDF/SVG) · §4.2 resize
- §0.10 HTTP + WebSocket API · §3 editor · §5 tests and eval harness · §7 first-line safety

**Deliberately not built**

- **§2 decomposition** (image → layers) — out of scope for this build, by request.
- **§3.1 Yjs multiplayer.** The schema and the CRDT dependency are in place; the
  sync server is not. Single-user editing works; concurrent editing would last-write-win.
- **§0.9 durable job queue.** Generation runs as an in-process asyncio task that
  publishes to the same Redis progress bus a worker would. The orchestrator is a plain
  `async` function taking a session and an emitter, so moving it onto `arq` is a
  call-site change plus that dependency — but today a server restart loses in-flight
  requests.

**Known limits**

- The template corpus has **42 skeletons (85 with variants)**; §1.2 asks for 150–300
  for v1. This is the single highest-leverage place to improve output quality, and it
  is design work rather than engineering work — see
  `backend/app/templates_corpus/skeletons.py` and its validator. Every `(kind, aspect)`
  family now carries both a subject-bearing and a text-only layout, which is the
  coverage retrieval actually depends on: `template.retrieve` filters hard on the pair,
  so a hole in that grid returns a layout authored for a different canvas shape rather
  than degrading gracefully. A test asserts the grid stays full. Density is the second
  axis: three of the skeletons are information-dense layouts with slots for an offer, a
  price, a feature list and a contact block, and retrieval prefers them for a brief that
  carries that much. Three is thin — a dense layout per `(kind, aspect)` is the next
  gap worth closing.
- Safety screening (`app/util/safety.py`) is pattern-based and blocks the categories
  §7 names outright. **A production deployment needs a real moderation provider** on
  both prompts and generated images; pattern matching cannot do that job.
- `gpt-image-1` exposes no seed, so INV-2 holds there by content-addressed cache
  rather than by seeded reproduction. Stub adapters are exactly reproducible.
- Upscaling is Lanczos + unsharp; §1.4.4's Real-ESRGAN needs a GPU.

---

## Configuration

All of `backend/.env` (see `.env.example`). Every model is selected by env var, so
swapping a provider never touches pipeline code:

| Variable | Default | Notes |
|---|---|---|
| `ADAPTER_TEXT_TO_IMAGE` | `auto` | `openai` · `stub` |
| `ADAPTER_TRANSPARENT_IMAGE` | `auto` | `openai` · `matte` (generate then cut out) · `stub` |
| `ADAPTER_MATTING` | `auto` | `rembg` (needs `.[localml]`) · `grabcut` |
| `ADAPTER_GLYPH_DETECTOR` | `auto` | `opencv` · `vision`. Never resolves to a no-op while a real image model is active |
| `ADAPTER_EMBEDDER` | `sentence-transformers` | `openai` · `hash` |
| `MAX_COST_CENTS_PER_REQUEST` | `200` | §6.7 budget ceiling |
