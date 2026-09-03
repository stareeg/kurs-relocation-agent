-- 0084_tg_ui_messages — журнал исходящих сообщений бота (TB-3.1).
-- Реестр для «живого» меню (последнее на чат) и отложенной уборки progress/digest/service.
-- kind: menu | card | progress | digest | service | hr_card

create table tg_ui_messages (
    id            bigint      generated always as identity primary key,
    chat_id       bigint      not null,
    message_id    bigint      not null,
    kind          text        not null,
    vacancy_id    text,
    created_at    timestamptz not null default now(),
    cleanup_after timestamptz
);

create index tg_ui_messages_chat_kind_idx
    on tg_ui_messages (chat_id, kind);
