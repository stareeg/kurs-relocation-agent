-- 0038_context_chat_messages — накопительный чат контекста (раздел «Чаты», вкладка «Контексты»).
-- Каждая заметка notes — отдельный контекст с диалогом владелец↔ассистент. Транскрипт
-- синхронизируется в notes.body для прикрепления к чатам вакансий через note_ids.
create table if not exists context_chat_messages (
    id          bigint      generated always as identity primary key,
    note_id     bigint      not null references notes(id) on delete cascade,
    role        text        not null,  -- 'user' | 'assistant'
    content     text        not null,
    created_at  timestamptz not null default now()
);
create index if not exists context_chat_messages_note_idx
    on context_chat_messages (note_id, created_at);
