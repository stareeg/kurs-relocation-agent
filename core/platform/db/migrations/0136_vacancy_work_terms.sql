-- 0136_vacancy_work_terms — кэш условий работы из текста вакансии (второй трек, Э2.1).
-- Та же механика, что 0081: PK по vacancy_id, пересчёт только при смене text_hash.
-- Без account_id: факт о тексте JD объективен и не зависит от того, чей это аккаунт
-- (тот же довод, что в 0097 для vacancy_skill_requirements).

create table vacancy_work_terms (
    vacancy_id  text primary key,
    text_hash   text not null,
    terms       jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);
