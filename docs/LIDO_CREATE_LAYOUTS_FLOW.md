# `make lido-create`: the end-to-end flow

This walks through exactly what happens, step by step, when you run
`make lido-create` (built-in recipe mode) or `make lido-create AI=1` (LLM mode): which
file does what, what the LLM is sent and returns, how a layout is checked, and how it
becomes a Lido template file and a preview PNG.

For *why* the layouts are designed the way they are (grid, shapes, photos, fonts), see
[AI_TEMPLATE_GENERATION.md](AI_TEMPLATE_GENERATION.md).

---

## 1. The files involved

| File | Job |
|---|---|
| `Makefile` → `lido-create` | Turns `COUNT=`, `AI=`, `SEED=`, `IDEA=` into script arguments |
| `scripts/lido_create_layouts.py` | The entry point: reads options, runs the loop, saves files |
| `backend/app/lido_create/kit.py` | The ingredients: palettes, fonts, themes, photo pool, the `Element` model, the `Canvas` drawing helpers |
| `backend/app/lido_create/recipes.py` | The 8 built-in layouts, and `mirror()` |
| `backend/app/lido_create/ai.py` | AI mode: builds the prompt, calls the LLM, runs the repair loop |
| `backend/app/lido_create/check.py` | The design checks every layout must pass |
| `backend/app/lido_create/lido.py` | Turns checked elements into real Lido.js JSON |
| `backend/app/lido_create/render.py` | HTML render + headless Chrome screenshot + overview sheet |
| `backend/app/lido_corpus/textfit.py` | *(existing)* measures text with the real font file |
| `backend/app/adapters/openai_adapters.py` | *(existing)* the project's OpenAI client, used for the LLM call |

---

## 2. The whole flow at a glance

```
make lido-create [AI=1]
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. START  (lido_create_layouts.py: main)                    │
│    read options · seed the random generator · find Chrome    │
│    load .history.json · build the photo pool · reserve IDs   │
└───────────────┬─────────────────────────────────────────────┘
                │
     ┌──────────┴───────────┐
     ▼                      ▼
┌──────────────┐     ┌────────────────────────────┐
│ 2a. RECIPE   │     │ 2b. AI MODE                │
│ pick recipe, │     │ pick palette/fonts/theme,  │
│ palette,     │     │ build prompt, call LLM,    │
│ fonts, theme │     │ get element list back      │
│ → recipe     │     │                            │
│ draws        │     │                            │
│ elements     │     │                            │
└──────┬───────┘     └─────────────┬──────────────┘
       │                           │
       ▼                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. CHECK  (check.py: validate)                              │
│    fit · overlap · background · contrast · edges · roles     │
│    recipe mode: fail → throw away, try another combination   │
│    AI mode:     fail → send errors to LLM, repair (≤2 times)  │
└───────────────┬─────────────────────────────────────────────┘
                │ passes
                ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. CONVERT  (lido.py: to_lido)                              │
│    elements → ROOT + ShapeLayer / FrameLayer / TextLayer /   │
│    logo layers · real photo URL · real colours · font URLs   │
└───────────────┬─────────────────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. SAVE + PREVIEW  (save, render.py)                        │
│    template_<id>.json · HTML → Chrome → previews/<id>.png    │
└───────────────┬─────────────────────────────────────────────┘
                ▼   (repeat 2–5 until COUNT templates are made)
┌─────────────────────────────────────────────────────────────┐
│ 6. FINISH  overview.png · .history.json · summary printed    │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Step 1: start-up

`main()` in `scripts/lido_create_layouts.py`:

1. **Parses the options** (`--count`, `--recipe`, `--theme`, `--palette`, `--fonts`,
   `--seed`, `--ai`, `--idea`, `--repairs`, `--out`…). `make lido-create COUNT=3 AI=1`
   becomes `python scripts/lido_create_layouts.py --count 3 --ai`.
2. **Seeds the random generator** with `--seed`. The same seed gives the same choices,
   so a batch can be reproduced.
3. **Finds Chrome/Chromium** for screenshots. If none is found, it still writes the
   templates, just without previews.
4. **Loads `.history.json`** from the output folder: every combination made before, so
   a rerun never repeats one.
5. **Builds the photo pool** (`kit.photo_pool()`):
   - reads every `lidojs_templates/template_*.json`
   - takes each photo frame's image URL (skipping logos), plus that template's `tags`
     and `name`
   - downloads each photo **once** to read its width and height, then caches the size
     in `drafts/.photo_cache.json` (later runs skip the download). It sends a normal
     browser user-agent header, because the CDN returns 403 to Python's default one.
   - skips images under 300px (logos, icons) and transparent cutouts
   - each photo gets **one** theme: the first match in the order fashion → interior →
     food → beauty → education → wellness → business → event
6. **Reserves IDs** (`next_ids`): starting at 90001, it skips every number already used
   by any `template_<n>.*` file anywhere under `lidojs_templates/`.

---

## 4. Step 2a: recipe mode (the default)

`from_recipes()` in the entry script repeats this until it has `COUNT` passing designs:

### 4.1 Choose a combination

| Choice | How it's picked |
|---|---|
| **Recipe** | The 8 recipes are shuffled and taken in order, so each is used once before any repeats |
| **Palette** | Random, but not one already used in this batch (until all 12 are used) |
| **Font pairing** | Same rotation across the 5 |
| **Theme** | Same rotation, but only themes with **enough photos** for this recipe (`twin_photo` needs 2 on-theme photos) |
| **Mirrored?** | 50% chance, only for recipes marked `mirrorable` |

These four choices are bundled into a `Variant` object (palette, fonts, theme, random
generator, photo pool).

If `palette | fonts | theme | recipe | mirrored` is already in `.history.json`, the
combination is skipped.

### 4.2 The recipe draws the layout

The recipe function (for example `split_offer` in `recipes.py`) draws onto a `Canvas`,
back to front. Nothing is Lido JSON yet. It's a list of simple `Element`s with pixel
coordinates and **role names instead of values**:

```python
c.photo(540, 0, 540, 1080, focus=0.3)             # photo, right half
c.logo(M, 60)                                      # logo, top left
k  = c.kicker(t.kicker, x=M, y=235, w=420)         # small line in "accent"
hl = c.headline(t.headline, x=M, y=k.y + k.h + 12, # headline flows under the kicker
                w=430, max_lines=3, start=112, smallest=64)
