# How the 5 AI-made templates were created (template_90001 – 90005)

This explains, step by step, how the draft templates (now stored in the `lido_drafts` table)
were made without anyone opening the Lido editor: where the ideas came from, how every
shape, photo and text box was placed, and how the screenshots were produced.

**In one sentence:** no image was generated and no design tool was used. A Lido
template is only a JSON file listing layers and their coordinates, so I wrote a small
Python script that writes that JSON directly, measured every text box with the
pipeline's own font code, and then rendered the JSON in a headless browser to get the
screenshots.

---

## 1. First, understanding what a template really is

Before designing anything I read how the repo stores and uses templates:

| What I read | What it taught me |
|---|---|
| `docs/TEMPLATE_DESIGN_GUIDE.md` | The design rules: decorations as shapes, real text boxes, 3–4 colours, room for longer text, logo separate |
| `docs/TEMPLATE_EXPORT_RULES.md` | The shapes the code expects: `ROOT` is the background, text boxes as wide as the visible space, real Google Fonts, `template_<number>.json` |
| `docs/TEMPLATE_METADATA_RULES.md` + `template_227.json` | The reference template and how roles and limits are used |
| All 19 existing templates | The exact JSON for each layer type (text, shape, photo frame, logo) |
| `backend/app/lido_corpus/loader.py` | How roles (headline, subhead, label, website…) are inferred from layer type and font size |
| `backend/app/lido_corpus/palette.py` | That the background colour, shape fills and text colours are recoloured to the user's palette, but images never are |
| `backend/app/lido_corpus/textfit.py` | How the pipeline measures text width with the real font file |
| `lidojs_templates/previews/*.png` | The quality bar the new templates had to match |

The key discovery: a template file looks like this, and nothing more:

```json
[{ "layers": {
    "ROOT":      { "type": {"resolvedName": "RootLayer", ...}, "props": {"color": "...", "boxSize": {...}},
                   "child": ["id-1", "id-2", "id-3"] },
    "id-1":      { "type": {"resolvedName": "ShapeLayer"}, "props": {"shape": "circle", "position": {...}, ...} },
    "id-2":      { "type": {"resolvedName": "FrameLayer"}, "props": {"clipPath": "...", "image": {...}} },
    "id-3":      { "type": {"resolvedName": "TextLayer"},  "props": {"doc": {...}, "fonts": [...]} }
}}]
```

- `ROOT.child` is the **stacking order**: the first id is drawn at the back, the last at the front.
- Every layer has `position` (top-left corner, in canvas pixels) and `boxSize` (width, height).

If you can write down coordinates, you can write a template.

---

## 2. Where the layout ideas came from

The five ideas are **standard social-media post layouts** that designers use again and
again. I didn't copy any specific design. I picked them so that together they cover
different jobs and don't look like each other:

| Template | Layout type | The job it does | Why it works for many businesses |
|---|---|---|---|
| 90001 | **Split panel**: text on a solid colour, photo on the other half, badge on the seam | Sale / discount | Any business with a product or person photo |
| 90002 | **Arch window**: centred headline, arch-shaped photo, pill button | Showcase / premium brand | Interior, salon, spa, boutique, real estate |
| 90003 | **List + circle photo** | Services / features | Agencies, clinics, coaching, any service list |
| 90004 | **Photo-top card**: photo band, colour panel, offer badge | Product / menu promo | Food, retail, product launches |
| 90005 | **Centred event invite**: script kicker, huge headline, date pill, wide photo | Event / opening / announcement | Any event, launch or opening |

I also varied things on purpose so matching has real choices:

- **Number of text boxes:** 4, 5, 5, 6 and 7.
- **Contact line:** website, phone + website, email, address.
- **Photo shape:** full rectangle, arch, circle, rounded rectangle.
- **Mood:** dark, light, white, deep colour, night.

Every idea was checked against the design guide's "simple test": nothing in the
decoration says "restaurant" or "gym". Only the placeholder photo and the placeholder
words do, and the pipeline replaces both at generation time.

---

## 3. How the layout was planned (the grid)

All five use the same simple system on a 1080 × 1080 canvas:

- **70px side margin.** Every left-aligned element starts at `x = 70`. This alone makes a
  design look "designed".
- **Top to bottom in reading order:** logo, kicker (small line), headline, supporting
  text, button, contact line at the bottom (around `y = 960–1010`).
- **Clear size steps (hierarchy):** kicker ~24–26px, body ~26px, button ~30–32px,
  headline 66–118px. The headline is 3–4× the body size, so the eye goes there first.
