-- 0005_enrichment — данные от HR per vacancy (S4 migration_plan): порт легаси SQLite
-- vacancy_enrichment на Postgres. Postgres — единственный источник истины (Google Sheets — зеркало).
-- vacancy_id = HH id (как jobs.vacancy_id), но БЕЗ FK: enrichment может прийти от HR раньше
-- скоринга и для вакансий вне jobs. Этапы собеседований (interview_stages) — отдельный этап S5.
create table vacancy_enrichment (
    vacancy_id          text        primary key,
    salary_hr_range     text        not null default '',
    salary_match        text        check (salary_match is null or salary_match in ('yes', 'no', 'unclear')),
    format_clarified    text        not null default '',
    team_size           text        not null default '',
    last_hr_contact_at  timestamptz,
    hr_contact_summary  text        not null default '',
    interview_debrief   text        not null default '',
    hr_link             text        not null default '',
    updated_at          timestamptz not null default now()
);
-- last_hr_contact_at — порядок digest «давно нет ответа HR» (легаси load_stale_hr_contacts).
create index vacancy_enrichment_last_contact_idx on vacancy_enrichment (last_hr_contact_at);
