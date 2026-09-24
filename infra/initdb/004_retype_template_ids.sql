-- Retype template/generation ids: `lido_templates.id` from text ('template_10091') to
-- a genuine integer (10091, its own id — see 001_schema.sql); `lido_generations.id`
-- from a text slug to an auto-increment integer (the old slug is kept as the new
-- `design_key` column, still what the API and object-store paths use publicly);
-- `lido_generations.template_id` becomes a real integer foreign key to
-- `lido_templates.id`. Idempotent and a no-op on a database created fresh from
-- 001/002 (which already declare this shape).
--
-- A generation whose template_id doesn't match any current template (e.g. it pointed
-- at a template that's since been deleted) has its template_id set to null — the
-- generation record itself is kept.

do $$
begin
  if exists (select 1 from information_schema.columns
             where table_name = 'lido_templates' and column_name = 'id'
               and data_type = 'text') then

    alter table lido_templates add column id_new integer;
    update lido_templates set id_new = substring(id from 'template_(\d+)')::integer;
    alter table lido_templates alter column id_new set not null;
    alter table lido_templates drop constraint lido_templates_pkey;
    alter table lido_templates drop column id;
    alter table lido_templates rename column id_new to id;
    alter table lido_templates add primary key (id);

    alter table lido_generations add column template_id_new integer;
    update lido_generations
      set template_id_new = substring(template_id from 'template_(\d+)')::integer;
    update lido_generations g
      set template_id_new = null
      where template_id_new is not null
        and not exists (select 1 from lido_templates t where t.id = g.template_id_new);
    alter table lido_generations drop column template_id;
    alter table lido_generations rename column template_id_new to template_id;
    alter table lido_generations
      add constraint lido_generations_template_id_fkey
      foreign key (template_id) references lido_templates (id) on delete set null;

    alter table lido_generations add column design_key text;
    update lido_generations set design_key = id;
    alter table lido_generations alter column design_key set not null;
    alter table lido_generations add constraint lido_generations_design_key_key unique (design_key);

    alter table lido_generations add column id_new integer;
    update lido_generations g
      set id_new = ranked.rn
      from (select id, row_number() over (order by created_at) as rn
              from lido_generations) ranked
      where ranked.id = g.id;
    alter table lido_generations drop constraint lido_generations_pkey;
    alter table lido_generations drop column id;
    alter table lido_generations rename column id_new to id;
    alter table lido_generations add primary key (id);
    alter table lido_generations alter column id add generated always as identity;
    perform setval(pg_get_serial_sequence('lido_generations', 'id'),
                   coalesce((select max(id) from lido_generations), 0));
  end if;
end $$;
