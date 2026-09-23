# Plan: make `Lido.js (template)` generation actually use the rich per-layer metadata

## Implementation status (2026-09-23): implemented — §2.1, §2.2, §2.4, §2.5

§2.2 (single structured call) is live on `POST /v1/lido/generate`; §2.3 remains the
documented fallback, not built. Where the build differs from or goes beyond this plan:

1. **Real font measurement** (`app/lido_corpus/textfit.py`). A characters-per-line
   estimate let "Vegan smoothie" through in the first live run, and "Smoothie" (239px in
   Yeseva One) overflowed the 200px headline box. Texts are now wrapped with the
   layer's actual font file, cached in `lidojs_templates/fonts/`.
2. **One text-only repair call, only when a limit is broken**, before mechanical
   clamping as the last resort. Happy path is still exactly 1 call; in 4 live runs, 3
   needed 1 call and 1 needed the repair (2 calls). No clamping was needed.
3. **No line breaks from the model.** Every `template_227` text layer is a single
   paragraph, which renders `\n` as a space; wrapping comes from box width. The example
   output below that uses `"Vegan\nSmoothies"` is superseded on this point.
4. **Contact rule is also enforced in code**: a website/phone/address that doesn't
   appear in the user's request is reverted to the template default, restoring the
   guarantee `DesignBrief` used to give.
5. **Output**: `<design_id>.json` saved to `lido_generated/`; generated images uploaded
   to MinIO at `design-assets/public/lido-generated/<design_id>/` and referenced by their
   direct URL (e.g. `http://localhost:9010/design-assets/public/lido-generated/...`).
   The bucket's existing policy already allows anonymous reads under `public/`, so these
   links never expire — the store's default presigned URLs last one hour, which would
   leave saved designs pointing at dead images. `S3_PUBLIC_BASE_URL` overrides the host
   if MinIO sits behind another address; if MinIO is down, the storage layer's local
   fallback is used, and a failed upload keeps that layer's template image and is
   reported in `image_failures`.
9. `template_227` background notes now require a saturated, medium-to-dark left panel:
   the template's text is always white, and a "peach and cream" request produced a
   pale panel with unreadable copy until the notes said so.
6. **Tuning knobs**: `LIDO_TEMPLATE_REASONING_EFFORT` (default `high`, via a new
   per-call `reasoning_effort` on the LLM adapter) and `LIDO_TEMPLATE_IMAGE_QUALITY`
   (default `high`).
7. `template_227` metadata fix: the promo block's `max_lines` 3 → 4, matching how its
   own copy sets in the reference image. Image `notes` rewritten for the model (they
   referenced internal code).
8. Removed now-dead code: `compose_ai.py` (old brief-based composer), the
   `DesignBrief`/embedding retrieval path, and the old hardcoded asset prompts.

Scope: **only** the `POST /v1/lido/generate` pipeline (the "Lido.js (template)" tab). No
changes to `Custom (DesignDoc)` or `Lido.js (scratch)`. No frontend changes required for
the core behavior (the frontend already just renders whatever `document` comes back and
has no concept of `meta`) — one optional, clearly-marked frontend addition is called out
below for review.

Testing scope, per your confirmation: **pin generation to `template_227.json` only**,
since it's currently the only template with rich metadata. `template_1/3/4/5.json` stay
untouched on disk (you said more rich templates are coming later) but won't be selected
yet. Model tiers: use whatever's already wired up (no new adapters) — confirmed below.

---

## 1. What's broken today (verified by reading every file in the path)

`generate_lido_design()` (`app/lido_corpus/pipeline.py:35-61`) already runs: retrieve →
compose text → generate assets → mechanical merge. The problem isn't the shape of the
pipeline, it's that **every step re-derives its own instructions from `DesignBrief`
alone and never reads the `meta` fields we just spent the last task authoring**:

