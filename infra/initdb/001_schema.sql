-- Database schema — IMPLEMENTATION_PLAN §0.7.
-- Part Two (decomposition) tables are omitted; that pipeline is deferred.

create extension if not exists vector;
create extension if not exists pgcrypto;

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  created_at timestamptz not null default now()
);

create table if not exists brand_kits (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  name text not null,
  palette jsonb not null default '[]',
  fonts jsonb not null default '[]',
  logo_asset_id uuid,
  tone text,
  created_at timestamptz not null default now()
);
create index if not exists brand_kits_user_idx on brand_kits (user_id);

create table if not exists documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  title text not null default 'Untitled',
  schema_version int not null,
  doc jsonb not null,
  ydoc bytea,
  thumb_asset_id uuid,
  provenance jsonb not null default '{"kind":"blank"}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists documents_user_updated_idx on documents (user_id, updated_at desc);

create table if not exists assets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete set null,
  kind text not null,
  storage_key text not null,
  mime text not null,
  width int,
  height int,
  has_alpha bool not null default false,
  bytes bigint,
  gen_hash text,
  gen_params jsonb,
  created_at timestamptz not null default now()
);
-- §6.1: identical generation requests must be free.
create unique index if not exists assets_gen_hash_key on assets (gen_hash)
  where gen_hash is not null;

create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null,
  doc_id uuid references documents(id) on delete cascade,
  layer_id text,
  type text not null,
  state text not null default 'queued',
  attempts int not null default 0,
  input jsonb not null default '{}',
  output jsonb,
  error text,
  cost_cents int not null default 0,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create index if not exists jobs_request_idx on jobs (request_id);
create index if not exists jobs_state_idx on jobs (state, type);

create table if not exists templates (
  id text primary key,
  name text not null,
  kind text not null,
  aspect text not null,
  tags text[] not null default '{}',
  skeleton jsonb not null,
  description text not null,
  -- Dimension follows the configured embedder (default: all-MiniLM-L6-v2 = 384).
  -- scripts/seed_templates.py reconciles this column if the model changes.
  embedding vector(384),
  quality_score real not null default 0.5,
  usage_count bigint not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists templates_kind_aspect_idx on templates (kind, aspect);
-- ivfflat needs rows before it can be built usefully; the seed script creates it.

create table if not exists generation_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  prompt text not null,
  brief jsonb,
  chosen_template_id text references templates(id),
  doc_id uuid references documents(id) on delete set null,
  state text not null default 'parsing',
  error text,
  cost_cents int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists gen_requests_user_idx on generation_requests (user_id, created_at desc);

-- §7: per-user daily spend ceiling.
create table if not exists usage_ledger (
  id bigserial primary key,
  user_id uuid references users(id) on delete cascade,
  day date not null default current_date,
  cost_cents int not null default 0,
  requests int not null default 0,
  unique (user_id, day)
);

create table if not exists exports (
  id uuid primary key default gen_random_uuid(),
  doc_id uuid references documents(id) on delete cascade,
  format text not null,
  scale real not null default 1,
  state text not null default 'queued',
  asset_id uuid,
  error text,
  created_at timestamptz not null default now(),
  finished_at timestamptz
);
