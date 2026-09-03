-- 0147_admin_support_messages — лента поддержки в карточке человека.
--
-- Два канала в одной таблице: `user` — переписка оператора с человеком через Telegram
-- (человек эти сообщения видит), `agent` — черновик оператора с LLM-агентом поддержки
-- (человек эти сообщения не видит). Не отдаём app_rls: это операторский контур, как
-- admin_audit, а не данные, которые человек читает в продукте.
create table admin_support_messages (
    id          bigint generated always as identity primary key,
    account_id  bigint not null references accounts(id) on delete cascade,
    channel     text   not null check (channel in ('user', 'agent')),
    role        text   not null check (role in ('admin', 'user', 'agent')),
    body        text   not null,
    reply_to_id bigint references admin_support_messages(id) on delete set null,
    created_at  timestamptz not null default now()
);

create index admin_support_messages_account_idx
    on admin_support_messages (account_id, created_at);

grant select, insert, update, delete on admin_support_messages to app_admin;
