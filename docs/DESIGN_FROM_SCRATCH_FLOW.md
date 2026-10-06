# Design from scratch: the full flow, step by step

This document follows **one real request** through the whole pipeline: from the prompt
typed into the "Design new template" tab, to the Lido JSON saved as a draft. Every
prompt, plan and JSON excerpt below comes from that run (**draft #69, "Summer Splash
Ticket Flow"**) or was rebuilt from it with the app's own code.

The **complete** files (full system prompts, plan, final template JSON) are in
[`design_from_scratch_example/`](design_from_scratch_example/). This page quotes the
important parts.

---

## The flow at a glance

```
 USER PROMPT
     │   POST /v1/lido/drafts/stream          (api/routes/lido_drafts.py)
     ▼
 ① PLAN — the "art director"                  plan.py        gpt-4o            6.4s
     │   reads the brief + layout catalogue + mood guide
     │   → DesignPlan: texts, photos, layout, mood, features, backdrop
     │   code cleans it (max 3 photos, no wide frames, unknown names…)
     │
     ├──► ② PHOTOS START RENDERING NOW, from the plan   photos.py   gpt-image   (parallel)
     │
     ▼
 ③ DESIGN — the "designer"                    brief.py       gpt-6-astra      63.5s
     │   reads the brief + the plan + the backdrop + 2 example layouts
     │   → BriefDesign: colours, fonts, every element with x/y/w/h
     ▼
 ④ BUILD + CHECK                              brief.py, check.py   (code, ~0.1s)
     │   normalise → add backdrop layers → validate → code fixes
     │   problems left? → REPAIR: a patch from gpt-4o (6.0s), at most 2 rounds
     ▼
 ⑤ FINISH                                     decorate.py, photos.py, lido.py, drafts.py
     │   contact icons → take the finished photos → Lido JSON → save + preview
     ▼
 DRAFT #69 saved (lido_drafts table)          total 78.0s
```

| Step | Time in #69 | Notes |
|---|---|---|
| ① Plan | 6.4s | one gpt-4o call |
| ② Photos | 0.0s at the end | 3 images rendered **during** ③, all ready when it finished |
| ③ Design | 63.5s | one gpt-6-astra call, 4,411 output tokens |
| ④ Repair | 6.0s | one gpt-4o patch call, 214 output tokens |
| ⑤ Save | 0.6s | Lido JSON, database row, preview screenshot |
| **Total** | **78.0s** | |

---

## 0. The request

The user typed this into the "Design new template" tab:

```text
Create a vibrant, high-energy social media promotional poster for **Imagicaa Water Park**
featuring an exciting **50% OFF ticket offer**. …

Show a dynamic collage of multiple realistic water park attractions: a gigantic twisting
water slide, high-speed racing slides, a giant wave pool, family raft ride, lazy river,
kids splash zone and a huge tropical pool. …

Make a large **ticket-shaped promotional badge** …   **50% OFF**  **WATER PARK TICKETS**
Add supporting offer text:   **SUMMER SPLASH SALE**  **LIMITED-TIME OFFER**  **BOOK NOW & SAVE 50%**
Include fictional test information:   **IMAGICAA WATER PARK**
  **Imagicaa Road, Khopoli, Maharashtra 410203**   **+91 98765 43210**
  **www.imagicaawaterpark.example**   **Open Daily: 10:00 AM – 7:00 PM**
Add attraction highlights:
  **Thrilling Water Slides • Wave Pool • Lazy River • Kids Splash Zone • Family Raft Rides**
Add a strong CTA:   **GRAB YOUR TICKETS NOW!**   **MAKE A SPLASH THIS SUMMER**
…
```
(The full prompt is in `8_saved_draft_record.json` → `prompt`.)

The frontend sends it to **`POST /v1/lido/drafts/stream`** with
`{prompt, variations: 1, palette?, logoUrl?}`. The route
([`lido_drafts.py`](../backend/app/api/routes/lido_drafts.py)) screens the prompt, then
runs `drafts.create_from_prompt()` and streams progress back, one JSON object per line:

```json
{"stage": "planning", "elapsedMs": 2}
{"stage": "designing", "variation": 0, "elapsedMs": 6410}
{"stage": "repairing", "variation": 0, "attempt": 2, "problems": 3, "elapsedMs": 70020}
{"stage": "photos", "variation": 0, "elapsedMs": 77300}
{"stage": "saving", "variation": 0, "elapsedMs": 77310}
{"stage": "draft", "variation": 0, "draft": { …the whole saved draft… }, "elapsedMs": 77965}
{"stage": "done", "elapsedMs": 77966}
```
(The `problems` count above is illustrative; the stages and their order are what the
code sends.)

With `variations: 2–3`, each variation gets its own plan and then runs ③–⑤ on its own,
in parallel.

---

## ① The plan: the "art director" decides WHAT goes in

**Code:** `plan.make_plan()` in [`plan.py`](../backend/app/lido_create/plan.py)
**Model:** `LIDO_PLAN_MODEL` = **gpt-4o** (chat completions, temperature 0.8, no reasoning)
**Output schema:** `DesignPlan` (strict structured output, so the model must fill every field)

The art director never places anything on the canvas. It decides *what* the design
contains and *how it should feel*.

### System prompt (~4,500 tokens), full text in `1_plan_system_prompt.txt`

| Section | What it tells the model |
|---|---|
| Role | "You are the ART DIRECTOR… you decide WHAT and HOW" |
| **DECIDE 1–11** | rules for each plan field: copy word for word; **1 to 3 photos** (from `LIDO_MAX_PHOTOS`), default ONE; logo; exclusions; 1–2 moods; features from those moods; a layout that fits the photo count; photo theme; notes; backdrop; contact icons |
| **LAYOUT CATALOGUE** | every entry of `library/layouts.yaml`, e.g. `- steps_flow (photos 1-3; suits process, how it works, steps): Three numbered steps run left to right as a flow…` |
| **MOOD GUIDE** | every entry of `library/moods.yaml`, showing only items switched on in the library menus |
| **NAMES YOU MAY USE** | the enabled frames, crops, shapes, strokes, effects and backdrops (from `library/*.yaml`) |

### User prompt, full text in `2_plan_user_prompt.txt`

```text
CLIENT BRIEF:
"""
Create a vibrant, high-energy social media promotional poster for **Imagicaa Water Park** …
"""

Recently made (choose something different):
- <one line per each of the last 10 drafts: its layout, photo count, frames, features>

Prefer a catalogue layout not in: <the layouts those recent drafts used>.

Write the design plan.
```

### How the layout is chosen

1. **Catalogue or invented?** About 1 in 4 designs (`FREE_SHARE = 0.25`) is told
   "FREE DESIGN: do NOT use the catalogue" and invents a `custom` layout. With several
   variations, the last one is always free.
2. Otherwise the model picks from the **layout catalogue**. It is told to avoid the
   layouts of the last 10 drafts (the "Recently made" lines), so designs vary.
3. **Code checks the photo count.** If the chosen layout's photo range doesn't include
   the plan's photo count, `_best_fitting()` swaps in one that fits. (In #64 the log
   showed `lido.plan.layout_swapped picked=triptych photos=4`.)

