-- 0037_prep_chat — накопительный чат подготовки по вакансии (вкладка «Технички», режим
-- «Подготовка»). Общий для всех этапов под вакансией: владелец просит «сгенерируй ещё пачку
-- вопросов», «объясни подробнее», задаёт встречные вопросы. История переживает перезагрузку
-- и переиспользуется между сессиями подготовки. Реплики хранятся как есть (markdown/plain),
-- без jsonb-обёртки — это лента, а не структурированные ответы.
create table if not exists prep_chat_messages (
    id          bigint      generated always as identity primary key,
    vacancy_id  text        not null,
    role        text        not null,  -- 'user' | 'assistant'
    content     text        not null,
    created_at  timestamptz not null default now()
);
create index if not exists prep_chat_messages_vacancy_idx
    on prep_chat_messages (vacancy_id, created_at);