...
```

Two things happen inside the `Canvas` helpers as they draw:

- **Real measuring.** Every text call measures with the actual font file
  (`textfit.TextMeasure` + `wrap`, the same code the generation pipeline uses) and sets
  the box height to `lines × font size × line height`.
- **Auto-fitting.** `headline(... start=112, smallest=64)` tries 112px, then 110, 108…
  until the copy fits `max_lines` with no word too wide for the box. Anton is narrow and
  Archivo Black is wide, so the same recipe gets a different size in each font.

Because later elements use `hl.y + hl.h`, a headline that wraps to 3 lines pushes
everything below it down. That's why one recipe works with any copy or font.

### 4.3 Mirroring

If the combination is mirrored, `mirror()` flips every element: `x → 1080 − x − w`, and
text alignment flips left ↔ right.

The design then goes to the checks (step 3). **Recipe mode makes no LLM call at all.**

---

## 5. Step 2b: AI mode (`AI=1`), and the LLM call

`from_ai()` in the entry script, then `invent()` in `backend/app/lido_create/ai.py`.

### 5.1 The script picks the "dress"; the LLM only designs the layout

The script chooses the palette, font pairing and theme itself, using the same batch
rotation as recipe mode. Without this, the LLM chose the same beige palette and serif
twice in a row. The LLM's only job is the composition.

### 5.2 What is sent to the LLM

One call with two messages.

**System message** (`SYSTEM` in `ai.py`): the rules of the game.

- **The canvas:** 1080 × 1080, and elements are drawn in list order (first = back).
- **The four element kinds and their fields:**
  - `shape` (rectangle or circle, radius, colour role, opacity, bleed)
  - `photo` (clip `rect` / `rounded` / `circle` / `arch`, focus)
  - `logo` (exactly one, 110 × 89, on a flat colour)
  - `text` (text, text_type, font role, size, align, max_lines, uppercase, letter
    spacing, line height; `h` = 0 because it's measured)
- **The text types:** headline (exactly one, largest), kicker, body, item, cta, badge,
  website / phone / email / address.
- **The colour roles:** bg, ink, accent, on_accent, soft (decoration only).
- **The rules that will be checked**, the same list as step 3, so the model knows what
  gets it rejected.
- **Good-design guidance:** a 70px margin grid, a clear size hierarchy, one element that
  breaks the grid, generic decorations, room for longer copy.

**User message**, built fresh for each layout:

1. **The 8 existing recipes**, one line each (taken from their docstrings), with
   "yours must look clearly different".
2. **Earlier AI layouts from this run**, as "name: idea" sentences, so it doesn't repeat
   itself.
3. **Two complete worked examples**: `split_offer` and `event_invite`, built by the real
   recipe code and serialised in the exact element JSON format. This shows the model
   real coordinates and sizes that are known to pass.
4. **The dress** (`_dress()`): the palette's actual RGB values per role, the display
   font and whether it's set uppercase, and the theme's placeholder copy (kicker,
   headline, body, cta, badge, items, date, contact lines).
5. **The request:** "Invent ONE new layout for it", plus your `IDEA="…"` if you gave
   one, otherwise "Surprise me with the idea."

### 5.3 How the call is made

```python
result = await llm.complete_json(system=SYSTEM, user=user, schema=AIDesign,
                                 temperature=0.9, max_tokens=16000)