| Gap | File:line | Concretely |
|---|---|---|
| Retrieval ignores exemplar signal | `retrieval.py:39-108` | Scores only `meta.description`/`tags`/`kind`. Never looks at `reference_note`. Every template (rich or not) is an equally eligible candidate. |
| Text-fill ignores limits/notes/lock | `compose_ai.py:33-42, 45-59` | `_slot_manifest` sends the LLM only `layer_id`/`role`/`current_text`/`max_chars`. `max_lines`, `notes`, `locked` are never sent — the model can't respect what it never sees. |
| No post-hoc enforcement | `compose.py:16-32` | `fill_template` writes whatever string the LLM returned, verbatim, no length/line check. `max_chars` is prompt-level guidance only. |
| Locked slots have no protection | `compose.py`, `assets_ai.py` | `locked` is read nowhere. A future locked *text* slot would get silently overwritten same as any other. |
| Image gen ignores `ImageSpec` entirely | `assets_ai.py:46-70` | `generate_background`/`generate_photo` build their own hardcoded prompt strings from `DesignBrief` fields only. `meta.background.prompt`, `slot.image.prompt/transparent/kind/generate` are never read. |
| No transparent cutout is ever produced | `assets_ai.py:35-44` | Both asset calls go through `registry.text_to_image()` (opaque). `registry.transparent_image()` (already implemented, `background="transparent"`, `has_alpha=True`) is never called. The circular subject-cutout slot on `template_227` structurally cannot get a real cutout today. |
| No prompt *adaptation* mechanism | (nowhere) | There's no LLM call anywhere in the asset path. Even if `slot.image.prompt` were read, it's the *reference* prompt (orange/salad) — reusing it verbatim for a "blue tech gadget" brief would be wrong. Nothing adapts it. |

Models already wired up (confirmed in `config.py`/`registry.py`/`openai_adapters.py`,
reused as-is per your answer):
- **Text/"thinking"**: `OpenAILLM.complete_json` → `settings.llm_model` (`gpt-6-astra`)
  at `settings.llm_reasoning_effort` (`low`) → Responses-API reasoning path. Already
  used by both `parse_brief` and `compose_lido_content` today.
- **Image, opaque**: `OpenAITextToImage` → `settings.image_model`
  (`gpt-image-2.5-sunburst`) via `registry.text_to_image()`.
- **Image, transparent**: `OpenAITransparentImage` (same model, `background="transparent"`,
  `has_alpha=True`) via `registry.transparent_image()` — implemented, wired into the
  registry, just never called by `assets_ai.py`.
- No Anthropic/Claude adapter exists anywhere in this repo (confirmed by grep) — out of
  scope, not needed since we're reusing the existing OpenAI adapters.

---

## 2. Proposed changes

### 2.1 Pin candidate selection to ready templates (`retrieval.py` / `pipeline.py`)

Add a one-line readiness gate: a template is an eligible candidate for
`/v1/lido/generate` only if `meta.reference_note` is set (that field's whole purpose is
"this is a deliberately-authored exemplar, safe to generate from"). Today that's exactly
`template_227`; every future template you enrich the same way becomes eligible
automatically, no code change needed.

- `retrieve_for_brief()` (`retrieval.py:79`): filter `templates` down to
  `[t for t in templates if t.meta.reference_note]` before scoring. If that list is
  empty, raise the same `AdapterError`-style failure the route already 400s/500s on
  today (no silent fallback to an unannotated template).
- Everything else about retrieval (embedding/keyword scoring) stays as-is — with one
  candidate it's a no-op selection, but the code path is ready for when you add more
  exemplar templates later; no rewrite needed then.

*(Alternative considered: hardcode the id `"template_227"`. Rejected — the readiness-gate
approach gets you "just use template_227 for now" today with zero extra code, and scales
to N exemplar templates later without touching this function again. Flag if you'd rather
hardcode the id for now instead — one-line difference.)*

### 2.2 PRIMARY approach: one structured, layer-wise call (your proposal)

Instead of decomposing into separate brief-parse / text-compose / background-prompt /
subject-prompt calls, make **one** `complete_json` call to the thinking model per
generation request, with a schema that returns everything keyed by `layer_id` — text
fills and adapted image prompts together, in one pass. Since the template is pinned
(2.1), we don't need `parse_brief`/`DesignBrief` for this flow at all: canvas size, kind,
and layer structure are already fixed by `template_227` itself, so the raw user prompt
can go straight into this one call instead of first being normalized into a generic
brief object.

