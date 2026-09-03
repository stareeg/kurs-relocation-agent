-- 0013_job_notes — поля карточки вакансии в вебе (JS-1.2): свободная заметка владельца и
-- явная дата отклика. published_at = дата ПУБЛИКАЦИИ вакансии (другое поле), поэтому дата
-- отклика хранится отдельно. Оба text (как published_at) — UI шлёт "YYYY-MM-DD".
-- Колонки не входят в insert/upsert save_job → повторный скоринг их не затирает (как прогресс воронки).
alter table jobs add column if not exists note text;
alter table jobs add column if not exists applied_at text;
