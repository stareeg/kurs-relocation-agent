-- 0095_accounts — Этап 1 (plans/vm_multitenant_hosting_2026_08_03.md §1, §2.1): корневая
-- сущность аккаунта + RLS-фундамент. За фичефлагом: ни один роутер/фоновая задача ещё не
-- проводит запросы через account_scope() (core/platform/db/account_scope.py) — это только
-- инфраструктура, которую Этап 2 подключит к require_account. RLS здесь включена только на
-- этих двух новых таблицах, ни на одной прикладной (funnel/hr/offers/…) — тот ретрофит идёт
-- доменом за доменом в Этапе 3.
--
-- Роли:
--   app_admin — BYPASSRLS, для будущих системных подключений (фоновые задачи/миграции).
--               Сегодня фактически избыточна: владелец таблиц (copilot) и так обходит RLS
--               как table owner, ничего не переключает роль. Заведена заранее по плану, чтобы
--               Этап 2/3 не пришлось возвращаться сюда за новой миграцией ролей.
--   app_rls    — обычная роль без BYPASSRLS. account_scope() переключает сессию на неё через
--                SET ROLE перед запросом и возвращает обратно на владельца в finally — без
--                этого переключения RLS ничего не значит: table owner видит все строки
--                независимо от app.account_id (см. account_scope.py).
--
-- CREATE ROLE требует CREATEROLE у роли copilot: в Docker/CI POSTGRES_USER — суперпользователь
-- по умолчанию (образ postgres:18 создаёт его как initdb-суперюзера), на нативной установке —
-- см. deploy/init_native_pg.sql (`alter role copilot createrole`). Если copilot заведён ДО этой
-- правки — накатить init_native_pg.sql заново (идемпотентно, `psql -U postgres -f …`).
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_admin') then
    create role app_admin nologin bypassrls;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'app_rls') then
    create role app_rls nologin;
  end if;
end
$$;

grant app_admin to current_user;
grant app_rls to current_user;

create table accounts (
    id                bigint      generated always as identity primary key,
    telegram_user_id  bigint      not null unique,
    telegram_username text,
    role              text        not null default 'member' check (role in ('owner', 'member')),
    status            text        not null default 'active' check (status in ('active', 'disabled')),
    created_at        timestamptz not null default now()
);

alter table accounts enable row level security;

-- Fail-closed (§1 плана): current_setting(..., true) без выставленного app.account_id даёт
-- NULL, сравнение с NULL никогда не истинно — забытый контекст прячет все строки, а не открывает.
create policy accounts_self_isolation on accounts
    using (id = current_setting('app.account_id', true)::bigint);

create table account_settings (
    account_id bigint      not null references accounts(id) on delete cascade,
    key        text        not null,
    value      jsonb       not null,
    updated_at timestamptz not null default now(),
    primary key (account_id, key)
);

alter table account_settings enable row level security;

create policy account_settings_isolation on account_settings
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on accounts, account_settings to app_rls, app_admin;

-- Backfill: сегодняшний единственный владелец становится аккаунтом №1, role='owner'.
-- Источник identity — telegram_owner (привязка через веб/бота), а если её ещё нет — user_id
-- из web_auth_token (кто-то уже вошёл по токену, но привязку в telegram_owner не завершил).
-- Свежая установка без ни одной из этих строк (чистая CI-БД, ещё не настроенный friend-install)
-- оставляет accounts пустой — первый /start заведёт аккаунт в Этапе 5.
insert into accounts (telegram_user_id, telegram_username, role, status)
select
    coalesce(
        (select (value ->> 'user_id')::bigint from app_settings where key = 'telegram_owner'),
        (select (value ->> 'user_id')::bigint from app_settings where key = 'web_auth_token')
    ) as telegram_user_id,
    coalesce(
        (select value ->> 'username' from app_settings where key = 'telegram_owner'),
        (select value ->> 'username' from app_settings where key = 'web_auth_token')
    ) as telegram_username,
    'owner',
    'active'
where coalesce(
    (select (value ->> 'user_id')::bigint from app_settings where key = 'telegram_owner'),
    (select (value ->> 'user_id')::bigint from app_settings where key = 'web_auth_token')
) is not null
on conflict (telegram_user_id) do nothing;
