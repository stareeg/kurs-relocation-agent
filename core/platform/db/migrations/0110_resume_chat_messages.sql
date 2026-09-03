-- 0110_resume_chat_messages — персист чата по резюме (вкладка «Резюме», правый нижний под
-- ResumeScoreCard). Раньше это был эфемерный диалог (resume_gap=true в /api/chat/stream) без PG:
-- история жила только в стейте компонента и исчезала при переходе в другой раздел. Теперь
-- лента реплик user/assistant пишется на аккаунт (тот же приём, что prep_chat_messages в 0037/0104).
--
-- Одна строка аккаунта — один «разговор» по резюме аккаунта запроса (M1), без vacancy-ключа:
-- резюме у аккаунта одно, чат общий. RLS-политика сразу account-изолирует (как 0104).

create table if not exists resume_chat_messages (
    id          bigint      generated always as identity primary key,
    account_id  bigint      not null,
    role        text        not null,  -- 'user' | 'assistant'
    content     text        not null,
    created_at  timestamptz not null default now()
);

create index if not exists resume_chat_messages_account_idx
    on resume_chat_messages (account_id, created_at);

alter table resume_chat_messages
    add constraint resume_chat_messages_account_id_fkey
    foreign key (account_id) references accounts (id) on delete cascade;

alter table resume_chat_messages enable row level security;
create policy resume_chat_messages_account_isolation on resume_chat_messages
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on resume_chat_messages to app_rls, app_admin;
