-- 0098_resumes — Этап 4 (plans/vm_multitenant_hosting_2026_08_03.md §6, §9): резюме — с файла
-- на диске (resume/resume_data.json) в Postgres на аккаунт. В отличие от 0097 это не ретрофит
-- существующей PG-таблицы — данные раньше жили только в файле, backfill владельца делает Python
-- при первом старте после этой миграции (core.domains.profile.structured_store.
-- load_resume_into_runtime), не SQL: миграции не читают файлы с диска.
--
-- account_id — он же PK: одна строка резюме на аккаунт (в отличие от jobs/hr_threads, здесь нет
-- отдельного суррогатного id — резюме не имеет множественности внутри аккаунта).

create table resumes (
    account_id bigint      not null primary key references accounts(id) on delete cascade,
    data       jsonb       not null,
    updated_at timestamptz not null default now()
);

alter table resumes enable row level security;

create policy resumes_account_isolation on resumes
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on resumes to app_rls, app_admin;
