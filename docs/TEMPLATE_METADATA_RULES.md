# Lido.js template metadata — authoring rules

`lidojs_templates/` holds the templates: raw Lido.js exports (`layers`) plus a
hand-authored `meta` block. `meta` is **not** read by the Lido editor — it exists purely so
`app.lido_corpus` (retrieval, composition, asset generation) and any future
template-generation pipeline have something structured to reason about, and so a rich
template like `template_227.json` can serve as a reference exemplar for generating new
ones.

`lidojs_templates/template_227.json` is the canonical example. Read it alongside this file.

## How the Lido.js (template) flow uses this metadata

`POST /v1/lido/generate` (`app/lido_corpus/pipeline.py`) picks a template with the
automatic match (every template here is a candidate — see `new_match_plan.md`), then
makes **one** LLM call that receives, straight from `meta`: every unlocked text slot's
`default_text`/`max_chars`/`max_lines`/`notes`, and every generated image's `prompt`/
`notes` (`meta.background` plus each slot `image`). The model returns all the copy and
all the image prompts at once, keyed by `layer_id`.

Two consequences for authoring:

- **`notes` and `prompt` are read by the model verbatim.** Write them for a designer, not
  a developer: no code names, field paths or file references. Say what the layer is and
  how it sits in the composition.
- **Limits are enforced, not just suggested.** After the call, every text is measured
  with the layer's real font (see "Text layers" below); anything over `max_chars` or
  `max_lines`, or with a word too wide for the box, gets one repair call and is trimmed
  mechanically if it still doesn't fit. A wrong limit therefore squeezes every
  generation — check them against the template's own copy.

## How `meta` is computed and preserved

`app/lido_corpus/loader.py:derive_meta()` runs on every load (API request, `python
scripts/enrich_lido_templates.py`, etc.) and **recomputes geometry-derived fields from
the layers every time** — `role`, `editable`, `default_text`, `font_size`, `position`,
`box_size`, `aspect`, `canvas_size`, `background_image_url`, `text_layer_count`. Never
hand-edit those; they can never drift out of sync with the actual document because they
aren't trusted from the file, only recomputed.

Everything else in `meta` is **human-authored** and is merged back in from the
existing file on every recompute, keyed by `layer_id` for per-slot fields:
`name`, `kind`, `tags`, `description`, `reference_note`, `background`, and per-slot
`max_chars`, `max_lines`, `locked`, `image`, `notes`. Set these by hand (or via an LLM
enrichment pass whose output you review) and they will survive re-enrichment.

Practical implication: if you add a new layer to a template that already has a `meta`
block, only that new layer needs metadata — everything else stays. If you delete a
layer, its stale slot entry in `meta.slots` is dropped automatically (slots are always
rebuilt from the current layer set; only matching `layer_id`s carry data forward).

## One object per layer

