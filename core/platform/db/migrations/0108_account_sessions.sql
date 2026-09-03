-- 0108_account_sessions — многоустройственные сессии входа (TG-bot запрос владельца
-- 2026-08-06): раньше `accounts.web_auth_token_sha256` — одна колонка, один активный токен на
-- аккаунт, перевыпуск в боте убивал cookie на любом другом устройстве/браузере. Токен нужен в
-- первую очередь на случай поломки, а не как единственный способ входа с нового устройства —
-- значит, у аккаунта должно быть НЕСКОЛЬКО одновременно активных сессий, каждая гасится
-- независимо (блок «Устройства» в Параметрах: список + отзыв по одной + «Выйти на всех»).
--
-- RLS — тот же паттерн, что у accounts/account_settings/account_telegram_links.
create table account_sessions (
    id                           bigint      generated always as identity primary key,
    account_id                   bigint      not null references accounts(id) on delete cascade,
    token_sha256                 text        not null unique,
    issued_at                    timestamptz not null default now(),
    revoked_at                   timestamptz,
    -- Какая Telegram-identity аккаунта запросила токен (secondary-identity тоже могут, см.
    -- 0107_account_telegram_links.sql) — для честной подписи строки в списке устройств.
    issued_via_telegram_user_id  bigint,
    -- User-Agent из первого браузерного логина этой сессией (POST /auth/token) — не выдумываем
    -- название устройства, показываем то, что реально пришло в заголовке, или ничего.
    login_user_agent             text
);

create index account_sessions_active_idx on account_sessions (account_id) where revoked_at is null;

alter table account_sessions enable row level security;

create policy account_sessions_isolation on account_sessions
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on account_sessions to app_rls, app_admin;

-- Backfill: у каждого аккаунта с уже выпущенным токеном — ровно одна сессия с той же историей.
insert into account_sessions (account_id, token_sha256, issued_at, revoked_at)
select id, web_auth_token_sha256, coalesce(web_auth_issued_at, now()), web_auth_revoked_at
from accounts
where web_auth_token_sha256 is not null;

alter table accounts
    drop column web_auth_token_sha256,
    drop column web_auth_issued_at,
    drop column web_auth_revoked_at;
