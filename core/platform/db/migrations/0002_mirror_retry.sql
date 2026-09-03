-- 0002_mirror_retry — очередь догона зеркал PG → Neo4j (задача 1.2, подшаг 4).
-- Мастер двойных сущностей — Postgres; зеркальный узел в Neo4j пишется best-effort.
-- При недоступности графа задание складывается сюда и догоняется планово (retry_pending).
-- Один ряд на сущность: повторная запись обновляет props/ошибку (upsert по label+entity_id).
create table mirror_retry (
    id          bigint generated always as identity primary key,
    label       text        not null,           -- Document | VisaItem | PortfolioItem
    entity_id   text        not null,           -- общий id с Postgres-таблицей-источником
    props       jsonb       not null default '{}'::jsonb,
    attempts    integer     not null default 0,
    last_error  text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    unique (label, entity_id)
);
create index mirror_retry_label_idx on mirror_retry (label);
