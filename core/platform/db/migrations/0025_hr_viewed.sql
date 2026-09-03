-- 0025_hr_viewed — сигнал «HR открыл резюме» (JS-9.1), ортогонален стадии воронки.
-- Просмотр резюме != скрининг (владелец 2026-06-22): на скрининг рассчитываем только когда HR
-- реально написал. hr_viewed_at пишется один раз (COALESCE в mark_resume_viewed) при синке
-- откликов с hh.ru/applicant/negotiations, момент детекта синком, не точная дата hh.
alter table jobs add column if not exists hr_viewed_at timestamptz;
