-- One-time cleanup for databases created before the app became Lido.js (template) only:
-- drops the Custom (DesignDoc) tables and the scratch flow's rows/column. Idempotent.

drop table if exists usage_ledger cascade;
drop table if exists exports cascade;
drop table if exists jobs cascade;
drop table if exists generation_requests cascade;
drop table if exists assets cascade;
drop table if exists documents cascade;
drop table if exists templates cascade;
drop table if exists brand_kits cascade;
drop table if exists users cascade;

delete from lido_generations where to_jsonb(lido_generations) ->> 'source' = 'scratch';
drop index if exists lido_generations_source_idx;
alter table lido_generations drop column if exists source;