In #69 the model picked **`steps_flow`** (photos 1–3), which fits 3 photos.

### Output: the plan (real, abridged; full in `3_plan_output.json`)

```json
{
  "texts": [
    {"role": "badge",    "text": "50% OFF"},
    {"role": "headline", "text": "WATER PARK TICKETS"},
    {"role": "subhead",  "text": "SUMMER SPLASH SALE"},
    {"role": "kicker",   "text": "IMAGICAA WATER PARK"},
    {"role": "address",  "text": "Imagicaa Road, Khopoli, Maharashtra 410203"},
    {"role": "phone",    "text": "+91 98765 43210"},
    {"role": "website",  "text": "www.imagicaawaterpark.example"},
    {"role": "item",     "text": "Thrilling Water Slides"},   … 5 items in total
    {"role": "cta",      "text": "GRAB YOUR TICKETS NOW!"},   … 17 texts in total
  ],
  "photos": [
    {"role": "hero", "frame": "rounded", "orientation": "portrait",
     "from_brief": "gigantic twisting water slide",
     "subject": "A gigantic twisting water slide with happy families enjoying the ride"},
    {"role": "supporting", "frame": "circle", "orientation": "portrait",
     "from_brief": "high-speed racing slides",
     "subject": "High-speed racing slides with groups of friends racing down"},
    {"role": "supporting", "frame": "torn_paper", "orientation": "portrait",
     "from_brief": "giant wave pool",
     "subject": "A giant wave pool with energetic splashes and people having fun"}
  ],
  "logo": true,
  "exclude": [],
  "moods": ["bold_loud"],
  "layout": "steps_flow",
  "custom_layout": null,
  "shapes": ["octagon", "parallelogram", "chevron"],
  "draw": ["underline", "sparkle"],
  "effects": ["shadow"],
  "gradient": "a strong band or a punchy two-colour background",
  "photo_theme": "event",
  "notes": "Ensure the ticket badge is prominently placed and the main attraction photos form the lively background. …",
  "backdrop": {"style": "diagonal_bands", "side": "bottom", "angle": 20.0, "split": 0.5, "tone": "accent"},
  "contact_icons": true
}
```

