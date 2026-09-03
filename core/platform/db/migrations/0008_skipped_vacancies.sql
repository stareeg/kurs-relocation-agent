-- 0008_skipped — пропущенные вакансии (S7 migration_plan): порт легаси SQLite skipped_vacancies
-- (backend/persistence/skipped_db.py) на Postgres. Postgres — единственный источник истины
-- (Sheets — зеркало). "skip" = решение «не подавать», ОРТОГОНАЛЬНО статусу воронки (jobs.status):
-- отдельная таблица, БЕЗ FK на jobs (пропуск может быть зафиксирован вручную для вакансии вне
-- jobs — как enrichment S4 / interview_stages S5 / offers S6). vacancy_id = HH id, unique.
-- created_at иммутабелен на conflict; scored_at и метаданные освежаются (порт ON CONFLICT DO UPDATE).
create table skipped_vacancies (
    id              bigint      generated always as identity primary key,
    vacancy_id      text        not null unique,
    url             text,
    title           text,
    company         text,
    overall_score   integer     check (overall_score is null or overall_score between 0 and 100),
    recommendation  text,
    skip_reason     text        not null,
    scored_at       timestamptz not null default now(),
    created_at      timestamptz not null default now()
);
-- scored_at desc — лента «последние пропущенные» (легаси load_skipped_list order by scored_at desc).
create index skipped_vacancies_scored_at_idx on skipped_vacancies (scored_at desc);
