---
name: lido-manual-meta
description: Hand-author the `meta` block of a Lido.js template in lidojs_templates/ without the enrichment script — read the layers, the finished-template screenshot and the background image, fix export defects, write the background prompt, text limits and notes, then verify read-only. Use when the user asks to add or write metadata for a template "manually", "by yourself", "custom" or "without the script".
argument-hint: <template_id> [extra instructions]
---

# Manual metadata for a Lido template

The argument is the template id (`template_11792` or just `11792`), optionally followed by
extra instructions from the user. Those override the defaults below.

## Input — ask only for what's missing

- **Template file:** `lidojs_templates/<id>.json`. Required.
- **Finished-template screenshot:** `lidojs_templates/previews/<id>.png` (or `.jpg`/`.webp`),
  or an image attached in the chat (then save a copy there too). If neither exists, ask for
  it before writing anything; it's the only way to know what each element is for.
- **Background image:** don't ask for it. Take the URL from the JSON (`ROOT.props.image`,
  or the `bgImage`-typed child of ROOT) and download it into your scratchpad directory with
  a browser user agent (the asset host rejects bare requests), then view it with Read:
  `curl -sL -A "Mozilla/5.0" -o <scratchpad>/bg_<id>.png "<url>"`
  When ROOT has no image and no `bgImage` child, the background is usually the first,
  full-canvas ImageLayer child (see "Background as a plain full-canvas ImageLayer" in step 2).
- **Logo layer:** the layer whose `type.type == "logo"`. If no layer is typed `logo`,
  **stop and ask the user which layer is the logo** (list the image/frame layers with
  their id, position and size) before changing anything. Never guess it from the picture.
- **Embedded images.** Some exports carry every image as a `data:image/...;base64,` URI
  (the file is then several MB on one line). Truncate URLs when printing (`url[:80]`), and
  decode each image into the scratchpad to view it:
  `base64.b64decode(url.split(',', 1)[1])` → `<scratchpad>/l_<layer8>.png`.

## Defaults — the user doesn't need to repeat these

- Never run `make lido-*` or `scripts/enrich_lido_templates.py` for drafting. Only the
  read-only checks below. Don't push to the database; tell the user the command at the end.
- The logo layer is always a Quick Hub placeholder from `https://assets.quickhub.ai/qh-assets/`.
  Any variant is fine; pick the one that reads best where the logo sits:
  `logo_black.png` / `logo_white.png` (127×103, stacked) or `logo_black_horizontal.png` /
  `logo_white_horizontal.png` (768×215, wide). Black on light areas, white on dark ones;
  horizontal for a wide, short box, stacked for a squarer one. It is locked and never
  regenerated; at fill time the brand's own logo file is swapped in.
- The background is regenerated for any user prompt, in any domain. Its prompt follows the
  layout, not the sample's look: keep the structure (panels, seams, where the main subject
  sits and how big it is, the areas kept clear for text, shapes that text sits on). The
  product, setting, colors and decoration follow the brief. See "Layout, not decoration"
  in step 4.
- Text is managed by judgment: role, word count, limits, notes.
- Don't change how the template looks. Geometry fixes keep the existing copy rendering
  exactly as in the screenshot.

## 1. Inspect the layers

```bash
cd /home/rushi/Desktop/canva-clone && backend/.venv/bin/python -c "
import json
d = json.load(open('lidojs_templates/<id>.json'))
print('top-level keys:', list(d[0].keys()))
L = d[0]['layers']; r = L['ROOT']
print('ROOT', r['type'], (r['props'].get('image') or {}).get('url'), r['props'].get('boxSize'))
for lid in r['child']:
    l = L[lid]; p = l['props']
    print('\n==', lid, l['type'])
    print('  pos', p.get('position'), 'box', p.get('boxSize'), 'scale', p.get('scale'), 'fontSizes', p.get('fontSizes'))
    if p.get('image'): print('  image', (p['image'].get('url') or '')[:100])
    if p.get('clipPath'): print('  clipPath', str(p['clipPath'])[:60])
    for para in (p.get('doc') or {}).get('content', []):
        a = para.get('attrs', {})
        print('  attrs', {k: a.get(k) for k in ('fontFamily','fontSize','textAlign','textTransform','lineHeight','letterSpacing')})
        for n in para.get('content', []): print('    text', repr(n.get('text')), 'marks', n.get('marks'))
    if p.get('effect'): print('  effect', p['effect'])
    print('  rotate', p.get('rotate'), 'shape', p.get('shape'), 'color', p.get('color'))
"
```

