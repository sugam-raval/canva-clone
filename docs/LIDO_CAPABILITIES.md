# What Lido.js can draw (reference)

Everything the Lido editor supports, and exactly how each feature is stored in the
exported JSON. Found by exporting one of everything from the editor. The source exports
and their screenshots are in `lidojs_templates/lido_core/` (not templates, so matching
never reads them).

The template generator (`backend/app/lido_create/`) reads this list from one place,
`shapes.py`, so the Lido writer, the preview, the design checks and the AI instructions
always agree.

| File in `lido_core/` | Shows |
|---|---|
| `shapes_collections.json` + `preview/shapes_collections.png` | all shapes, lines, a gradient fill, transparency, borders, corner radius |
| `frame_collections.json` + `preview/frame_collection.png` | all photo-frame outlines, one with a photo |
| `background_gradient.json`, `radial_gradient.json`, `linear_gradient_{0,45,90,135}.json` | page-background gradients |
| `text_effect.json` + `preview/text_effect.png` | text effects |
| `draw_feature.json` + `preview/draw_feature.png` | freehand drawing |
| `element_feature.json` + `preview/element_feature.png` | icons (not used yet) |

---

## Shapes: `ShapeLayer`

```json
{"type": {"resolvedName": "ShapeLayer"},
 "props": {"shape": "chevron", "position": {"x": 0, "y": 0},
           "boxSize": {"width": 173, "height": 58}, "rotate": 0, "scale": 5.0625,
           "color": "#5E6278", "roundedCorners": 63, "transparency": 0.35,
           "border": {"style": "solid", "weight": 4, "color": "rgb(0, 0, 0)"}}}
```

**The 20 shape names:** `rectangle`, `circle`, `triangle`, `triangleUpsideDown`,
`rhombus`, `pentagon`, `hexagonVertical`, `hexagonHorizontal`, `octagon`,
`parallelogram`, `parallelogramUpsideDown`, `trapezoid`, `trapezoidUpsideDown`, `cross`,
`chevron`, `arrowPentagon`, `arrowRight`, `arrowLeft`, `arrowTop`, `arrowBottom`.

These outlines were measured from the editor's rendering (unit square, see `shapes.py`):
- octagon: corners cut at 30%
- cross: arms in thirds
- parallelograms and trapezoids: slant about 10% of the width
- block arrows: head starts at 73% of the length, body is the middle 46%
- chevron and arrowPentagon: point about 10% deep

| Property | Notes |
|---|---|
| `roundedCorners` | Rectangle. **Visible radius in px = `roundedCorners` ÷ `scale`** (63 ÷ 5.06 ≈ 12 px, measured) |
| `transparency` | 0–1, the whole shape |
| `border.style` | `solid`, `shortDashes` (dashed), `dots` (dotted) |
| `scale` | 5.0625 on a 1080 canvas (only scales the border/radius units) |
| `rotate` | Degrees, around the shape's centre |

## Gradients: a `color` object instead of a string

On a `ShapeLayer.color` or on `ROOT.props.color` (the page background):

```json
"color": {"style": "linear", "angle": 45,
          "colors": [{"color": "rgba(235, 71, 61, 1)", "percent": 14.5},
                     {"color": "rgba(235, 71, 61, 0)", "percent": 99.6}]}
```

- **Two stops.** Each stop has its own colour, its own transparency (the `rgba` alpha)
  and a position (`percent`). A common pattern is one colour fading to transparent.
- **`style`:** `linear` or `radial`.
- **`angle`:** linear direction. It's assumed to be CSS-style (0 = towards the top, 90 = right,
  180 = down); **confirm the direction in the editor.** Radial exports carry `angle`
  too (180) but ignore it.
- When a gradient has no `angle`, it runs top → bottom.

## Lines: `LineLayer`

```json
{"type": {"resolvedName": "LineLayer"},
 "props": {"style": "dots", "boxSize": {"width": 120, "height": 4},
           "color": "rgb(94, 98, 120)", "position": {"x": 29, "y": 39}, "scale": 1,
           "rotate": 0, "arrowStart": "none", "arrowEnd": "arrow"}}
```

