-- 0155_agent_runs — запуски агента, поток событий и серверный персист главного чата (A-3).
--
-- Запуск живёт в отдельном процессе-задаче API, но его следы — в Postgres: статус и
-- события переживают перезапуск API, SSE читает события догоном по id (Last-Event-ID),
-- пауза на подтверждении держится сколько угодно и продолжается с чекпойнта графа
-- (thread_id) даже из нового процесса.
--
-- Режимы (модель COWORK, без аренды: у нас одна реплика):
--   queued           — строка создана, задача ещё не стартовала (мгновение);
--   running          — задача крутится в этом процессе;
--   waiting_approval — граф стоит на interrupt: ждём «да» человека (переживает рестарт);
--   done / failed    — терминальные; failed ставится и задачам, убитым перезапуском API.
--
-- Чат-сессии: свободный главный чат получает серверные диалоги (список слева) — раньше
-- он жил только в localStorage вкладки.

create table agent_runs (
    id          bigint      generated always as identity primary key,
    account_id  bigint      not null references accounts(id) on delete cascade,
    session_id  bigint,                      -- чат-сессия главного чата, если запуск из неё
    goal        text        not null,
    status      text        not null default 'queued'
                            check (status in ('queued','running','waiting_approval','done','failed','cancelled')),
    thread_id   text        not null,        -- тред чекпойнтов графа (interrupt/resume)
    stop_reason text,
    answer      text,
    error       text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

alter table agent_runs enable row level security;

create policy agent_runs_isolation on agent_runs
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on agent_runs to app_rls, app_admin;

create index agent_runs_account_idx on agent_runs (account_id, created_at desc);
create index agent_runs_session_idx on agent_runs (session_id, created_at desc);
create index agent_runs_open_idx on agent_runs (status) where status in ('queued', 'running', 'waiting_approval');

-- account_id в событиях — не избыточность: RLS событий проверяет его напрямую
-- (джойн в политике не нужен), а менеджер всё равно сверяет запуск с аккаунтом.
create table agent_events (
    id          bigint      generated always as identity primary key,
    run_id      bigint      not null references agent_runs(id) on delete cascade,
    account_id  bigint      not null references accounts(id) on delete cascade,
    type        text        not null,
    payload     jsonb       not null default '{}'::jsonb,
    node        text,                        -- узел графа, породивший событие
    duration_ms double precision,            -- время узла (метрика p90 шага, OQ-29)
    created_at  timestamptz not null default now()
);

alter table agent_events enable row level security;

create policy agent_events_isolation on agent_events
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on agent_events to app_rls, app_admin;

create index agent_events_run_idx on agent_events (run_id, id);

create table agent_chat_sessions (
    id         bigint      generated always as identity primary key,
    account_id bigint      not null references accounts(id) on delete cascade,
    title      text        not null default 'Новый диалог',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table agent_chat_sessions enable row level security;

create policy agent_chat_sessions_isolation on agent_chat_sessions
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on agent_chat_sessions to app_rls, app_admin;

create index agent_chat_sessions_account_idx on agent_chat_sessions (account_id, updated_at desc);

create table agent_chat_messages (
    id         bigint      generated always as identity primary key,
    session_id bigint      not null references agent_chat_sessions(id) on delete cascade,
    account_id bigint      not null references accounts(id) on delete cascade,
    role       text        not null check (role in ('user', 'assistant')),
    content    text        not null,
    created_at timestamptz not null default now()
);

alter table agent_chat_messages enable row level security;

create policy agent_chat_messages_isolation on agent_chat_messages
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on agent_chat_messages to app_rls, app_admin;

create index agent_chat_messages_session_idx on agent_chat_messages (session_id, id);
