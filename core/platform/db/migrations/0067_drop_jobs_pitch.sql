-- 0067_drop_jobs_pitch — снос мёртвого pitch-фасада (план 2026-07-23, шаг 18): `jobs.pitch`
-- было только зеркалом среза защиты из `vacancy_screening_questions`, канон уже там.

alter table jobs drop column if exists pitch;
