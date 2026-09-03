-- 0004_logs — витрина логов для интерфейса (ревизия plans/log_system.md, L6).
-- Весь поток INFO+ оседает сюда фоновым неблокирующим писателем (core.observability.pg_sink):
-- хендлер кладёт запись в очередь, отдельный async-таск батчит и пишет executemany.
-- При простое PG строки буферизуются в logs/_pg_spool.jsonl и дозаливаются при восстановлении.
-- fields — произвольные поля из extra (agent/tier/model/tokens_in/tokens_out/cost_usd/latency_ms).
create table copilot_logs (
    id       bigserial   primary key,
    ts       timestamptz not null default now(),
    level    text        not null,
    logger   text,
    event    text,
    task_id  text,
    msg      text        not null,
    fields   jsonb
);
-- ts desc — основной порядок выдачи /api/logs; level/event/task_id — фильтры витрины.
create index copilot_logs_ts_idx on copilot_logs (ts desc);
create index copilot_logs_level_idx on copilot_logs (level);
create index copilot_logs_event_idx on copilot_logs (event);
create index copilot_logs_task_id_idx on copilot_logs (task_id);
