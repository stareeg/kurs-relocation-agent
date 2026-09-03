-- 0119_account_sessions_activity — данные для будущей admin-картины активности (сколько
-- реальных пользователей, когда последний раз заходили, откуда) и capacity planning: раньше
-- `accounts`/`account_sessions` не хранили last_seen ни на одном уровне и IP не хранили вообще —
-- только момент выдачи/отзыва токена (issued_at/revoked_at) и UA с первого браузерного логина.
alter table accounts
    add column last_seen_at timestamptz,
    add column last_seen_ip text;

-- IP браузера с первого обмена токена на cookie (POST /auth/token) — та же семантика, что у
-- login_user_agent (0108_account_sessions.sql): не перезаписывается, «с чем залогинились».
alter table account_sessions
    add column login_ip text;
