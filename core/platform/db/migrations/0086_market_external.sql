-- 0086_market_external — D-07: внешние показания рынка с hh, которые снимает расширение со
-- страниц, что владелец и так открывает (план market_redesign_v3, п.2.6) — без единого
-- серверного запроса к hh. Дневная/месячная идемпотентность через upsert по естественному
-- ключу: повторный заход в те же сутки/тот же месяц перезаписывает значение, не плодит строку.

-- «Сколько вакансий по моему запросу» (E-01): счётчик со страницы выдачи hh, копится по неделям.
create table market_demand_readings (
    id          bigint      generated always as identity primary key,
    day         date        not null default current_date,
    query       text        not null,
    count       int         not null,
    source      text        not null default 'hh_serp',
    captured_at timestamptz not null default now(),
    created_at  timestamptz not null default now()
);
-- один показатель на день/запрос/источник — повтор за сутки обновляет count, не плодит строку.
create unique index market_demand_readings_natural_idx on market_demand_readings (day, query, source);

-- «Резюме на вакансию» (E-03): месячный индекс рынка, со страницы статистики hh либо вручную.
create table market_index_readings (
    id          bigint      generated always as identity primary key,
    month       date        not null,
    value       numeric     not null,
    source      text        not null default 'manual',
    captured_at timestamptz not null default now(),
    created_at  timestamptz not null default now()
);
-- один показатель на месяц — новый съём того же месяца обновляет значение, не плодит строку.
create unique index market_index_readings_month_idx on market_index_readings (month);
