-- 0114_llm_usage_tier — статистика токенов на «Параметрах» переходит на разрез по тиру
-- (basic/advanced) вместо «всего/сегодня». Старые строки без tier бесполезны для новой
-- витрины, а история всё равно остаётся на стороне OpenRouter — решение владельца: очистить
-- таблицу, чтобы не городить backfill ради обнулённого впоследствии счётчика.
truncate table llm_usage;

alter table llm_usage
    add column if not exists tier text not null default 'basic';

create index if not exists llm_usage_account_tier_day_idx
    on llm_usage (account_id, tier, day);
