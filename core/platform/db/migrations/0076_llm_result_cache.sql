-- 0076_llm_result_cache — L-17: кэш результатов LLM.
-- Ключ: feature + версия промпта + хэш нормализованного входа (см. call._cache_key).

create table if not exists llm_result_cache (
    cache_key       text primary key,
    feature         text not null,
    prompt_version  text not null,
    input_hash      text not null,
    value_kind      text not null check (value_kind in ('text', 'json', 'pydantic')),
    schema_ref      text not null default '',
    value_text      text,
    value_json      jsonb,
    created_at      timestamptz not null default now(),
    expires_at      timestamptz,
    hits            integer not null default 0
);

create index if not exists llm_result_cache_feature_created_idx
    on llm_result_cache (feature, created_at desc);

create index if not exists llm_result_cache_expires_idx
    on llm_result_cache (expires_at)
    where expires_at is not null;
