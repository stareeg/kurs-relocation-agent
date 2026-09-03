-- 0125_gm_profile_snapshots — GM-13 (plans/getmatch_extension_improvements_2026_08_16.md §Шаг 11):
-- история снимков getmatch-профиля кандидата (GET /api/profiles), из которых Copilot считает
-- расхождения резюме (getmatch vs Copilot). По образцу resume_stats (0017): account-scoped + RLS,
-- jsonb raw для полей сверх денормализованных. БЕЗ FK на accounts? Нет — account_id FK обязателен,
-- как в 0101. Сравнение всегда по последнему снимку (order by captured_at desc).

create table gm_profile_snapshots (
    id          bigint      generated always as identity primary key,
    account_id  bigint      not null references accounts (id) on delete cascade,
    captured_at timestamptz not null default now(),
    raw         jsonb       not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

-- последний снимок аккаунта (свежие первыми) — читает вкладка «Резюме» и приём из расширения.
create index gm_profile_snapshots_account_idx on gm_profile_snapshots (account_id, captured_at desc);

alter table gm_profile_snapshots enable row level security;
create policy gm_profile_snapshots_account_isolation on gm_profile_snapshots
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on gm_profile_snapshots to app_rls, app_admin;
