# Colour theme: a user palette applied during generation

Status: **implemented** (2026-09-29). Code: `backend/app/lido_corpus/palette.py`, wired in
through `pipeline.py` and `generate_ai.py`. API: `POST /v1/lido/generate` takes
`palette`. UI: the "Colour theme" row on the Lido page.

## What the user gives

Up to **4 colours** (`#rrggbb`), in order. The first is the **primary**, then the
secondary, the accent and one extra. The palette is **optional**:

- **No palette** (field missing, `null` or `[]`): generation is exactly as before. The
  model gets the same message, the images get the same prompts, and the design keeps the
  template's own colours.
- **Template search never looks at colour.** The palette is applied only after the
  template is chosen, while it is generated.

## What gets recoloured

| Part of the design | How |
|---|---|
| Shapes (fill and border) | The template's accent colours by prominence (area covered): the most prominent one takes the primary, the next the secondary, and so on. |
| Text (every colour run, paragraph colours, `props.colors`, effect colours) | Same mapping, then made readable (below). |
| Shades of one colour | They move together: a lighter shade of the template's brown becomes a lighter shade of the palette colour. |
| Near-black / near-white text and shapes | They move only to a palette colour that is itself that dark or light (e.g. black text → a deep navy in the palette). Otherwise they stay. |
| Root colour | Same mapping. |
| Background and photos | The fill model is told the palette and the final text colours. A fixed palette line is added to every image prompt. |
| Food, products, people in photos and cutouts | They keep their natural colours. The palette goes into the setting, props, lighting and accents. |

Each template colour takes the next palette colour **on its own light/dark side**. A
dark panel with white text on it stays dark. If the palette has no colour that dark, the
next palette colour is darkened. A shape with text on it counts as the opposite side of
that text. So the template's structure (light text on dark areas, dark text on light
areas) is kept, and the background prompt's "keep this area dark" notes stay true.

## Readability: checked three times

1. **Text on a shape** must reach WCAG contrast with the shape's *new* colour: 3:1 for
   text of 24px and larger, 4.5:1 for smaller text.
2. **Text on the picture** keeps its original light/dark side, at least as far from the
   opposite pole as the original colour was.
3. **Against the background the design ships with**, the pixels behind every text box are
   measured (median of the box). That is the newly generated background, or, when none was
   generated (`generateImages: false`, or its generation/upload failed), the template's own
   background picture, downloaded for the check. A text colour that doesn't reach the
   contrast above is swapped.
   The order of preference is: the first readable palette colour, then the same hue made
   lighter or darker, then black or white. The layers this happened to are listed in
   `theme.contrastFixed`.

## What is recorded

`meta.generation.theme` on the saved design, and `theme` in the API response:

```json
{
  "palette": ["#0b3d2e", "#f2c14e", "#e4572e", "#f7f3e9"],
  "colorMap": {"#16263c": "#0b3d2e", "#ffffff": "#f7f3e9"},
  "textColors": {"<layer_id>": {"#ffffff": "#f7f3e9"}},
  "contrastFixed": []
}
```

Both are absent/`null` when no palette was chosen.

## Limits

- Fonts are not changed. Only their colours are.
- Text sitting on a *photo frame* (not the background or a shape) is only protected by
  rule 2, not measured.
- The image model follows the palette well for backgrounds (checked: pizza request with
  the "Forest" palette gave a deep-green background with gold, red-orange and cream
  accents). It is still a model, so small accents may drift.
