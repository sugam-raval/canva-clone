# Design library: what "design from scratch" can use

Everything the AI can choose from when it designs a new template from a prompt lives
in this folder. **Edit these files, not the Python code**, to change what the AI uses.

Restart the backend after any change, then run `make test` to check it.

## The files

| File | What it controls | Remove an item | Add an item |
|---|---|---|---|
| `shapes.yaml` | Lido shapes (badges, bands, arrows) | comment its line | Lido's own shapes only: its outline must exist in `SHAPES` in `shapes.py` |
| `frames.yaml` | photo frame outlines (brush, torn paper, letters…) | comment its line | add its outline to `frame_outlines.json`, then a line here |
| `crops.yaml` | simple photo crops (rect, rounded, circle, cutout…) | comment its line | needs drawing code in `lido.py` |
| `draw.yaml` | hand-drawn strokes (underline, loop, arrow…) | comment its line | needs a branch in `draw.py` `draw_path` |
| `effects.yaml` | text effects (shadow, lift, hollow) | comment its line | Lido's own effects only: `TEXT_EFFECTS` in `shapes.py` |
| `bullets.yaml` | list markers | comment its line | needs a branch in `lists.py` `bullet_marks` |
| `line_ends.yaml` | line end markers | comment its line | Lido's own line ends only: `LINE_ENDS` in `shapes.py` |
| `backdrops.yaml` | layered gradient backgrounds | comment its line | needs a branch in `backdrops.py` `expand` (+ `SIDES`) |
| `layouts.yaml` | post structures the art director picks | comment out the entry's lines | copy an entry and edit it; no code needed |
| `moods.yaml` | which frames/shapes/strokes/effects/backdrops fit each feeling | comment out the entry's lines | copy an entry and edit it; no code needed |
| `icons.yaml` | line icons beside contact lines and inside bullets | comment out the entry's lines | copy an entry (24×24 SVG path); check with `make lido-doodles` |
| `frame_outlines.json` | the frames' geometry | — (switch frames off in `frames.yaml`) | see `frames.yaml` |

## Removing something: comment it out

The menus (`shapes.yaml` … `backdrops.yaml`) have one line per item:

```yaml
chevron: "notched arrow band pointing right; step flows, direction strips"
# octagon: "octagon; stop-sign style badges"      <- switched off
```

An item that's commented out is gone for the AI **everywhere**:

- it isn't in the designer's or the art director's instructions,
- a mood that lists it simply skips it,
- the AI's reply schema doesn't allow it, so the model can't write it even if it tried.

Uncomment the line to bring it back.

**What stays drawable.** The code can still draw the item. The hand-made example designs
the AI is shown may still contain it, and the general design advice in `ai.py` may still
mention it as an example ("chevrons for flow"). Neither lets the AI *use* it, because the
schema decides.

**Switching off a whole kind.** If you comment out every line of a menu:

- no shapes: the AI gets no shape elements,
- no strokes: no hand-drawn accents,
- no backdrops: the backdrop is always none.

`frames.yaml` and `crops.yaml` can't both be empty, because a photo needs one of them.

## Adding something

For a **layout** or a **mood**, copy an existing entry in `layouts.yaml` / `moods.yaml` and
edit it. The comment at the top of each file explains every field. No code needed.

For a **shape, frame, stroke, bullet, effect, line end or backdrop**, the menu line is
what the AI reads, but something must also be able to *draw* the new item. The "Add an
item" column above says where. Add the drawing code first, then the line:

```yaml
wave: "a wavy band across the canvas; playful, summer"
```

The hint after the name is what the AI reads. Say what it looks like and when to use it.
Wrap it in double quotes, because a hint containing `: ` or `#` breaks YAML otherwise.

## Mistakes are caught at startup

A name the code can't draw (a typo, or a new item whose drawing code isn't written yet)
stops the backend with a message like:

```
library/shapes.yaml lists 'chevronn', which the code can't draw (only: arrowBottom, …).
Fix the spelling, or add its drawing code first — see library/README.md.
```

A mood or layout naming something unknown is reported by `make test`.