- `boxSize.width` is the length, `boxSize.height` is the thickness, and `rotate` sets the angle.
- `style`: `solid`, `shortDashes`, `dots`.
- `arrowStart` / `arrowEnd`: `none`, `arrow`, `triangle`, `bar`, `circle`, `square`,
  `diamond`, `outlineCircle`, `outlineSquare`, `outlineDiamond`.

## Photo frames: `FrameLayer` with `clipPath`

```json
{"type": {"resolvedName": "FrameLayer"},
 "props": {"clipPath": "M 28.4 238.6 c ...", "position": {...},
           "boxSize": {"width": 61.13, "height": 86.77}, "scale": 0.2769, "rotate": 0,
           "image": {"url": "...", "boxSize": {"width": 250.7, "height": 313.4},
                     "position": {"x": -14.9, "y": 0}}}}
```

- The frame's **natural size = the outline's bounds = `boxSize ÷ scale`**. A frame keeps
  its outline's aspect ratio.
- `image.boxSize` / `image.position` are in natural units: the photo is cover-fitted
  and centred.
- **41 outlines**, saved by name in `backend/app/lido_create/data/frames.json`:
  - circle, egg_blob, brush_stroke, brush_band, scallop_badge, triangle, ring (donut),
    oval, torn_paper, brush_swoosh, corner_card, rounded_card, gem, brush_layers,
    torn_panel
  - `letter_A` … `letter_Z`

## Text effects: `TextLayer.props.effect`

```json
"effect": {"name": "shadow", "settings": {"offset": 52, "direction": -141, "blur": 11,
                                          "transparency": 37, "color": "rgb(0, 0, 0)"}}
"effect": {"name": "lift",   "settings": {"intensity": 50}}
"effect": {"name": "hollow", "settings": {"thickness": 50}}
```

- **Hollow:** outline-only letters, readable only at large sizes. The generator requires 56 px or more.
- **Shadow `color`:** recoloured with the palette (this already worked).

## Freehand drawing: `DrawLayer`

```json
{"type": {"resolvedName": "DrawLayer"},
 "props": {"path": "M 15.352,6.352 C 18.307,5.182 ...", "color": "#0571d3",
           "width": 5, "position": {...}, "boxSize": {...}, "rotate": 0,
           "scale": 1.49, "transparency": 1}}
```

- `path` is in the layer's own space, stretched by `scale`. `width` is the stroke width.
- **The generator** writes its own marker strokes (`draw.py`) with `scale` 1:
  underline, double_underline, circle, arrow, squiggle, zigzag, sparkle, check.

## Icons: `ImageLayer` (not used yet)

```json
{"type": {"resolvedName": "ImageLayer"},
 "props": {"image": {"url": "https://assets.quickhub.ai/qh-templates/1758865525_70.png",
                     "boxSize": {"width": 50, "height": 50}, ...}, ...}}
```

Icons are small transparent PNGs (128 × 128, dark). An image can't change colour, so
using them needs a light and a dark version of each. This has been left for later.

---

## Palette recolouring (the generation pipeline)

`backend/app/lido_corpus/palette.py` maps a template's colours onto a user's palette:

| Feature | Recoloured? |
|---|---|
| Shape fill / border | ✅ (always was) |
| **Gradient** on a shape or on the page | ✅ each stop recoloured, **transparency kept** (a fade stays a fade) |
| **LineLayer / DrawLayer** colour | ✅ |
| Text colour, text shadow colour | ✅ (always was) |
| Icons (ImageLayer) | ❌ images can't be recoloured |

## Still to confirm in the Lido editor

1. **Gradient direction.** Open a draft that has an angled gradient and check the
   fade runs the way the preview shows (CSS angles assumed).
2. **Hand-drawn strokes** written by the generator (`scale` 1) sit where the preview
   shows them.
3. **Rotated shapes** rotate around their centre.
