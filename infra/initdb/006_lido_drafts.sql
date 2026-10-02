-- Draft templates designed from a prompt ("Design new template", POST /v1/lido/drafts)
-- or by `make lido-create`, waiting for review. Never match candidates: a reviewed
-- draft is exported into lidojs_templates/ (`make lido-draft-export ID=<id>`, which
-- names the file template_<n>) and onboarded with `make lido-add`.
--
-- Replaces the old file storage in lidojs_templates/drafts/ (template_<n>.json,
-- previews/template_<n>.png, template_<n>.info.json); `scripts/lido_drafts.py import`
-- moves those in, keeping the old name as info.importedFrom.

create table if not exists lido_drafts (
  -- the draft's id everywhere (GET /v1/lido/drafts/<id>, its previews' object-store path)
  id integer generated always as identity primary key,
  -- brief (designed from a prompt), ai / recipe (make lido-create), manual (imported
  -- without any record of how it was made)
  source text not null default 'brief',
  prompt text not null default '',
  name text not null default '',
  -- the notebook line the art director avoids repeating (drafts.recent_fingerprints)
  fingerprint text,
  -- public object-store URL of the screenshot; null when none could be taken
  preview_url text,
  -- how it was made, for the review UI: layout, theme, palette, fonts, colours, plan,
  -- photo subjects/source, check problems… (the camelCase LidoDraftInfo fields)
  info jsonb not null default '{}',
  -- how long designing it took, request start → this draft saved (null when unknown:
  -- imported, or made by `make lido-create`)
  generation_ms integer,
  -- the same, step by step: planMs (shared by a request's variations), designMs and
  -- photosMs (this variation's own), saveMs (storing it + its preview), totalMs
  timing jsonb not null default '{}',
  -- the raw Lido export, `[{"layers": …}]` — what is exported into the corpus
  document jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists lido_drafts_created_idx on lido_drafts (created_at desc);
create index if not exists lido_drafts_fingerprint_idx on lido_drafts (created_at desc)
  where fingerprint is not null;
