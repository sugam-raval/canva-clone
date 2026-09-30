# Roadmap: more variety in AI-designed templates

This is the step-by-step plan to make the AI designer (the **Design new template** tab
and `make lido-create AI=1`) produce more varied and more creative templates, closer
to Canva AI.

Fonts, photos and canvas size stay as they are for now. This plan is only about
**shapes, effects (like gradients) and creative layout**.

Do the steps in order. Each step ends with a **"Done when"** check, so you know it
worked before you move on.

---

## Before you start: 3 rules to remember

**Rule 1: Lido must be able to draw it.**
Our preview is our own renderer. The real editor is Lido.js. If we write a property
Lido doesn't know, the preview looks fine but the editor shows nothing. So every new
shape or effect must be **tested once in the Lido editor**.

**Rule 2: Decoration must change colour with the user's palette.**
This is Rule 1 of `docs/TEMPLATE_DESIGN_GUIDE.md`. If a shape keeps its own colour
forever, it clashes when a user picks their brand colours.

**Rule 3: Every new thing touches the same 6 places.**

| # | Place | File | What you add |
|---|---|---|---|
| 1 | The element model | `backend/app/lido_create/kit.py` → `Element` | the new field or value |
| 2 | Lido JSON writer | `backend/app/lido_create/lido.py` | how it is written into the template |
| 3 | Preview renderer | `backend/app/lido_create/render.py` | how it is drawn in the PNG |
| 4 | Design checks | `backend/app/lido_create/check.py` → `covers()` | its outline, so text-on-shape checks work |
| 5 | Palette recolour | `backend/app/lido_corpus/palette.py` → `apply_theme` | how its colour changes with the palette |
| 6 | AI instructions | `backend/app/lido_create/ai.py` → `SYSTEM` | one line on what it is and when to use it |

Plus: **one test** in `backend/tests/test_lido_create.py` and **one draft** opened in
the Lido editor.

---

## Step 0: Find out what Lido can draw (about 15 minutes)

**Why:** everything else depends on the exact property names Lido uses.

**What to do:**

1. Open the Lido editor and start a new blank 1080 × 1080 design.
2. From the shapes panel, add **one of every shape** it offers (triangle, star, arrow,
   heart, line, polygon… whatever is there).
3. Give one shape a **gradient fill**, if the editor has that option.
4. Give one shape an **outline only** (no fill), if possible.
5. Add one text with a **shadow** or **outline** effect, if the editor has it.
6. Add one **line** element, if there is one.
7. Export the design as JSON and save it as `test/lido_capabilities.json`.

**Then:** look in the JSON for each shape layer's `"shape": "..."` value and any new
property names (for example `gradient`, `shadow`, `strokeDasharray`). Write them in a
short list at the top of this file under "Lido supports".

**Done when:** you have a list like:

```
Lido supports:
- shape names: rectangle, circle, octagon, triangle, star, ...
- gradient: yes/no, property name: ...
- outline-only fill: yes/no, how: ...
- text shadow: yes/no, property name: ...
```

---

## Step 1: Make each new shape a single entry

**Why:** today a new shape must be added in 4 files (writer, preview, checks, AI
text). If you put it in one place, each new shape becomes quick and safe.

**What to do:**

1. Create `backend/app/lido_create/shapes.py`.
2. In it, make one small class or dict entry per shape, holding:
   - `name`: e.g. `"starburst"`
   - `lido`: how to write it (the Lido `shape` name, or a crop path, see Step 2)
   - `outline(x, y)`: returns True if a point is inside the shape (for the checks)
   - `preview_css` or `svg_path`: how to draw it in the preview
   - `ai_hint`: one short sentence for the AI, e.g. *"starburst: a spiky badge for
     SALE / % OFF"*
3. Change `lido.py`, `render.py` and `check.py` so they **look up the shape in this
   registry** instead of having their own `if shape == ...` code.
4. In `ai.py`, build the shape list in the `SYSTEM` text from the registry
   (`ai_hint` of every entry), so the AI always knows every shape.
5. Move the existing shapes (rectangle, circle, and the photo crops hexagon, diamond,
   blob, leaf) into the registry first. Nothing new yet.

**Done when:** all tests still pass (`make test`), and `make lido-create COUNT=5`
gives the same kind of results as before.

---

## Step 2: Add new shapes

There are two ways to add a shape. Use **Way A** whenever Step 0 says Lido has it.

### Way A: Lido already has the shape

Just add a registry entry that writes `"shape": "<Lido's name>"` on a `ShapeLayer`.
It recolours automatically, because `palette.py` already recolours every
`ShapeLayer.color`.

### Way B: Lido does not have the shape

