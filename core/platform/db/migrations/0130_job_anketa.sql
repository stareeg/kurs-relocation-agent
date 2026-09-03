-- 0130_job_anketa — состояние анкеты работодателя при автооткликах (Фаза 3,
-- auto_apply_roadmap_2026_08_17.md). Тот же приём, что competition (0129)/remote_feasibility
-- (0015): параллельный jsonb рядом с основным score, не новая таблица. AnketaState
-- {status, platform, questions, answers, requested_at, resolved_at} — пишется раннером через
-- report_attempt при outcome="anketa", читается/подтверждается веб-очередью (JobsToolbar/
-- JobDetailDrawer), забирается раннером повторно при status="approved" для реальной отправки.
-- NULL — вакансия никогда не встречала анкету.
alter table jobs add column if not exists anketa jsonb;