Then view the screenshot and the background image. Convert every position to percent of
the canvas (`x / width`, `y / height`); the prompt and notes use percentages.

## 2. Fix export defects (see docs/TEMPLATE_EXPORT_RULES.md)

Measure text in its real font before deciding. `exact: True` means the real font file was
used; otherwise the width is only an estimate:

```bash
cd /home/rushi/Desktop/canva-clone && backend/.venv/bin/python -c "
from app.lido_corpus.loader import load_enriched, DEFAULT_CORPUS_DIR
from app.lido_corpus.generate_ai import _text_target
t = load_enriched(DEFAULT_CORPUS_DIR / '<id>.json')
for s in t.meta.slots:
    if s.resolved_name != 'TextLayer': continue
    x = _text_target(s, t.layers[s.layer_id].props)
    print(s.role, s.layer_id[:8], 'exact', x.measure.exact, 'box', round(x.box_width))
    for w in ['<sample text>', '<candidate replacement>']: print(f'   {w!r}: {x.measure.width(w):.0f}px')
" 2>&1 | grep -v '^20'
```

- **Background on a nested child.** If ROOT has no image and a child with
  `type.type == "bgImage"` carries it, copy the child's whole `image` object onto
  `ROOT.props.image` (the app's preview only draws ROOT) and leave the child as it is.
- **Background as a plain full-canvas ImageLayer.** If ROOT has no image and the first
  child is an untyped ImageLayer covering the whole canvas (the background photo, as in
  template_101), move it onto ROOT: copy its `image` object to `ROOT.props.image` with
  `boxSize` = the canvas, `position` 0/0, `rotate` 0; set `ROOT.type.type = "bgImage"`;
  then remove the child from `ROOT.child` and from `layers`. Left in place it would be
  classified as a `photo`, and would cover any regenerated background (template_100 was
  done the same way).
- **Logo layer → Quick Hub FrameLayer.** Once the logo layer is known (typed `logo`, or
  the one the user named), always rewrite it to the corpus standard, whatever it held
  before (an embedded `data:` logo, a sample brand's logo, an ImageLayer):
  - `type` = `{"type": "logo", "resolvedName": "FrameLayer", "fixedText": null, "replacableText": null}`
  - `props` = `{"position", "boxSize", "scale": 1, "rotate": 0, "image": {"url": URL,
    "thumb": URL, "boxSize": <same as props.boxSize>, "position": {"x": 0, "y": 0}, "rotate": 0}}`
    with URL = the chosen Quick Hub variant (see Defaults).
  - Size: keep that variant's ratio (127:103 stacked, 768:215 horizontal), fitted inside the old box (height-limited if
    the old box is wider, width-limited if taller), centered on the old box's center.
  - In meta, the slot gets `"resolved_name": "FrameLayer"`, `"role": "logo"`,
    `locked: true`, the matching `position`/`box_size`, and `reference_url` = the same URL.
- **Fake-centered text.** A visually centered column (title, subtitle, tagline all sitting
  around x ≈ canvas/2 in the screenshot) whose layers are `textAlign: left` will look off
  center as soon as copy of another length goes in. Switch those paragraphs'
  `attrs.textAlign` to `center` and give each box a width it can grow into, centered on
  the sample's measured midpoint (`x_new = x + text_width/2 - new_width/2`; measure the
  doc's raw text, nbsp's included). The sample still renders in the same place.
