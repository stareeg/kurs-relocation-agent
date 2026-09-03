-- 0024_market_snapshots — дневной снимок ВСЕХ агрегатов вкладки «Рынок» (pulse + search-metrics)
-- одним jsonb-блобом. Реконструкция «сутки назад» в pulse.py фильтрует мутабельные строки
-- (jobs.score/status может переписаться поверх) — неточно. Реальный снимок даёт точную дельту
-- день-ко-дню и полную картину для LLM-сводки ситуации (situation.py), без догадок задним числом.
-- Один снимок на календарный день (upsert), значения обновляются при каждом заходе на «Рынок».

create table market_snapshots (
    id          bigint      generated always as identity primary key,
    day         date        not null unique,
    captured_at timestamptz not null default now(),
    payload     jsonb       not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);
-- история по дням, свежие первыми (поиск «последний снимок строго до дня X»).
create index market_snapshots_day_idx on market_snapshots (day desc);
