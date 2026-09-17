# Implementation Plan — AI Layered Design Generator & Image Decomposer

**Audience:** an AI coding agent (or engineer) implementing this end to end.
**Deliverable:** a Canva-style system where (A) a text prompt produces a fully
editable multi-layer design, and (B) an uploaded flat image is decomposed into
separate editable layers. Both produce the *same* document format and open in the
*same* editor.

Read Section 0 fully before writing any code. It defines the contracts every
other section depends on. Do not change the document schema after M2 without a
migration.

---

## Table of contents

- [0. Foundations](#0-foundations)
  - [0.1 Product scope](#01-product-scope)
  - [0.2 Core architectural principle](#02-core-architectural-principle)
  - [0.3 Tech stack](#03-tech-stack)
  - [0.4 Repository layout](#04-repository-layout)
  - [0.5 The document schema](#05-the-document-schema)
  - [0.6 Coordinate system and transforms](#06-coordinate-system-and-transforms)
  - [0.7 Database schema](#07-database-schema)
  - [0.8 Asset storage conventions](#08-asset-storage-conventions)
  - [0.9 Job queue and event contracts](#09-job-queue-and-event-contracts)
  - [0.10 HTTP + WebSocket API surface](#010-http--websocket-api-surface)
  - [0.11 Render parity contract](#011-render-parity-contract)
- [1. Part One — prompt to editable composition](#1-part-one--prompt-to-editable-composition)
- [2. Part Two — flat image to editable layers](#2-part-two--flat-image-to-editable-layers)
- [3. The editor](#3-the-editor)
- [4. Export and resize](#4-export-and-resize)
- [5. Quality, evals, and testing](#5-quality-evals-and-testing)
- [6. Cost, caching, and performance](#6-cost-caching-and-performance)
- [7. Safety and abuse](#7-safety-and-abuse)
- [8. Milestones and definition of done](#8-milestones-and-definition-of-done)
- [9. Agent task checklist](#9-agent-task-checklist)

---

# 0. Foundations

## 0.1 Product scope

**In scope**

1. Prompt → editable design (poster, social post, story, ad, thumbnail, banner).
2. Upload flat raster image → decomposed editable layers.
3. Editor: move, resize, rotate, restyle, retype, regenerate any single layer.
4. Per-layer AI operations: regenerate, restyle, remove background, expand
   (outpaint), erase (inpaint), rewrite copy.
5. Export PNG / JPEG / PDF / SVG at arbitrary scale.
6. Resize a design to another canvas size with constraint-based reflow.

**Out of scope for v1**

- Video, animation, multi-page documents (schema leaves room; do not build).
- Real-time multiplayer cursors (CRDT is in from day one, presence is not).
- 3D layers, mesh warp, custom font upload.

**Non-goals — explicitly do not do these**

- Do not generate a flat image and then segment it in order to produce Part One
  output. That is Part Two's job and it is lossy. Part One composes structure
  first.
- Do not render text into pixels anywhere in the generation path.

## 0.2 Core architectural principle

> **Structure first, pixels second. Layers are editable because they were never
> merged.**

Every generated design begins life as a JSON scene graph with empty asset slots.
Assets are generated *per slot* and attached. The renderer composites at view
time and at export time — never destructively.

Three invariants the agent must enforce with tests:

- **INV-1 (text is text):** no layer of `type: "text"` may ever be replaced by a
  raster. Image prompts must include negative text terms, and generated images
  must pass a glyph detector.
- **INV-2 (reproducibility):** every asset layer stores the exact parameters that
  produced it (`model`, `prompt`, `negativePrompt`, `seed`, `params`). Re-running
  them must reproduce the asset byte-for-byte where the provider supports seeds.
- **INV-3 (render parity):** client canvas render and server export render of the
  same document must agree within a fixed perceptual threshold. Enforced by a
  golden-image test suite.

## 0.3 Tech stack

Chosen for a small team shipping fast. Alternatives listed; the agent should not
substitute without recording the decision in `docs/adr/`.

| Layer | Choice | Alternative |
|---|---|---|
| Web app | TypeScript, React, Vite | Next.js |
| Canvas engine | Konva (react-konva) | Fabric.js, PixiJS, Skia-wasm |
| Doc state / undo / sync | Yjs (`Y.Doc`, `y-websocket`) | Automerge |
| API | Node 20, Fastify, tRPC or REST + Zod | NestJS |
| Queue | BullMQ on Redis | Temporal, SQS |
| DB | Postgres 16 + `pgvector` | Postgres + Qdrant |
| Object storage | S3-compatible (S3 / R2 / MinIO) | GCS |
| ML workers | Python 3.11, FastAPI, PyTorch, `diffusers` | Replicate / Fal hosted |
| Server-side raster export | Skia via `@napi-rs/canvas`, or headless Chromium | node-canvas |
| SVG rasterisation | `resvg` | librsvg |
| LLM | Any tool-calling model with JSON-schema-constrained output | — |
| Text measurement | `harfbuzzjs` + `opentype.js` (shared client/server) | browser-only measure |

**Model roles.** Treat every model as a swappable adapter behind an interface.
Do not hardcode a vendor. Required capabilities, with the family that provides
them (verify current best-in-class at implementation time — this list ages fast):

| Capability | Adapter interface | Model family |
|---|---|---|
| Text→image | `TextToImage` | SDXL / Flux-class latent diffusion |
| Text→image with alpha | `TransparentImage` | LayerDiffuse-style transparent-latent LoRA |
| Background removal / matting | `Matting` | BiRefNet, RMBG, ViTMatte (trimap) |
| Instance segmentation (promptable) | `Segmenter` | SAM-family (points/box prompts) |
| Open-vocabulary detection | `Detector` | Grounding-DINO-class |
| Inpainting / outpainting | `Inpainter` | SD-inpaint / Flux-fill-class |
| Depth estimation | `DepthEstimator` | Depth-Anything-class monocular depth |
| OCR + text detection | `TextRecognizer` | PaddleOCR, DocTR, or cloud OCR |
| Raster→vector | `Vectorizer` | VTracer, potrace |
| Upscale | `Upscaler` | Real-ESRGAN-class |
| Glyph presence check | `GlyphDetector` | reuse the text detector above |
| Embeddings (template search) | `Embedder` | any 768–1536-d text embedder |

Each adapter lives in `packages/ml-adapters/` with a local implementation and a
hosted implementation, selected by env var. **Ship hosted first**, self-host
later; do not block Part One on GPU provisioning.

## 0.4 Repository layout

```
/apps
  web/                 React editor + generation UI
  api/                 Fastify API, auth, docs CRUD, job dispatch
  sync/                y-websocket server (CRDT rooms)
  render/              server-side render + export service
/services
  orchestrator/        Node: pipeline state machines (Part One & Part Two)
  ml-gateway/          Python FastAPI: routes to model adapters, batching
  workers/             Python BullMQ consumers: one module per asset job type
/packages
  doc-schema/          TS types + Zod + JSON Schema + migrations  (SOURCE OF TRUTH)
  layout-engine/       text measurement, autofit, constraints, collision solver
  renderer-core/       pure scene-graph → draw-command list (client+server share)
  ml-adapters/         model adapter interfaces + impls
  template-corpus/     skeleton templates + tags + seed script
  eval/                eval harness, golden images, scoring
/docs
  adr/                 architecture decision records
  IMPLEMENTATION_PLAN.md
```

`packages/doc-schema` and `packages/layout-engine` must have **zero DOM and zero
Node-only dependencies** so both browser and server import them unchanged. This
is what makes INV-3 achievable.

## 0.5 The document schema

This is the single most important artifact in the project. Write it first.

`packages/doc-schema/src/types.ts`:

```ts
export type DocId = string;
export type LayerId = string;

export interface DesignDoc {
  id: DocId;
  schemaVersion: 3;                 // bump + migration on any breaking change
  title: string;
  canvas: Canvas;
  layers: Layer[];                  // paint order: index 0 = bottom
  palette: string[];                // hex, extracted or brand-provided
  fonts: FontRef[];                 // every font referenced by text layers
  provenance: Provenance;           // how this doc came to exist
  createdAt: string;                // ISO
  updatedAt: string;
}

export interface Canvas {
  width: number;                    // px at scale 1
  height: number;
  background: string;               // hex or 'transparent'
  safeMargin: number;               // px; layout solver keeps content inside
  dpi: number;                      // 72 screen, 300 print
}

export interface FontRef {
  family: string;
  weights: number[];
  source: 'google' | 'system' | 'hosted';
  url?: string;                     // for 'hosted'
}

export type Provenance =
  | { kind: 'generated'; brief: DesignBrief; templateId: string; requestId: string }
  | { kind: 'decomposed'; sourceAssetId: string; pipelineVersion: string;
      confidence: number }
  | { kind: 'blank' }
  | { kind: 'duplicated'; fromDocId: DocId };
```

### Layer union

```ts
export type Layer =
  | ImageLayer | TextLayer | ShapeLayer | SvgLayer | GroupLayer;

export interface BaseLayer {
  id: LayerId;
  name: string;                     // shown in the layer panel
  role: LayerRole;                  // semantic slot — drives AI ops & resize
  frame: Frame;                     // geometry
  opacity: number;                  // 0..1
  blendMode: BlendMode;
  visible: boolean;
  locked: boolean;
  clipToParent?: boolean;
  effects: Effect[];
  constraints: Constraints;         // for resize-to-other-format
  meta: LayerMeta;
}

export type LayerRole =
  | 'background' | 'subject' | 'object' | 'decoration'
  | 'headline' | 'subhead' | 'body' | 'cta' | 'caption'
  | 'logo' | 'badge' | 'overlay' | 'unknown';

export interface Frame {
  x: number; y: number;             // top-left in canvas px
  w: number; h: number;
  rotation: number;                 // degrees, clockwise, about the frame centre
  flipX?: boolean; flipY?: boolean;
}

export type BlendMode =
  | 'normal' | 'multiply' | 'screen' | 'overlay' | 'soft-light' | 'darken'
  | 'lighten' | 'color-dodge' | 'difference';

export interface LayerMeta {
  /** Everything needed to regenerate this layer's pixels. INV-2. */
  generation?: GenerationParams;
  /** For decomposed docs: how this layer was found. */
  extraction?: ExtractionInfo;
  /** Free-form, never load-bearing for rendering. */
  notes?: Record<string, unknown>;
}

export interface GenerationParams {
  adapter: string;                  // 'TextToImage' | 'TransparentImage' | ...
  model: string;
  prompt: string;
  negativePrompt?: string;
  seed: number;
  params: Record<string, number | string | boolean>;
  producedAt: string;
}
```

### Image layer

```ts
export interface ImageLayer extends BaseLayer {
  type: 'image';
  assetId: string;                  // resolves to a URL via the asset service
  hasAlpha: boolean;
  naturalSize: { w: number; h: number };
  fit: 'fill' | 'cover' | 'contain';
  /** Crop within the source image, normalised 0..1. */
  crop?: { x: number; y: number; w: number; h: number };
  /** Non-destructive colour adjustments applied at render time. */
  adjust?: Adjustments;
  /**
   * Decomposition only: the inpainted plate that sits behind this layer, so
   * moving it does not reveal a hole. Rendered by the layer directly below in
   * the same `occlusionGroup`, or by the background.
   */
  backPlateAssetId?: string;
  occlusionGroup?: string;
}

export interface Adjustments {
  brightness?: number;  // -1..1
  contrast?: number;
  saturation?: number;
  temperature?: number; // -1 cool .. 1 warm  — used by harmonisation
  hueRotate?: number;   // degrees
}
```

### Text layer — never rasterised

```ts
export interface TextLayer extends BaseLayer {
  type: 'text';
  content: string;                  // may contain \n
  fontFamily: string;
  fontWeight: number;
  fontStyle: 'normal' | 'italic';
  fontSize: number;                 // px, may be rewritten by autofit
  lineHeight: number;               // multiplier
  letterSpacing: number;            // px
  align: 'left' | 'center' | 'right';
  verticalAlign: 'top' | 'middle' | 'bottom';
  color: string;
  textTransform?: 'none' | 'uppercase' | 'capitalize';
  /** Solver may shrink/grow fontSize within these bounds to fit `frame`. */
  autoFit?: { min: number; max: number; mode: 'shrink' | 'shrink-grow' };
  /** If true, frame height follows content instead of clipping it. */
  autoHeight?: boolean;
  stroke?: { color: string; width: number };
  /** Set by harmonisation when the underlying region is busy. */
  backdrop?: { color: string; opacity: number; padding: number; radius: number };
}
```

### Shape, SVG, group

```ts
export interface ShapeLayer extends BaseLayer {
  type: 'shape';
  shape: 'rect' | 'ellipse' | 'line' | 'polygon' | 'path';
  fill?: string;                    // hex or 'none'
  stroke?: { color: string; width: number; dash?: number[] };
  radius?: number;                  // rect corner radius; 999 => pill
  points?: number[];                // polygon/line
  pathData?: string;                // SVG path 'd' for shape:'path'
}

export interface SvgLayer extends BaseLayer {
  type: 'svg';
  assetId: string;                  // stored .svg
  /** Recolour by mapping original fills to new ones. */
  colorMap?: Record<string, string>;
  preserveAspect: boolean;
}

export interface GroupLayer extends BaseLayer {
  type: 'group';
  children: Layer[];                // nested; transforms compose
}
```

### Effects and resize constraints

```ts
export type Effect =
  | { kind: 'shadow'; dx: number; dy: number; blur: number;
      color: string; opacity: number; spread?: number }
  | { kind: 'blur'; radius: number }
  | { kind: 'stroke'; color: string; width: number }   // outline for cutouts
  | { kind: 'glow'; color: string; radius: number; opacity: number };

/**
 * Drives resize-to-other-format. Each axis is pinned, centred, or scaled.
 * Layout solver reads these; the editor exposes them in an inspector.
 */
export interface Constraints {
  horizontal: 'left' | 'right' | 'center' | 'scale' | 'stretch';
  vertical: 'top' | 'bottom' | 'middle' | 'scale' | 'stretch';
  /** Keep w/h ratio when scaling. Always true for image subjects. */
  lockAspect: boolean;
  /** Layer may be dropped entirely if the target canvas is too small. */
  optional?: boolean;
  /** Lower z-importance layers are dropped first when space runs out. */
  priority: number;                 // 0 (drop first) .. 100 (never drop)
}
```

### Worked example

A generated product post. Note: real text layers, a transparent-PNG subject,
a stored back-plate, and full generation params.

```json
{
  "id": "doc_9f2",
  "schemaVersion": 3,
  "title": "Run Lighter — story",
  "canvas": { "width": 1080, "height": 1920, "background": "#0F172A",
              "safeMargin": 72, "dpi": 72 },
  "palette": ["#0F172A", "#F5B700", "#FFFFFF"],
  "fonts": [{ "family": "Inter", "weights": [400, 700, 900], "source": "google" }],
  "provenance": { "kind": "generated", "templateId": "tpl_story_hero_02",
                  "requestId": "req_771", "brief": { "...": "..." } },
  "layers": [
    {
      "id": "l_bg", "type": "image", "name": "Background", "role": "background",
      "assetId": "as_bg_1", "hasAlpha": false,
      "naturalSize": { "w": 1088, "h": 1920 }, "fit": "cover",
      "frame": { "x": 0, "y": 0, "w": 1080, "h": 1920, "rotation": 0 },
      "opacity": 1, "blendMode": "normal", "visible": true, "locked": false,
      "effects": [],
      "constraints": { "horizontal": "stretch", "vertical": "stretch",
                       "lockAspect": false, "priority": 100 },
      "meta": { "generation": {
        "adapter": "TextToImage", "model": "t2i-v1",
        "prompt": "moody navy gradient studio backdrop, soft top-left light, empty floor, no text",
        "negativePrompt": "text, letters, words, watermark, logo, signature, ui",
        "seed": 88121, "params": { "steps": 28, "cfg": 4.5, "ar": "9:16" },
        "producedAt": "2026-09-10T09:12:04Z" } }
    },
    {
      "id": "l_shoe", "type": "image", "name": "Product", "role": "subject",
      "assetId": "as_shoe_rgba", "hasAlpha": true,
      "naturalSize": { "w": 1400, "h": 1100 }, "fit": "contain",
      "frame": { "x": 120, "y": 880, "w": 840, "h": 660, "rotation": -6 },
      "opacity": 1, "blendMode": "normal", "visible": true, "locked": false,
      "effects": [{ "kind": "shadow", "dx": 0, "dy": 26, "blur": 48,
                    "color": "#000000", "opacity": 0.32 }],
      "adjust": { "temperature": -0.08 },
      "constraints": { "horizontal": "center", "vertical": "middle",
                       "lockAspect": true, "priority": 95 },
      "meta": { "generation": {
        "adapter": "TransparentImage", "model": "t2i-alpha-v1",
        "prompt": "white and amber running shoe, three-quarter view, studio lighting, transparent background",
        "negativePrompt": "text, watermark, background, floor, shadow",
        "seed": 4410, "params": { "steps": 30, "cfg": 5 },
        "producedAt": "2026-09-10T09:12:19Z" } }
    },
    {
      "id": "l_head", "type": "text", "name": "Headline", "role": "headline",
      "content": "Run\nLighter", "fontFamily": "Inter", "fontWeight": 900,
      "fontStyle": "normal", "fontSize": 148, "lineHeight": 0.98,
      "letterSpacing": -4, "align": "left", "verticalAlign": "top",
      "color": "#FFFFFF", "textTransform": "uppercase",
      "autoFit": { "min": 72, "max": 168, "mode": "shrink" },
      "frame": { "x": 72, "y": 220, "w": 780, "h": 330, "rotation": 0 },
      "opacity": 1, "blendMode": "normal", "visible": true, "locked": false,
      "effects": [],
      "constraints": { "horizontal": "left", "vertical": "top",
                       "lockAspect": false, "priority": 90 },
      "meta": {}
    },
    {
      "id": "l_cta_bg", "type": "shape", "name": "CTA pill", "role": "cta",
      "shape": "rect", "fill": "#F5B700", "radius": 999,
      "frame": { "x": 72, "y": 1660, "w": 420, "h": 108, "rotation": 0 },
      "opacity": 1, "blendMode": "normal", "visible": true, "locked": false,
      "effects": [],
      "constraints": { "horizontal": "left", "vertical": "bottom",
                       "lockAspect": false, "priority": 80 },
      "meta": {}
    }
  ],
  "createdAt": "2026-09-10T09:12:00Z",
  "updatedAt": "2026-09-10T09:12:31Z"
}
```

### Validation and migration

- Author Zod schemas alongside the types; export a generated JSON Schema
  (`zod-to-json-schema`) — the LLM composer is constrained against **that exact
  file**, so drift is impossible.
- `validateDoc(doc): Result<DesignDoc, DocError[]>` runs on every write.
- `migrate(doc)` handles `schemaVersion` upgrades. Keep migrations pure and
  tested with fixture documents in `packages/doc-schema/fixtures/`.

## 0.6 Coordinate system and transforms

- Origin top-left, y down, units = canvas px at `scale = 1`.
- `rotation` is degrees clockwise about the frame **centre**.
- Group transforms compose: child frame is relative to the group's frame origin,
  and the group's rotation applies to the whole subtree.
- Implement once, in `packages/renderer-core`:

```ts
export function localToWorld(layer: Layer, ancestors: GroupLayer[]): Matrix2D;
export function worldBounds(layer: Layer, ancestors: GroupLayer[]): Rect; // AABB
export function hitTest(doc: DesignDoc, point: Point): LayerId | null;
```

Never duplicate transform math in the editor or the exporter. Both call these.

## 0.7 Database schema

```sql
create extension if not exists vector;

create table users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  created_at timestamptz default now()
);

create table brand_kits (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  name text not null,
  palette jsonb not null default '[]',      -- ["#0F172A", ...]
  fonts jsonb not null default '[]',        -- FontRef[]
  logo_asset_id uuid,
  tone text                                  -- "confident, minimal"
);

create table documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  title text not null default 'Untitled',
  schema_version int not null,
  doc jsonb not null,                        -- last materialised DesignDoc
  ydoc bytea,                                -- Yjs state vector snapshot
  thumb_asset_id uuid,
  provenance jsonb not null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index on documents (user_id, updated_at desc);

create table assets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete set null,
  kind text not null,                        -- 'image'|'svg'|'upload'|'backplate'|'mask'
  storage_key text not null,                 -- s3 key
  mime text not null,
  width int, height int,
  has_alpha bool default false,
  bytes bigint,
  -- INV-2 + cache key
  gen_hash text,                             -- sha256 of canonical GenerationParams
  gen_params jsonb,
  created_at timestamptz default now()
);
create unique index on assets (gen_hash) where gen_hash is not null;

create table jobs (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null,
  doc_id uuid references documents(id) on delete cascade,
  layer_id text,
  type text not null,                        -- see 0.9
  state text not null default 'queued',      -- queued|running|done|failed|skipped
  attempts int default 0,
  input jsonb not null,
  output jsonb,
  error text,
  started_at timestamptz, finished_at timestamptz
);
create index on jobs (request_id);

create table templates (
  id text primary key,                       -- 'tpl_story_hero_02'
  name text not null,
  kind text not null,                        -- 'story'|'post'|'poster'|'banner'|'thumbnail'
  aspect text not null,                      -- '9:16'
  tags text[] not null default '{}',         -- ['minimal','product','high-contrast']
  skeleton jsonb not null,                   -- TemplateSkeleton (see 1.2)
  description text not null,                 -- what it is good for; embedded
  embedding vector(1536),
  quality_score real default 0.5,            -- updated from user acceptance
  usage_count bigint default 0
);
create index on templates using ivfflat (embedding vector_cosine_ops);

create table generation_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  prompt text not null,
  brief jsonb,
  chosen_template_id text references templates(id),
  doc_id uuid references documents(id),
  state text not null default 'parsing',
  cost_cents int default 0,
  created_at timestamptz default now()
);
```

## 0.8 Asset storage conventions

```
assets/{userId}/{assetId}/original.{ext}      # canonical, lossless where possible
assets/{userId}/{assetId}/w{512|1024|2048}.webp
assets/{userId}/{assetId}/mask.png            # 8-bit alpha, decomposition
assets/{userId}/{assetId}/backplate.webp      # inpainted plate
docs/{docId}/thumb.webp
```

Rules:

- Layers reference `assetId`, never a URL. The asset service resolves to a signed
  URL plus a size ladder; this keeps documents portable and CDN-swappable.
- Alpha assets are stored as PNG or lossless WebP. **Never JPEG an alpha asset** —
  it destroys the matte edge.
- Derivatives are generated lazily on first request and cached.
- Every generated asset gets `gen_hash = sha256(canonicalJson(GenerationParams))`
  and the unique index makes identical requests free (see §6).

## 0.9 Job queue and event contracts

One BullMQ queue per resource class so GPU work cannot starve cheap work:

`q.llm`, `q.image`, `q.image-alpha`, `q.matting`, `q.inpaint`, `q.segment`,
`q.ocr`, `q.vector`, `q.render`, `q.export`.

Job types (`jobs.type`):

```
# Part One
brief.parse            template.retrieve      compose.layout
asset.background       asset.subject          asset.object
asset.icon             asset.upscale
harmonize.palette      harmonize.contrast     harmonize.shadow
layout.solve           doc.assemble           doc.thumbnail

# Part Two
decompose.preprocess   decompose.text-detect  decompose.ocr
decompose.detect       decompose.segment      decompose.depth-order
decompose.matte        decompose.inpaint      decompose.vectorize
decompose.font-match   decompose.assemble

# Editing
layer.regenerate       layer.restyle          layer.remove-bg
layer.expand           layer.erase            copy.rewrite
export.render
```

Every job envelope is identical:

```ts
export interface JobEnvelope<I = unknown> {
  jobId: string;
  requestId: string;               // groups all jobs for one user action
  docId: string;
  layerId?: string;
  type: JobType;
  input: I;
  idempotencyKey: string;          // = gen_hash where applicable
  attempt: number;
  deadlineAt: string;
}
```

Progress is published to Redis pub/sub on channel `progress:{requestId}` and
fanned out over WebSocket:

```ts
export type ProgressEvent =
  | { t: 'request.started'; requestId: string; plan: JobType[] }
  | { t: 'brief.ready'; brief: DesignBrief }
  | { t: 'doc.skeleton'; doc: DesignDoc }          // placeholders, render NOW
  | { t: 'job.started'; jobId: string; type: JobType; layerId?: string }
  | { t: 'layer.patch'; layerId: string; patch: Partial<Layer> }  // asset arrived
  | { t: 'job.failed'; jobId: string; type: JobType; recoverable: boolean }
  | { t: 'doc.solved'; doc: DesignDoc }            // after layout solve
  | { t: 'request.done'; docId: string; costCents: number }
  | { t: 'request.failed'; reason: string };
```

**Progressive delivery is a hard requirement.** `doc.skeleton` must reach the
client in under 3 s. The user watches placeholders fill in. Do not wait for all
assets before showing anything.

Retry policy: 3 attempts, exponential backoff (2 s, 8 s, 30 s). On final failure,
substitute a graceful fallback (solid colour from palette for a background,
drop an `optional` decoration, keep text) and mark the layer
`meta.notes.degraded = true`. **A partial design always beats an error page.**

## 0.10 HTTP + WebSocket API surface

```
POST   /v1/generate                 { prompt, kind?, size?, brandKitId?, count? }
                                    -> { requestId, docIds[] }
GET    /v1/requests/:id             -> state + job graph
WS     /v1/progress?requestId=      -> ProgressEvent stream

POST   /v1/uploads                  multipart -> { assetId }
POST   /v1/decompose                { assetId, mode: 'auto'|'guided' }
                                    -> { requestId, docId }
POST   /v1/decompose/:id/hint       { kind:'add'|'split'|'merge'|'drop',
                                      points?, box?, layerIds? }

GET    /v1/docs/:id                 -> DesignDoc
PATCH  /v1/docs/:id                 JSON-patch (non-CRDT clients / server ops)
WS     /v1/sync/:docId              Yjs room

POST   /v1/docs/:id/layers/:lid/regenerate   { promptOverride?, seed?, strength? }
POST   /v1/docs/:id/layers/:lid/remove-bg
POST   /v1/docs/:id/layers/:lid/expand       { edges:{l,r,t,b}, prompt? }
POST   /v1/docs/:id/layers/:lid/erase        { maskAssetId | brushPath }
POST   /v1/docs/:id/copy/rewrite             { layerIds[], instruction }

POST   /v1/docs/:id/resize          { width, height } -> new docId
POST   /v1/docs/:id/export          { format:'png'|'jpeg'|'pdf'|'svg', scale }
                                    -> { exportId }
GET    /v1/exports/:id              -> signed URL
```

All request/response bodies validated with the same Zod schemas the LLM is
constrained against.

## 0.11 Render parity contract

`packages/renderer-core` exports a **pure** function:

```ts
export function toDrawList(doc: DesignDoc, opts: { scale: number }): DrawCommand[];

export type DrawCommand =
  | { op: 'clear'; color: string }
  | { op: 'saveTransform'; matrix: Matrix2D }
  | { op: 'restore' }
  | { op: 'image'; assetUrl: string; dest: Rect; crop?: Rect;
      opacity: number; blend: BlendMode; adjust?: Adjustments }
  | { op: 'textRun'; runs: PositionedGlyphRun[]; color: string; ... }
  | { op: 'path'; d: string; fill?: string; stroke?: Stroke }
  | { op: 'effect'; effect: Effect; targetIndexRange: [number, number] };
```

- Two thin backends consume the same list: `renderer-konva` (browser) and
  `renderer-skia` (server, `@napi-rs/canvas`).
- Text is laid out **once** by `layout-engine` using HarfBuzz, producing
  `PositionedGlyphRun[]` (glyph ids + advances). Both backends draw the same
  glyph positions. This is the only way to get identical text between browser
  and server.
- **Test:** for every fixture doc, render client (Playwright) and server, compare
  with SSIM. Fail CI below 0.995. Add a fixture for each new effect or layer type.

---

# 1. Part One — prompt to editable composition

Pipeline: **parse → retrieve → compose → generate assets → harmonise → solve →
assemble**. Stages 1–3 are cheap and sequential. Stage 4 is expensive and
parallel. Stages 5–6 are deterministic code, not AI.

```
prompt
  └─> 1.1 brief.parse            (LLM, ~1s)
        └─> 1.2 template.retrieve (pgvector, ~50ms)
              └─> 1.3 compose.layout (LLM + JSON schema, ~3s)
                    ├─> emit doc.skeleton to client  ◀── user sees layout here
                    └─> 1.4 asset.* jobs (parallel, GPU, 4–20s)
                          └─> 1.5 harmonise.*  (CPU, <1s)
                                └─> 1.6 layout.solve (CPU, <100ms)
                                      └─> 1.7 doc.assemble + thumbnail
```

## 1.1 Intent parser → DesignBrief

**Job:** `brief.parse`. Turn a messy human prompt plus optional brand kit into a
strict brief. This is the only stage allowed to ask the user a question.

```ts
export interface DesignBrief {
  kind: 'story' | 'post' | 'poster' | 'banner' | 'thumbnail' | 'ad' | 'flyer';
  canvas: { width: number; height: number };
  subjectDescription: string | null;   // null => text-only / abstract design
  copy: {
    headline?: string;
    subhead?: string;
    body?: string;
    cta?: string;
    caption?: string;
  };
  mood: string[];                      // ['minimal','premium','high-contrast']
  colorDirection: {
    mode: 'brand' | 'from-prompt' | 'auto';
    palette?: string[];
  };
  typography: { vibe: 'geometric' | 'humanist' | 'serif-editorial' | 'display-bold';
                familyHint?: string };
  layoutHints: {
    subjectPlacement?: 'left' | 'right' | 'center' | 'bottom' | 'full-bleed';
    density: 'sparse' | 'balanced' | 'dense';
  };
  language: string;                    // BCP-47; drives font subset + shaping
  needsClarification?: { question: string; options: string[] };
  assetsProvided?: { logoAssetId?: string; productAssetIds?: string[] };
}
```

**Rules the prompt must encode:**

- Infer canvas size from `kind` unless stated. Table of defaults:
  story 1080×1920, post 1080×1350, square 1080×1080, poster 2480×3508 @300dpi,
  banner 1500×500, thumbnail 1280×720.
- If the user supplied copy in quotes, use it **verbatim**. Never paraphrase user
  copy. If no copy, write it — short, punchy, ≤ 5 words for a headline.
- Brand kit, when present, overrides palette/fonts/tone.
- Detect the prompt's language and set `language`. Non-Latin scripts change font
  selection and require HarfBuzz shaping — do not fall back to Latin metrics.
- Set `needsClarification` **only** when a wrong guess would waste GPU spend
  (e.g. no canvas size and no design kind inferable). Maximum one question, with
  tappable options. Otherwise proceed with defaults and let the user edit.

Implementation: single LLM call, temperature 0.2, response constrained to the
`DesignBrief` JSON Schema. Validate with Zod; on failure, one repair round-trip
with the validation errors appended, then fall back to a heuristic parser
(regex for sizes, keyword map for `kind`).

## 1.2 Template corpus and retrieval

This is where layout quality actually comes from. **A curated skeleton corpus
beats a smarter LLM every time.** Budget real effort here.

### Skeleton schema

A skeleton is a `DesignDoc` with slots instead of content — normalised
coordinates so it works at any size within its aspect family.

```ts
export interface TemplateSkeleton {
  id: string;
  kind: DesignBrief['kind'];
  aspect: string;                    // '9:16'
  tags: string[];
  description: string;               // embedded for retrieval
  gridBaseline: number;              // e.g. 8 — solver snaps to this
  slots: Slot[];
  variants?: { id: string; patch: Partial<Slot>[] }[];  // e.g. left/right subject
}

export interface Slot {
  slotId: string;
  role: LayerRole;
  layerType: Layer['type'];
  /** Normalised 0..1 of canvas w/h. Solver converts to px. */
  frameN: { x: number; y: number; w: number; h: number; rotation?: number };
  required: boolean;
  constraints: Constraints;
  /** Text slots */
  text?: { maxChars: number; sizeN: number; weight: number;
           align: TextLayer['align']; transform?: TextLayer['textTransform'];
           autoFitN: { min: number; max: number } };
  /** Image slots: what the asset worker should be told to make */
  image?: { promptTemplate: string; transparent: boolean;
            aspectPreference?: string };
  /** Shape slots */
  shape?: Partial<ShapeLayer>;
  /** Where in the palette this slot draws its colour */
  paletteRole?: 'primary' | 'accent' | 'neutral' | 'on-primary';
  zIndex: number;
}
```

`promptTemplate` uses `{{subjectDescription}}`, `{{mood}}`, `{{palette}}`
placeholders filled by the composer. Example:

```
"{{subjectDescription}}, three-quarter view, {{mood}} studio lighting,
 clean transparent background, product photography, no text"
```

### Seeding the corpus

- Author **150–300 skeletons** minimum for v1: at least 20 per `kind`, each with
  2–4 variants. Hand-design them (or port from a licensed template pack — check
  the licence).
- Every skeleton must be reviewed by a designer at three copy lengths (short /
  medium / overflowing) and two subject aspect ratios. If it breaks, fix the
  `autoFitN` bounds or the slot frame — not the solver.
- `description` should read like a design brief, because that is what it is
  matched against: *"Full-bleed product hero for stories. Huge two-line display
  headline top-left, product bottom-right bleeding off the edge, pill CTA
  bottom-left. Best for single physical products, bold brands, high contrast."*
- Seed script: `packages/template-corpus/seed.ts` → validates each skeleton
  against Zod, embeds `description`, upserts into `templates`.

### Retrieval

```ts
async function retrieveTemplates(brief: DesignBrief): Promise<TemplateSkeleton[]> {
  const query = renderBriefAsSearchText(brief);   // kind + mood + placement + density
  const emb = await embedder.embed(query);
  return sql`
    select * from templates
    where kind = ${brief.kind}
      and aspect = ${nearestAspect(brief.canvas)}
      and (${brief.subjectDescription === null} = ('text-only' = any(tags)))
    order by (embedding <=> ${emb}) * 0.8 - quality_score * 0.2
    limit 3`;
}
```

Hard filters first (kind, aspect, text-only vs subject), then vector similarity
blended with `quality_score`. Return 3 candidates. If the user asked for N
variations, use N distinct templates rather than N seeds of one template — the
variety users want is *layout* variety, not noise variety.

`quality_score` is updated from a feedback signal: exported without edits = +,
deleted within 30 s = −, heavy manual repositioning = −. Bandit-style, updated
nightly.

## 1.3 Layout composer

**Job:** `compose.layout`. Input: brief + 3 candidate skeletons. Output: a
complete `DesignDoc` with empty `assetId`s and per-layer asset prompts.

The LLM does **not** invent coordinates. Its job is:

1. Pick the best skeleton and variant, with a one-line reason.
2. Write or place the copy into text slots, respecting `maxChars`.
3. Choose the palette (from brand kit, or derive 3–5 hexes from the prompt) and
   assign each slot's colour from `paletteRole`.
4. Choose the font family for the `typography.vibe` from an allow-list.
5. Fill each image slot's `promptTemplate` into a final `prompt` +
   `negativePrompt`.
6. Optionally nudge a slot frame within ±8% and drop `required: false` slots.

Constrain output to this shape — small and hard to get wrong:

```ts
export interface ComposerOutput {
  templateId: string;
  variantId?: string;
  reason: string;
  palette: string[];                 // 3..5 hex
  font: { family: string; headlineWeight: number; bodyWeight: number };
  slots: {
    slotId: string;
    include: boolean;
    text?: { content: string };
    color?: string;
    frameNudge?: { dx: number; dy: number; dw: number; dh: number };  // -0.08..0.08
    imagePrompt?: { prompt: string; negativePrompt: string };
  }[];
}
```

**Composer system-prompt requirements (write these explicitly):**

- Image prompts must always append the negative-text block:
  `text, letters, words, numbers, typography, watermark, logo, signature, caption, ui, frame, border`.
- A `transparent: true` slot's prompt must not mention background, floor,
  surface, or shadow.
- Background prompts must describe an *empty* scene with room where the subject
  and headline will sit. Give the model the occupied regions in words:
  *"leave the upper-left third uncluttered"*.
- Never write copy longer than `maxChars`. Count characters, not words.
- Uppercase transforms are applied at render time — do not pre-uppercase content
  (it breaks non-Latin text and user editing).

Then, in **deterministic code**, expand `ComposerOutput` + skeleton into a
`DesignDoc`:

```ts
function expand(skeleton: TemplateSkeleton, out: ComposerOutput,
                brief: DesignBrief): DesignDoc {
  // 1. denormalise frameN -> px using brief.canvas, apply frameNudge, clamp to canvas
  // 2. snap to gridBaseline
  // 3. materialise Layer objects in zIndex order, assetId = '' (placeholder)
  // 4. attach GenerationParams stubs (prompt, negativePrompt, seed = rng())
  // 5. copy Constraints from slot
  // 6. validateDoc() — throw on failure, do not ship an invalid doc
}
```

Emit `doc.skeleton` **immediately** after this. The client renders text, shapes
and palette-coloured placeholder rectangles for pending images. This is the
perceived-latency win.

### Failure handling

- Invalid JSON → one repair attempt with errors, then fall back to
  `templateId = candidates[0].id`, mechanical copy placement, palette from
  brief. Never fail the request at this stage.
- Composer picks a `slotId` that does not exist → ignore that entry, log it as an
  eval signal.

## 1.4 Asset workers

All jobs in this stage are independent. Dispatch as a fan-out and stream each
result back as a `layer.patch`.

### Ordering rule (important)

Generate the **background first**, then subjects, because subject harmonisation
needs the background's palette and light direction. If latency matters more than
polish, run them fully parallel and harmonise afterwards using the extracted
palette only.

### 1.4.1 `asset.background`

```python
def run(job):
    p = job.input
    img = t2i.generate(
        prompt=p.prompt, negative_prompt=p.negative_prompt,
        width=snap64(p.width), height=snap64(p.height),   # model-friendly dims
        seed=p.seed, steps=28, cfg=4.5)
    assert_no_glyphs(img, job)         # see 1.4.6
    img = resize_cover(img, p.width, p.height)
    return store_asset(img, kind='image', gen_params=p)
```

- Ask the model for the nearest supported resolution, then upscale/crop to the
  exact canvas size. Never stretch non-uniformly.
- For print (`dpi: 300`), generate at ~1/2 target and run `asset.upscale`.

### 1.4.2 `asset.subject` — transparent output

Two paths; pick by adapter availability, and record which was used.

**Path A — native transparent generation** (preferred): a transparent-latent
model returns RGBA directly. Cleanest edges, no matting artefacts.

**Path B — generate then matte:**

```python
def run(job):
    p = job.input
    rgb = t2i.generate(prompt=p.prompt + ", isolated on plain flat background",
                       negative_prompt=p.negative_prompt, seed=p.seed)
    assert_no_glyphs(rgb, job)
    alpha = matting.infer(rgb)                     # BiRefNet/RMBG -> soft alpha
    alpha = refine_alpha(alpha)                    # see below
    rgba = compose_rgba(rgb, alpha)
    rgba = trim_transparent_border(rgba)           # tight bbox; update naturalSize
    return store_asset(rgba, kind='image', has_alpha=True, gen_params=p)
```

`refine_alpha` — this is what separates professional output from
cut-out-with-scissors:

1. Threshold to a confident foreground (α>0.95) and confident background
   (α<0.05); the rest is the unknown band.
2. Build a trimap from that band, dilated by `max(2, 0.004 * min(w,h))` px.
3. Run a trimap matting model (ViTMatte-class) on the band only.
4. Feather 1 px, then **decontaminate colour**: for band pixels, estimate
   foreground colour as `F = (I - (1-α)B) / α` with `B` sampled from the local
   background ring. Skipping this leaves a halo of the old background around
   hair and edges — the single most common visible defect.
5. Despeckle: drop connected alpha components smaller than 0.05% of the bbox.

Store the alpha channel separately as `mask.png` too — the editor's
remove-background and refine-edge tools reuse it.

### 1.4.3 `asset.object` and `asset.icon`

- Secondary props/decorations: same as `asset.subject` but lower resolution and
  lower step count. These are `optional: true` layers — if they fail, drop them.
- Icons: prefer a **library lookup** (bundle an open-licence icon set, search by
  keyword, recolour via `SvgLayer.colorMap`) over generation. Vector icons are
  crisper, smaller, instantly recolourable and free.
- Only fall back to `Vectorizer` on a generated raster if the library misses.

### 1.4.4 `asset.upscale`

Triggered when `naturalSize < frame size * 1.2` or on print export. Real-ESRGAN
-class 2×/4×. Cache by `gen_hash + scale`.

### 1.4.5 Provided assets

If `brief.assetsProvided` has a logo or product photo:

- Logo → `SvgLayer` if SVG, else `ImageLayer` with `remove-bg` applied.
- Product photo → run matting, then treat exactly like a generated subject. This
  path is very common in practice; make it first class.

### 1.4.6 Glyph gate (enforces INV-1)

```python
def assert_no_glyphs(img, job, max_coverage=0.004, max_boxes=2):
    boxes = text_detector.detect(img)          # detection only, no recognition
    cov = sum(area(b) for b in boxes) / (img.width * img.height)
    if cov > max_coverage or len(boxes) > max_boxes:
        raise RetryWithStrongerNegative(boxes=boxes)
```

On retry: strengthen the negative prompt, change the seed, drop CFG slightly.
After 2 failed retries, inpaint the detected boxes away with the `Inpainter`
using the surrounding context. Log every trigger — a high rate for a given
template means its `promptTemplate` is inviting text.

## 1.5 Harmonisation

Independently generated layers do not belong to the same photograph. These
deterministic passes make them look like they do. All CPU, all fast.

### 1.5.1 `harmonize.palette`

1. Extract the background's dominant colours (k-means in Lab, k=5, weighted to
   the regions the text will sit over).
2. If `colorDirection.mode !== 'brand'`, replace the composer's palette with
   the extracted one, keeping the accent hue but snapping its lightness/chroma
   to be distinguishable (ΔE > 25 from the background).
3. Write back to `doc.palette` and re-apply `paletteRole` colours to shape and
   text layers.

### 1.5.2 `harmonize.contrast`

For every text layer, in paint order:

1. Rasterise everything **below** it at low res (e.g. 240 px wide) — this is
   cheap and exact, and is why the renderer must be shareable.
2. Sample the region under the text's AABB. Compute mean luminance and
   luminance variance.
3. Pick the text colour from the palette with the best WCAG contrast ratio
   against the mean; require ≥ 4.5:1 for body, ≥ 3:1 for display ≥ 32 px.
4. If variance is high (busy region) and no palette colour reaches the
   threshold, escalate in this order:
   - add `TextLayer.backdrop` (scrim pill/box behind the text),
   - insert a gradient `ShapeLayer` overlay between the image and the text,
   - as a last resort, nudge the text frame to a calmer region found by scanning
     candidate positions on the grid.
5. Never silently ship failing contrast. Record
   `meta.notes.contrastRatio` so evals can catch regressions.

### 1.5.3 `harmonize.shadow`

Cutouts float unless grounded.

1. Estimate the background's light direction: gradient of a heavily blurred
   luminance map → dominant direction vector.
2. Set each subject's shadow `dx, dy` opposite to it, `blur ≈ 0.06 * subject
   height`, `opacity 0.25–0.4` scaled by background darkness.
3. For a subject standing on a visible surface, add a squashed contact shadow:
   an ellipse `ShapeLayer` with heavy blur at the subject's alpha-bottom, drawn
   immediately below the subject layer.

### 1.5.4 `harmonize.color-match`

Match the subject to the background's white balance: compute mean Lab of the
background's mid-tones and of the subject's non-transparent pixels; write the
delta into `ImageLayer.adjust.temperature` and `saturation`, clamped to ±0.15.
Non-destructive, so the user can undo it in the inspector.

## 1.6 Layout solver

**Deterministic. No AI.** `packages/layout-engine`. Runs after assets land (and
again after every user edit that changes text or size).

```ts
export function solve(doc: DesignDoc, opts: SolveOpts): SolveResult;

export interface SolveResult {
  doc: DesignDoc;
  violations: Violation[];   // unresolvable issues, surfaced in the UI
}
```

Order of operations — do not reorder, later steps assume earlier ones:

1. **Measure text.** HarfBuzz-shape each text layer at its current size with the
   real font file. Produce line breaks (greedy, then Knuth-Plass for body
   copy ≥ 3 lines), glyph advances, and a tight ink bounding box. Cache by
   `(text, family, weight, size, letterSpacing, width, language)`.
2. **Autofit.** Binary search `fontSize` within `autoFit` bounds until the shaped
   block fits `frame` (≤ 12 iterations). If `autoHeight`, grow `frame.h` to the
   measured height instead. If still overflowing at `min`, emit a violation and
   truncate with an ellipsis only as a last resort.
3. **Safe margins.** Translate any layer whose AABB crosses `canvas.safeMargin`
   back inside, unless its role is `background` or its frame is intentionally
   full-bleed (`w >= canvas.width`).
4. **Collision resolution.** Build the AABB set for non-background, non-overlay
   layers. For each overlapping pair, resolve by (a) moving the
   lower-`priority` layer along the axis of least penetration, (b) if it cannot
   move without breaking a margin, shrink it within its autofit bounds, (c) if
   it is `optional`, hide it. Iterate to a fixed point, max 20 passes.
   Do **not** attempt full constraint programming for v1; greedy penetration
   resolution on a snapped grid is sufficient and debuggable.
5. **Optical alignment.** Align text blocks by ink edge, not frame edge (a
   left-aligned capital "T" needs a small negative offset). Align the subject's
   *alpha* centroid, not its frame centre.
6. **Grid snap.** Round all x/y/w/h to `gridBaseline`.
7. **Re-validate.** `validateDoc`. Emit `doc.solved`.

If you build one thing well in this project, build this. Users forgive mediocre
images; they do not forgive a headline colliding with a product.

## 1.7 Assemble, thumbnail, deliver

1. Persist the doc, initialise the Yjs room from it, write `documents.ydoc`.
2. `doc.thumbnail`: server render at 512 px → `docs/{id}/thumb.webp`.
3. Emit `request.done` with accumulated `cost_cents`.
4. Client transitions from the streaming preview to the live editor on the same
   canvas, without a reload or visual jump.

## 1.8 Multiple variations

For `count: N`, run 1.1 once, then 1.2 with `limit N`, then 1.3–1.6 per
template, sharing the background asset across variants **only** when their
aspect and prompt hash match (big cost saver). Present as a grid; the user
opens one to edit.

---

# 2. Part Two — flat image to editable layers

**Goal:** given one flat raster image, output a `DesignDoc` whose layers can be
moved, retyped and restyled independently, with the holes behind moved objects
already filled.

**Set expectations in the product copy.** Decomposition is inference, not
recovery — whatever was hidden must be invented. Target: *"good enough that
editing is faster than rebuilding"*, not perfect reconstruction. Always let the
user refine interactively (§2.10) and always keep the original upload as a
fallback flat layer they can revert to.

```
upload
 └─ 2.1 preprocess
     ├─ 2.2 text detect + OCR + style estimate ──┐
     ├─ 2.3 object detect + segment              │
     │    └─ 2.4 depth / z-order                 │
     │         └─ 2.5 alpha refine (matting)     │
     ├─ 2.6 flat-region vectorise ───────────────┤
     └─ 2.7 inpaint back-plates  ◀── needs all masks from 2.2/2.5
              └─ 2.8 assemble doc ◀─────────────┘
                   └─ 2.9 quality gate → 2.10 guided refinement
```

## 2.1 `decompose.preprocess`

- Decode, strip EXIF, auto-orient. Reject > 8000 px or > 40 MP (downscale with a
  warning instead of failing).
- Keep the **original** at full resolution as `assets/.../original`. Run the ML
  pipeline at a working resolution of 1536 px on the long edge; store the scale
  factor. All masks are produced at working res and **upsampled with edge-aware
  guided filtering** back to full res before final compositing — never with
  nearest-neighbour, which produces staircase mattes.
- Detect if the image is a screenshot / vector-origin graphic (low colour count,
  large flat regions, hard edges). If so, bias toward the vectorisation path
  (§2.6) and away from matting — flat graphics decompose far better as shapes.
- Set `doc.canvas` to the original pixel dimensions.

## 2.2 Text extraction

The highest-value step: text is what users most want to edit, and it converts
cleanly to a real `TextLayer`.

**`decompose.text-detect` → `decompose.ocr` → style estimate**

1. Detect text regions (quad boxes, rotation-aware). Group into lines, then into
   paragraphs by proximity, alignment and consistent leading.
2. Recognise content per line. Keep per-character confidence.
3. Estimate style for each paragraph:
   - **Colour:** median colour of pixels where the stroke mask is confident
     (erode the glyph mask by 1 px first, so anti-aliased edge pixels do not
     drag the colour toward the background).
   - **Size:** cap-height in px measured from the glyph mask → `fontSize`
     via the matched font's unitsPerEm ratio.
   - **Leading:** baseline-to-baseline distance / fontSize → `lineHeight`.
   - **Tracking:** (measured line width − shaped width at that size) / (n−1)
     → `letterSpacing`.
   - **Alignment:** compare left/right/centre variance of the line boxes.
   - **Weight/italic:** stroke-width-to-cap-height ratio → nearest weight bucket;
     dominant glyph slant angle → italic.
4. **`decompose.font-match`:** render the recognised string in each candidate
   font from the available library at the estimated size, and score against the
   cropped glyph mask (IoU + Chamfer distance on the skeleton). Pick the best.
   Store the top 3 in `meta.notes.fontCandidates` so the UI can offer swaps.
5. Emit a `TextLayer` per paragraph, `role` guessed by size rank
   (largest → `headline`, next → `subhead`, small+bottom → `caption`,
   inside a button-like shape → `cta`).
6. Union all glyph masks (dilated 3 px) into the **text mask** for inpainting.

Quality gate: if mean OCR confidence < 0.6 for a region, do **not** create a
text layer — leave those pixels in the background. A wrong-text layer is worse
than no layer.

## 2.3 Object detection and segmentation

**`decompose.detect`:** open-vocabulary detection with a prompt list built from
a caption of the image plus a generic vocabulary
(`person, face, product, bottle, phone, food, car, animal, plant, logo, badge,
button, icon, shape`). Keep boxes with score > 0.35, NMS at IoU 0.6.

**`decompose.segment`:** promptable segmenter (SAM-family) with each box as a
prompt. Additionally run automatic mask proposals and merge:

```python
masks = []
for box in boxes:
    m = segmenter.from_box(box, multimask=True)
    masks.append(pick_best(m))                 # highest predicted IoU
masks += segmenter.automatic(image, points_per_side=32)
masks = dedupe(masks, iou_thresh=0.85)
masks = [m for m in masks
         if area_frac(m) > 0.005 and area_frac(m) < 0.85    # not dust, not the whole image
         and not overlaps_text_mask(m, thresh=0.5)]
masks = merge_adjacent_same_object(masks)      # e.g. shoe + its lace mask
```

Cap at **12 object layers**. More than that is unusable in a layer panel and
explodes inpainting cost. Rank by `area × detection_score × centrality` and keep
the top 12; the rest stay in the background.

## 2.4 Depth ordering

Layers must stack correctly or moving one looks wrong.

1. Run monocular depth estimation → depth map.
2. For each mask, take the median depth of its pixels.
3. Sort layers back-to-front by median depth (largest depth = furthest = lowest
   z). Background is always index 0.
4. **Occlusion check:** for each pair of masks whose dilated boundaries touch,
   determine who occludes whom by comparing depth in a thin band along the shared
   boundary. If A is nearer along the boundary, A goes above B. Use this to
   correct the depth-median ordering, which fails on large tilted objects.
5. Group mutually-occluding objects into one `occlusionGroup` — they share a
   back-plate.

## 2.5 Alpha refinement

Segmentation masks are binary and blocky; they must become soft mattes or every
extracted layer will have a hard, obviously-cut edge.

Reuse `refine_alpha` from §1.4.2 exactly: trimap from the mask boundary band →
trimap matting model → colour decontamination → despeckle. For hair, fur,
foliage and glass, widen the unknown band (`0.012 * min(w,h)`).

Then, per layer:

- Crop to the tight alpha bbox; that becomes `frame` and `naturalSize`.
- Store RGBA as lossless WebP/PNG. Store the raw mask separately.
- Record `meta.extraction`:

```ts
export interface ExtractionInfo {
  method: 'sam-box' | 'sam-auto' | 'ocr' | 'vectorize' | 'background';
  detectionLabel?: string;          // 'running shoe'
  detectionScore?: number;
  maskArea: number;                 // fraction of canvas
  matteConfidence: number;          // 0..1, from trimap band agreement
  wasOccluded: boolean;
  backPlateInpainted: boolean;
}
```

## 2.6 Flat-region vectorisation

For screenshots, posters and vector-origin graphics, many "objects" are really
solid shapes — convert those to real `ShapeLayer`/`SvgLayer` instead of rasters.
They then scale and recolour perfectly.

Heuristic to qualify a mask as flat:

- Colour variance inside the mask below a threshold (single fill), **and**
- boundary is well approximated by few segments (Douglas-Peucker on the contour
  keeps > 95% IoU with ≤ 12 vertices), **or**
- the contour fits a rect/rounded-rect/ellipse primitive with IoU > 0.97.

Then:

- Primitive fit → `ShapeLayer` with `shape`, `radius`, `fill`. Best outcome:
  fully parametric.
- Otherwise → `VTracer`/potrace → `pathData` on a `ShapeLayer`, or a multi-path
  `SvgLayer` with `colorMap` for logos and icons.
- Detect gradients (fit a linear ramp along the dominant colour axis, R² > 0.9)
  and represent them as an `SvgLayer` rather than flattening to a mid colour.

## 2.7 Inpainting back-plates

**The expensive, quality-critical step.** Every extracted layer leaves a hole.

Do it in **one pass, back to front**, not per layer independently — otherwise
plates disagree with each other where objects overlap.

```python
def build_backplates(image, layers_sorted_back_to_front, text_mask):
    # 1. Reconstruct a clean background: remove ALL foreground + text at once.
    all_fg = union([l.mask for l in layers_sorted_back_to_front] + [text_mask])
    bg_plate = inpainter.fill(image, dilate(all_fg, r=6),
                              prompt="clean empty background, consistent lighting")
    plates = {'background': bg_plate}

    # 2. For each occlusion group, the plate is the composite of everything
    #    behind it, so moving the group reveals a plausible scene, not a hole.
    composite = bg_plate.copy()
    for group in groups(layers_sorted_back_to_front):
        plates[group.id] = composite.copy()
        composite = alpha_over(composite, group.rgba, group.frame)
    return plates
```

Rules:

- **Dilate masks by 4–8 px before inpainting.** Un-dilated masks leave a 1–2 px
  ghost ring of the removed object, which is instantly visible when the layer
  moves.
- Inpaint at working res in tiles for large images (512–768 px tiles, 64 px
  overlap, feathered blend), or the model will lose global coherence.
- Skip the plate when a layer's mask touches no other object and the background
  behind it is uniform (variance below threshold): just fill with the local mean
  colour. Much cheaper, visually identical.
- Set `ImageLayer.backPlateAssetId` and `occlusionGroup`; set
  `extraction.backPlateInpainted`.
- Cap total inpaint jobs per image (e.g. 4 plate renders). Beyond that, merge
  occlusion groups.

## 2.8 `decompose.assemble`

Emit a `DesignDoc`:

1. `provenance = { kind: 'decomposed', sourceAssetId, pipelineVersion, confidence }`.
2. Layer 0 = background `ImageLayer` pointing at `bg_plate` (full-bleed,
   `constraints.priority = 100`).
3. Object layers in depth order, each with `role` mapped from its detection
   label (`person`/`product` → `subject`, `logo` → `logo`, `button` → `cta`,
   else `object`).
4. Text layers on top, in reading order.
5. Vector layers wherever §2.6 qualified.
6. A hidden `ImageLayer` named "Original (flat)" at the very bottom,
   `visible: false`, pointing at the untouched upload — the user's escape hatch.
7. `doc.palette` = k-means palette of the original image.
8. `doc.fonts` = matched font families.
9. Run the **same layout solver** (§1.6) in *measure-only* mode: shape the text,
   verify autofit bounds are sane, but **do not move anything**. The user
   expects their image to look identical on open. Only enable the moving passes
   after their first edit.

## 2.9 Quality gate and graceful degradation

Compute a confidence score and pick an output tier:

```ts
const confidence =
  0.35 * meanMatteConfidence +
  0.25 * meanOcrConfidence +
  0.20 * inpaintQuality +            // no-reference sharpness/seam metric on plates
  0.20 * (1 - unresolvedOverlapFraction);
```

| Tier | Condition | Output |
|---|---|---|
| Full | conf ≥ 0.7 | all layers, plates, vectors |
| Reduced | 0.45 ≤ conf < 0.7 | background + text layers + top 3 objects only |
| Minimal | conf < 0.45 | flat background + text layers only |
| Failed | text and objects both unusable | flat image as a single layer + a message offering guided mode |

Always ship *something* openable in the editor. Tell the user which tier they
got, in plain words: *"I pulled out 4 objects and 3 text blocks. The background
behind the bottle was reconstructed, so it may look different if you move it."*

## 2.10 Guided refinement (ship this — it fixes what automation misses)

Endpoint: `POST /v1/decompose/:id/hint`. In the editor, the user can:

- **Add layer:** click/lasso a region → run `segmenter.from_points` on the
  original at full res → refine alpha → inpaint just that hole → insert a layer.
- **Split layer:** draw a line across a layer → split the mask, re-matte both.
- **Merge layers:** union masks, single back-plate.
- **Drop layer:** delete and composite it permanently back into the background
  plate (cheaper and cleaner than keeping it).
- **Refine edge:** brush over the alpha with an adjustable feather/decontaminate
  strength; re-runs trimap matting on the brushed band only.
- **Fix text:** correct the recognised string, swap the matched font from the
  stored candidate list.

Each hint is an incremental job — never re-run the whole pipeline. Reuse the
cached original, depth map, and existing plates.

---

# 3. The editor

Shared by both parts. Nothing about the editor knows which pipeline created the
document; that is the payoff of the single schema.

## 3.1 State and sync

- The document lives in a `Y.Doc`: `layers` as a `Y.Array` of `Y.Map`s,
  `canvas`/`palette` as `Y.Map`s. Text content is a `Y.Text` so concurrent typing
  merges.
- Undo/redo via `Y.UndoManager` scoped to the local client.
- Server ops (regenerate, solve, harmonise) apply as Yjs transactions with
  `origin: 'server'`, so they are excluded from the user's undo stack unless
  wrapped as a single named "AI edit" step (do wrap them — users expect ⌘Z to
  undo an AI change).
- Materialise `documents.doc` from the `Y.Doc` on a 2 s debounce for querying,
  thumbnails and export.

## 3.2 Canvas interactions

Required for parity with expectations: select (click, marquee, ⌘-click for
multi), move (with snap guides to canvas centre, safe margins, other layers'
edges/centres), resize (8 handles, shift = aspect lock, corner-only for text
with autofit), rotate, group/ungroup, z-reorder (layer panel drag + ⌘↑/↓),
duplicate, lock, hide, opacity/blend inspector, effects inspector, colour picker
constrained to `doc.palette` plus a free picker, text editing in place with the
real font and live re-shaping.

Performance: keep the interactive canvas at device pixel ratio, cache each
static layer as a bitmap (Konva `layer.cache()`), invalidate only the layers
touched by the current gesture. Re-solve layout on gesture end, not per frame.

## 3.3 Per-layer AI operations

Every one of these is a job that returns a `layer.patch`; the layer's identity
and frame are preserved so the edit is non-destructive in the layer sense.

| Action | Job | Behaviour |
|---|---|---|
| Regenerate | `layer.regenerate` | reuse stored `GenerationParams` with a new seed; optional prompt override |
| Restyle | `layer.restyle` | img2img at strength 0.45–0.7 keeping composition |
| Remove background | `layer.remove-bg` | matting + refine on an opaque layer, sets `hasAlpha` |
| Expand / outpaint | `layer.expand` | grow the frame, inpaint new edges, keep the original pixels bit-identical inside |
| Erase | `layer.erase` | brush mask → inpaint that region of this layer only |
| Rewrite copy | `copy.rewrite` | LLM rewrites selected text layers together (so headline and subhead stay coherent), respecting each layer's autofit `maxChars`; then re-solve |
| Recolour | client-side | palette remap for shapes/SVG/text — no model call |

After any operation that changes text or size, re-run `solve()` and animate
layers to their new positions (150 ms ease) so the change is legible.

---

# 4. Export and resize

## 4.1 Export

- `export.render` job in `apps/render`. Load doc, resolve assets at the highest
  needed derivative, `toDrawList(doc, { scale })`, draw with `renderer-skia`.
- **PNG/JPEG:** direct raster at `scale` (1×–4×), with `dpi` metadata.
- **PDF:** vector-preserving — text drawn as real embedded-font text runs,
  shapes/SVG as vector paths, images embedded at target dpi. Do **not**
  rasterise the whole page; a poster PDF with live text is a real feature.
  Handle CMYK conversion for print presets.
- **SVG:** shapes and text as SVG elements, images as embedded base64 or linked
  hrefs. Note in the UI that blend modes and some effects degrade.
- Font licensing: verify embedding rights per family; keep a per-font
  `embeddable` flag and fall back to outlining glyphs (converting to paths) when
  embedding is not permitted.

## 4.2 Resize to another format

`POST /v1/docs/:id/resize` — this is where `Constraints` pays off.

1. Pick the nearest template aspect family; if the source doc came from a
   template with a variant for the target aspect, use that variant's slot frames
   directly (best results by far).
2. Otherwise, apply constraints per layer: pinned edges stay pinned, `center`
   recentres, `scale` scales proportionally with the canvas, `stretch` fills.
3. Backgrounds: re-crop with `fit: cover` around the saliency centroid (compute
   a saliency map, or reuse the subject mask). If the aspect change exceeds 25%,
   **outpaint** the background to the new aspect instead of cropping — much
   better than a hard crop.
4. Re-run the solver with the new `safeMargin`. Drop `optional` layers by
   ascending `priority` while violations remain.
5. Return a **new** doc; never mutate the original.

---

# 5. Quality, evals, and testing

## 5.1 Unit and property tests

- `doc-schema`: validation, migrations, round-trip JSON.
- `layout-engine`: text measurement against fixtures (golden glyph positions);
  autofit convergence (property test: result always fits or reports a
  violation); collision solver terminates and never leaves an overlap between
  two `priority >= 50` layers.
- `renderer-core`: transform composition, hit testing, draw-list stability.

## 5.2 Golden-image render parity (INV-3)

For every fixture doc, render in browser (Playwright) and server, compare with
SSIM; fail below 0.995. Fixtures must cover: rotation, groups, every blend mode,
every effect, alpha edges, RTL text, CJK text, emoji, autofit at both bounds.

## 5.3 Generation evals (`packages/eval`)

Fixed set of 100 prompts across all `kind`s, plus 20 brand-kit prompts and 10
non-English prompts. For each generated doc, compute automatic metrics:

| Metric | Definition | Target |
|---|---|---|
| Text overflow rate | text layers with an overflow violation | < 1% |
| Collision rate | overlapping pairs, `priority ≥ 50` | 0% |
| Contrast pass rate | text layers meeting WCAG threshold | > 98% |
| Glyph leakage | generated images failing the glyph gate | < 2% |
| Margin violations | layers crossing `safeMargin` | 0% |
| Copy length compliance | text within slot `maxChars` | > 99% |
| Schema validity | docs passing `validateDoc` | 100% |
| p95 time to skeleton | | < 3 s |
| p95 time to complete | | < 25 s |
| Cost per design | | tracked, budgeted |

Plus a weekly human rating (1–5 on "would you post this without editing?") on a
30-design sample. Automatic metrics catch regressions; only humans catch ugly.

## 5.4 Decomposition evals

Build a labelled set of 60 images (photos, posters, screenshots, social graphics)
with hand-authored ground-truth layers.

| Metric | Definition | Target |
|---|---|---|
| Layer recall | GT objects matched at mask IoU ≥ 0.7 | > 0.75 |
| Layer precision | proposed layers matching a GT object | > 0.8 |
| Mask boundary quality | boundary F-score / SAD on the alpha band | tracked |
| OCR word accuracy | on the text-heavy subset | > 0.9 |
| Z-order accuracy | correctly ordered occluding pairs | > 0.9 |
| Inpaint quality | user-rated 1–5 on revealed plates | > 3.5 |
| Move-and-reveal test | move each layer 20% of canvas, human rates the hole | > 3.5 |

The move-and-reveal test is the one that actually predicts satisfaction. Automate
the moving, rate the results manually.

## 5.5 Load and soak

- 50 concurrent generation requests: queue depth, GPU utilisation, p95 latency.
- One 8000 px upload decomposing while 20 generations run — verify queue
  isolation prevents starvation.

---

# 6. Cost, caching, and performance

One design costs 3–8 image generations. Control it deliberately.

1. **Content-addressed asset cache.** `gen_hash = sha256(canonicalJson({adapter,
   model, prompt, negativePrompt, seed, params}))`, unique index on
   `assets.gen_hash`. Identical requests are free. Canonicalise key order and
   normalise whitespace in prompts or you will miss most hits.
2. **Two-tier models.** Fast/cheap model for previews and variation grids; the
   good model on "refine" or first export. Store both asset ids; upgrade lazily.
3. **Reuse backgrounds** across variants of one request (§1.8).
4. **Resolution discipline.** Generate at the smallest resolution that covers the
   layer's on-canvas size × 1.2. Upscale only on export.
5. **Text-measurement cache** keyed as in §1.6.1 — hot path during typing.
6. **Skip work:** no inpainting for uniform backgrounds; no upscaling for layers
   under 400 px; no depth estimation for single-object images.
7. **Budgets.** Per-request cost ceiling and per-user daily ceiling recorded in
   `generation_requests.cost_cents`; degrade (fewer variants, cheaper model)
   rather than erroring.
8. **Warm pools.** Keep model weights resident; cold starts dominate p95 latency
   on GPU workers. Batch same-model jobs with a 200 ms collection window.

Latency budget for one design:

| Stage | Budget |
|---|---|
| brief.parse | 1.0 s |
| template.retrieve | 0.1 s |
| compose.layout | 2.5 s |
| **→ skeleton visible** | **< 3.0 s** |
| background gen | 6 s |
| subject gen + matte | 8 s (parallel with background where possible) |
| harmonise + solve | 0.5 s |
| **→ complete** | **< 20 s** |

---

# 7. Safety and abuse

- **Prompt injection via uploads.** Text recognised from an uploaded image is
  **data, never instructions**. Pass OCR output to the LLM only inside a clearly
  delimited data block with an explicit instruction to treat it as content to
  reproduce, never to follow. Same for any text found in a generated image.
- **Content filters** on both input prompts and output images (NSFW, violence,
  CSAM detection on uploads — non-negotiable, use a dedicated provider).
- **Likeness and IP.** Block prompts naming real individuals for photoreal
  generation, and trademarked characters/brands. Run a logo/character similarity
  check on outputs. For decomposition, uploads are user content — do not train
  on them without explicit opt-in.
- **Font and template licensing.** Track licence per font and per template;
  block export paths that would violate them.
- **Rate limits** per user and per IP on generation and decomposition; both are
  GPU-expensive and attractive to abuse.
- **Provenance metadata.** Write C2PA-style content credentials into exports for
  AI-generated imagery where required.
- **Data retention.** Uploads and intermediate masks deleted on a schedule
  (default 30 days); document a delete-my-data path that also purges assets.

---

# 8. Milestones and definition of done

Each milestone must be demoable and shippable behind a flag. Do not start the
next until the previous one's DoD passes.

### M0 — Foundations (week 1)
`doc-schema` (types + Zod + JSON Schema + validate + migrate), repo scaffolding,
`renderer-core` draw list, `renderer-konva`, `renderer-skia`, Postgres + S3 +
Redis up, asset service with derivative ladder.
**DoD:** a hand-written fixture doc renders identically (SSIM ≥ 0.995) in browser
and server export, and validates.

### M1 — Editor MVP (week 2–3)
Yjs sync, layer panel, select/move/resize/rotate, text editing with real
shaping, inspector, undo/redo, PNG export.
**DoD:** a user can build the §0.5 worked example by hand and export it.

### M2 — Layout engine (week 3–4)
HarfBuzz measurement, autofit, safe margins, collision resolution, grid snap,
optical alignment, violation reporting.
**DoD:** property tests pass; a 5-word headline and a 40-word headline both fit
the same template without collision.

### M3 — Part One end to end (week 4–7)
Brief parser, 60 seeded templates, retrieval, composer with constrained JSON,
background + subject workers (hosted adapters), glyph gate, harmonisation,
progressive streaming.
**DoD:** 20 diverse prompts each produce an editable design in < 25 s with 0
collisions, 0 margin violations, and no baked-in text. Skeleton visible < 3 s.

### M4 — Part One quality (week 7–9)
Corpus to 150+ templates, native transparent generation, alpha refinement with
decontamination, shadow/light matching, variations, resize-to-format, eval
harness with the §5.3 metrics wired to CI.
**DoD:** eval targets in §5.3 met; human rating ≥ 3.5/5 average.

### M5 — Part Two end to end (week 9–12)
Preprocess, text detection + OCR + style estimate + font match, detect + segment,
depth ordering, alpha refinement, single-pass back-plate inpainting, assemble,
quality tiers.
**DoD:** on the 60-image eval set, layer recall > 0.7, z-order accuracy > 0.85,
every image produces an openable doc (tier Minimal or better), move-and-reveal
rating ≥ 3.0.

### M6 — Refinement and polish (week 12–14)
Guided refinement hints, per-layer AI ops (regenerate/expand/erase/remove-bg/
rewrite), PDF + SVG export, vectorisation path, cost controls, safety filters,
observability dashboards.
**DoD:** §5.4 targets met; p95 costs within budget; all §7 items implemented.

---

# 9. Agent task checklist

Work top to bottom. Each item should be a single PR with tests.

**Foundations**
- [ ] `packages/doc-schema`: types, Zod, JSON Schema export, `validateDoc`, `migrate`, fixtures
- [ ] `packages/renderer-core`: transforms, `worldBounds`, `hitTest`, `toDrawList`
- [ ] `apps/web` Konva backend + `apps/render` Skia backend consuming the same draw list
- [ ] Golden-image parity harness in CI
- [ ] Asset service: upload, `gen_hash` dedupe, derivative ladder, signed URLs
- [ ] BullMQ queues, `JobEnvelope`, progress pub/sub, WebSocket fan-out, retry + degrade

**Editor**
- [ ] Yjs document binding, `UndoManager`, server-origin transactions
- [ ] Selection, transform handles, snap guides, layer panel, inspectors
- [ ] In-place text editing with live HarfBuzz re-shaping
- [ ] Layer caching + gesture-end re-solve for 60 fps

**Layout engine**
- [ ] HarfBuzz + opentype text measurement with cache
- [ ] Line breaking (greedy + Knuth-Plass), autofit binary search
- [ ] Safe margins, AABB collision resolution, grid snap, optical alignment
- [ ] `solve()` violation reporting surfaced in the UI

**Part One**
- [ ] `brief.parse` with constrained JSON, repair loop, heuristic fallback
- [ ] `TemplateSkeleton` schema, 60 seed templates, seed + embed script
- [ ] `retrieveTemplates` with hard filters + vector search + quality blend
- [ ] `compose.layout` with `ComposerOutput` schema and deterministic `expand()`
- [ ] Emit `doc.skeleton` under 3 s
- [ ] `asset.background`, `asset.subject` (both paths), `asset.object`, `asset.icon`, `asset.upscale`
- [ ] `refine_alpha` with trimap matting + colour decontamination + despeckle
- [ ] Glyph gate with retry + inpaint fallback
- [ ] `harmonize.palette` / `.contrast` / `.shadow` / `.color-match`
- [ ] `doc.assemble`, thumbnail, cost accounting
- [ ] Variations, provided-asset path (logo/product photo)
- [ ] Corpus to 150+, designer review at 3 copy lengths

**Part Two**
- [ ] `decompose.preprocess` with working-res + guided mask upsampling
- [ ] Text detect → OCR → style estimate → font match → `TextLayer`s + text mask
- [ ] Open-vocab detect → promptable segment → dedupe/filter → cap at 12
- [ ] Depth estimation → median-depth sort → boundary occlusion correction → groups
- [ ] Alpha refinement per layer + `ExtractionInfo`
- [ ] Flat-region qualification → primitive fit / vectorise / gradient fit
- [ ] Single-pass back-to-front back-plate inpainting with dilation + tiling
- [ ] `decompose.assemble` with hidden original layer + measure-only solve
- [ ] Confidence score, output tiers, honest user-facing summary
- [ ] Guided refinement: add / split / merge / drop / refine-edge / fix-text

**Cross-cutting**
- [ ] Per-layer AI ops (regenerate, restyle, remove-bg, expand, erase, rewrite)
- [ ] PNG/JPEG/PDF/SVG export with live text in PDF; font embedding rights check
- [ ] Resize-to-format via constraints + saliency crop + outpaint
- [ ] Eval harness: generation metrics + decomposition metrics in CI
- [ ] Cost caching, two-tier models, budgets, warm pools, batching
- [ ] Safety: injection isolation for OCR text, content filters, IP/likeness, rate limits, retention
- [ ] Observability: per-job latency/cost/failure dashboards, per-template quality feedback loop

---

## Appendix A — the five failure modes that will bite you

1. **Baked-in text.** Any text in a generated raster is unfixable by the user.
   Negative prompts alone are not enough; the glyph gate is mandatory.
2. **Halos on cutouts.** Skipping colour decontamination leaves a fringe of the
   old background. It reads as "cheap AI" instantly.
3. **Text colliding with the subject** at long copy lengths. Layout solver, and
   template review at three copy lengths, are the fix — not a better model.
4. **Revealed holes** in decomposed docs. Dilate masks, inpaint back-to-front in
   one pass, and store per-group plates.
5. **Client/server render drift.** Different text shaping between browser and
   export is the classic version. Shape once in shared code; enforce with SSIM
   in CI.

## Appendix B — build vs buy for v1

Ship hosted model APIs behind the `ml-adapters` interfaces. Self-host only the
models you call on every single request and where per-call cost dominates
(matting and segmentation are small and cheap to self-host; diffusion is not,
until volume justifies the GPUs). The adapter boundary means this is a config
change, not a rewrite — so do not spend M3 provisioning GPUs.
