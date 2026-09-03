-- 0133_international_profile_snapshots — снимок международного опыта из текста резюме.
-- Кэш по resume_hash: пересчёт только при изменении резюме (тот же приём, что 0081).

create table international_profile_snapshots (
    account_id   bigint      not null references accounts (id) on delete cascade,
    resume_hash  text        not null,
    data         jsonb       not null default '{}'::jsonb,
    created_at   timestamptz not null default now(),
    primary key (account_id, resume_hash)
);

alter table international_profile_snapshots enable row level security;
create policy intl_profile_account_isolation on international_profile_snapshots
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on international_profile_snapshots to app_rls, app_admin;
