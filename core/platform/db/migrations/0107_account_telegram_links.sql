-- 0107_account_telegram_links — «Добавить аккаунт»: несколько Telegram-identity на один
-- аккаунт (без owner-hardcode плана мультиаккаунта, TG-bot запрос владельца 2026-08-06).
--
-- Соискатели часто пишут HR с одного Telegram-аккаунта, а личным пользуются для остального,
-- хотя боту можно писать с любого — раньше второй Telegram-id при первом /start заводил
-- ВТОРОЙ независимый accounts-ряд (member), плодя дубли. Эта таблица даёт account_id
-- дополнительные ("secondary") Telegram-identity поверх основной (accounts.telegram_user_id) —
-- бот привязывает их кнопкой «Добавить аккаунт» + токен уже существующего аккаунта
-- (bot_app.services.account_link), не заводя новый accounts-ряд.
--
-- RLS — тот же паттерн, что у accounts/account_settings (0095_accounts.sql): политика заведена
-- для целостности схемы, хотя core/repo/* сегодня ходит мимо неё через get_pool() (owner
-- таблиц copilot обходит RLS так же, как это уже принято для accounts).
create table account_telegram_links (
    id                bigint      generated always as identity primary key,
    account_id        bigint      not null references accounts(id) on delete cascade,
    telegram_user_id  bigint      not null unique,
    telegram_username text,
    telegram_chat_id  bigint,
    linked_at         timestamptz not null default now()
);

alter table account_telegram_links enable row level security;

create policy account_telegram_links_isolation on account_telegram_links
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on account_telegram_links to app_rls, app_admin;