- **One element that "breaks" the grid:** the badge sitting on the seam in 90001 and 90004,
  the pill overlapping the arch in 90002, the orange dot on the ring in 90003. That
  overlap is what makes a layout feel lively rather than boxy.

Example, template 90001 (numbers are real coordinates from the file):

```
x=0                     x=540                   x=1080
┌───────────────────────┬───────────────────────┐ y=0
│ LOGO (70,60)          │                       │
│                       │                       │
│ NEW COLLECTION (y235) │                       │
│ SUMMER                │      PHOTO FRAME      │
│ STYLE    (y280-634)   │   x=540, w=540,       │
│ SALE     Anton 112px  │   full height 1080    │
│                       │                       │
│ Fresh looks… (y672)  ( 50% )  ← circle badge  │
│                      ( OFF )    x=430, 220×220│
│ [ SHOP NOW ] (y850)   │    sits on the seam   │
│                       │                       │
│ www.yourwebsite.com   │                       │
└───────────────────────┴───────────────────────┘ y=1080
```

The panel on the left isn't a shape at all: it's just the `ROOT` background colour
(navy) showing where the photo doesn't cover it.

---

## 4. How the shapes were made

A shape is one `ShapeLayer`. Only two shape types were needed: `rectangle` and `circle`.

```json
{
  "type": { "type": null, "resolvedName": "ShapeLayer", "fixedText": null, "replacableText": null },
  "props": {
    "shape": "rectangle",
    "position": { "x": 70, "y": 850 },
    "boxSize":  { "width": 270, "height": 78 },
    "color": "rgb(252, 163, 17)",
    "roundedCorners": 160,
    "scale": 5.0625,
    "rotate": 0
  },
  "child": [], "locked": false, "parent": "ROOT"
}
```

The tricks used:

| Effect | How it's made |
|---|---|
| **Button / pill** | A `rectangle` with `roundedCorners`, and a text box of the **same x and width** placed on top with `textAlign: center` |
| **Circle badge** | A `circle` shape with a centred text box inside it (90001, 90004) |
| **Ring around a photo** (90003) | A teal circle 640px wide drawn *first*, then a circle photo 560px wide drawn on top, offset by 40px on each side, which leaves a 40px teal ring |
| **Soft background circles** (90002) | `circle` shapes with `"transparency": 0.35`, drawn before the photo so they peek out from behind it |
| **Corner circles** (90005) | Circles placed partly off the canvas (for example `x = -90`), so only a quarter or half shows |
| **Bullet dots** (90003) | Small 30px teal circles next to each list item |

Two small details:

- `scale` is the value Lido writes for a shape drawn on a fresh canvas (1080 ÷ 213.33 ≈
  5.06). I copied that from the existing 1080px templates.
- **Why shapes and not images:** `palette.py` recolours shape fills. When a user picks
  their own brand colours, every button, badge, ring and dot follows. A decoration drawn
  into an image would stay amber forever.

---

## 5. Where the photos came from, and how they are cropped

### Source

**No image was generated or downloaded from the internet.** The photos are ones already
used by the existing corpus templates, hosted at `assets.quickhub.ai`. I collected every
photo URL from the 19 templates, downloaded them, built a contact sheet and picked the
one that suited each layout:

| Template | Placeholder photo | Taken from |
|---|---|---|
| 90001 | Woman portrait, beige backdrop | template_4 |
| 90002 | Interior living room (portrait shape, suits an arch) | template_10091 |
| 90003 | Business meeting | template_7 |
| 90004 | Plated dessert and glass | template_5 |
| 90005 | Group toasting at a dinner table | template_1825 |

They are only placeholders. At generation time the pipeline replaces every photo slot
with a new AI photo that matches the user's business.

### Photo frames (how the crop shape works)

A photo is a `FrameLayer`. Its crop shape is an SVG path (`clipPath`) drawn in a small
coordinate space that is always **500 units wide**, and `scale` stretches it to the real
size:

```
scale = frame width ÷ 500
clip height = 500 × (frame height ÷ frame width)
```

For 90001's photo (540 × 1080): scale = 1.08, clip space 500 × 1000.

The four crop shapes I wrote:

| Shape | Path idea |
|---|---|
| Rectangle | `M 0 0 L 500 0 L 500 h L 0 h Z` |
| Circle | The exact circle path already used by the corpus templates |
| Arch (90002) | Straight sides and bottom, with the top made from two curves forming a half-circle |
| Rounded rectangle (90005) | Straight edges with a `Q` curve at each corner, same style as template_1 |

### Making the photo fill the frame ("cover" fit)

