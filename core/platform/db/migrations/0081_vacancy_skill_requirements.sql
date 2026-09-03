-- 0081_vacancy_skill_requirements — кэш требуемых навыков вакансии (S-02, skills_2026_07_28.md).
-- Своя таблица, а не llm_result_cache (L-17): агрегату (S-04) нужно читать сразу N строк по
-- выборке одним запросом. PK по vacancy_id — пересчёт только при смене text_hash.

create table vacancy_skill_requirements (
    vacancy_id  text primary key,
    text_hash   text not null,
    skills      jsonb not null default '[]'::jsonb,
    created_at  timestamptz not null default now()
);
