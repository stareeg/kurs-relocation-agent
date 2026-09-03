-- 0120_resume_chat_replies_attachments — паритет чата по резюме с чатом «Рынка» (0115) и
-- чатом по вакансии: ответ на сообщение (reply_to_message_id, как у hr_messages) и вложения
-- (как у prep/market_chat_message_attachments). До этой миграции чат по резюме (0110) не
-- поддерживал ни того, ни другого — композер был упрощённым (только текст, без ответов,
-- без выделения/удаления/вложений).

alter table resume_chat_messages
    add column reply_to_message_id bigint references resume_chat_messages (id) on delete set null;

create table resume_chat_message_attachments (
    id            bigint      generated always as identity primary key,
    account_id    bigint      not null references accounts (id) on delete cascade,
    message_id    bigint      not null references resume_chat_messages (id) on delete cascade,
    attachment_id bigint      not null references attachments (id) on delete restrict,
    position      integer     not null default 0,
    created_at    timestamptz not null default now(),
    unique (message_id, attachment_id)
);

create index resume_chat_message_attachments_msg_idx
    on resume_chat_message_attachments (message_id, position);
create index resume_chat_message_attachments_account_id_idx
    on resume_chat_message_attachments (account_id);

alter table resume_chat_message_attachments enable row level security;
create policy resume_chat_message_attachments_account_isolation on resume_chat_message_attachments
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on resume_chat_message_attachments to app_rls, app_admin;
