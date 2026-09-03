-- 0074_career_facts — A-28: долгая память кандидата на Postgres (замена Neo4j/Graphiti).
-- Факт + тип + источник (vacancy/debrief/chat) + дата + уверенность + срок годности.
-- Читается при сборке контекста подготовки и чата.

create table career_facts (
    id              bigint      generated always as identity primary key,
    fact            text        not null,
    fact_type       text        not null default 'note'
        check (fact_type in (
            'skill_gap', 'strength', 'preference', 'constraint',
            'company', 'note', 'other'
        )),
    source_kind     text        not null
        check (source_kind in (
            'vacancy', 'debrief', 'chat', 'manual', 'offer', 'other'
        )),
    source_ref      text        not null default '',
    confidence      real        not null default 0.7
        check (confidence >= 0 and confidence <= 1),
    recorded_at     timestamptz not null default now(),
    expires_at      timestamptz,
    payload         jsonb       not null default '{}'::jsonb,
    created_at      timestamptz not null default now()
);

create index career_facts_recorded_idx on career_facts (recorded_at desc);
create index career_facts_source_idx on career_facts (source_kind, source_ref);
-- Активность (expires_at null | > now()) фильтруем в запросе: now() не IMMUTABLE →
-- частичный индекс с now() Postgres не принимает.
create index career_facts_expires_idx on career_facts (expires_at);
