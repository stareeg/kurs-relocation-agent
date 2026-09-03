-- 0009_prep_sessions — подготовка к собеседованию и напоминания (S9 migration_plan): порт легаси
-- SQLite bot/storage/interview_prep_db.py на Postgres. questions/responses — jsonb (легаси держал
-- JSON-текст). vacancy_id = HH id; БЕЗ FK на jobs (prep может быть сгенерирован для вакансии вне jobs,
-- как enrichment S4 / interview_stages S5).
create table prep_sessions (
    id              bigint      generated always as identity primary key,
    interview_id    bigint,
    vacancy_id      text        not null,
    stage           text        not null default 'screening',
    generated_at    timestamptz not null default now(),
    questions       jsonb       not null default '[]'::jsonb,
    responses       jsonb       not null default '[]'::jsonb,
    status          text        not null default 'generated',
    finished_at     timestamptz
);
-- vacancy_id + свежесть — история подготовок по вакансии (легаси load_prep_history order desc).
create index prep_sessions_vacancy_idx on prep_sessions (vacancy_id, generated_at desc);

-- Напоминания подготовки: fire_at — когда послать prep-пинг до собеса. Идемпотентность по
-- (interview_id, fire_at) среди не-сработавших обеспечивает репозиторий (легаси schedule_reminder).
create table prep_reminders (
    id              bigint      generated always as identity primary key,
    interview_id    bigint,
    vacancy_id      text        not null,
    company         text        not null default '',
    position        text        not null default '',
    stage           text        not null default 'screening',
    interview_dt    timestamptz not null,
    fire_at         timestamptz not null,
    chat_id         bigint      not null,
    fired           boolean     not null default false,
    created_at      timestamptz not null default now()
);
-- (fired, fire_at) — выборка «созревшие и ещё не отправленные» (легаси load_due_reminders).
create index prep_reminders_due_idx on prep_reminders (fired, fire_at);
