-- 0030_resume_score_six_metrics — расширение снимка скора до 6 компонент (JS-10 v2).
-- Было 4 (ats, role_match, content_quality, completeness) → стало 6:
--   ats / stack_coverage / top_jobs_match / bullet_quality / completeness / skills_fit.
-- Метрики стали опираться на корпус вакансий в системе (top_jobs_match — по топ-N
-- скорингованных вакансий) и на hh-лимит 30 тегов (skills_fit). Старые role_match и
-- content_quality переименованы в stack_coverage и bullet_quality; добавлены top_jobs_match
-- и skills_fit. Историю не теряем: старые колонки переименовываем, новые добавляем с
-- дефолтом 0 (для уже сохранённых снимков значения восстановить нельзя — разовая миграция).
alter table resume_score_history rename column role_match       to stack_coverage;
alter table resume_score_history rename column content_quality  to bullet_quality;
alter table resume_score_history add column top_jobs_match integer not null default 0;
alter table resume_score_history add column skills_fit      integer not null default 0;
