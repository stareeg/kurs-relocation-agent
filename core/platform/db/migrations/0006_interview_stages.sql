-- 0006_interview_stages — этапы собеседований per vacancy (S5 migration_plan): порт легаси
-- SQLite interview_stages на Postgres. Postgres — единственный источник истины (Sheets — зеркало).
-- vacancy_id = HH id (как jobs.vacancy_id / vacancy_enrichment.vacancy_id), но БЕЗ FK: этап может
-- быть распознан LLM из письма HR раньше скоринга и для вакансий вне jobs (как и enrichment, S4).
-- enum'ы = text + CHECK (конвенция 0001); времена timestamptz.
create table interview_stages (
    id                  bigint generated always as identity primary key,
    vacancy_id          text        not null,
    stage_type          text        not null default 'hr_screening'
        check (stage_type in ('hr_screening', 'live_coding', 'system_design', 'theory', 'soft_skills', 'manager')),
    scheduled_at        timestamptz,
    format              text        not null default 'unknown'
        check (format in ('online', 'offline', 'unknown')),
    status              text        not null default 'scheduled'
        check (status in ('scheduled', 'completed', 'cancelled', 'rescheduled')),
    calendar_event_id   text        not null default '',
    calendar_event_url  text        not null default '',
    notes               text        not null default '',
    created_at          timestamptz not null default now()
);
-- (vacancy_id, scheduled_at) — выборка этапов вакансии по порядку и digest «ближайшие собеседы».
create index interview_stages_vacancy_idx on interview_stages (vacancy_id, scheduled_at);