### Code cleans the plan (`plan._clean`)

The model's plan is never trusted as is:

| Rule | In #69 |
|---|---|
| Photos the brief never asked for are dropped (`from_brief` must quote the brief) | ok |
| **At most `LIDO_MAX_PHOTOS` photos** | the brief named **7 attractions**; only **3** were kept |
| A frame name that doesn't exist (or is switched off in `library/`) → `rounded` | ok |
| With 3+ photos: no wide frames (`rounded_card`, `oval`…), landscape → square | ok |
| Shapes / strokes / effects not in the library menus are removed | ok |
| The backdrop is clamped (angle 10–30°, split 0.35–0.65, allowed side) | ok |
| A price in the brief can't be excluded; a requested CTA can't be excluded | ok |

---

## ② Photos start rendering, before the design exists

**Code:** `PhotoPrefetch.from_plan()` in [`photos.py`](../backend/app/lido_create/photos.py)

As soon as the plan is clean, **every planned photo starts rendering in parallel**.
They render while the designer works (step ③), so normally nothing is left to wait for
at the end.

The shape each photo is rendered at comes from the plan:

| Photo | Plan says | Rendered at |
|---|---|---|
| hero | crop `rounded`, portrait | 0.75 (3:4), **896×1184** |
| supporting | crop `circle` | 1.0, **1024×1024** |
| supporting | frame `torn_paper` | the frame's own shape, 1.18, **1120×944** (a frame's shape beats the orientation) |

### The image prompt, exactly as sent (full in `6_image_prompts.txt`)

```text
A gigantic twisting water slide with happy families enjoying the ride

Absolutely do not include any of the following in the image: text, letters, words,
numbers, typography, watermark, logo, signature, caption, ui, frame, border.
```
`model = IMAGE_MODEL (gpt-image-2.5-flare)`, `quality = LIDO_TEMPLATE_IMAGE_QUALITY (medium)`,
`size = 896x1184`.

For a **cutout** photo (`frame: cutout`, e.g. a product), the request also asks for a
transparent background and adds: *"ONE single subject only, complete and whole, centred
in frame… isolated on a fully transparent background"*. It also adds negatives like
*"duplicate subject… background, backdrop… solid background"*.

> **Worth knowing.** The image is rendered from the **plan's** short subject, because it
> starts before the designer has written anything. The designer later writes a longer
> subject for the same photo, e.g. *"A gigantic colorful twisting water slide towers
> above happy families … dramatic summer sunlight in realistic premium campaign
> photography."* That longer text is what the review UI shows under "Photo subjects",
> but it isn't the text that was rendered. If photos need more style (lighting, mood,
> "premium campaign photography"), the place to add it is the plan's `subject` rule
> (`plan.py`, DECIDE 2) or `GeneratedPhotos.render` (`photos.py`).

Each request has a **90s timeout** (`IMAGE_TIMEOUT_SECONDS`). A request that hangs is
sent once more.

---

## ③ The design: the "designer" decides WHERE everything goes

**Code:** `design_from_brief()` in [`brief.py`](../backend/app/lido_create/brief.py)
**Model:** `LIDO_LAYOUT_MODEL` = **gpt-6-astra**, reasoning effort **low** (Responses API)
**Output schema:** `BriefDesign`
**Parallel drafts:** `LIDO_LAYOUT_CANDIDATES` (1 = one draft; 2 = two at once, first to pass wins)

### System prompt (~4,000 tokens), full text in `4_design_system_prompt.txt`

| Section | What it tells the model |
|---|---|
| Role | a senior social-media designer laying out one 1080×1080 template with pixel coordinates |
| **ELEMENTS** | every element kind and its fields: `shape`, `line`, `draw`, `list`, `dots`, `photo`, `logo`, `text` (bullets, crops, line ends and effects come from `library/*.yaml`) |
| **SHAPES / FRAMES / DRAW** | the enabled items, each with its hint from `library/` |
| GRADIENTS, COLOUR ROLES | how gradients and the 5 colour roles (`bg ink accent on_accent soft`) work |
| **RULES THAT ARE CHECKED** | what `check.py` rejects: text fit, overlaps, text on photos, contrast, edges, photo count and size… |
| PRO TEMPLATE TECHNIQUES | headline pairing, reverse band, offer badge, price tag, photo fade, … |
| GOOD DESIGN | margins, hierarchy, balance |
| **YOU ARE DESIGNING FROM A CLIENT BRIEF** | use the client's exact copy, one list element for all items, plain text only, a `subject` for every photo, the plan overrides everything |
| FONT SETS, PHOTO THEMES | the 5 font sets with their character; the photo themes |