New module, e.g. `app/lido_corpus/generate_ai.py`:

```python
class LidoLayerTextFill(BaseModel):
    layer_id: str
    text: str

class LidoLayerImagePrompt(BaseModel):
    layer_id: str          # "ROOT" for the background, or the photo slot's layer_id
    prompt: str            # final, brief-adapted image-generation prompt

class LidoTemplateFillOutput(BaseModel):
    text_fills: list[LidoLayerTextFill]
    image_prompts: list[LidoLayerImagePrompt]

async def generate_template_fill(user_prompt: str, template: LidoTemplateFile) -> LidoTemplateFillOutput
```

#### Exact input payload

Built entirely from the template's own `meta` — no `DesignBrief` involved. For
`template_227`, `_build_user_message(user_prompt, template)` produces:

```
User's design request:
"Create a promo for my vegan smoothie bar — cheerful, bright green and yellow branding"

Fill these text layers exactly as given (do not add, remove, or merge layers):
[
  {
    "layer_id": "14819dc3-ee3c-410d-ae88-ef2d6de07b2e",
    "role": "body",
    "current_text": "Healthy but Tasty Diet?",
    "max_chars": 40,
    "max_lines": 2,
    "notes": "Kicker line above the script accent — a short rhetorical question or teaser framing the offer. Keep it to one short sentence, at most 2 lines at this font size; do not let it grow into a paragraph."
  },
  {
    "layer_id": "86279fff-8f09-48bd-94eb-c0e981c4a67d",
    "role": "label",
    "current_text": "Get Yours!",
    "max_chars": 20,
    "max_lines": 1,
    "notes": "Script-font accent phrase, single line only — a short high-energy call-in. 1-3 words; never wraps."
  },
  {
    "layer_id": "d151f974-b143-47fd-9b56-d64625400d89",
    "role": "headline",
    "current_text": "Healthy Food",
    "max_chars": 24,
    "max_lines": 2,
    "notes": "Primary headline — the product/category name, bold and short. 1-2 words per line, at most 2 lines."
  },
  {
    "layer_id": "d835c471-0cb3-418d-901c-33f64b5c7140",
    "role": "subhead",
    "current_text": "Limited Happy Hours Promo",
    "max_chars": 40,
    "max_lines": 3,
    "notes": "Uppercase tracked promo/CTA line — the concrete offer. Up to 3 short lines; keep each line to 1-3 words."
  },
  {
    "layer_id": "bab7c3c8-d0ce-468c-8faa-311e0d0563ee",
    "role": "website",
    "current_text": "www.yourwebsite.com",
    "max_chars": 30,
    "max_lines": 1,
    "notes": "Website or contact line, always a single line, never wraps. CONTACT RULE: only replace this if the user's request explicitly gives a website/phone/address — otherwise return current_text unchanged verbatim."
  }
]
(the logo slot, 210b6d7e..., is locked and intentionally omitted — never fill it)

Rewrite these reference image prompts to match the request while preserving their
structural framing exactly as instructed in the system prompt:
[
  {
    "layer_id": "ROOT",
    "purpose": "background",
    "reference_prompt": "Diagonal two-panel flat-lay background on a square canvas. A solid flat brand-color panel (this template: warm orange) fills roughly the left 40% of the frame; the remaining ~60% on the right is a light neutral surface (this template: white marble/stone). ... IMPORTANT: leave the visual center of the frame empty of any dish, plate, or product — do not generate a subject there. That area is reserved for a separate transparent subject-cutout layer composited on top.",
    "notes": "The reference photo currently on this layer has its own dish baked into the center. When generating a fresh background for a new brief, deliberately crop/prompt that central subject out — it is supplied separately by the circular transparent subject-cutout layer and must not be duplicated in the background itself."
  },
  {
    "layer_id": "d73f71ae-32c9-4e72-ae99-94d780750314",
    "purpose": "subject_cutout",
    "reference_prompt": "Top-down (flat-lay) food photography, subject only, isolated on a transparent background: an alpha-channel PNG with no backdrop, table surface, or baked-in drop shadow. Shot from directly above under soft natural light, styled with visible ingredients/garnish, and framed so the subject fills a circular mask edge-to-edge with no empty corners once cropped. Only the food + vessel silhouette should have pixels; everything else must be true alpha transparency, not white or a solid color.",
    "notes": "This is the floating subject that sits over the background's seam inside this layer's own circular clipPath mask. It must be produced as a genuine alpha-transparent cutout ..."
  }
]
```

