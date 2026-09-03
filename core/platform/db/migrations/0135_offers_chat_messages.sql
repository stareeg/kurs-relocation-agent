-- 0135_offers_chat_messages — персист чата вкладки «Офферы» (под карточками).
-- Зеркало 0111+0115 (market) / 0110+0120 (resume): один разговор на аккаунт, reply_to +
-- вложения. RLS/account_id с нуля в CREATE TABLE, не ретрофит.

create table if not exists offers_chat_messages (
    id                   bigint      generated always as identity primary key,
    account_id           bigint      not null references accounts (id) on delete cascade,
    role                 text        not null,  -- 'user' | 'assistant'
    content              text        not null,
    reply_to_message_id  bigint      references offers_chat_messages (id) on delete set null,
    created_at           timestamptz not null default now()
);

create index if not exists offers_chat_messages_account_idx
    on offers_chat_messages (account_id, created_at);

alter table offers_chat_messages enable row level security;
create policy offers_chat_messages_account_isolation on offers_chat_messages
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on offers_chat_messages to app_rls, app_admin;

create table offers_chat_message_attachments (
    id            bigint      generated always as identity primary key,
    account_id    bigint      not null references accounts (id) on delete cascade,
    message_id    bigint      not null references offers_chat_messages (id) on delete cascade,
    attachment_id bigint      not null references attachments (id) on delete restrict,
    position      integer     not null default 0,
    created_at    timestamptz not null default now(),
    unique (message_id, attachment_id)
);

create index offers_chat_message_attachments_msg_idx
    on offers_chat_message_attachments (message_id, position);
create index offers_chat_message_attachments_account_id_idx
    on offers_chat_message_attachments (account_id);

alter table offers_chat_message_attachments enable row level security;
create policy offers_chat_message_attachments_account_isolation on offers_chat_message_attachments
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on offers_chat_message_attachments to app_rls, app_admin;
