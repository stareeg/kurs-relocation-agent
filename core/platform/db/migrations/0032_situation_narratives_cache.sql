-- 0032_situation_narratives_cache — JS-22.9: denorm schema_version + fingerprint grid для stale-кэша.

alter table situation_narratives
    add column if not exists schema_version smallint not null default 1;

alter table situation_narratives
    add column if not exists grid_fingerprint text;

-- Backfill v2 из jsonb (до колонки могли писать только в narrative).
update situation_narratives
set schema_version = 2
where schema_version = 1
  and coalesce((narrative->>'schema_version')::int, 1) = 2;

create index if not exists situation_narratives_version_created_idx
    on situation_narratives (schema_version, created_at desc);