```

- `llm` is the project's existing adapter (`app/adapters/registry.py → llm()` →
  `OpenAILLM`). It uses `OPENAI_API_KEY` and `LLM_MODEL` from `backend/.env`, the same
  model the rest of the app uses. With no key, the script stops with a clear message.
- **Structured output:** `schema=AIDesign` is converted to an OpenAI *strict* JSON
  schema (`app/adapters/openai_schema.py`). The model **cannot** reply with anything
  except JSON of this exact shape:

  ```python
  class AIDesign(BaseModel):
      name: str              # e.g. "diagonal_lookbook"
      idea: str              # the composition in one sentence
      elements: list[Element]
  ```

  `Element` is the same model the recipes produce, so AI output and recipe output are
  interchangeable from here on.
- `temperature=0.9` asks for more creative variety. If the configured model is a
  reasoning model that rejects temperature, the adapter drops it automatically.
- One call takes about 30–60 seconds.

### 5.4 After the reply

1. **Normalise** (`_normalise`): fill any loose defaults (font, size, line height,
   alignment), and **re-measure every text height** with the real font. The model's own
   `h` is never trusted. The logo is fixed at 110 × 89.
2. Wrap it as a `Design` (named `ai:<name>`, with the palette, fonts and theme chosen
   in 5.1).
3. Run **the same checks** as recipe mode (step 3).

### 5.5 The repair loop

If any check fails, the script makes another call with:

- the dress again,
- the model's own layout JSON,
- the exact list of failures, for example
  `kicker 'New Collection': straddles the edge of a shape (sits on 2 different colours)`,
- "Return the corrected layout (same idea, fix every problem…)".

This repeats up to `--repairs` times (default 2), so at most 3 LLM calls per layout.

- If it passes: it's saved.
- If it still fails: it's skipped and the failures are printed, unless you pass
  `--keep-failed`, which saves it with a "(N unresolved problems)" note.

---

## 6. Step 3: the checks (`check.py: validate`)

The same function runs for recipe and AI designs. It returns a list of plain-English
problems; an empty list means the design passes.

**How "what's behind the text" is worked out.** For each text, the script takes the
area its letters actually cover (not the whole box: a 420px box holding a 270px line is
only checked on 270px, aligned left, centre or right). It samples 18 points (6 × 3) over
that area. For each point it walks down the stack of layers beneath the text to find the
first shape or photo covering it (circles and arches use their true shape, not their
bounding box). Semi-transparent shapes are blended with what's under them.

| Check | Fails when… |
|---|---|
| Fit | Text wraps to more than `max_lines`, or a word is wider than its box (real font) |
| On a photo | Any sample point lands on a photo |
| Straddling | Sample points land on more than one colour (text crossing a shape's edge) |
| Contrast | Below 4.5:1 for text under 36px, or 3:1 for larger text (WCAG) |
| Covered | A shape, photo or logo is drawn **above** the text at any sample point |
| Overlap | Two texts overlap, or the logo overlaps a text |
| Edges | Text or logo closer than 30px to the canvas edge; a shape or photo off-canvas without `bleed` |
| Logo | Not exactly one, or not on one flat colour |
| Photos | Fewer than 1 or more than 2, or smaller than 200px on a side |
| Counts | Fewer than 3 or more than 9 texts; more than one of any contact type |
| Roles | Not exactly one headline, or another text as large as the headline (the backend loader would take *that* one as the headline) |
| Colour use | Text in the `soft` colour |

**What happens on failure:**
- **Recipe mode:** the combination is thrown away silently and another is tried, up to
  `COUNT × 40` attempts. Pass `--verbose` to see each rejection and its reason.
- **AI mode:** the failures go back to the LLM (5.5).

---

## 7. Step 4: converting to Lido JSON (`lido.py: to_lido`)

Only now does the design become a real Lido export: `[{"layers": {...}}]`.

| Element | Becomes | Details |
|---|---|---|
| (canvas) | `ROOT` `RootLayer` of type `bgImage` | `color` = the palette's bg, `image: null`, so the whole background is recolourable and needs no background prompt |
| shape | `ShapeLayer` | Colour role → `rgb(...)`; `circle` or `rectangle`; corner radius → `roundedCorners` (≈ 4 × px, approximate); opacity → `transparency`; `scale` = 1080 ÷ 213.33 as Lido writes it |
| photo | `FrameLayer` | **The photo is picked here** (`pick_photo`): prefer unused → on-theme → closest shape. `clipPath` is drawn in a 500-unit-wide space (rect / rounded / circle / arch), `scale` = width ÷ 500, and the image is "cover"-fitted: scaled to fill, centred horizontally, vertical position from `focus` |
| logo | `FrameLayer` of type `logo` | Looks at the colour behind it and picks `logo_white.png` on dark colours or `logo_black.png` on light ones |
| text | `TextLayer` | ProseMirror `doc` with font, size, colour, alignment, line height, letter spacing, uppercase; `fonts` carries the real gstatic `.ttf` URL; box height from the measured lines |

Each layer gets a new UUID and is appended to `ROOT.child` in element order, which is
the stacking order.

The text types map to Lido's `type.type`, which is what the backend loader uses to
assign roles later:

| Element text_type | Lido `type.type` | Role the loader gives it |
|---|---|---|
| headline, kicker, body, item | `bodyText` | largest → headline, next → subhead, rest → body |
| cta, badge | `static` | label |
| website, phone, email, address | `website`, `phoneNumber`, `email`, `address` | the same contact role |

---

## 8. Step 5: save and preview

`save()` in the entry script:

1. Writes `drafts/template_<id>.json`.
2. **Preview** (`render.py`):
   - `html()` draws the layers as plain HTML: text as `div`s (wrapping like the Lido
     editor), shapes as coloured `div`s, photo frames as SVG with the same `clipPath`
     and image offsets, and fonts loaded from their gstatic URLs.
   - `screenshot()` opens that page in headless Chrome and screenshots it. The window
     is 300px taller than the canvas (Chrome's viewport is a bit shorter than its window
     size), then the image is cropped to exactly 1080 × 1080.
   - Result: `drafts/previews/template_<id>.png`.
3. Prints one line: `template_90006  split_offer  food  navy-amber  modern-serif  mirrored 6 texts`.

---

## 9. Step 6: finish

- `overview.png`: every preview from this run on one contact sheet, 4 per row.
- `.history.json`: updated with the new combinations (recipe mode only).
- The paths are printed.

Then it's your turn to review. Moving a keeper into the corpus hands it to the normal
pipeline:

```bash
mv lidojs_templates/drafts/template_N.json lidojs_templates/
mv lidojs_templates/drafts/previews/template_N.png lidojs_templates/previews/
make lido-add TEMPLATE=template_N KIND=post
```

From there `make lido-add` drafts the `meta` block (a separate LLM + vision call that
reads the preview PNG), verifies it and adds the template to the database. Nothing from
`lido-create` changes that step.

---

## 10. A worked example: one AI layout from start to finish

`make lido-create AI=1 COUNT=1`:

```
collecting placeholder photos from the corpus...          ← step 1 (cache hit, instant)
writing to lidojs_templates/drafts/
  asking the LLM for layout 1/1 (fashion, sky-cobalt, tall-caps)...   ← 5.1 dress chosen
    ai attempt 1: 'diagonal_lookbook' — passes            ← 5.2–5.4 + step 3
  template_90006  ai:diagonal_lookbook fashion  sky-cobalt  tall-caps  6 texts   ← steps 4–5
