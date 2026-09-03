-- 0096_accounts_identity — Этап 2 (plans/vm_multitenant_hosting_2026_08_03.md §3, §2.1):
-- identity threading в API. `web_auth_token` и `telegram_owner` переезжают с одной глобальной
-- строки в `app_settings` на колонки конкретного аккаунта в `accounts` — личность и её токен
-- входа теперь один и тот же ряд, а не два раздельных key/value с совпадающим user_id, который
-- код был обязан сверять руками.
--
-- Что остаётся в `app_settings` (НЕ переезжает): `telegram_link_token` (pending-токен привязки
-- живёт ДО существования аккаунта — привязывать его не к чему) и `telegram_bot_identity` (кэш
-- getMe — общесистемный факт про сам бот, не про чей-то аккаунт). Таблица `app_settings` не
-- дропается — сужается до этих двух ключей + временного bootstrap-хранилища для «Параметров»
-- в окне между свежей установкой и первой привязкой Telegram (core/repo/settings.py:
-- account_id=None → app_settings).
alter table accounts
    add column telegram_chat_id       bigint,
    add column web_auth_token_sha256  text,
    add column web_auth_issued_at     timestamptz,
    add column web_auth_revoked_at    timestamptz;

-- Backfill для инсталляций, уже прошедших Этап 1 (0095): владелец получил строку в accounts,
-- но токен/чат остались в app_settings. Свежая CI/friend-установка без этих ключей — no-op.
do $$
declare
    v_owner_id bigint;
begin
    select id into v_owner_id from accounts where role = 'owner' order by id limit 1;

    if v_owner_id is not null then
        update accounts
        set telegram_chat_id = (s.value ->> 'chat_id')::bigint
        from app_settings s
        where accounts.id = v_owner_id
          and s.key = 'telegram_owner';

        update accounts
        set web_auth_token_sha256 = s.value ->> 'token_sha256',
            web_auth_issued_at = (s.value ->> 'issued_at')::timestamptz,
            web_auth_revoked_at = (s.value ->> 'revoked_at')::timestamptz
        from app_settings s
        where accounts.id = v_owner_id
          and s.key = 'web_auth_token';

        -- Остальные ключи «Параметров» (веса скоринга, ключ OpenRouter, онбординг, аватар, …) —
        -- один-в-один в account_settings владельца. `telegram_owner`/`web_auth_token` уже учтены
        -- выше (колонки accounts), `telegram_link_token`/`telegram_bot_identity` глобальны.
        insert into account_settings (account_id, key, value)
        select v_owner_id, key, value
        from app_settings
        where key not in (
            'telegram_owner', 'web_auth_token', 'telegram_link_token', 'telegram_bot_identity'
        )
        on conflict (account_id, key) do nothing;

        delete from app_settings
        where key not in ('telegram_link_token', 'telegram_bot_identity');
    end if;
end
$$;
