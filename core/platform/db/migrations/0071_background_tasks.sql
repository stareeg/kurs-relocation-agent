-- 0071_background_tasks — A-20: единая очередь фоновых задач (замена APScheduler + create_task).
-- Идемпотентность по ключу среди активных (pending/running); claim — FOR UPDATE SKIP LOCKED.

create table background_tasks (
    id              bigint      generated always as identity primary key,
    kind            text        not null,
    idempotency_key text,
    priority        integer     not null default 100,
    payload         jsonb       not null default '{}'::jsonb,
    status          text        not null default 'pending'
        check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),
    attempts        integer     not null default 0,
    max_attempts    integer     not null default 3,
    run_at          timestamptz not null default now(),
    started_at      timestamptz,
    finished_at     timestamptz,
    last_error      text        not null default '',
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- Горячий путь воркера: ближайшая pending по приоритету и run_at.
create index background_tasks_claim_idx
    on background_tasks (priority asc, run_at asc, id asc)
    where status = 'pending';

-- Один активный экземпляр на ключ (salary_estimate:vid, morning_digest:дата, …).
create unique index background_tasks_idempotency_active_uidx
    on background_tasks (idempotency_key)
    where idempotency_key is not null
      and status in ('pending', 'running');

create index background_tasks_list_idx
    on background_tasks (created_at desc);

create index background_tasks_kind_status_idx
    on background_tasks (kind, status);
