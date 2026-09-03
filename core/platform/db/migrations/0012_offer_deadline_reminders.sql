-- 0012_offer_deadline_reminders — напоминания о дедлайне оффера (S12 migration_plan, defer из S11):
-- порт легаси SQLite-таблицы offer_deadline_reminders (bot/storage/offers_db.py) на Postgres.
-- Продюсер (planner оффера в apps/bot) ставит два пинга — за 24ч и 2ч до deadline; консьюмер —
-- фоновая петля бота (порт offer_deadline_loop). vacancy_id = HH id; БЕЗ FK на offers/jobs
-- (как prep_reminders S9 — напоминание самодостаточно, чистится по fired/возрасту).
-- Идемпотентность по (vacancy_id, kind): повторная постановка обновляет fire_at и сбрасывает fired.
create table offer_deadline_reminders (
    id              bigint      generated always as identity primary key,
    vacancy_id      text        not null,
    kind            text        not null check (kind in ('24h', '2h')),
    fire_at         timestamptz not null,
    chat_id         bigint      not null,
    fired           boolean     not null default false,
    created_at      timestamptz not null default now(),
    unique (vacancy_id, kind)
);
-- (fired, fire_at) — выборка «созревшие и ещё не отправленные» (легаси load_due_deadline_reminders).
create index offer_deadline_reminders_due_idx on offer_deadline_reminders (fired, fire_at);