The image inside the frame has its own size and offset. To fill the frame with no gaps,
the photo is scaled by whichever factor is bigger, width or height, then centred:

```
s = max(500 ÷ photo width, clip height ÷ photo height)
image size   = photo size × s
image offset = (clip size − image size) × focus
```

`focus` is normally 0.5 (centred). For the portrait in 90001 it is 0.3, which keeps the
face higher in the frame instead of cutting through the forehead.

---

## 6. How the text boxes were made to fit perfectly

This is the part that makes the templates pass the pipeline's checks.

1. **Fonts:** only real Google Fonts, each with its gstatic `.ttf` URL in `props.fonts`
   (Anton, Archivo Black, Oswald, Montserrat, DM Serif Display, Great Vibes). Heavy
   display fonts give bold headlines without needing a "bold" style, because the
   pipeline measures each font family with a single font file.
2. **Measuring:** for every text box, the script calls the **same functions the
   pipeline uses** (`TextMeasure` and `wrap` from `backend/app/lido_corpus/textfit.py`).
   These load the real font file and measure the text in pixels.
3. **Box height is calculated, not guessed:**
   `height = number of lines × font size × line height`.
   For example, "SUMMER STYLE SALE" in Anton 112px wraps to 3 lines at a 430px width:
   3 × 112 × 1.05 = 352.8px.
4. **Headroom:** the script printed the widest line against the box width for each
   text. Every one leaves spare room (for example "Summer Style Sale": 371 of 430px), so
   longer real copy still fits.

The script printed a report like this for every box:

```
bodyText    'Summer Style Sale'    3 line(s), widest 371/430px
static      'Shop Now'             1 line(s), widest 159/270px
website     'www.yourwebsite.com'  1 line(s), widest 273/420px
```

### Text types (so roles come out right)

Each text box's `type.type` was chosen on purpose, because `loader.py` uses it to
decide the role:

| `type.type` | Used for | Role the loader gives it |
|---|---|---|
| `bodyText` | Headline, kicker, body copy | Largest one → headline, next → subhead, rest → body |
| `static` | Button text, badge text | label |
| `website`, `phoneNumber`, `email`, `address` | Contact lines | website, phone, email, address |

---

## 7. Colours

Each template uses **one background colour, one or two accents and white or a dark ink**,
which is 3–4 colours as the design guide asks:

| Template | Palette |
|---|---|
| 90001 | Navy background, amber accent, white text |
| 90002 | Cream background, dark brown text, terracotta accent |
| 90003 | White background, teal, orange, dark ink |
| 90004 | Deep green, mustard, ivory |
| 90005 | Plum, coral, butter yellow, white |

Contrast rule followed everywhere: text sits on a **flat colour**, never on a busy part
of a photo. Light text goes on dark colours, dark text on light colours, and button text
is the opposite of its button.

---

## 8. Logo

The logo is its own `FrameLayer` with `type: "logo"`, copied exactly from how
template_227 does it (`objectFit: contain`). It uses the existing
`logo_white.png` / `logo_black.png` assets: white on dark templates, black on light
ones. It's always in a sensible spot: a top corner, top centre, or bottom right.

---

## 9. How the screenshots were produced

Lido itself wasn't available to take the screenshots, so:

1. The script also writes an **HTML page** for each template. Text is drawn as HTML
   (so it wraps like Lido does), shapes are `div`s, and photo frames are SVGs using the
   same `clipPath` and image offsets as the JSON.
2. **Headless Google Chrome** opens each page and saves a screenshot.
3. The screenshot is cropped to exactly 1080 × 1080. The first try cut off the bottom,
   because Chrome's window is slightly shorter than its size setting.
4. I looked at every screenshot and fixed what was wrong. For example, a terracotta
   circle in 90002 was sitting under the headline, so I moved it behind the arch.

---

## 10. Final checks

- The backend's own loader (`derive_meta`) read all five files without errors, and
  assigned roles as intended.
- No background image was set, so no background prompt is needed. The whole background
  is recolourable.
- All placeholder text fits its box, measured with the real fonts.

---

## 11. Known limits (be aware)

- **The screenshots come from my HTML renderer, not the Lido editor.** They are close,
  but `roundedCorners` on buttons is approximated (about `roundedCorners ÷ 4` pixels of
  radius). Import each JSON into the Lido editor. If it looks different there, use an
  editor screenshot as the preview.
- **Role quirk in 90003:** the first service item ("Strategy & Planning", 28px) becomes
  "subhead" because it's larger than the kicker (24px). Explain it in that slot's
  `notes` during review, or make the kicker bigger.
- **IDs 90001–90005 are placeholders.** Rename them if they clash with real template IDs.