### User prompt: ALL the context the designer gets (full in `5_design_user_prompt.txt`)

The user prompt has four parts:

**1. The brief, word for word**
```text
CLIENT BRIEF:
"""
Create a vibrant, high-energy social media promotional poster for **Imagicaa Water Park** …
"""
```

**2. The plan, rewritten as instructions** (`plan_brief(plan)`, real text):
```text
DESIGN PLAN (from the art director — build exactly this)
- Layout: steps_flow: Three numbered steps run left to right as a flow (chevrons, arrows
  or lines connecting them); headline above; one photo or one small photo per step.
- Photos: exactly 3, each in its frame (…) and with its shape (its picture is already
  being made at that shape):
  1. hero: A gigantic twisting water slide with happy families enjoying the ride — frame: rounded, portrait (w/h about 0.75)
  2. supporting: High-speed racing slides with groups of friends racing down — frame: circle
  3. supporting: A giant wave pool with energetic splashes and people having fun — frame: torn_paper
- Text, use these exact words (roles map to text_type; price/date → badge, subhead → body):
  - badge: '50% OFF'
  - headline: 'WATER PARK TICKETS'
  - subhead: 'SUMMER SPLASH SALE'
  - body: 'LIMITED-TIME OFFER'
  - body: 'BOOK NOW & SAVE 50%'
  - kicker: 'IMAGICAA WATER PARK'
  - address: 'Imagicaa Road, Khopoli, Maharashtra 410203'
  - phone: '+91 98765 43210'
  - website: 'www.imagicaawaterpark.example'
  - body: 'Open Daily: 10:00 AM – 7:00 PM'
  - cta: 'GRAB YOUR TICKETS NOW!'
  - body: 'MAKE A SPLASH THIS SUMMER'
  - list of 5 items — put ALL of them in ONE list element (it lays them out as 2 columns
    of 3): ['Thrilling Water Slides', 'Wave Pool', 'Lazy River', 'Kids Splash Zone', 'Family Raft Rides']
- Logo: one small logo
- Mood: bold_loud — feel: loud, high contrast, huge numbers or words, one dominant
  element, slanted energy; avoid: timid small type, lots of empty space, pastel softness
- Features to use: shapes: octagon, parallelogram, chevron; hand-drawn: underline,
  sparkle; text effects: shadow; gradient: a strong band or a punchy two-colour background
- Do NOT add: nothing excluded
- Art direction: Ensure the ticket badge is prominently placed …
- Contact icons: a small icon is added beside each website/phone/email/address line —
  leave about 50px free to the left of those lines
```

**3. The backdrop**: already drawn by code, so the designer is told where text may go
(`backdrops.brief_for()`, real text):
```text
BACKDROP — drawn for you underneath everything; do not draw it yourself and set
background to null: two slanted bands (a 120px accent band, then a thin soft one) cross
the canvas, starting along the line (0, 343) to (1080, 737) and running down from it —
decoration, keep text off them.
Text areas:
- the plain canvas (about x 0-1080, y 0-1080): text in ink or accent
- the plain canvas (about x 0-1080, y 360-840): text in ink or accent
- the soft backdrop panel (about x 0-1020, y 480-900): text in ink
Keep every text (and its pill or badge) entirely inside ONE area, never across an edge
between areas. Photos and decoration may sit anywhere.
```
If the client gave brand colours, a `BRAND COLOURS — fixed by the client…` line is added
here too.

**4. Two example layouts.** These are no longer in this part. `fresh_promo` and
`spotlight_launch` are now a **fixed** part of the designer's instructions
(`brief.designer_instructions()`), after the rules. So everything except the brief, the
plan and the backdrop is byte-identical on every call, and OpenAI can serve it from its
prompt cache at a tenth of the price. The request marks the end of that shared part
with an explicit cache breakpoint and sends `prompt_cache_key="lido-design"` (the plan
call sends `"lido-plan"`). The user prompt ends with:
```text
Design the template: name, idea, colours, font set, photo theme, elements.
```
(The files in `design_from_scratch_example/` were captured before this change: there,
the examples still sit in `5_design_user_prompt.txt`.)

