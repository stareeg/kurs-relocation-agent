-- 0011_salary_calibration_pipeline — очередь калибровки + служебное состояние (S9 migration_plan).
-- ВАЖНО: таблица salary_calibration_samples уже создана 0003 (Задача 1.3) и хранит историч. сэмплы
-- (читает core.scoring.salary_estimator) — её НЕ трогаем, лишь добавляем queue_id для связи НОВЫХ
-- сэмплов (из пересланных постов) с очередью. Здесь заводим недостающие очередь/сессии/meta —
-- легаси-пайплайн калибровки (queue→LLM-extract→samples) переезжает с SQLite на эти таблицы (S11).
create table salary_calibration_queue (
    id              bigint      generated always as identity primary key,
    chat_id         bigint      not null,
    message_id      bigint      not null,
    raw_text        text        not null,
    forward_channel text        not null default '',
    status          text        not null default 'pending',
    error           text        not null default '',
    content_hash    text        not null default '',
    created_at      timestamptz not null default now(),
    processed_at    timestamptz,
    unique (chat_id, message_id)
);
create index salary_calibration_queue_status_idx on salary_calibration_queue (status);
create index salary_calibration_queue_hash_idx on salary_calibration_queue (content_hash);

-- Связь новых сэмплов с очередью (историч. 40 строк из 0003 остаются с queue_id = null).
alter table salary_calibration_samples
    add column queue_id bigint references salary_calibration_queue (id);

-- Какие чаты сейчас в режиме калибровки (легаси salary_calibration_sessions).
create table salary_calibration_sessions (
    chat_id     bigint      primary key,
    enabled_at  timestamptz not null default now()
);

-- Произвольные key/value (легаси salary_calibration_meta — служебные флаги/курсоры).
create table salary_calibration_meta (
    key     text primary key,
    value   text not null
);
