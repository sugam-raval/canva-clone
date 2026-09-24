# Lido.js Template Designer

Type a request ("Diwali sale, 30% off, call 98765 43210") and get a finished,
editable Lido.js design: the app picks the best template from `lidojs_templates/`,
writes every text layer, generates every image, and saves the result.

One flow only: **Lido.js (template)**. (The earlier Custom/DesignDoc engine and the
Lido.js scratch flow were removed on 2026-09-24, with their code, tables and stored
files.)

---

## Quick start

Requires Python 3.11+, Node 20+ and Docker.

```bash
make setup     # Python + Node deps, Postgres (pgvector) + MinIO, templates into the database
make dev       # API on :8000, web app on :5173
```

Open <http://localhost:5173>, type a request, press **Generate**. Add your key for real
output (without it the model adapters fall back to stubs):

```bash
echo "OPENAI_API_KEY=sk-..." >> backend/.env
```

`GET /v1/health` reports which model each capability resolved to.

**Upgrading an existing database** (created before this version): `make db-upgrade`
applies every file in `infra/initdb/` — all idempotent. It creates `lido_templates` and
drops the old Custom/scratch tables.

---

## How a request becomes a design

```
 request ──► 1. pick the best template     app/lido_corpus/matcher.py  (lido_templates, pgvector)
          ──► 2. ONE LLM call              every text layer + every image prompt, from the
                                           template's own per-layer metadata
          ──► 3. check the copy            real-font measurement; one repair call if needed
          ──► 4. generate images           transparent cutout or opaque, per layer spec
          ──► 5. fill + save               lido_generations (Postgres), images in MinIO
```

API (`backend/app/api/routes/lido.py`):

| Endpoint | What it does |
|---|---|
| `POST /v1/lido/generate` | request → filled design. `templateId` picks one exactly, `randomTemplate` picks at random, neither = automatic match (explained in `match`) |
| `GET /v1/lido/templates` | every template in the catalog |
| `POST /v1/lido/templates/sync` | mirror `lidojs_templates/*.json` into the database now (`?force=true` re-embeds all) |
| `GET /v1/lido/generations` | generation history, newest first |
| `GET /v1/lido/generations/{id}` | one saved design, to reopen it |

---

## Where things are stored

| What | Where |
|---|---|
| Template files (authoring source) | `lidojs_templates/*.json` — edited by hand and by the enrich script |
| Template catalog + embeddings | Postgres table **`lido_templates`** (pgvector `vector(384)`, HNSW cosine index). `id` is the template's own numeric id, taken from its file name (`template_300.json` -> `300`) — a genuine integer, not a surrogate. |
| Generated designs | Postgres table `lido_generations`. `id` is a plain auto-increment integer (not exposed); `design_key` is the public slug (`tpl-glow-7073edfd`) used in `GET /v1/lido/generations/<id>` and in uploaded images' object-store path. `template_id` is an integer foreign key to `lido_templates.id` (`on delete set null`, so deleting a template keeps the generation record). |
| Generated images | MinIO bucket `design-assets`, under `public/lido-generated/<design_key>/` |

**Files → database.** The JSON files stay the source you edit and review. The API mirrors
them into `lido_templates` at startup and then at most every `LIDO_TEMPLATE_SYNC_SECONDS`
(default 10) on the next request. A new file is added (once it has a `meta` block), a
changed one updated, a deleted one removed. `make lido-sync` does it on demand. If the database is down (or
`LIDO_TEMPLATE_STORE=files`), everything runs from the files in memory.

**Why Postgres + pgvector and not ChromaDB.** Postgres is already running for the
generation history and already has pgvector. Keeping templates, their vectors and the
history in one database means one service, one backup, transactional updates, and
plain SQL joins. At this size (tens to a few thousand templates) pgvector's search is
instant. ChromaDB would add a second store to run and keep in sync, with no gain here.

---

## How a template is picked

Full explanation with worked examples: [`docs/new_match_plan.md`](docs/new_match_plan.md).

1. **Details the user gave** — phone, email, website, address, offer, price, date — found
   with simple patterns and double-checked by one small `LLM_MODEL_FAST` call. A detail
   the model adds only counts if it quotes the exact words from the request.
2. **English topic line** — the same call writes one short English line about the request,
   in any input language (the local embedding model only understands English).
3. **Topic score** — pgvector's cosine similarity between the topic line's embedding and
   each template's stored embedding.
4. **Priority rule** — if any template has a slot for **every** detail the user gave, the
   pick comes from those only, by topic. Otherwise the best
   `0.6 × topic + 0.4 × details held` wins. Both subtract 0.05 per contact slot the user
   left empty (its placeholder would ship on the design).

### What gets embedded, and when it is re-embedded

Each template's embedding is made from its **card** — a few English sentences built from:

| Source | Fields |
|---|---|
| `meta` | `name`, `kind`, `description`, `tags` |
| text slots | the sample text of every text layer, grouped by role (headline, subhead, body, label) |
| detected | detail slots (phone, email, website, address, offer, price, date), buttons, list size, photo count |