- **Oversized text boxes.** A leftover default width (often 536.3px), a box past the canvas
  edge (`x + width > canvas`), or a box far wider than the space the text visibly has
  (e.g. a 70px badge): narrow it to the visible space from the screenshot. Keep the
  alignment anchor so the copy doesn't move: `left` keeps `position.x`; `right` keeps
  `x + width` (set a new `x`); `center` keeps `x + width/2`. The new width must be at least
  the widest line of the template's own copy. Keep the stray `boxSize.x`/`y` keys.
- **Boxes too narrow for their own copy.** If the copy doesn't fit its box (e.g. an email
  that the editor breaks mid-word), widen the box into free space seen in the screenshot,
  using the same anchor rule.
- **Broken sample text.** `type.replacableText` is the fallback copy when a fill fails.
  Fix it when it doesn't match the doc text (e.g. `newcoffee` for "new" / "coffee").
- **Incomplete `type` objects.** Every layer's `type` must have all four keys like the
  rest of the corpus: `{"type", "resolvedName", "fixedText", "replacableText"}`. Fill the
  missing ones with `null`, and keep any values already set (`bgImage`, `logo`, ...).
- Change nothing else in `layers`.

## 3. Work out the roles (they are recomputed, don't fight them)

The loader recomputes `role`, `editable`, `default_text`, `font_size`, `position`,
`box_size`, `aspect`, `canvas_size`, `background_image_url` and `text_layer_count` on
every load (`backend/app/lido_corpus/loader.py`, `_extract_slots`/`_role_for`). Write
them to match what it computes:

- `default_text` = `type.replacableText`, else the doc's text nodes joined, whitespace collapsed.
- Free text = TextLayers typed `bodyText`/`title`/`static`/untyped, whose text isn't an
  email/URL/phone. Headline = the largest `fontSizes[0]` among them (ties: file order).
  Subhead = the next largest that isn't `static`. Other `static` text → `label`, else `body`.
- **Ranking ignores `scale`.** The headline is picked by raw `fontSizes[0]`, but the
  rendered size is `fontSizes[0] × scale`. A short big title with a large `scale` can lose
  to a longer line, so the real headline gets `subhead` (template_101). Don't change the
  layers to fix it; say the real role in both slots' `notes`.
- Typed `phoneNumber`/`email`/`address`/`website` → that contact role; untyped text that
  looks like a URL/email/phone gets it too. FrameLayer or ImageLayer → `logo` (typed
  `logo`, or "logo" in the image file name), else `photo`. A RootLayer child → `background`.
- Every non-logo ImageLayer is a `photo` slot and `_verify` demands an image spec for it.
  Small fixed ImageLayers (icons inside circles, map pins, gradient/fade overlays) get
  `locked: true` and `{"kind": "decorative_shape", "generate": false, "transparent": true,
  "prompt": null, "reference_url": null, "notes": "<what it is>. Fixed: never regenerate."}`.
  Locking also keeps them out of `reserved_overlay_areas`.

When a role is wrong for the design (a name split over three layers, a badge tagged
`subhead`), say what the slot really is in its `notes`.

Only these fields persist from the file: `name`, `kind`, `tags`, `description`,
`background`, and per slot `max_chars`, `max_lines`, `locked`, `image`, `notes`.

## 4. Write `meta`

Append `"meta"` after `"layers"` with Edit (not a script). If the file is too big for
Edit (embedded images), hand-write the whole meta block with Write into
`<scratchpad>/meta_<id>.json` and merge it with a two-line script
(`d[0]['meta'] = json.load(...)`; dump with `indent=2, ensure_ascii=False`). Print the
loader's computed slot fields first so you copy them exactly. Leave
`background_image_url` `null` when the background is a `data:` URI (the loader
recomputes it). The logo's `reference_url` is always the Quick Hub URL. Slots go in the layers' file
order, one per ROOT child.

- **name** (2–4 words), **kind** (`post`/`story`/`poster`/`banner`/`thumbnail`/`ad`/
  `flyer`), **tags** (3–5), **description** (one sentence). Template matching reads
  these, so be specific (not just "sale") about what the layout is for, e.g. "New Product
  Launch Post", not "New Coffee Post". Keep one or two tags for the sample's domain so
  matching still finds it there.
