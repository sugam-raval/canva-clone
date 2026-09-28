# Template export rules — don't let a template silently break

`make lido-add`'s mechanical verify (`scripts/enrich_lido_templates.py:_verify`, see
[`TEMPLATE_METADATA_RULES.md`](TEMPLATE_METADATA_RULES.md)) catches a lot, but it only
checks what it was written to check. Twice now a raw export shaped slightly differently
than the rest of the corpus has passed verify clean and still produced a broken result:

- `template_11447` — the template's own placeholder text (`reallygreatsite.com`)
  physically didn't fit its own text box. Verify *did* catch this one (`FAIL`), but only
  because the box happened to be narrow enough — a slightly bigger box would have hidden
  the same problem.
- `template_11134` — its background picture lived on a nested child layer instead of on
  `ROOT` itself. Verify had no rule for that shape, so it passed clean, `meta.background`
  silently stayed empty, and every design generated from it kept the template's own
  stock photo instead of a brief-matched one — invisible until someone actually compared
  a generated design's background against the prompt.

Both were the same failure mode: **the export wasn't in the shape the pipeline
assumes**. This file is the checklist for that — the structural assumptions baked into
the code (not the human-authored `meta` fields, which is what
[`TEMPLATE_METADATA_RULES.md`](TEMPLATE_METADATA_RULES.md) covers), so you can check a
new template against them *before* trusting a clean `make lido-add` run.

## The assumptions the pipeline hardcodes

**One `ROOT` layer, and it IS the background image layer.**
`BACKGROUND_LAYER_ID = "ROOT"` (`backend/app/lido_corpus/generate_ai.py`) — background
generation reads and writes `layers["ROOT"].props.image` and nowhere else.
`ROOT.type.type` should be `"bgImage"` directly, same as every template already in
`lidojs_templates/` except `template_11134`. Check with:

```bash
python3 -c "
import json
d = json.load(open('lidojs_templates/template_N.json'))
print(d[0]['layers']['ROOT']['type'].get('type'))"
```

If that prints anything other than `bgImage` and the visible background is on a
*different* layer (look for `"type": "bgImage"` elsewhere in the file, usually a child
of `ROOT`), the export is the shape `template_11134` and `template_7347` had (it seems
common in the `without_<category>_<n>.png` exports). The pipeline now handles it:

- Detection falls back to that child (`root_background_url()` in
  `backend/app/lido_corpus/loader.py`), so `meta.background` gets drafted, and `_verify`
  fails a template whose background image has no `meta.background` prompt. Before this,
  both passed silently with no background prompt.
- At generation time the new background URL is copied onto that child too
  (`background_mirror_ids()` in `backend/app/lido_corpus/generate_ai.py`), or the design
  would keep showing the template's own photo.
- Still copy the background URL onto `ROOT.props.image` as well: the app's own preview
  (`frontend/src/lib/lidoRender.tsx`) only draws `ROOT`'s image, so without it the
  template shows a blank background there.

**Text boxes must be about as wide as the space the text visibly has.** Some exports
keep a leftover default width (536px in `template_7347`) on every text box, even text
inside a 70px badge. The fit check measures against the box, so with a 536px box it
lets "ORDER NOW" through on one line, 94px wide, overflowing the badge in every
generated design. Look for boxes that run past the canvas edge
(`position.x + boxSize.width > canvas width`) or are far wider than their text, and
narrow them to the visible space; the template's own copy looks the same, and the
checks then enforce the real limit.

**The template's own default text must fit its own box, in its own font, at its own
size — always check with the real renderer, never by eye.** A box that looks "roughly
wide enough" can still be a few pixels short once the real font's actual glyph widths
are measured. Before `make lido-add`, or any time you touch a text slot's box, font size
or default text:

```bash
cd backend && .venv/bin/python -c "
from app.lido_corpus.loader import load_enriched, DEFAULT_CORPUS_DIR
from app.lido_corpus.generate_ai import text_targets, check_text
t = load_enriched(DEFAULT_CORPUS_DIR / 'template_N.json')
for x in text_targets(t): print(x.slot.role, check_text(x.slot.default_text, x) or 'OK')"
```

If a slot's placeholder is genuinely too tight (e.g. a long domain like
`reallygreatsite.com` in a narrow footer box), shorten the placeholder — don't widen the
box just to make the check pass, since the box width is also what real generated text
has to fit into later.

**Font family must be a real, fetchable Google Fonts family name** (or the layer's own
`props.fonts` must carry a working font URL). `check_text`'s width math is only as good
as the font it measures with; an unresolvable family silently falls back to a rough
per-character estimate, which can pass verify and still overflow (or wrongly fail) in
the real font.

**The logo slot must be locked, with a non-generated image.** `role: "logo"` +
`locked: false` or a `generate: true` image spec is a hard error — a logo is never
supposed to be regenerated per-brief.

**Every photo/frame slot needs an image spec.** No `image` at all means the sample photo
baked into the export would never get replaced for a real brief — also a hard error.

**File name must be `template_<integer>.json`.** `lido_templates.id` is that integer
directly, not a surrogate key (`app/db/repo.py:template_db_id`) — there's nowhere else
for it to come from.

**There is no "reviewed" gate any more.** Older docs/code used to talk about
`meta.reference_note` marking a template as reviewed and required before it was a match
candidate — that field and the `ready` column it fed are gone entirely (they were purely
informational for a while, then removed). Every template with a `meta` block is a match
candidate the moment `make lido-add` succeeds. That makes the "was this actually
reviewed by a human" question purely a matter of you having looked at the diff — nothing
in the system tracks or enforces it, so don't rely on the corpus to tell you which
templates still need a look.

## Before trusting a clean `make lido-add`

1. Run the text-fit check above for every text slot, even though `_verify` already runs
   it — reading the actual numbers (not just OK/FAIL) tells you how much margin you have.
2. Check `ROOT.type.type == "bgImage"` as above. If not, work out where the real
   background picture is and make sure `meta.background.prompt` actually gets drafted
   (an empty `meta.background` on a template with a visible photo background is always
   wrong, verify or no verify).
3. Open the file and sanity-check `meta.background.prompt` against the actual picture,
   and `name`/`tags`/`description` against what the template is actually for — matching
   reads these, and the AI draft gets them wrong more often than the mechanical checks.
4. Generate one test design from it and compare the generated background/photos against
   the prompt you gave — the only way to catch a mismatch like `template_11134`'s is to
   actually look at a generated result, since nothing mechanical currently checks that a
   generated background reaches every layer that renders it.
