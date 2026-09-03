-- 0065_offer_comparisons_cache — кэш результата LLM-автосравнения набора офферов (RD-22),
-- по хэшу состава+состояния офферов, чтобы не дёргать LLM повторно на неизменившемся наборе.

create table offer_comparisons_cache (
    id                serial primary key,
    vacancy_ids_hash  text not null unique,
    comparison        jsonb not null,
    computed_at       timestamptz not null default now()
);