Use this trick: a **photo frame (`FrameLayer`) can be cropped to any outline**, using
`clipPath`. If you put a **plain one-colour image** inside it, it looks exactly like a
filled shape of any outline: a wave, a starburst, a ribbon.

How:

1. Draw the outline as an SVG path in a 500 × 500 box (like `BLOB_500` in `lido.py`).
2. Make a small one-colour PNG (e.g. 64 × 64) with Pillow, upload it to the asset
   store (`app/storage/assets.py`), and use its URL as the frame's image.
3. **Recolour (important):** mark these frames, for example with
   `"type": {"type": "colorShape", ...}` plus the colour role, so the pipeline knows
   they are colour shapes, not photos. In `palette.py`, when a palette is applied,
   make a new PNG in the new colour and swap the URL.
4. Make sure the loader does not treat these frames as photo slots. In
   `backend/app/lido_corpus/loader.py` → `_role_for`, return `"decoration"` for them,
   or the pipeline will try to regenerate them as photos.

### First shapes to add (in this order)

| Shape | What it is used for | Easy outline idea |
|---|---|---|
| `triangle` | corner accents, arrows | 3 points |
| `chevron` | "next" arrows, direction | 6-point arrow |
| `starburst` | SALE, 50% OFF badges | 16–24 alternating outer/inner points |
| `ribbon` | offer labels with a notched end | rectangle + V cut on one side |
| `speech_bubble` | testimonials, "New!" | rounded rect + small triangle tail |
| `half_circle` | corner and edge accents | half of the circle path |
| `wave_band` | curved top of a footer/header | rectangle whose top edge is 2–3 curves |
| `dashed_line` | dividers | a row of short thin rectangles |

For each shape:

1. Add the registry entry (Step 1).
2. Write its `outline()`. For polygons, reuse `_in_polygon` in `check.py`. For curvy
   shapes, a polygon approximation is fine.
3. Add a test: build one element, check `covers()` is True inside and False outside.
4. Generate one draft that uses it and **open it in the Lido editor** (Rule 1).

**Done when:** the new shape appears in AI designs (run
`make lido-create AI=1 COUNT=3 IDEA="big starburst badge"`), and looks the same in the
editor as in the preview.

---

## Step 3: Gradients, patterns and glows

These are all made the same way: **our code draws a small image, no AI needed.**

| Effect | How to make the image (Pillow) | Where to use it |
|---|---|---|
| Linear gradient | blend colour A → colour B across the image | backgrounds, panels, bands |
| Radial gradient (spotlight) | colour in the centre fading outwards | behind the headline or product |
| Stripes | alternating thin bands, then rotate | corner patches, panels |
| Halftone dots | dots getting smaller across the image | textures in empty corners |
| Soft glow | a blurred circle with transparency | "premium", "tech", "night" looks |

**What to do:**

1. Create `backend/app/lido_create/fills.py` with one function per effect, e.g.
   `linear_gradient(color_a, color_b, angle) -> PNG bytes`.
2. Use the colour **roles** (`accent`, `soft`…), not fixed colours, so it follows the
   palette.
3. Put the image either:
   - on **ROOT** as the background image (`ROOT.props.image`), with
     `meta.background.generate = false` so the pipeline keeps it instead of generating
     a photo, or
   - in a **frame with a crop path** (Step 2, Way B) for gradient panels and shapes.
4. **Recolour:** same as Step 2 Way B. Store which effect and which colour roles were
   used, so `palette.py` can redraw the image in the user's colours.
5. **Checks:** text on a gradient has no single colour. In `check.py`, treat a
   gradient as its **darkest and its lightest colour**, and require the text contrast to
   pass against **both**.