### Output: the design (abridged)

The raw reply isn't stored. This excerpt is **reconstructed from the saved draft** (same
positions and texts) to show the shape of the answer:

```json
{
  "name": "Summer Splash Ticket Flow",
  "idea": "A bold three-stop attraction flow, with cinematic ride photography and a giant perforated sale ticket overlapping the imagery. …",
  "colors": {"bg": "#fff7d6", "ink": "#073c63", "accent": "#f74736", "on_accent": "#ffffff", "soft": "#bceeeb"},
  "fonts": "condensed-poster",
  "photo_theme": "event",
  "background": null,
  "elements": [
    {"kind": "shape", "shape": "parallelogram", "x": 800, "y": 36, "w": 220, "h": 18, "color": "accent", …},
    {"kind": "logo", "x": 70, "y": 38, "w": 110, "h": 89},
    {"kind": "text", "text_type": "kicker", "text": "IMAGICAA WATER PARK", "x": 212, "y": 54, "w": 550, "h": 0, "font": "display", "size": 35, "color": "ink", …},
    {"kind": "text", "text_type": "headline", "text": "WATER PARK TICKETS", "x": 65, "y": 150, "w": 955, "h": 0, "font": "display", "size": 100, "effect": "shadow", …},
    {"kind": "draw", "draw": "underline", "x": 72, "y": 267, "w": 290, "h": 12, "color": "accent", …},
    {"kind": "photo", "clip": "rounded", "x": 60, "y": 309, "w": 300, "h": 400, "radius": 24,
     "subject": "A gigantic colorful twisting water slide towers above happy families …"},
    {"kind": "photo", "clip": "circle", "x": 387, "y": 320, "w": 320, "h": 320, "subject": "Groups of friends race down …"},
    {"kind": "photo", "frame": "torn_paper", "x": 729, "y": 323, "w": 320, "h": 271, "subject": "A giant turquoise wave pool …"},
    {"kind": "shape", "shape": "octagon", "x": 74, "y": 320, "w": 64, "h": 64, "color": "accent"},
    {"kind": "text", "text_type": "badge", "text": "01", "x": 83, "y": 331, "w": 46, …},
    {"kind": "shape", "shape": "chevron", "x": 346, "y": 446, "w": 45, "h": 45, …},
    {"kind": "text", "text_type": "badge", "text": "50% OFF", "x": 441, "y": 582, "size": 79, …},
    {"kind": "list", "items": ["Thrilling Water Slides", "Wave Pool", "Lazy River", "Kids Splash Zone", "Family Raft Rides"],
     "x": 65, "y": 741, "w": 545, "h": 150, "bullet": "…a filled-circle style…", "columns": null, "size": 21, "color": "ink"},
    {"kind": "shape", "shape": "rectangle", "x": 638, "y": 799, "w": 374, "h": 67, "radius": 34, "color": "accent"},
    {"kind": "text", "text_type": "cta", "text": "GRAB YOUR TICKETS NOW!", "x": 651, "y": 818, "color": "on_accent", …},
    {"kind": "text", "text_type": "phone",   "text": "+91 98765 43210", "x": 157, "y": 958, …},
    {"kind": "text", "text_type": "website", "text": "www.imagicaawaterpark.example", "x": 615, "y": 960, …},
    {"kind": "text", "text_type": "address", "text": "Imagicaa Road, Khopoli, Maharashtra 410203", "x": 154, "y": 1010, …}
  ]
}
```

The real reply also contains every optional field of each element (`null` when unused),
because strict structured output requires all fields. Output tokens are the slowest and
most expensive part of the call ($50 per million on gpt-6-astra), so the format in
[`kit.py`](../backend/app/lido_create/kit.py) is kept lean:
- **one small model per element kind** (`ShapeOut`, `TextOut`, `PhotoOut`…), so a text
  doesn't carry shape fields;
- **whole pixels**: `"x": 822`, not `822.0`;
- **rarely used settings grouped**, so one `null` covers them: a shape's gradient, opacity,
  rotate and outline are its `style`; a photo's tilt and bleed its `style`; a text's effect
  and its colour one `effect: {"name": "shadow", "color": "soft"}`.

Measured on the 14 hand-made layouts, this is 25% fewer reply tokens than the previous
flat format. `kit.to_element()` turns each reply element back into the internal `Element`.

The schema's allowed values (shapes, frames, crops, strokes, bullets, effects, line ends)
come from `library/*.yaml`. A switched-off item can't be written at all.

