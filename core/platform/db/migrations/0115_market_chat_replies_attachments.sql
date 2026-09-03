-- 0115_market_chat_replies_attachments — паритет чата «Рынка» с чатом по вакансии (Заход 6, п.7):
-- ответ на сообщение (reply_to_message_id, как у hr_messages) и вложения (как у
-- prep_chat_message_attachments) — до этой миграции чат «Рынка» не поддерживал ни то, ни другое.

alter table market_chat_messages
    add column reply_to_message_id bigint references market_chat_messages (id) on delete set null;

create table market_chat_message_attachments (
    id            bigint      generated always as identity primary key,
    account_id    bigint      not null references accounts (id) on delete cascade,
    message_id    bigint      not null references market_chat_messages (id) on delete cascade,
    attachment_id bigint      not null references attachments (id) on delete restrict,
    position      integer     not null default 0,
    created_at    timestamptz not null default now(),
    unique (message_id, attachment_id)
);

create index market_chat_message_attachments_msg_idx
    on market_chat_message_attachments (message_id, position);
create index market_chat_message_attachments_account_id_idx
    on market_chat_message_attachments (account_id);

alter table market_chat_message_attachments enable row level security;
create policy market_chat_message_attachments_account_isolation on market_chat_message_attachments
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on market_chat_message_attachments to app_rls, app_admin;
