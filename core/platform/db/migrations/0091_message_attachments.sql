-- 0091_message_attachments — связки вложений-картинок с сообщениями конкретных лент (Э2-5,
-- plans/chat_image_attachments_2026_08_03.md §2.2). Одна таблица на ленту (как reply_to_message_id
-- в 0087/0089): своя, с настоящим FK и каскадом на сообщение, а не общая с полиморфным типом.
-- `on delete restrict` на attachment_id — блоб не может пропасть из-под живой связки, чистит его
-- только GC (core/domains/assistant/attachments/repo.py::gc_candidates), который сначала проверяет
-- отсутствие ссылок в этих таблицах.

create table hr_message_attachments (
    id            bigint      generated always as identity primary key,
    message_id    bigint      not null references hr_messages (id) on delete cascade,
    attachment_id bigint      not null references attachments (id) on delete restrict,
    position      integer     not null default 0,
    created_at    timestamptz not null default now(),
    unique (message_id, attachment_id)
);
create index hr_message_attachments_msg_idx on hr_message_attachments (message_id, position);

-- Прицел на Этап 3 плана (Технички · Агент) — заводим здесь же, чтобы не плодить миграцию под
-- одну таблицу; репозиторий вложений подключит её к `_SURFACE_TABLES`, когда появится вызывающий
-- код (сейчас пустая, GC ей не мешает).
create table prep_chat_message_attachments (
    id            bigint      generated always as identity primary key,
    message_id    bigint      not null references prep_chat_messages (id) on delete cascade,
    attachment_id bigint      not null references attachments (id) on delete restrict,
    position      integer     not null default 0,
    created_at    timestamptz not null default now(),
    unique (message_id, attachment_id)
);
create index prep_chat_message_attachments_msg_idx on prep_chat_message_attachments (message_id, position);
