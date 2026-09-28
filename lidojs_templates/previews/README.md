# Template previews

A screenshot of each finished template — text and logo placed on the background —
named after the template file:

    template_7347.json  ->  previews/template_7347.png   (.jpg / .jpeg / .webp also work)

`make lido-add` / `make lido-meta` show it to the drafting models next to the text-free
background (`scripts/enrich_lido_templates.py`, `_load_preview`). Without it they can't
tell what a blank badge is for or which element is the promoted product, and the draft
gets noticeably worse.

- Only used while drafting metadata; the app never reads these at runtime.
- Only a real screenshot of that exact template — a placeholder here would be taken as
  the design and mislead the draft.
- Drafts never overwrite a filled field, so to redraft a template with a new screenshot,
  delete its `meta` block first.
