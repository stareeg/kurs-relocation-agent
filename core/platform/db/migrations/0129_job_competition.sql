-- 0129_job_competition — под-скор «шанс на отклик» (Этап 6 §6.2, scoring_precision_2026_08_17).
-- Параллелен основному score (jsonb), тот же приём, что remote_feasibility (0015):
-- CompetitionInsight {level, responses_per_day, age_days, reasoning}. Детерминированный расчёт
-- (competition.py), без LLM — считается синхронно вместе со скорингом, пишется в upsert save_job.
-- NULL / level="unknown" — total_responses ещё не собран (см. competition.py docstring).
alter table jobs add column if not exists competition jsonb;