```

In detail:

1. The script picks the fashion theme, the `sky-cobalt` palette and the Bebas Neue font
   pairing, and reserves ID 90006.
2. The prompt carries the rules, the 8 recipe summaries, 2 example layouts, sky-cobalt's
   RGB values, "Bebas Neue, set headlines uppercase", and the fashion copy ("Summer
   Style Sale", "50% Off", "Shop Now"…).
3. The LLM replies with strict JSON: name `diagonal_lookbook`, a one-sentence idea, and
   around 10 elements (two offset photos, a cobalt "50% OFF" tab, a headline, body, a
   button, a website line, the logo).
4. Text heights are re-measured, then all checks pass on the first attempt.
5. `to_lido` picks two fashion photos (the portrait and the full-length shot), picks the
   logo colour for the pale background, and writes the layers.
6. Chrome renders the preview; `template_90006.json` and its PNG are saved.

If the check in step 4 had failed (say the badge text straddled the photo edge), the
script would send the layout plus
`badge '50% Off': straddles the edge of a shape (sits on 2 different colours)` back to
the LLM, and you would see `ai attempt 2: … — passes` on the next line.

---

## 11. Cost and time

| Mode | LLM calls | Time per template |
|---|---|---|
| Recipe (default) | **0** | ~2–4 s (mostly the Chrome screenshot) |
| AI (`AI=1`) | 1, or up to 3 with repairs | ~30–60 s per call |

The first run downloads each corpus photo and font once. Later runs use the caches
(`drafts/.photo_cache.json`, `lidojs_templates/fonts/`).

---

## 12. Designing from a prompt in the UI ("Design new template" tab)

The web app's **Design new template** tab (`frontend/src/pages/DraftStudio.tsx`) takes a
free-text prompt, the kind you'd give a designer, and designs a brand-new template
from it: layout, decoration, colours, fonts **and the copy**, all from the prompt.

```
UI prompt ──► POST /v1/lido/drafts {prompt, variations 1–3}
                 │  (app/api/routes/lido_drafts.py; prompt screened by screen_prompt)
                 ▼
        drafts.create_from_prompt()                 app/lido_create/drafts.py
                 │  photo pool loaded (cached corpus photos)
                 │  one creative direction per variation (none for a single design)
                 ▼  variations run in parallel
        brief.design_from_brief()  ×N               app/lido_create/brief.py
                 │  1 LLM call: layout + colours + fonts + copy + photo subjects
                 │  check.validate() → failures sent back for repair (≤ 2 rounds)
                 ▼
        photos.resolve_photos(source)               app/lido_create/photos.py
                 │  CachedPhotos today: a corpus photo per frame
                 ▼
        drafts.save_draft()  →  template_<id>.json + previews/<id>.png + <id>.info.json
                 ▼
