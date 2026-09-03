-- 0043_retro_snapshots — RD-18: недельное ретро воронки («что менять МНЕ»).
-- Append-only лента (в отличие от market_snapshots/0024 — дневной upsert для дельт день-ко-дню):
-- каждый клик «Собрать ретро» пишет новую строку, чтобы было видно, помогли ли действия из
-- прошлого ретро. report хранит структурный вывод LLM (диагноз воронки + причины отказов + действия).
create table retro_snapshots (
    id             bigint      generated always as identity primary key,
    created_at     timestamptz not null default now(),
    period_days    int         not null default 7,
    summary        text        not null default '',
    report         jsonb       not null default '{}'::jsonb,
    schema_version int         not null default 1
);
-- лента, свежие первыми.
create index retro_snapshots_created_at_idx on retro_snapshots (created_at desc);