A template is re-embedded automatically whenever its **fingerprint** changes. The
fingerprint hashes the **whole `meta` block** (as recomputed from the layers on every
load), the embedding model name and the card format version. So **any** edit to a
template's metadata or to the text in its layers triggers a re-embed on the next sync —
you never need to re-index by hand. Changing `SENTENCE_TRANSFORMER_MODEL` re-embeds
everything (the column is `vector(384)`: a model with another size also needs the column
altered).

```bash
make lido-sync                  # sync changed templates now and print every template's card
make lido-sync FORCE=1          # re-embed every template
backend/.venv/bin/python scripts/lido_match.py show "Diwali sale, 30% off, call 98765 43210"  # explain one pick
backend/.venv/bin/python scripts/lido_match.py test   # run backend/app/lido_corpus/match_cases.jsonl
```

`lido_match.py test` prints every miss with its scores and exits non-zero below 85 %
first-pick accuracy. Add a line to the cases file for each new template.

The embedding model runs locally (`SENTENCE_TRANSFORMER_MODEL`, default
`all-MiniLM-L6-v2`). It is an optional extra that `make install` already installs:

```bash
cd backend && uv pip install --extra-index-url https://download.pytorch.org/whl/cpu -e ".[embed]"
```

Without it, matching still works, with topic falling back to word overlap.

---

## Adding a new template — start to end

All template JSON files live in **`lidojs_templates/`** (one file per template, named
`template_<id>.json`; the file name without `.json` is the template id). The database
table `lido_templates` is filled from this folder — you never edit the table directly.

### The three commands

Each works on **all** templates, or on **one** with `TEMPLATE=template_300`:

| Command | Scope | What it does |
|---|---|---|
| **`make lido-add`** | templates **not yet in the database** — all of them, or `TEMPLATE=x` | draft metadata (only if the template needs it) → verify → add to `lido_templates` with its embedding, in one step. A template already in the database is left completely untouched. |
| **`make lido-meta`** | templates with no metadata yet — all of them, or `TEMPLATE=x` | draft metadata → verify. No database write. |
| **`make lido-sync`** | templates already tracked — all changed ones, or `TEMPLATE=x` | verify → push to `lido_templates` + re-embed. For pushing hand-edits to a template that's already in the database. |

`lido-add` is what you run for a new template — it figures out on its own whether it
needs drafting. Reach for `lido-meta` or `lido-sync` only when you want just one half
(e.g. draft metadata without touching the database yet, or re-sync after a hand-edit).

`FORCE=1`: with `lido-meta` it re-drafts **every** template (still only empty fields);
with `lido-sync` it re-embeds even unchanged templates. `lido-add` never needs `FORCE=1`
— by definition it only ever touches templates the database doesn't have yet.

**Batch behaviour of `lido-add`:** every new template is checked independently. One that
fails verification is skipped and reported — it does **not** stop the others in the same
run from being added.

**Verification** (`lido-add`, `lido-meta`, `lido-sync` all run it). It checks every rule
of the metadata rules that can be checked in code, and **an error blocks that template
from the database**:

| Error (blocks the sync) | Warning (for your review) |
|---|---|
| no `meta` block yet | `tags` empty |
| `name` or `description` empty | a text slot has no `notes` |
| background image but no background prompt | background prompt doesn't forbid text |
| a photo frame with no image spec, or a spec with no prompt | no `reference_note` yet |
| logo not locked / would be regenerated | |
| a text slot with no `max_chars` | |
| the template's own text breaks its own limits (real font) | |

### Step by step

**1. Drop the file in.** Save the raw Lido.js export as
`lidojs_templates/template_300.json` (format `[{"layers": {...}}]`, no `meta` needed —
but a file with full hand-written `meta` already works too, e.g. one promoted from
elsewhere). Until its id is in the database it's ignored by matching.

**2. Run one command.**

```bash
make lido-add TEMPLATE=template_300      # or just `make lido-add` for every template
                                         # not yet in the database
```

For each template it's given, `lido-add` first checks whether it already verifies
cleanly. If it does (e.g. a file that already has complete, hand-written metadata), it's
added to `lido_templates` with its embedding straight away — no model calls. If it
doesn't (usually because it has no `meta` yet), the LLM and vision model draft the
missing fields first (name, kind, tags, description, slot roles, background and photo
prompts, logo lock, text notes and limits), it's verified again, and only then added.
A template whose id is already in the database is reported and left alone; in batch
mode, one that still fails verification is skipped and reported — it doesn't stop the
rest of the batch.

**3. Review the draft by hand.** An automatic draft is a strong start, not a guarantee —
being in the database only means it passed the *mechanical* checks, not a human review.
Open the file and check the `meta` block against
[`docs/TEMPLATE_METADATA_RULES.md`](docs/TEMPLATE_METADATA_RULES.md) and the
reference example `template_227.json`. The draft gets these wrong most often:
- the **background prompt** — compare it with the actual background picture (the image
  model can miss elements, e.g. a photo panel that is part of the background);
- **name / tags / description** — they must say what the template is *for*
  ("interior design", not only "sale"); matching reads them;