---

## 12. Making more templates: the script

Everything above is now automated in `scripts/lido_create_layouts.py`.

```bash
make lido-create                      # 5 new drafts from the built-in layout recipes
make lido-create COUNT=10 SEED=7      # 10 drafts; the same SEED gives the same batch
make lido-create AI=1 COUNT=3         # let the LLM invent 3 brand-new layouts
make lido-create AI=1 IDEA="testimonial quote with a portrait"

# more control:
backend/.venv/bin/python scripts/lido_create_layouts.py --list     # every option
backend/.venv/bin/python scripts/lido_create_layouts.py \
    --recipe arch_showcase --theme beauty --palette plum-coral --count 3
```

Output goes to the database as drafts (the `lido_drafts` table,
`infra/initdb/006_lido_drafts.sql`), with each preview screenshot uploaded to the object
store; review them in the **Design new template** tab. Each draft is known by its row
`id`; it gets a `template_<n>` name (from 90001) only when exported. Nothing enters matching until you export a draft into
the corpus:

```bash
make lido-draft-export ID=<draft id>   # writes template_N.json + previews/template_N.png, prints N
make lido-add TEMPLATE=template_N KIND=post
```

### How it produces different creatives

Each template is **a recipe × a palette × a font pairing × a copy theme**, optionally
mirrored left to right:

| Ingredient | Count | Where |
|---|---|---|
| Layout recipes | 10: the 5 above plus `card_over_photo`, `twin_photo`, `offset_frame`, and the pro `fresh_promo` and `geo_agency` | `backend/app/lido_create/recipes.py` |
| Palettes | 12, each pairing already contrast-safe | `kit.py` → `PALETTES` |
| Font pairings | 5: Anton, Archivo Black, DM Serif Display, Playfair Display, Bebas Neue (with Montserrat, Oswald and Great Vibes) | `kit.py` → `FONT_SETS` |
| Copy themes | 8: fashion, interior, business, food, event, beauty, education, wellness | `kit.py` → `THEMES` |

Within one batch the script rotates through recipes, palettes, fonts and themes, so
items don't repeat. It also skips every combination already saved as a draft, so a rerun never produces
the same one twice.

Recipes don't use fixed coordinates for everything. Positions **flow from the measured
text**: a headline that wraps to 3 lines pushes the body and button down, and headlines
shrink step by step until they fit their line budget in whatever font was picked.

### Photos

The script collects every photo already used by the corpus templates, downloads each
once to learn its size (cached in `lidojs_templates/.photo_cache.v2.json`), and gives it **one**
theme from its template's tags. It skips logos, icons and transparent cutouts. Each
frame gets an on-theme photo whose shape is closest to the frame's shape. A theme is
only used with a recipe it has enough photos for, so a portrait is never paired with a
plate of food.

### The checks (why the results are consistent)

Before anything is saved, `backend/app/lido_create/check.py` checks each design. A
combination that fails is thrown away and another is tried:

- every text fits its box and line budget, measured with the real font
- no text overlaps other text, the logo or a photo, and nothing is drawn on top of text
- every text sits on **one** flat colour (never across a shape's edge) with WCAG
  contrast of 4.5:1, or 3:1 for large text
- text and logo stay at least 30px from the edge; the logo sits on a flat colour
- 1–2 photos, each at least 200px on each side
- the headline is the largest text, so the loader assigns the right roles

Run with `--verbose` to see what was rejected and why.

### AI mode (`AI=1`)

The script gives the LLM (the project's configured OpenAI model) the design rules, the
existing recipes (to avoid copying them), two recipes in the exact element format, and a
palette, font pairing and copy theme from the same rotation. The LLM returns a new
layout as a list of elements. The layout goes through **the same checks**, and any
failures are sent back for repair, up to 2 rounds (`--repairs`). Each layout takes about
a minute. Expect AI layouts to be more varied but less polished than the recipes:
review them more carefully. When you like one, it can become a new recipe.

### Adding your own recipe, palette or theme

- **Palette:** add a `Palette(...)` line in `kit.py`. `soft` is a decoration colour only.
  The checks will reject a palette whose text colours don't contrast.
- **Theme:** add a `Theme(...)` with its placeholder copy and the corpus tags its photos
  come from.
- **Recipe:** write a function in `recipes.py` using the `Canvas` helpers (`c.photo`,
  `c.shape`, `c.logo`, `c.headline`, `c.kicker`, `c.text`, `c.button`, `c.contact`),
  back to front, and register it in `RECIPES`. Then run
  `--recipe your_recipe --count 8 --verbose` and read what the checks reject.
