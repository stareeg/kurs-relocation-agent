-- 0055_resume_score_v2 — FR2-46: балл резюме из 4 компонент вместо 6.
-- structure / market_coverage / writing / role_fit (+ meta для фонового LLM-refresh).
-- Старые снимки аппроксимируем: structure≈mean(ats,completeness),
-- market≈mean(stack,top_jobs), writing←bullet_quality, role_fit←skills_fit.

alter table resume_score_history add column if not exists structure integer;
alter table resume_score_history add column if not exists market_coverage integer;
alter table resume_score_history add column if not exists writing integer;
alter table resume_score_history add column if not exists role_fit integer;
alter table resume_score_history add column if not exists resume_hash text not null default '';
alter table resume_score_history add column if not exists corpus_fp text not null default '';
alter table resume_score_history add column if not exists writing_ready boolean not null default false;
alter table resume_score_history add column if not exists role_fit_ready boolean not null default false;

update resume_score_history
set
  structure = round((coalesce(ats, 0) + coalesce(completeness, 0)) / 2.0),
  market_coverage = round((coalesce(stack_coverage, 0) + coalesce(top_jobs_match, 0)) / 2.0),
  writing = coalesce(bullet_quality, 0),
  role_fit = coalesce(skills_fit, 0);

update resume_score_history
set total = round((structure + market_coverage + writing + role_fit) / 4.0);

alter table resume_score_history alter column structure set not null;
alter table resume_score_history alter column market_coverage set not null;
alter table resume_score_history alter column writing set not null;
alter table resume_score_history alter column role_fit set not null;

alter table resume_score_history drop column if exists ats;
alter table resume_score_history drop column if exists stack_coverage;
alter table resume_score_history drop column if exists top_jobs_match;
alter table resume_score_history drop column if exists bullet_quality;
alter table resume_score_history drop column if exists completeness;
alter table resume_score_history drop column if exists skills_fit;
