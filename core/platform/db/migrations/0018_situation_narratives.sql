-- 0018_situation_narratives — кэш последней LLM-сводки ситуации «как идём / что по рынку» (AF-4).
-- Reasoning-модель (GLM-5.2, effort high) собирает воронку + рыночные срезы + динамику резюме в человеческую
-- сводку. LLM = деньги: генерация только по кнопке, последняя сводка кэшируется здесь, чтобы
-- повторный заход на «Рынок» не жёг токены. Append-only — последняя строка = текущий кэш.

create table situation_narratives (
    id         bigint      generated always as identity primary key,
    created_at timestamptz not null default now(),
    summary    text        not null default '',
    narrative  jsonb       not null default '{}'::jsonb
);
-- последняя сводка первой (GET тянет latest).
create index situation_narratives_created_idx on situation_narratives (created_at desc);