---

## ④ Build, check, fix, repair

**Code:** `design_from_brief()` → `build()`, `auto_fix()` in [`brief.py`](../backend/app/lido_create/brief.py);
`validate()` in [`check.py`](../backend/app/lido_create/check.py)

### 4a. Build: the reply becomes real elements (`build()`)
1. Each written element (`TextOut`, `PhotoOut`…) becomes the full internal `Element`.
2. `normalise()` ([`ai.py`](../backend/app/lido_create/ai.py)):
   - **text heights are measured** with the real fonts (the model writes `h: 0`), and a text
     that doesn't fit is stepped down in size, to 70% at most;
   - the **list element is laid out**: 5 items become 5 text elements plus bullet shapes
     and glyphs, in 2 columns (layers 28–42 in the final JSON);
   - a `dots` element becomes a grid of small circles; a framed photo's height follows the
     frame's aspect.
3. The **backdrop layers are put underneath everything** (the two `diagonal_bands`
   rectangles: layers 0–1 in the final JSON).

### 4b. Check (`validate()`): about 40 rules
Text fits its box and line limit · no text overlaps text or the logo · text never sits on
a photo or across a shape's edge · **contrast** ≥ 4.5:1 (3:1 for big display text) · 30px
from the edges · exactly one headline, one logo · photo count = the plan's, each at least
200px (140px with 3+ photos) · no shape under a photo · the plan's texts and list items are
all there · nothing the brief excluded · enough decoration · …

### 4c. Code fixes first (`auto_fix()`), no AI needed
Each fix is tried only when a matching problem exists, and **kept only if it leaves fewer
problems**:

| Problem contains | Fix |
|---|---|
| `line break`, `emoji`, `'soft'` | clean the text, recolour `soft` text to `ink` |
| `wraps to`, `wider than` | step the font size down (to 60% at most) |
| `contrast` | try each text colour role, keep the best |
| `sits on a photo` | slide a solid card under the text |
| `overlaps` | move the lower text down (or the upper one up) |
| `logo` | move the logo to a free corner |
| `runs off the canvas` | slide the photo/shape back inside |
| `px on each side)` (photo too small) | enlarge the photo to the minimum |
| `behind a photo` | remove the shape under the photo |

### 4d. Repair: a small patch from the model
If problems remain, the design goes back **as a numbered list**, with the problems and
hints:

```text
CLIENT BRIEF: """ …the brief… """

DESIGN PLAN … (the same plan text as above, so the repair still respects it)

Your design:
{"name": "Summer Splash Ticket Flow", "idea": "…", "background": null}
Elements (drawn in this order: first = back, last = front):
0: {"kind":"shape","x":800.0,"y":36.0,"w":220.0,"h":18.0,"color":"accent","shape":"parallelogram"}
1: {"kind":"logo","x":70.0,"y":38.0,"w":110.0,"h":89.0}
2: {"kind":"text","x":212.0,"y":54.0,…,"text":"IMAGICAA WATER PARK","text_type":"kicker",…}
…

It fails these checks:
- body 'BOOK NOW & SAVE 50%': contrast 3.3:1 against what's behind it, needs 4.5:1
- …

How to fix:
- Pick a text colour role that reads on what's behind it (ink on bg, on_accent on accent, …)

Measured text boxes in your design (real heights — the list element is already laid out here):
  kicker 'IMAGICAA WATER PARK': x 212-762, y 54-92, size 34
  …

Return ONLY the edits that fix every problem: replace an element (its number and the
whole corrected element), delete one, or insert a new one before a number (…). Keep the
idea and the brief's copy; leave every element that is fine alone.
```
(The problem lines above are examples. The problems sent in #69's repair round aren't
stored, only the ones left at the end.)

**Model:** `LIDO_REPAIR_MODEL` = **gpt-4o** (temperature 0.4). **Output schema:** `BriefRepair`:
```json
{"edits": [
  {"action": "replace", "index": 14, "element": {"kind": "text", "text": "BOOK NOW & SAVE 50%", "color": "ink", …}},
  {"action": "delete",  "index": 9,  "element": null},
  {"action": "insert",  "index": 3,  "element": {"kind": "shape", …}}
]}
```
The code applies the edits to the numbered list, then runs 4a–4c again:

- A repair is **kept only if it leaves the same number of problems or fewer** (never worse).
- At most **2 rounds**.
- Repairs **stop early** when the problems left are the same kinds the model already
  failed to fix, so another round would only repeat the same answer (`lido.brief.repairs_stalled`).

