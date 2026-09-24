-- Lido.js (template) generation history.
--
-- The generated document (`[{"layers": ..., "meta": ...}]`) is stored directly in
-- `document` — the source of truth a design is reopened from. `path` is kept only for
-- a design promoted in from the old file-based storage (nullable; new rows leave it null).

create table if not exists lido_generations (
  id text primary key,
  template_id text,
  name text not null default '',
  kind text not null default 'post',
  aspect text not null default '1:1',
  prompt text not null default '',
  canvas_size jsonb not null default '{}',
  thumbnail_url text,
  document jsonb not null default '{}',
  path text,
  created_at timestamptz not null default now()
);
create index if not exists lido_generations_created_idx on lido_generations (created_at desc);