UI shows the preview, idea, colours, fonts, photo subjects and check status,
and lists every draft (GET /v1/lido/drafts) with open / download / delete.
```

### What differs from `AI=1` in the CLI

| | CLI `AI=1` | UI prompt (`/v1/lido/drafts`) |
|---|---|---|
| Colours | Picked from the 12 palettes by the script | **Chosen by the LLM to match the prompt** (any 5 hex colours, contrast still checked) |
| Fonts | Rotated by the script | Chosen by the LLM from the 5 font sets, by their described character |
| Copy | The theme's placeholder copy | **Written from the prompt**: the user's own headline, price, offer, CTA and contact are used exactly when given |
| Photos | Placeholder | Placeholder, plus a `subject` per photo saying what it should show |
| Variety | "Different from the recipes and earlier layouts" | Each variation gets a different **creative direction** (asymmetric split, magazine cover, photo-dominant, typographic, layered, minimal, grid, framed) |

### The extra rules the LLM gets for prompts (`BRIEF_RULES` in `brief.py`)

- Use the client's exact copy; placeholders only when the prompt gives none.
- At most 9 text boxes. A long feature list is cut to the 3 most important items.
- One text box is one paragraph: no line breaks, no emoji, bullets or icon characters.
  Two checks enforce this (`check.py`), so the repair loop fixes it.
- Visual effects in the prompt (glow, reflections, lighting) go into the photo
  `subject`, not into shapes.
- The headline dominates (typically 90–140px), and the creative direction is mandatory.

### The API

| Method | Path | Does |
|---|---|---|
| POST | `/v1/lido/drafts` | `{prompt, variations}` → the new drafts, each with its document |
| GET | `/v1/lido/drafts` | Every draft, newest first (no documents) |
| GET | `/v1/lido/drafts/{id}` | One draft with its document |
| GET | `/v1/lido/drafts/{id}/preview.png` | Its screenshot |
| DELETE | `/v1/lido/drafts/{id}` | Removes its JSON, info file and preview |

A request takes ~30–120 s: one LLM call per variation, in parallel, plus any repairs.

### Adding image generation later

Only one function changes: `photo_source()` in `app/lido_create/drafts.py`. Today it
returns `CachedPhotos`. A generating source implements the same
`photo_for(element, variant)` using `element.subject` as the image prompt
(`registry.text_to_image()`), uploads the result, and returns a `Photo` with its URL and
size. The sketch is in the docstring of `app/lido_create/photos.py`. The designer, the
checks, the Lido writer and the UI don't change. The info file already records
`photoSource`, so each draft shows which source filled it.
