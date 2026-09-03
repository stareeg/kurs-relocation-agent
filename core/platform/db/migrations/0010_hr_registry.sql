-- 0010_hr_registry — реестр привязок HR ↔ vacancy_id (S9 migration_plan): порт легаси SQLite
-- backend/persistence/hr_registry_db.py. Один HR (hr_key) — несколько vacancy_id; PK составной.
-- БЕЗ FK на jobs: привязка может появиться от HR раньше скоринга вакансии.
create table hr_vacancy_links (
    hr_key      text        not null,
    vacancy_id  text        not null,
    company     text        not null default '',
    position    text        not null default '',
    hr_link     text        not null default '',
    updated_at  timestamptz not null default now(),
    primary key (hr_key, vacancy_id)
);
-- hr_key — все вакансии этого HR (легаси list_vacancy_ids_for_hr); vacancy_id — обратный поиск.
create index hr_vacancy_links_hr_idx on hr_vacancy_links (hr_key);
create index hr_vacancy_links_vid_idx on hr_vacancy_links (vacancy_id);
