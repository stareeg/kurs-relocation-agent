-- 0124_add_job_skills_specialization.sql
-- getmatch RSC-парсер (Шаг 4 плана plans/getmatch_refactoring_plan.md) извлекает
-- структурированные поля из initialVacancy: навыки, специализацию, грейд.
-- Детерминированный маппинг без повторного LLM-извлечения — храним как есть.
--
-- DEFAULT '{}' для skills: существующие вакансии (hh/getmatch/habr/tg) не ломаются,
-- NULL/пустой массив равнозначны «не указано».

alter table jobs
    add column if not exists skills text[] not null default '{}',
    add column if not exists specialization text,
    add column if not exists seniority text;
