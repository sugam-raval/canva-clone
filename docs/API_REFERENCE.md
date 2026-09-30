# API reference (quick lookup)

Base path: `/v1`. All bodies and responses are JSON, camelCase on the wire (Python code
uses snake_case internally — both are accepted on request bodies). Interactive docs:
`GET /docs` (Swagger) once the server is running.

| Method | Path | What it does |
|---|---|---|
| `POST` | [`/v1/lido/generate`](#post-v1lidogenerate) | Fill a Lido template from a prompt (the main endpoint) |
| `GET`  | [`/v1/lido/templates`](#get-v1lidotemplates) | List every template in the corpus |
| `POST` | [`/v1/lido/templates/sync`](#post-v1lidotemplatessync) | Re-sync `lidojs_templates/*.json` into the database now |
| `GET`  | [`/v1/lido/generations`](#get-v1lidogenerations) | Generation history, newest first |
| `GET`  | [`/v1/lido/generations/{design_id}`](#get-v1lidogenerationsdesign_id) | Reopen one saved design |
| `GET`  | [`/v1/health`](#get-v1health) | Service health check |

---

## POST `/v1/lido/generate`

Fills a Lido template from a plain-text prompt: one LLM call writes every text layer and
image prompt, images are generated and uploaded, the result is saved to
`lido_generations`, and the full filled document is returned.

### Request body

```json
{
  "prompt": "Cozy coffee shop promo, warm tones, headline \"Morning Magic\", 20% off this week",
  "kind": "post",
  "generateImages": true,
  "templateId": null,
  "randomTemplate": false,
  "palette": ["#6b3f1d", "#e8b04b"],
  "logoUrl": "https://assets.example.com/brand/logo.png"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `prompt` | string | **yes** | 1–2000 characters. The design brief. |
| `kind` | `"story"｜"post"｜"poster"｜"banner"｜"thumbnail"｜"ad"｜"flyer"｜null` | no | Hint only; omit to auto-detect. |
| `generateImages` | boolean | no | Default `true`. `false` skips image generation — the template's own images are kept. |
| `templateId` | string \| `null` | no | Pick an exact template by id (e.g. `"template_227"`), skipping the automatic match entirely. 404 if it doesn't exist. |
| `randomTemplate` | boolean | no | Default `false`. Pick uniformly at random across the whole corpus. Ignored if `templateId` is set. |
| `palette` | array of hex strings \| `null` | no | Up to **4** colours (`"#rrggbb"`), first = primary. Applied to text/shapes/images during generation; template search never uses it. Omit or send `[]` for no theme (generation is then exactly as without this field) — see [`docs/palette_theme.md`](palette_theme.md). Any entry that isn't a colour, or more than 4 entries → `400`. |
| `logoUrl` | string \| `null` | no | An http(s) image URL. When given, it's swapped directly into the chosen template's logo slot (a plain code-level URL replacement, no AI, no re-cropping — logo slots render `objectFit: contain`). Ignored if the chosen template has no logo slot. Not a colour or a generation prompt — malformed URLs (not starting `http://`/`https://`) → `400`. |

Precedence when choosing a template: `templateId` wins outright; otherwise
`randomTemplate: true` picks at random; otherwise the automatic best-match runs
(`docs/new_match_plan.md` + `docs/slot_fit_match_plan.md`) and its reasoning comes back
in the response's `match` field.

### Response `200` — `LidoGenerateResponse`

```json
{
  "document": [ { "layers": { "...": "..." }, "meta": { "...": "..." } } ],
  "templateId": "template_227",
  "templateScore": 1.0,
  "designId": "tpl-cozy-coffee-45891d51",
  "textFills": [
    { "layerId": "14819dc3-...", "role": "body", "text": "20% off this week" },
    { "layerId": "86279fff-...", "role": "label", "text": "Sip & Save!" },
    { "layerId": "bab7c3c8-...", "role": "website", "text": "www.yourwebsite.com" },
    { "layerId": "d151f974-...", "role": "headline", "text": "Cozy Coffee" },
    { "layerId": "d835c471-...", "role": "subhead", "text": "Morning Magic" }
  ],
  "imageFills": [
    { "layerId": "ROOT", "url": "https://.../design-assets/public/lido-generated/tpl-cozy-coffee-45891d51/background.png" }
  ],
  "imagePrompts": [
    { "layerId": "ROOT", "prompt": "Diagonal two-panel flat-lay background on a square canvas for a cozy coffee shop promo..." }
  ],
  "imageFailures": [],
  "droppedLines": [],
  "theme": {
    "palette": ["#6b3f1d", "#e8b04b"],
    "colorMap": {},
    "textColors": { "14819dc3-...": { "#ffffff": "#ffffff" } },
    "contrastFixed": []
  },
  "match": null
}
```

| Field | Type | Notes |
|---|---|---|
| `document` | array (1 item) | `[{ "layers": {...}, "meta": {...} }]` — the filled Lido document, ready for the editor. |
| `templateId` | string | Which template was filled. |
| `templateScore` | number | `1.0` for an explicit/random pick; the match score (0–1) for an automatic pick. |
| `designId` | string | Slug used as the generation's id and its asset path; reopen with `GET /v1/lido/generations/{designId}`. |
| `textFills` | array of `{layerId, role, text}` | Final copy per text layer. |
| `imageFills` | array of `{layerId, url}` | Permanent public URL per generated/uploaded image (empty if `generateImages` was `false`, or empty per-layer on a render failure). |
| `imagePrompts` | array of `{layerId, prompt}` | The final image-generation prompt used per layer (palette line included when a theme was given). |
| `imageFailures` | array of string | Layer ids whose image failed to render/upload — that layer keeps the template's original image. |
| `droppedLines` | array of string | Lines the user explicitly asked for (quoted text) that had no slot in the chosen template — never silently lost, always reported here. |
| `theme` | object \| `null` | Present only when `palette` was given. `colorMap`: template colour → new colour (hex → hex). `textColors`: per text layer, old colour → final colour. `contrastFixed`: layer ids whose text colour was swapped to stay readable against the generated background. `null` when no palette was chosen. |
| `match` | object \| `null` | `null` for an explicit `templateId` or `randomTemplate` pick. Otherwise the automatic-match explanation (see below). |

`match` object (`LidoMatchInfo`), only present for an automatic pick:

| Field | Type | Notes |
|---|---|---|
| `path` | `"holds_all"｜"best_match"` | `holds_all`: the pick places every line and detail the user gave. |
| `tier` | `"A"｜"B"｜"C"` | A = fits everything; B = keeps every must-keep item (headline, offer, price, contact); C = best effort. |
| `topicLine` | string | The request's topic, in English (translated if needed). |
| `requestDetails` | array of string | Which of `phone/email/website/address/offer/price/date` were found in the prompt. |
| `requestedLines` | array of string | Every line the user explicitly asked for (quoted text). |
| `usedLlm` | boolean | Whether the topic/detail LLM call succeeded (`false` = pattern fallback only). |
| `embedder` | string | Name of the embedding model used for topic similarity, or `"word-overlap"`/`"none"` as a fallback. |
| `candidates` | array | Top matches, best first — each with `templateId`, `score`, `topic`, `details`, `held`, `missing`, `emptyContactSlots`, `tier`, `coverage`, `placedLines`, `droppedLines`. |

### Errors

| Status | When |
|---|---|
| `400` | Prompt fails safety screening (`detail` explains why), or `palette` is invalid (bad colour / more than 4). |
| `404` | `templateId` doesn't match any template in the corpus. |
| `422` | Request body fails schema validation (e.g. missing `prompt`, `kind` not one of the allowed values). |
| `500` | Corpus is empty, generation failed unexpectedly, or the design was generated but could not be saved (regenerate and retry). |
| `503` | The LLM provider is unavailable. |

---

## GET `/v1/lido/templates`

Lists every template in the catalog — every one is a candidate for the automatic match.
No parameters.

### Response `200` — array of `LidoTemplateSummary`

```json
[
  {
    "id": "template_227",
    "name": "Restaurant Split Promo",
    "kind": "post",
    "aspect": "1:1",
    "tags": ["restaurant", "food", "promo", "split-layout"],
    "description": "Diagonal split-panel food promo: solid color panel + light surface panel, a circular transparent subject cutout floating over the seam, a logo, and five text layers (kicker, script accent, headline, promo line, website)."
  }
]
```

---

## POST `/v1/lido/templates/sync`

Mirrors `lidojs_templates/*.json` into the `lido_templates` table right now, re-embedding
only templates whose metadata changed since the last sync. The API also does this by
itself at startup and every `LIDO_TEMPLATE_SYNC_SECONDS`; call this to force it sooner.

### Query parameters

| Field | Type | Required | Notes |
|---|---|---|---|
| `force` | boolean | no | Default `false`. `true` re-embeds every template, not just changed ones. |

### Response `200`

```json
{
  "added": ["template_990"],
  "reembedded": ["template_227"],
  "unchanged": ["template_1", "template_2"],
  "deleted": [],
  "model": "sentence-transformers/all-MiniLM-L6-v2"
}
```

### Errors

| Status | When |
|---|---|
| `503` | The database is unreachable (`detail` includes the underlying error). |

---

## GET `/v1/lido/generations`

Generation history, newest first.

### Query parameters

| Field | Type | Required | Notes |
|---|---|---|---|
| `limit` | integer | no | Default `50`, clamped to `1–200`. |
| `offset` | integer | no | Default `0`, clamped to `≥ 0`. |

### Response `200` — array of `LidoGenerationSummary`

```json
[
  {
    "id": "tpl-cozy-coffee-45891d51",
    "templateId": "template_227",
    "name": "Cozy Coffee",
    "kind": "post",
    "aspect": "1:1",
    "prompt": "Cozy coffee shop promo, warm tones, headline \"Morning Magic\", 20% off this week",
    "canvasSize": { "width": 675, "height": 675 },
    "thumbnailUrl": "https://.../background.png",
    "path": null,
    "createdAt": "2026-09-29T13:16:42.656330+00:00"
  }
]
```

`document` is **not** included here (summary only) — fetch it with the endpoint below.

---

## GET `/v1/lido/generations/{design_id}`

Reopens one saved design in full.

### Path parameters

| Field | Type | Required | Notes |
|---|---|---|---|
| `design_id` | string | **yes** | The `designId` returned by `POST /v1/lido/generate` (e.g. `"tpl-cozy-coffee-45891d51"`). |

### Response `200`

```json
{
  "designId": "tpl-cozy-coffee-45891d51",
  "document": [ { "layers": { "...": "..." }, "meta": { "...": "..." } } ]
}
```

### Errors

| Status | When |
|---|---|
| `404` | No design with that `design_id`. |

---

## GET `/v1/health`

No auth, no parameters — for uptime checks.

### Response `200`

```json
{
  "status": "ok",
  "database": true,
  "adapters": { "llm": "openai:gpt-...", "textToImage": "...", "transparentImage": "..." },
  "openaiConfigured": true
}
```

---

## Conventions used throughout

- **Casing:** every request/response field is camelCase on the wire. Sending snake_case
  also works (both are accepted), but responses are always camelCase.
- **Unknown fields are rejected** (`extra: "forbid"`) — a typo'd field name in a request
  body returns `422`, not a silent no-op.
- **Error shape:** `{ "detail": "<message>" }` for all error responses (FastAPI/Pydantic
  default), whatever the status code.
- **Colours:** always `#rrggbb` hex on the wire; `rgb(r, g, b)` is also accepted as
  request input and normalized to hex.
- **IDs:** `templateId` is a file stem in `lidojs_templates/` (e.g. `"template_227"`);
  `designId` is a generated slug, distinct from the internal numeric DB id.
