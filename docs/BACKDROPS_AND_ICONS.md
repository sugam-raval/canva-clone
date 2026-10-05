# Backdrops and icons ("Design new template")

Two code-built layers the code places, so the designer model never has to draw a
diagonal edge or an icon by coordinates.

## Backdrops — layered gradient backgrounds

`backend/app/lido_create/backdrops.py`. The plan's `backdrop` picks a style and a few
knobs; `expand()` turns it into full-bleed gradient shapes under everything else.

| Style | Built from | Knobs |
|---|---|---|
| `split_half` | one gradient panel on a side | side left/right/top/bottom, split |
| `diagonal_split` | a long rotated panel | side top/bottom, angle, split |
| `diagonal_bands` | two slanted bands | angle, split |
| `corner_glow` | two radial glows from opposite corners over a fade | side left/right |
| `spotlight` | one large radial glow | side center/left/right/top/bottom |
| `horizon_arc` | a huge circle rising from an edge | side top/bottom, split |

- Colours are roles (`tone`: accent / soft / on_accent), so brand palettes apply.
- The designer is told the geometry and the text areas with the colours that read in
  each — measured with the checks' own contrast maths when the palette is known.
- The layers are normal shapes (marked `backdrop`): text is checked against them like
  any other shape; photos may sit on them; a glow that fades out before its rim has no
  edge to straddle (`check.seamless`).
- Which moods use which styles: `backdrops:` in `library/moods.yaml`.

To add a style: write its geometry in `expand()`, describe it in `STYLES`, list its
sides in `SIDES`, then add it to the moods that suit it.

## Photo fade (scrim)

A full-bleed photo with one fade layer over it: a canvas-sized rectangle in the canvas
colour, solid up to `start_at` (30-40%) and fading to transparent by 100%, so the photo
melts into a calm flat area that holds the logo, headline, copy and button — the look
of a Lido layer like:

```json
{"shape": "rectangle", "color": {"style": "linear", "angle": 180, "colors": [
  {"color": "rgb(221, 213, 206)", "percent": 29}, {"color": "rgba(…, 0)", "percent": 100}]}}
```

- `angle` 180 fades from the top, 0 from the bottom, 90 from the left, 270 from the
  right. The designer writes it as a normal shape with `gradient: {style: linear,
  angle, start: bg, end: null, start_at, end_at: 100}` (technique in `ai.py`); the art
  director can pick it as the `photo_fade` layout (`library/layouts.yaml`).
- Checks: text on the fading part still "sits on a photo" (it must stay in the solid
  part); the photo counts as hidden only where a fade is more than 80% opaque
  (`check.HIDES_FADE`), so the photo below the fade stays the hero.

## Icons — beside contact lines, and as list bullets

`backend/app/lido_create/library/icons.yaml` (18 icons: 16 contact/info icons and 2
bullet glyphs) is the icon library; `doodles.py` draws one into any box as a Lido `DrawLayer` (exact
strokes); `decorate.add_contact_icons` places them.

- A clean icon goes beside each website / phone / email / address line (`pairs_with`),
  in the text's colour; the text moves over to make room. On unless the plan sets
  `contact_icons: false` or excludes contact details.
- Every icon is re-checked and dropped if it adds a problem.
- **List bullets** are solid markers drawn by `lists.py` from Lido shapes — dot, dash
  ("–"), ring, square, diamond, triangle, check, check_circle (white tick in a filled
  circle), arrow_circle, plus, number, and fancier two-part ones: check_ring (tick in a
  circle outline), check_square, arrow_square, plus_circle, target, diamond_outline,
  number_ring, glow_dot — sized from the text and centred on each item's first line; the designer picks the style per list and mood. The library's `bullet:
  true` entries (tick, chevron) are only the glyphs inside the tick and arrow bullets.

### Adding icons

- **Your own**: add an entry with `source: hand` to `doodles.yaml` — a stroke path in a
  24 x 24 box (the format is documented at the top of the file).
- **From Lucide** (ISC, `library/icons.LICENSE.md`): add a line to `CATALOG` in
  `scripts/build_doodles.py` and run it; it never touches hand-drawn entries.
- Then `make lido-doodles`: validates the library (bad paths, duplicates, paths
  leaving the box) and draws every icon on a sheet in `lidojs_templates/doodles/`.
