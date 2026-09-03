-- 0053_company_canonical — FR2-40 (plans/friendly_release_2.md):
-- каноническое имя работодателя для матчинга лайк/дизлайк и кандидатов (FR2-41+).
-- Сырое jobs.company сохраняем как пришло; канон заполняется при save_job и
-- командой `python -m core.companies.backfill` (детерминированный нормализатор, без LLM).
alter table jobs add column if not exists company_canonical text;
create index if not exists jobs_company_canonical_idx on jobs (company_canonical);