Each layer in `layers` must represent exactly one design object — one background, one
logo, one text block, one photo/subject frame, one shape. Don't combine two concerns
into a single layer (e.g. don't bake a subject *and* a background into one `bgImage`
layer, don't put two sentences with different roles in one `TextLayer`). This keeps the
1:1 mapping between a layer and a `meta.slots` entry (or `meta.background` for `ROOT`)
clean, which is what makes per-layer generation instructions possible at all.

## Layer roles and what metadata they need

### `ROOT` (background) — `meta.background`

`ROOT` never gets a `meta.slots` entry (see `_extract_slots`, which explicitly skips
it); its generation spec lives in the sibling `meta.background` field instead. Fill in
an `ImageSpec`:

- `kind: "background_photo"`
- `generate: true` unless this template intentionally reuses a fixed background
- `transparent: false` — backgrounds are opaque, full-bleed
- `prompt` — the **exact, reusable image-generation instruction**. Describe the actual
  composition (panel layout, colors, where accent elements sit, lighting/style), not
  just "a food background". Specific enough that regenerating from the prompt alone
  reproduces the same *kind* of image, with the brief's own subject/palette swapped in.
- `reference_url` — the asset currently on this layer, for visual reference
- `notes` — anything a generator must know that isn't a style instruction. The most
  common one: **if a foreground subject-cutout layer sits on top of this background,
  say so explicitly and tell the generator to leave that area empty** (see below).
  The other: **text colours are fixed by the template, so state the contrast the
  background must keep.** `template_227`'s text is always white; a "soft peach and
  cream" request once produced a pale left panel with unreadable white copy until the
  notes said that panel must stay saturated and medium-to-dark.

### A foreground subject — transparent cutout vs. cover-cropped photo

A `FrameLayer` with `role: "photo"` can be filled two different ways, and metadata must
say which:

1. **`subject_cutout`** — an alpha-transparent PNG containing only the subject (no
   backdrop, no baked-in shadow), typically masked into a shape via the layer's own
   `clipPath`. Use this whenever the layer is meant to *float* over the background —
   i.e. the background is visible around/behind it, or the mask shape isn't a plain
   rectangle. Set `image.transparent: true` and write a `prompt` that explicitly asks
   for an isolated subject on a transparent background, framed to fill its mask
   edge-to-edge.
2. **`background_photo`-style opaque photography, cover-cropped by `clipPath`** — an
   ordinary rectangular photo that Lido crops into a shape at render time. It only
   looks identical to a true cutout when the subject happens to fill its mask exactly
   with no gaps — otherwise the photo's own background shows through inside the mask,
   unlike a real cutout which would show the *template's* background there instead.

The pipeline picks the image adapter from `image.transparent` alone (`true` → native
transparent generation, `false` → ordinary text-to-image), never from anything the model
says, so this flag is what decides whether you get a real alpha cutout.

If you're not sure which one a layer needs, look at whether the mask shape is a
non-rectangular crop sitting over patterned/colored background (→ almost certainly needs
`subject_cutout`) or a plain rectangle tucked into an otherwise photo-free area (→ opaque
cover-cropped photo is fine, and simpler to generate).

Either way, set `image.kind`, `image.transparent`, `image.prompt`, and `image.notes`
(e.g. "this must fill the mask completely — no empty corners" or "clipPath crops this
into a circle at render time; keep the source image a full rectangle").

### Logo — never regenerated

Logo layers (`type.type: "logo"`, `role: "logo"`) are brand assets, not generated
content:

- `locked: true` on the slot
- `image.kind: "logo_static"`, `image.generate: false`
- `image.reference_url` pointing at the current logo asset
- A `notes` line saying so explicitly, so an automated filler or a future human skimming
  the file doesn't assume it's fair game

A logo slot is only ever *swapped* (a different brand supplies its own logo file), never
recolored, re-cropped, or run through image generation.

### Text layers — fixed count, explicit limits

A template ships with an exact number of text layers. When using a template as a
generation reference, **that count is fixed** — a generator must fill the existing
slots, not add new ones or drop existing ones. Record the count in
`meta.text_layer_count` (computed automatically — don't hand-set it) and reinforce the
rule in `meta.reference_note` if the template is meant as an exemplar.

For every text slot, set:

- `max_chars` — a real ceiling for *this* slot's role and font size, not just the
  auto-computed `len(default_text) * 1.4 + 8` fallback (that formula is only a safety
  net for slots nobody has reviewed yet). A single-line CTA and a three-line promo block
  need very different limits even at similar font sizes.
- `max_lines` — set this whenever a slot's visual role depends on staying short (a
  script-accent phrase that must never wrap, a headline capped at two lines). Leave it
  `null` only when wrapping to any number of lines is genuinely fine. Base it on what
  the box actually holds — box height ÷ (font size × line height) — and on how the
  default copy really sets in the reference render: `template_227`'s promo block
  ("Limited Happy Hours Promo") sets as four one-word lines, so its limit is 4, not 3.
- `notes` — the slot's *function*, not just its current copy: what kind of phrase goes
  here, how many words is reasonable, whether it's a question/CTA/label/offer. This is
  what lets a generator write appropriate new copy instead of just obeying a character
  count.

Line wrapping is measured, not estimated from a character count: a character count
can't tell that "Smoothie" (239px in Yeseva One at 50px) overflows a 200px headline box
that "Healthy" (196px, same letter count) fits. `app/lido_corpus/textfit.py` wraps each
text with the layer's actual font, size, `textTransform` and `letterSpacing`. Fonts are
cached in `lidojs_templates/fonts/` (gitignored), downloaded on first use from the URL
the layer's own `props.fonts` carries or, when that list is empty (as it is for Yeseva
One in `template_227`), from Google Fonts by family name. A font that can't be fetched
falls back to an estimate, so keep the family name a real Google Fonts family.

Roles (`role` on each slot) are inferred automatically from `type.type` and relative
font size (see `_role_for` in `loader.py`) — largest `bodyText` layer becomes
`headline`, second-largest becomes `subhead`, the rest become `body`. You don't set
`role` by hand; if the inferred role is wrong for a template's actual design intent, say
so in that slot's `notes` rather than fighting the inference.

## Template-level fields

- `name` / `kind` / `tags` / `description` — short, human-facing summary. `kind` is one
  of `post`, `story`, `poster`, `banner`, `thumbnail`, `ad`, `flyer`.
- `reference_note` — records that a human reviewed the template; add it only once every
  slot's metadata is authored and checked. State the composition family in one sentence,
  then say explicitly what varies per brief (background subject/palette, cutout subject,
  text copy) versus what's structurally fixed (layer count, roles, the logo slot). It is
  for humans, not sent to the model, and it does **not** limit the automatic match:
  every file in `lidojs_templates/` that has a `meta` block is a candidate (new_match_plan.md). So a generated design
  (saved to the `lido_generations` DB table, not to disk — see
  `infra/initdb/002_lido_generations.sql`) must be reviewed *before* it is saved into `lidojs_templates/` as
  a new file; its note is cleared on purpose to show it has not been reviewed.

## Adding a new template

The full start-to-end checklist is in the README ("Adding a new template — start to
end"). In short:

1. Drop the raw Lido export (`[{"layers": {...}}]`, no `meta`) into `lidojs_templates/` as
   `template_<id>.json`. A file with no `meta` block is ignored by matching and is not
   copied to the database until step 2.
2. `make lido-add TEMPLATE=template_<id>` (or `make lido-add` for every template not
   yet in `lido_templates`) — drafts the complete `meta` (LLM + vision; only empty
   fields are filled; skipped entirely if the file already verifies cleanly), verifies
   every mechanical rule in this file, and adds the template to `lido_templates` with
   its embedding. A verification error skips just that template (others in the same
   batch still go through) and tells you what to fix. A template already in the
   database is left untouched — see `make lido-sync` for pushing later edits.
3. Review and hand-edit the draft against the rules above, with `template_227.json` as
   the reference. Always compare the background prompt with the actual picture, and make
   sure `name`, `description` and `tags` say what the template is for — matching reads
   them.
4. Check the template's own copy against its own limits with the real font — if it
   doesn't fit, the limits are wrong, not the copy:

   ```bash
   cd backend && .venv/bin/python -c "
   from app.lido_corpus.loader import load_enriched, DEFAULT_CORPUS_DIR
   from app.lido_corpus.generate_ai import text_targets, check_text
   t = load_enriched(DEFAULT_CORPUS_DIR / 'template_N.json')
   for x in text_targets(t): print(x.slot.role, check_text(x.slot.default_text, x) or 'OK')"
   ```

5. Add `meta.reference_note` once reviewed (it records the review; every template with
   `meta` is a match candidate either way).
6. Add a test request for it to `backend/app/lido_corpus/match_cases.jsonl`, then
   `make lido-sync TEMPLATE=...` and `python scripts/lido_match.py test`. Later edits: edit the file, then
   `make lido-sync` (or let the running API pick it up within
   `LIDO_TEMPLATE_SYNC_SECONDS`); only templates whose `meta` changed are re-embedded.
