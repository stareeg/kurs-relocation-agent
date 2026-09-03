-- 0060_screening_self_pres — FR3-49/50: канонический пакет скрининга = защита (бывший pitch) +
-- нападение (groups). Расширяем vacancy_screening_questions; jobs.pitch остаётся зеркалом среза
-- защиты для старых клиентов / VacancyPitchSection до FR3-51.

alter table vacancy_screening_questions
    add column if not exists accents jsonb not null default '[]'::jsonb,
    add column if not exists hr_questions jsonb not null default '[]'::jsonb,
    add column if not exists why_company text not null default '';