**In #69:** 1 repair round (6.0s, 214 tokens). It finished with 2 contrast problems left,
which the next round wouldn't have fixed:
```
body 'BOOK NOW & SAVE 50%': contrast 3.3:1 against what's behind it, needs 4.5:1
cta 'GRAB YOUR TICKETS NOW!': contrast 3.3:1 against what's behind it, needs 4.5:1
```
The draft is still saved. Its problems are listed in the review UI ("2 check(s) failing").

---

## ⑤ Finish: icons, photos, Lido JSON, save

1. **Contact icons** (`decorate.add_contact_icons`): a line icon from `library/icons.yaml`
   is drawn beside the phone, website and address lines. These are `DrawLayer`s 49, 51
   and 53, so the designer leaves 50px free for them.
2. **Photos** (`PhotoPrefetch.resolve`): the design's 3 photos are paired with the 3
   renders started in ②. The plan and the design have the same photo count, so they're the
   same photos, whatever wording the designer used. A render is re-done only if its frame
   ended up very differently shaped (more than 1.5×). In #69 all 3 were ready: photo wait
   **0.0s**.
3. **Lido JSON** (`lido.to_lido`): every element becomes a Lido layer (below).
4. **Save** (`drafts.save_draft`): one row in `lido_drafts` (document + info), then a
   preview screenshot uploaded to the object store, then the timings.

---

## The final Lido JSON

Full file: `7_final_lido_template.json`. It's a list with one page, `[{"layers": {…}}]`.
`ROOT` is the canvas; its `child` list gives the drawing order (first = back).

**#69 has 55 layers:** 1 root, 20 `TextLayer`, 18 `ShapeLayer`, 10 `DrawLayer`,
4 `FrameLayer` (3 photos + logo), 2 `LineLayer`.

| # | Layer | What it is | Came from |
|---|---|---|---|
| 0–1 | ShapeLayer rectangle | the two diagonal bands | backdrop (code) |
| 3 | FrameLayer `logo` | logo placeholder | designer |
| 6 | TextLayer `bodyText` | WATER PARK TICKETS | designer (headline) |
| 7 | DrawLayer | underline under the headline | designer (`draw`) |
| 9–11 | FrameLayer | the 3 generated photos | designer + ② |
| 12–19 | Shape + Text | octagon step badges "01/02/03" and chevrons | designer |
| 24 | TextLayer `static` | 50% OFF | designer (badge) |
| 28–42 | Shape + Draw + Text | the list: 5 bullets (a filled circle with a small mark) and 5 items | **one** `list` element, laid out by code |
| 45 | TextLayer `static` | GRAB YOUR TICKETS NOW! | designer (cta) |
| 48–53 | Text + Draw | phone, website, address, each with an icon | designer + icons (code) |

### Element → Lido layer

| Element kind | Lido layer | Notes |
|---|---|---|
| canvas | `RootLayer` (`bgImage`) | `props.color`: flat colour or gradient |
| shape | `ShapeLayer` | `shape`, `color`/gradient, `border`, `roundedCorners`, `transparency` |
| photo | `FrameLayer` | `image.url` = the generated photo; `clipPath` for a frame outline |
| logo | `FrameLayer` type `logo` | swapped for the client's logo (or the stock logo) |
| text | `TextLayer` | `props.doc` (rich text), fonts, colours, `effect` |
| line | `LineLayer` | style and end markers |
| draw / icon | `DrawLayer` | an SVG path |

**Text types** decide what a filled template may replace: headline, kicker, body and item
become `bodyText` (`replacableText`); cta, badge and caption become `static`
(`fixedText`); website, phone and email keep their own type.

### Three real layers (abridged)