`purpose` on each image entry is informational for the model only (helps it understand
"this one sits behind" vs "this one floats on top") — which adapter to call afterward is
still decided purely from our own `transparent`/`kind` fields on the template, never from
the model's output (see "Downstream handling" below).

#### Exact system prompt

```
You are an expert brand designer and art director filling in a fixed template layout
from a user's design request. The template's structure (which layers exist, their
size, and their role) is FIXED — you never add, remove, merge, or reinterpret layers.
Your job has two parts, and both must stay internally consistent with each other and
with the user's request: write the on-brand copy for every text layer, and rewrite the
two reference image prompts so the generated images match the same request.

TEXT LAYERS:
- Write copy for every text layer listed, in the voice implied by the user's request.
- Obey max_chars and max_lines exactly — count characters and line breaks yourself
  before answering. A layer marked "never wraps" or max_lines: 1 must be a single line,
  no exceptions.
- Follow each layer's "notes" field — it describes what kind of phrase belongs there
  (headline vs kicker vs CTA vs label), not just a length limit.
- If a layer's notes contain a CONTACT RULE, follow it exactly: only replace that
  layer's text if the user's request explicitly supplies that kind of information
  (an actual website/phone/address); otherwise return current_text unchanged, verbatim.
- All text layers should read as one coherent piece of marketing copy for the same
  product/offer — not five unrelated sentences.

IMAGE PROMPTS:
- Each reference_prompt encodes a specific composition: layout, camera angle, lighting,
  and style choices that make this template's look work. Preserve that structure.
- Change only what the user's request implies should change: the subject matter,
  color palette, and mood/style words. Do not restate the reference prompt verbatim,
  and do not discard its structural instructions (camera angle, panel layout, "leave
  the center empty", "transparent background, no backdrop", etc.) — those are load-
  bearing and must survive in your rewrite.
- The background and subject prompts must describe a single coherent scene together
  (same product category, same palette, same mood) even though they're generated as
  two separate images later.
- Keep each rewritten prompt roughly the same length and level of detail as its
  reference — a terse rewrite will produce a worse image than the reference did.

Return strictly the JSON schema you were given. Exactly one text_fills entry per text
layer listed above (same layer_id set, no more, no fewer), and exactly one
image_prompts entry per image layer listed above (same layer_id set).
```

#### Exact expected output (schema instance, same example)

```json
{
  "text_fills": [
    {"layer_id": "14819dc3-ee3c-410d-ae88-ef2d6de07b2e", "text": "Craving Something Fresh?"},
    {"layer_id": "86279fff-8f09-48bd-94eb-c0e981c4a67d", "text": "Sip Happy!"},
    {"layer_id": "d151f974-b143-47fd-9b56-d64625400d89", "text": "Vegan\nSmoothies"},
    {"layer_id": "d835c471-0cb3-418d-901c-33f64b5c7140", "text": "NEW FLAVORS\nEVERY WEEK"},
    {"layer_id": "bab7c3c8-d0ce-468c-8faa-311e0d0563ee", "text": "www.yourwebsite.com"}
  ],
  "image_prompts": [
    {
      "layer_id": "ROOT",
      "prompt": "Diagonal two-panel flat-lay background on a square canvas. A solid flat bright lime-green panel fills roughly the left 40% of the frame; the remaining ~60% on the right is a light neutral surface (pale wood or cream stone). ... IMPORTANT: leave the visual center of the frame empty of any cup, bowl, or product — do not generate a subject there. That area is reserved for a separate transparent subject-cutout layer composited on top."
    },
    {
      "layer_id": "d73f71ae-32c9-4e72-ae99-94d780750314",
      "prompt": "Top-down (flat-lay) photography, subject only, isolated on a transparent background: an alpha-channel PNG with no backdrop, table surface, or baked-in drop shadow. A tall glass of bright green vegan smoothie topped with fresh mint and a striped paper straw, shot from directly above under soft natural light, framed so the glass and its garnish fill a circular mask edge-to-edge with no empty corners. Only the glass + garnish silhouette should have pixels; everything else must be true alpha transparency."
    }
  ]
}
```

