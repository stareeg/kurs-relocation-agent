-- 0059_prep_topics — готовность по темам под конкретную вакансию+этап (подраздел «Прогресс»
-- в Техничках). Темы генерит LLM по тексту вакансии; уровень растёт, когда владелец
-- просматривает ответы в пачках вопросов (обычно ~2 пачки на ступень weak→medium→confident).

create table if not exists prep_topics (
    id              bigserial   primary key,
    vacancy_id      text        not null,
    stage           text        not null,
    topic           text        not null,
    level           text        not null default 'weak'
                    check (level in ('confident', 'medium', 'weak')),
    packs_reviewed  int         not null default 0,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (vacancy_id, stage, topic)
);

create index if not exists prep_topics_vacancy_stage_idx
    on prep_topics (vacancy_id, stage);
