-- Провижининг нативного PostgreSQL 18 под Career & Relocation Copilot.
-- Создаёт роль и базу `copilot` (операционка + витрина логов + чекпойнты оркестратора).
-- Запуск от суперюзера postgres (один раз):
--   psql -h 127.0.0.1 -p 5432 -U postgres -f scripts/init_native_pg.sql
-- Затем накатить схему: python -m core.platform.db.migrate
-- Идемпотентно: роль и база создаются только если их ещё нет.

-- Роль приложения (login + пароль). CREATE ROLE нельзя пропустить через IF NOT EXISTS — оборачиваем в DO.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'copilot') then
    create role copilot login password 'copilot';
  end if;
end
$$;

-- База. CREATE DATABASE недопустим внутри DO/транзакции — генерим команду и гоним через \gexec.
select 'create database copilot owner copilot'
where not exists (select 1 from pg_database where datname = 'copilot')\gexec

-- Миграция 0095_accounts.sql заводит служебные роли app_rls/app_admin через CREATE ROLE —
-- обычной login-роли без атрибута это не позволено. В Docker/CI POSTGRES_USER и так
-- суперпользователь (initdb-бутстрап образа postgres:18), здесь — та же привилегия для
-- нативной установки.
-- Идемпотентно: ALTER ROLE безопасно перевыполнять на уже существующей роли.
alter role copilot createrole;