- **background** (`kind: background_photo`, `generate: true`, `transparent: false`,
  `reference_url` = the background URL):
  - `prompt`: the overall layout (split, panels, seams) with percent positions. Then the
    main subject: "the product the brief promotes, in a setting that suits it", with the
    sample in `(this template: ...)`, and where it sits and how much it fills, keeping size,
    placement and angle. Then the shapes that text sits on (badges, stickers, banners,
    footer bars, button panels) with position and size, in an `IMPORTANT:` sentence: they
    must stay. Keep the areas behind text plain. Every color is marked
    `(this template: ...)`. End with exactly:
    `No text, lettering, logos or watermarks anywhere in the image.`
  - **A separate photo-frame layer's area must be an explicit, IMPORTANT prohibition, not
    a soft "leave it plain".** When a template has its own photo/logo layer(s) sitting on
    top of this background (masked photo frames, cutouts), the fill-time model rewrites
    this prompt for the brief and will readily paint the brief's subject into a merely
    "plain" area — it has no way to know that area belongs to a different layer unless
    told forcefully. Put it in the same `IMPORTANT:` sentence as the kept shapes (never
    as a separate soft sentence, and never right after describing that area in visual
    detail, which primes the opposite result): name the shape (round/rounded-rect/etc.)
    and its region, then **"draw no circles, rings, frames, shadows, photos or imagery of
    any kind there — keep plain [flat color / background surface] matching
    [the base / the shape's own fill], as if the canvas physically ended at that
    boundary; do not let the scene, gradient or lighting reach into it even faded, even
    though the brief is about a visual subject — that subject belongs only in the
    separate photo layer(s), never in this background."**
  - **The wording is the main protection.** `mask_reserved_areas()`
    (`backend/app/lido_corpus/assets_ai.py`) can paint over each photo frame's area of
    the generated background, but it is off by default (`LIDO_MASK_RESERVED_AREAS=false`)
    because its flat patch shows as soon as a photo layer is moved in the editor. So
    unless it has been switched on, whatever the image model draws behind a photo frame
    stays in the background. Verify after writing: generate one test design and look at
    the actual background image (`result.image_fills['ROOT']`) — confirm no photo
    content leaked into the photo frames' areas. `_verify` cannot detect this.
  - **Layout, not decoration.** A template must work for any domain (coffee, gym, fashion,
    real estate...). Don't describe or require the sample's small static decorations:
    thin rules, steam or swoosh lines, splatter, sparkles, doodles, squiggles, confetti,
    theme icons. Name them only to forbid copying them. Instead write: "Colors and any
    small accents follow the brief; add accents only if they genuinely suit its theme,
    keep them few and subtle and out of the text areas, and never copy this template's own
    decorations." Mood, lighting and style also follow the brief. The only fixed
    requirement is what text contrast needs, e.g. "keep the photo dimmed where the title
    crosses it". Decide by function: if text sits on it, or it defines the layout, keep
    it; if it only decorates, drop it. When unsure (e.g. an icon row paired with text
    labels), keep the row but let its icons follow the brief.
  - `notes`: for each text region, its real color (from the text's `color` mark, not the
    paragraph `attrs.color`, which is often a black placeholder), where it is, and what it
    reads against. Light/white text needs a saturated, darker area behind it; dark text
    needs a light, calm one. Text on a shape baked into the image means the shape must stay
    there at its size and color. Mention thin/outline text and the logo corner. End with
    what is fixed (the layout and the text-bearing shapes only); everything else, colors
    included, is decided by the brief. Text colors are fixed in the layers, so a
    brief-chosen palette must still give each text region the contrast it needs.
- **Text slots:** `notes` say the slot's function, word count, line structure and peers,
  with 2–3 good replacement examples from different domains (check that they fit, with
  the verify step), and what goes wrong if it's longer. Contact slots:
  only real details from the request, otherwise keep the sample. `max_chars` and
  `max_lines` must be at least those of the template's own copy.
- **Logo slot:** `locked: true`, and exactly this image spec (with its own logo URL):

  ```json
  {"kind": "logo_static", "generate": false, "transparent": true, "prompt": null,
   "reference_url": "<the layer's image url>",
   "notes": "Brand logo — reuse the asset exactly as supplied. Never regenerate, recolor, re-crop, or let a filler touch this layer; only ever swap in a different brand's own logo file."}
  ```

  and a slot `notes` saying it is the Quick Hub placeholder (which variant) and where it sits.
- **Photo frames** (`role: photo`): an ordinary photo in a masked frame gets
  `kind: background_photo`, `transparent: false`, a prompt with `(this template: ...)`,
  and a note that the mask crops at render time, so the source stays a full rectangle.
  A transparent cutout gets `kind: subject_cutout`, `transparent: true`, and a prompt
  asking for the subject only as an alpha-channel PNG with no backdrop. The background
  prompt must then leave that area empty (`IMPORTANT: leave ... empty ...`). For an
  ordinary frame, the background prompt must draw no circle, ring or photo under it.
  **The subject category itself must be swappable, not just its look.** The fill model
  is told it may change "the subject matter" but must keep the prompt's structural
  instructions (angle, pose, framing) — if the prompt's category is a person ("a person
  ... waist-up, eye level"), a food or product brief has no equivalent pose to map onto,
  and the result is inconsistent or a mismatched stock-photo style. Open with the
  category itself as a variable: "the main subject the brief is about — a person, a
  dish, a product, whichever the request calls for", the sample in
  `(this template: ...)`, then "choose whatever pose, angle and styling naturally suit
  that kind of subject" before giving the sample's own framing as one example. Add: keep
  the subject whole, compact and centered, filling most of the frame with no loose
  scattered elements near the edge (crumbs, splashes, confetti) — those get cut off by a
  tight or circular mask. When a template has more than one photo frame, say in each
  one's `notes` how it relates to the others (wider vs. closer view, hero vs. detail) so
  a domain swap still produces two complementary shots, not two near-duplicates.
- **Background child slot** (a RootLayer child): `image: null`, `notes: null`. Its spec
  lives in `meta.background`.

## 5. Verify, read-only

```bash
cd /home/rushi/Desktop/canva-clone && backend/.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from pathlib import Path
from app.lido_corpus.loader import load_enriched
from app.lido_corpus.generate_ai import text_targets, check_text, image_targets, background_mirror_ids
from app.lido_corpus.textfit import wrap
import enrich_lido_templates as enrich
p = Path('lidojs_templates/<id>.json'); t = load_enriched(p)
for s in t.meta.slots: print(f'{s.role:10s} {s.layer_id[:8]} locked={s.locked} chars={s.max_chars} lines={s.max_lines} {s.default_text!r}')
tg = {x.layer_id[:8]: x for x in text_targets(t)}
for k, x in tg.items(): print(k, wrap(x.slot.default_text, x.measure, x.box_width), check_text(x.slot.default_text, x) or 'OK')
cands = {'<layer8>': ['<good copy>', '<too long copy>']}
for k, texts in cands.items():
    for s in texts: print(k, repr(s), wrap(s, tg[k].measure, tg[k].box_width), check_text(s, tg[k]) or 'OK')
print('images:', [(i.layer_id, i.spec.kind) for i in image_targets(t)], 'mirrors:', background_mirror_ids(t))
print('verify:', enrich._verify(p))
" 2>&1 | grep -v '^20'
```

It is done when:
- the recomputed roles match what you wrote;
- the template's own copy is OK and wraps like the screenshot;
- realistic replacement copy is OK and clearly too-long copy is rejected;
- `verify` is `([], [])`.

## 6. Report

Tell the user:
- the background prompt: what changes per prompt, what is kept, and the contrast rules;
- each text slot's purpose and limits;
- any layer fixes, and why the copy still looks the same;
- the check results;
- the next command: `make lido-add TEMPLATE=<id>`, or `make lido-sync TEMPLATE=<id>` if
  the template is already in the database.
