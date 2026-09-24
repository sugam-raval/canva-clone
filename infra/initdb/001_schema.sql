-- Lido.js (template) flow — template catalog with embeddings.
--
-- Runs on a fresh database volume only (docker-entrypoint-initdb.d). For an existing
-- database, `make db-upgrade` applies every file in this folder (all idempotent).

create extension if not exists vector;

-- One row per template. The JSON files in lidojs_templates/ are the authoring source;
-- the API (and `make lido-sync`) mirrors them here, re-embedding only templates whose
-- metadata changed (see app/lido_corpus/store.py). `source_file` is set for rows that
-- came from a file, so a row added any other way is never deleted by a sync.
create table if not exists lido_templates (
  id text primary key,
  name text not null default '',
  kind text not null default 'post',
  aspect text not null default '1:1',
  tags text[] not null default '{}',
  description text not null default '',
  document jsonb not null,                   -- the template file: [{"layers", "meta"}]
  card text not null default '',             -- the English text that gets embedded
  details jsonb not null default '{}',       -- detail slots: phone, website, offer, ...
  fingerprint text not null default '',      -- hash of meta + model + card format
  embedding vector(384),                     -- all-MiniLM-L6-v2 (SENTENCE_TRANSFORMER_MODEL)
  embedding_model text,
  ready boolean not null default false,      -- has meta.reference_note (human-reviewed)
  source_file text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists lido_templates_embedding_idx
  on lido_templates using hnsw (embedding vector_cosine_ops);