6. Add to the AI instructions: which effects exist and when to use them (e.g. *"radial
   spotlight behind the product for premium/tech briefs"*).

If Step 0 shows **Lido has a native gradient property**, use that instead of images.
It's simpler and recolours more easily.

**Done when:** a prompt like *"premium tech launch with a glowing spotlight"* gives a
design with a gradient or glow, and it recolours when you pick a palette in the
**Fill a template** tab.

---

## Step 4: A library of ready-made components (the biggest quality jump)

**Why:** today the AI places every small shape by coordinates, which is hard for it.
Canva works from **ready-made elements**. Give the AI named components and it only
has to say where to put them.

**What to do:**

1. Create `backend/app/lido_create/components.py`.
2. Write each component as a small function, like the recipes in `recipes.py`, that
   draws a group of shapes and texts onto the `Canvas`, e.g.
   `offer_badge(c, x, y, size, lead, text)`.
3. Add a new element kind `"component"` to `Element` in `kit.py`, with fields
   `component` (the name) and `params` (a small dict: texts, style).
4. In `ai.py` → `normalise()`, **expand** each component into its shapes and texts,
   the same way `dots` is expanded today.
5. List every component in the AI instructions with one line each, and show one in the
   example layout.

**First components to build:**

| Component | What it looks like |
|---|---|
| `offer_badge` | circle or starburst: "UP TO" + "50% OFF" (already exists as `_offer_badge` in `recipes.py`; move it) |
| `price_tag` | outlined tag: "ONLY" + price (already inside `fresh_promo`; move it) |
| `contact_block` | label + value + ring marker (already `Canvas.contact_block`) |
| `ribbon_label` | ribbon shape with a short text |
| `feature_list` | 3–4 items, each with a bullet marker, evenly spaced |
| `numbered_steps` | 1-2-3 circles with a short text beside each |
| `quote_block` | big quote mark + text + name line |
| `date_block` | big day number + month + time |
| `corner_frame` | L-shaped lines in 2 or 4 corners |
| `photo_polaroid` | photo with a thick white border, slightly rotated |

**Background styles** (also components, drawn first):
`diagonal_split`, `wave_footer`, `spotlight`, `inset_frame`, `corner_blobs`,
`half_panel`.

**Done when:** AI designs use components (look at the `layout` in the draft's
`.info.json`), and fewer designs fail the checks (see `attempts` in the same file).

---

## Step 5: The variety engine

**Why:** the AI tends to repeat itself. These steps push it to do something new.

Do these one at a time:

1. **More creative directions.** In `brief.py`, grow `DIRECTIONS` from 8 to 30 or
   more. Mix a layout type + a background style + a mood, e.g. *"diagonal split,
   spotlight glow, bold and loud"*.
2. **Rotate the examples.** In `ai.py`, `EXAMPLE_RECIPES` is always the same 2
   layouts. Keep a longer list and pick 2 at random per call.
3. **Remember past designs.** After each design, save a short "fingerprint" (the
   direction + component names + where the photo sits) in the draft info. Before a new
   design, send the last 10 fingerprints and say *"make it different from these"*.
4. **Pick the best of 3 (quality boost).** Make 3 variations → render the PNGs →
   send the 3 images + the prompt to a **vision model** with a short checklist (clear
   hierarchy, balance, not crowded, fits the brief) → keep the best one. The
   enrichment script already calls a vision model (`_vision_json` in
   `scripts/enrich_lido_templates.py`), so copy that pattern.
5. **One self-critique round (optional).** Send the winner's PNG back to the vision
   model: *"what 2 things would a senior designer fix?"*, then one repair call with that
   feedback.

Note: 4 and 5 cost about 2–4× more API calls per design. Make them a checkbox in the
UI ("Best quality").

**Done when:** 10 designs from the same prompt look clearly different from each
other.

---

## Step 6: Learn from your reviews

**Why:** your taste is the best guide. Let the library grow from what you like.

**What to do:**

1. In `frontend/src/pages/DraftStudio.tsx`, add 👍 / 👎 buttons on each draft.
2. Save the vote into the draft's `.info.json` (new API route
   `POST /v1/lido/drafts/{id}/vote` in `backend/app/api/routes/lido_drafts.py`).
3. Add a **"Use as example"** button on 👍 drafts. It copies the design's elements into
   a new example list that Step 5.2 picks from.
4. Use 👎 designs as "don't do this" fingerprints in Step 5.3.

**Done when:** after a week of use, new designs look more like the ones you liked.

---

## Suggested order and effort

| Order | Step | Effort | Gain |
|---|---|---|---|
| 1 | Step 0: what Lido can draw | 15 min | needed for everything |
| 2 | Step 1: shape registry | ½ day | makes the rest fast |
| 3 | Step 4: components | 1–2 days | biggest quality jump |
| 4 | Step 2: new shapes | 1 day + ~1 hr per shape | visible variety |
| 5 | Step 3: gradients and effects | 1–2 days | "premium" looks |
| 6 | Step 5: variety engine | 1–2 days | stops repetition |
| 7 | Step 6: feedback | ½ day | keeps improving by itself |

---

## After every step: the checklist

- [ ] `make test` passes
- [ ] `make lint` passes
- [ ] `make lido-create COUNT=5` still works (built-in layouts)
- [ ] `make lido-create AI=1 COUNT=3` works and uses the new feature
- [ ] one new draft opened in the **Lido editor** looks the same as its preview PNG
- [ ] the new feature changes colour when a palette is applied
- [ ] section 13 of `docs/LIDO_CREATE_LAYOUTS_FLOW.md` updated with what you added
