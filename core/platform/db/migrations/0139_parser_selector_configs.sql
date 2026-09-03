-- 0139_parser_selector_configs — горячий оверрайд CSS-селекторов парсера площадки.
-- Инфраструктурный синглтон на источник (`hh`), без account_id: селекторы одни на всю
-- установку, это не пользовательская настройка. Дефолт живёт в репозитории
-- (`core/domains/opportunities/sources/hh_selectors.json`); строка здесь — только
-- «hh сломался в субботу, деплой ждать не хочу». RLS не включаем: нечего изолировать.

create table parser_selector_configs (
    source      text primary key,
    version     integer not null default 1 check (version > 0),
    config      jsonb   not null,
    updated_at  timestamptz not null default now()
);

grant select, insert, update, delete on parser_selector_configs to app_rls, app_admin;
