-- 0078_market_analytics_snapshot — L-25: снапшоты «Рынка» (grid/pulse/market), считаются по
-- расписанию фоновой задачей (A-20), роутер отдаёт мгновенно без пересчёта на каждый заход.
-- Один снимок на kind (upsert) — свежие значения перезаписывают payload.

create table market_analytics_snapshot (
    kind        text        primary key,
    payload     jsonb       not null default '{}'::jsonb,
    computed_at timestamptz not null default now()
);
