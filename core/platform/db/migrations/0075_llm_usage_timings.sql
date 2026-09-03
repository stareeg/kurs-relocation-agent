-- 0075_llm_usage_timings — L-02: тайминги LLM-вызова в cost-учёте.
-- ttfb_ms / total_ms / queue_ms / attempt / cache_hit заполняются из call.run (A-07).

alter table llm_usage
    add column if not exists ttfb_ms   integer,
    add column if not exists total_ms  integer,
    add column if not exists queue_ms  integer,
    add column if not exists attempt   integer,
    add column if not exists cache_hit boolean not null default false;

create index if not exists llm_usage_day_feature_idx
    on llm_usage (day, agent);
