-- 0111_market_chat_messages — персист чата по ситуации на рынке (вкладка «Рынок», внизу
-- под графиками). Диалог с карьерным стратегом: владелец спрашивает про свою ситуацию на
-- рынке, LLM отвечает с опорой на собранные facts (воронка/гейты/деньги/отклик резюме).
-- Заменяет бывший блок «Что сделать» (next-steps) на свободный диалог.
--
-- Зеркало 0110_resume_chat_messages.sql: одна строка аккаунта — один разговор по ситуации
-- рынка (без vacancy-ключа). RLS-политика account-изолирует с нуля, как и resume_chat_messages.

create table if not exists market_chat_messages (
    id          bigint      generated always as identity primary key,
    account_id  bigint      not null,
    role        text        not null,  -- 'user' | 'assistant'
    content     text        not null,
    created_at  timestamptz not null default now()
);

create index if not exists market_chat_messages_account_idx
    on market_chat_messages (account_id, created_at);

alter table market_chat_messages
    add constraint market_chat_messages_account_id_fkey
    foreign key (account_id) references accounts (id) on delete cascade;

alter table market_chat_messages enable row level security;
create policy market_chat_messages_account_isolation on market_chat_messages
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on market_chat_messages to app_rls, app_admin;