```json
"cdd0…": {                                   // a headline — TextLayer
  "type": {"resolvedName": "TextLayer", "type": "bodyText", "replacableText": "NEW DOVE SHINE SHAMPOO"},
  "props": {
    "position": {"x": 140.0, "y": 198.0}, "boxSize": {"width": 800.0, "height": 134.64},
    "doc": {"type": "doc", "content": [{"type": "paragraph",
      "attrs": {"fontFamily": "DM Serif Display", "fontSize": "66.0px", "color": "rgb(36, 48, 71)",
                "textAlign": "center", "lineHeight": "1.02", "textTransform": "uppercase"},
      "content": [{"type": "text", "text": "NEW DOVE SHINE SHAMPOO"}]}]},
    "fonts": [{"name": "DM Serif Display", "fonts": [{"urls": ["https://fonts.gstatic.com/…ttf"]}]}],
    "effect": {"name": "hollow", "settings": {"thickness": 50}}
  },
  "parent": "ROOT"
}
"1767…": {                                   // a generated photo — FrameLayer
  "type": {"resolvedName": "FrameLayer", "type": null},
  "props": {
    "position": {"x": 230.0, "y": 340.0}, "boxSize": {"width": 620.0, "height": 620.0},
    "image": {"url": "https://…/design-assets/public/lido-generated/drafts/photo-11ff….png", …},
    "imageStyle": {"objectFit": "contain", …}
  },
  "parent": "ROOT"
}
"3733…": {                                   // a pill — ShapeLayer
  "type": {"resolvedName": "ShapeLayer"},
  "props": {"shape": "rectangle", "color": "rgb(248, 247, 244)", "roundedCorners": 101,
            "border": {"color": "rgb(218, 215, 208)", "style": "solid", "weight": 1.0},
            "position": {"x": 425.0, "y": 143.0}, "boxSize": {"width": 230.0, "height": 40.0}}
}
```
(These three come from draft #68, a simpler run. #69's file has the same structure.)

### What else is saved with the draft
`8_saved_draft_record.json` holds everything the review UI shows: `plan`, `name`, `idea`,
`colors`, `fonts`, `backdrop`, `contactIcons`, `photoSubjects`, `attempts`, `problems`,
`fingerprint` (used by the next plans' "Recently made"), `cost` (the bill: total, per
step, every call with its tokens; drafts made after cost tracking was added), and the
timings:
```json
"timing":   {"planMs": 6405, "designMs": 70890, "photosMs": 0, "saveMs": 627, "totalMs": 77965},
"llmCalls": [{"step": "draft", "ms": 63484, "outputTokens": 4411},
             {"step": "repair", "ms": 6032, "outputTokens": 214}]
```

---

## Debugging: where to look

### Log lines, in the order they appear
| Log line | Step | Tells you |
|---|---|---|
| `lido.plan.layout_swapped` | ① | the chosen layout didn't fit the photo count |
| `lido.plan.wide_frame_swapped` | ① | a wide frame was replaced (3+ photos) |
| `lido.plan … layout=… photos=…` | ① | **plan done**: layout, moods, photo count |
| `lido.drafts.photo_started planned=True` | ② | one line per photo rendering from the plan |
| `lido.brief.model layout=… repair=…` | ③ | which models are used |
| `lido.brief.llm_call step=draft ms=… outputTokens=… reasoningTokens=… cachedInputTokens=…` | ③ | **design call done**: how much was thinking, how much input came from the cache |
| `lido.brief.auto_fixed fix=… before=… after=…` | ④ | a code fix that helped |
| `lido.brief.llm_call step=repair` / `lido.brief.repaired before= after=` | ④ | a repair round and its effect |
| `lido.brief.repairs_stalled` | ④ | repairs stopped: the model couldn't fix what's left |
| `openai.image_timeout_retry` | ② | an image request hung and was resent |
| `lido.drafts.photo_prefetch photos= renders= reused= wasted=` | ⑤ | **renders = images generated**; wasted should be 0 |
| `lido.drafts.cost total_usd=… plan=… design=… repair=… photo=…` | ⑤ | **what the template cost** (priced from each call's tokens, `backend/app/costs/pricing.yaml`) |
| `lido.drafts.timing … totalMs=` | ⑤ | the timings saved with the draft |

### Files
| What | Where |
|---|---|
| API route + stream | `backend/app/api/routes/lido_drafts.py` |
| Orchestration (variations, photos, saving) | `backend/app/lido_create/drafts.py` |
| ① Art director prompt + plan cleanup | `backend/app/lido_create/plan.py` |
| ② Photo rendering + reuse | `backend/app/lido_create/photos.py` (prompt text: `lido_corpus/assets_ai.py`) |
| ③ Designer prompt rules, repair loop, code fixes | `backend/app/lido_create/brief.py` |
| ③ Designer base prompt (ELEMENTS, RULES, TECHNIQUES) | `backend/app/lido_create/ai.py` |
| ④ The checks | `backend/app/lido_create/check.py` |
| ⑤ Lido JSON writer | `backend/app/lido_create/lido.py` |
| Everything the AI may choose from | `backend/app/lido_create/library/` (see its README) |
| Models and limits | `backend/.env`, section 3 "DESIGN FROM SCRATCH" |
| Prices, and the per-template bill | `backend/app/costs/` (`pricing.yaml` = the price list) |
