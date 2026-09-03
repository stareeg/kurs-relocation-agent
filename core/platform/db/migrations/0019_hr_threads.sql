-- 0019_hr_threads — переписки с HR по вакансии (AF-5): треды + сообщения in/out.
-- Диалог с HR часто уходит из hh в Telegram (ссылка в разделе «Обо мне»). Ведём его в системе,
-- привязываем к вакансии, чтобы по десяткам параллельных процессов не теряться (CLAUDE.md).
-- vacancy_id = HH id, БЕЗ FK на jobs (тред может быть для вакансии вне jobs, как debrief/prep).
-- hr_messages.thread_id — внутренний FK на hr_threads с каскадом (удаление треда чистит сообщения).

-- Тред переписки по вакансии (контакт + канал + статус). Несколько HR по одной вакансии не исключаем.
create table hr_threads (
    id           bigint      generated always as identity primary key,
    vacancy_id   text        not null,
    contact_name text        not null default '',
    channel      text        not null default 'telegram'
                 check (channel in ('telegram', 'hh', 'email', 'phone', 'other')),
    company      text        not null default '',
    status       text        not null default 'active'
                 check (status in ('active', 'waiting', 'closed')),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
-- треды по вакансии, свежие сверху (updated_at освежается новым сообщением/сменой статуса).
create index hr_threads_vacancy_idx on hr_threads (vacancy_id, updated_at desc);

-- Сообщение треда: входящее (in, от HR) или исходящее (out, владелец). Ручной ввод (вставка из TG).
create table hr_messages (
    id         bigint      generated always as identity primary key,
    thread_id  bigint      not null references hr_threads (id) on delete cascade,
    direction  text        not null default 'in' check (direction in ('in', 'out')),
    body       text        not null default '',
    sent_at    timestamptz not null default now(),
    created_at timestamptz not null default now()
);
-- лента сообщений треда по времени (старые слева — хронология диалога).
create index hr_messages_thread_idx on hr_messages (thread_id, sent_at);
