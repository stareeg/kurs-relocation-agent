-- 0029_notes — личные шпаргалки владельца (JS-19): свободные заметки вне резюме/легенды с
-- полнотекстовым поиском. Осознанно лёгкая версия без эмбеддингов/Neo4j (та память заморожена до
-- оффера) - обычная таблица + Postgres tsvector, которую можно позже выкинуть или смигрировать в
-- Graphiti. use_in_rag - явный тумблер подмешивания заметки в LLM-контекст (Q&A по вакансии,
-- тренажёр JS-12), по умолчанию включён - не всё автоматом идёт в промпт, как draft/publish JS-2.1.
create table if not exists notes (
    id bigserial primary key,
    title text not null default '',
    body text not null default '',
    tags text[] not null default '{}',
    use_in_rag boolean not null default true,
    search_vector tsvector generated always as (
        setweight(to_tsvector('russian', coalesce(title, '')), 'A')
        || setweight(to_tsvector('russian', coalesce(body, '')), 'B')
    ) stored,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists notes_search_vector_idx on notes using gin(search_vector);
create index if not exists notes_tags_idx on notes using gin(tags);