- **photo frames** — transparent cutout vs. an ordinary photo that fills its frame.

**4. Mark it reviewed** by adding `meta.reference_note` (see the rules file). It shows as
`ready` in `GET /v1/lido/templates`.

**5. Push your edits.** The template is already in the database after step 2, so from
here on it's an *existing* template — use `lido-sync`, not `lido-add`:

```bash
make lido-sync TEMPLATE=template_300     # verify + re-embed (only if the meta changed)
```

If the API is running you can skip this: it re-checks the folder every
`LIDO_TEMPLATE_SYNC_SECONDS` (default 10) and at startup. The API does **not** verify, so
run `make lido-sync` after hand edits to catch mistakes.

**6. (Recommended) test matching.** Add one or two example requests for it to
`backend/app/lido_corpus/match_cases.jsonl`, then:

```bash
backend/.venv/bin/python scripts/lido_match.py show "a request this template should win"
backend/.venv/bin/python scripts/lido_match.py test
```

**Later edits** (to a template already in the database): edit the JSON file, then
`make lido-sync TEMPLATE=...`. To re-draft a field the script filled, empty it and run
`make lido-meta TEMPLATE=...` (it only fills empty fields) — or just run
`make lido-add TEMPLATE=...` again, which does nothing since the id is already tracked
(fix the field by hand instead, or drop it from the database first with
`docker exec ... psql ... -c "delete from lido_templates where id=300"` if
you really want it redrafted from scratch). **Removing a template:** delete its file,
then `make lido-sync`.

### What the enrich script drafts

| Field | How |
|---|---|
| name, kind, tags, description | one LLM call over the template's text slots |
| slot roles | computed on every load from type tags and sample text: the largest text is the headline; websites, phones and emails are recognised from their text; logos from their type or logo image file; text is never "decoration" |
| background prompt + notes | vision model reads the background, plus layout facts computed from the layers (text colour and position, photo frames that must stay empty) |
| photo frames | vision-drafted prompt; a transparent cutout only if the template's own sample image is transparent, otherwise an opaque photo that fills its frame |
| logo | locked, never regenerated (no LLM) |
| text notes, max_chars, max_lines | one batched LLM call, floored so the template's own copy always fits (measured with the real font and the layer's scale) |

Image reading uses `LIDO_ENRICH_VISION_MODEL` (default `gpt-4o`), falling back to
`LLM_MODEL_FAST`. Other enrich flags: `--force` (recompute, keeping hand-authored fields),
`--no-llm`, `--dir path/`, `--check` (exit 1 if any template has no `meta`).

---

## Project layout

```
backend/app/
  api/            FastAPI app, the /v1/lido routes, request/response models
  lido_corpus/    loader, matcher (details, match_index, store), fill (generate_ai),
                  images (assets_ai), compose, text measurement (textfit)
  adapters/       OpenAI image + LLM adapters, stubs, local embedding model
  db/             SQL for lido_templates and lido_generations
  storage/        MinIO/S3 (or local folder) uploads
  util/           prompt safety screen
backend/tests/    offline test suite (no database, no model calls)
frontend/src/     one page: request → design, match explanation, history
infra/            docker-compose (Postgres + pgvector, MinIO) and initdb SQL
lidojs_templates/ the template JSON files
scripts/          enrich_lido_templates.py (metadata), lido_match.py (sync, match tests)
docs/             TEMPLATE_METADATA_RULES.md, new_match_plan.md, plan.md
test/             your personal scratch files — git-ignored, never committed
```

---

## Testing

```bash
make test      # backend tests — offline: no database, no model calls
make lint      # ruff + TypeScript
```

Tests run with `LIDO_TEMPLATE_STORE=files`, so they never touch the real
`lido_templates` table.

---

## Configuration

All in `backend/.env` (see `backend/.env.example`).

| Variable | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | — | required for real output |
| `LLM_MODEL` / `LLM_REASONING_EFFORT` | `gpt-6-astra` / `low` | the main fill call |
| `LLM_MODEL_FAST` | `gpt-4o-mini` | repair call and the request profile for matching |
| `IMAGE_MODEL` | `gpt-image-2.5-sunburst` | image generation |
| `LIDO_TEMPLATE_IMAGE_QUALITY` | `high` | `low` · `medium` · `high` |
| `LIDO_ENRICH_VISION_MODEL` | `gpt-4o` | reads backgrounds/photos in `make lido-meta` / `make lido-add` |
| `SENTENCE_TRANSFORMER_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | template embeddings (384 numbers) |
| `LIDO_TEMPLATE_STORE` | `db` | `db` (Postgres) · `files` (in memory) |
| `LIDO_TEMPLATE_SYNC_SECONDS` | `10` | how often a request re-checks the files |
| `DATABASE_URL` | local Postgres on :5442 | |
| `S3_*`, `S3_PUBLIC_BASE_URL` | local MinIO on :9010 | where generated images go |
| `ADAPTER_TEXT_TO_IMAGE` / `ADAPTER_TRANSPARENT_IMAGE` / `ADAPTER_LLM` | `auto` | `openai` · `stub` |