(the website text above stays unchanged because the example request never mentioned a
URL — the CONTACT RULE in its `notes` did its job)

Note `d151f974`'s text uses `\n` to force a manual line break inside its 2-line budget —
`_clamp_fill` (next section) still validates the result against `max_chars`/`max_lines`
regardless of whether the model added its own breaks or not.

Downstream handling is **identical regardless of which approach produced the data**:
- Clamp every text fill through `_clamp_fill(text, max_chars, max_lines)` — still
  mechanically enforced after the call, never trusted from the model alone.
- Route each image prompt to `registry.transparent_image()` or `registry.text_to_image()`
  based on **our own** `slot.image.transparent`/`meta.background.transparent` from the
  template metadata — never from anything the model returns, so there's no way for the
  model to accidentally request the wrong adapter.
- Locked slots are never included in the request in the first place, and `fill_template`
  still skips `locked=True` as defense in depth.

**Why this is the recommended primary approach:** 1 thinking-model call per request
instead of up to 4 → lower latency and cost; the model sees the copy and both image
prompts together in one pass, so it can keep them thematically coherent (decomposed
calls are blind to each other's output); and it drops the `DesignBrief` dependency for
this flow entirely, which is otherwise machinery built for the generic multi-kind
DesignDoc pipeline and not needed once the template is pinned.

**Known risk:** cramming tightly-constrained short-form copy and long descriptive
photography prompts into one JSON response is two different "skills" in one call — more
surface area for the model to do one part well and the other poorly than two focused
calls would have. This is exactly the risk you flagged, and exactly why 2.3 stays
documented as the fallback rather than being deleted.

**Open item:** contact-style slots (this template only has `website`, no `phone`/
`address`) previously got verbatim-or-blank handling from `DesignBrief.copy_text.contact`
(`compose_ai.py:88-99`) specifically to avoid the LLM hallucinating a fake contact detail.
Under this approach that has to become a prompting instruction instead ("only replace a
website/phone/address slot if the user's prompt explicitly gives one; otherwise return
the slot's own `default_text` unchanged") — lower-stakes for `template_227` since it's
just a placeholder URL, but worth deciding now since it stops being mechanically
guaranteed once `DesignBrief` is out of the loop.

### 2.3 FALLBACK approach: decomposed multi-call (try only if 2.2's quality falls short)

Keep this documented, implement it only if the single-call approach under-delivers on
either the copy or the image-prompt half:

- **Text composition** (`compose_ai.py`, `compose.py`): `_slot_manifest()` gains
  `max_lines` and `notes` per slot, and drops any `locked=True` slot from the manifest
  entirely. `_system_prompt()` states `max_lines`/`notes` explicitly, not just
  `max_chars`. Same `_clamp_fill()` enforcement pass as 2.2. `fill_template()` skips
  `locked=True` slots before writing.
- **Asset generation** (`assets_ai.py`): rework `generate_lido_assets()` so the
  background, if `template.meta.background` is set, is generated via a new helper
  `adapt_image_prompt(reference_prompt, notes, user_prompt)` before calling
  `registry.text_to_image()`; each `photo`-role slot with `slot.image` set gets the same
  treatment, routed to `registry.transparent_image()` if `slot.image.transparent` else
  `registry.text_to_image()`, and skipped entirely if `slot.locked` or
  `slot.image.generate is False`. Falls back to today's hardcoded prompt-building for any
  template without this metadata (backward compatible with templates 1/3/4/5).
- `adapt_image_prompt()` itself: one `complete_json` call per image slot — i.e. this is
  where the "up to 4 calls" count from before comes from (1 brief parse if kept, 1 text
  compose, 1 background adapt, 1 subject adapt). Degrades to the raw reference prompt
  unmodified if the call fails, same pattern `assets_ai.py` already uses.

If you end up needing this path, the natural way to tell is the eval harness in §3:
run the same prompt set through both, compare copy-limit violations, thematic drift
between text/image, and prompt-adherence quality.

### 2.4 Small correctness fix, unrelated but found in research

`routes/lido.py:79` hardcodes `LidoSlotFillInfo.role="text"` for every fill instead of
the slot's real role. One-line fix: pass the actual role through from `result.text_fills`
(needs `compose_lido_content` to return role alongside text, or the route to look it up
from `template.meta.slots`). Included because it's in the exact code path we're already
touching; skip it if you'd rather keep this change minimal.

### 2.5 API surface

- Add `generate_images: bool = True` to `LidoGenerateRequest` (parity with
  `LidoScratchRequest`, which already has this). Lets you iterate on text-fill quality
  during testing without paying for image generation every call. Route passes it through
  to `generate_lido_design(..., generate_assets=body.generate_images)` instead of the
  current hardcoded `True`.
- No other request/response shape changes. `meta` still doesn't need to reach the
  frontend for this to work.

**Optional, not required** — surfacing `template.meta.reference_note` and per-slot
`notes` in `LidoGenerateResponse` plus a small `LidoTest.tsx` display tweak, purely so
that while *you're* testing in the UI you can see why a given fill/image was produced.
Flag in review if you want this; it's a ~10-line addition on top of everything above, not
a prerequisite.

---

## 3. Testing (currently zero coverage for this pipeline — confirmed by research)

New `backend/tests/test_lido_generate_template.py`, exercising `generate_lido_design`
directly (mirroring how `test_lido_scratch_design.py` already tests the scratch path)
with a handful of varied prompts:

- Only `template_227` is ever selected (readiness gate works).
- Every filled text slot respects its `max_chars`/`max_lines` after clamping.
- The logo slot's text/image are byte-identical to the template's defaults (never
  touched).
- The subject slot, when `generate_images=True` and adapters are stubbed/mocked, goes
  through `registry.transparent_image()` not `registry.text_to_image()` — asserted via a
  mock/spy, not a real API call (keeps tests offline).
- `generate_template_fill()` (2.2) degrades sanely when the LLM call fails (repair
  round-trip, then a clear error — no silent fallback to unadapted reference prompts,
  since unlike 2.3 there's no separate adapt step to fall back to).
- The final `document` round-trips through `LidoDocument.model_validate(...)` cleanly.
- Same test file works unchanged if 2.3 is later implemented — it asserts on the
  resulting `document`/fills, not on which approach produced them.

## 4. Out of scope (explicitly, per your answers)

- Multi-template retrieval scoring using rich metadata — deferred until more exemplar
  templates exist; the readiness-gate design in 2.1 means this needs no rework later,
  just more annotated `.json` files.
- Any Anthropic/Claude adapter — none exists in this repo; not adding one.
- Per-call reasoning-effort override, `load_corpus()` caching — noted as follow-ups by
  the research but not needed for "make template_227 generate perfectly," not included.
- `Custom (DesignDoc)` and `Lido.js (scratch)` flows — untouched.

---

## Status

- **2.2 (single structured call) confirmed as the approach to implement now.** §2.3
  (decomposed multi-call) stays documented only, not built unless 2.2 underperforms.
- Contact/website handling resolved: baked directly into the system prompt as an
  explicit CONTACT RULE (see the exact prompt text above), not left as an open question.

## Open decisions still needing your confirmation before implementation

1. **2.1** — readiness gate via `meta.reference_note` presence, vs. hardcoding
   `template_id == "template_227"`. Recommendation: readiness gate.
2. **2.4** — fix the `role="text"` bug while we're in this file, or leave it (unrelated
   to your ask, found incidentally).
3. **2.5 optional** — worth adding `reference_note`/slot `notes` to the response for UI
   debugging while testing, or keep the response shape exactly as-is?
