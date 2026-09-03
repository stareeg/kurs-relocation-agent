-- 0126_gm_trust_snapshots — GM-12 (plans/getmatch_extension_improvements_2026_08_16.md §Шаг 12):
-- история снимков чеклиста доверия getmatch (/api/trust), из которых Copilot показывает статус
-- заполненности профиля getmatch («N/6» + пропуски). По образцу gm_profile_snapshots (0125):
-- account-scoped + RLS, jsonb raw для полей сверх денормализованных. Вывод всегда по последнему
-- снимку (order by captured_at desc).

create table gm_trust_snapshots (
    id          bigint      generated always as identity primary key,
    account_id  bigint      not null references accounts (id) on delete cascade,
    captured_at timestamptz not null default now(),
    raw         jsonb       not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

-- последний снимок аккаунта (свежие первыми) — читает вкладка «Резюме» и приём из расширения.
create index gm_trust_snapshots_account_idx on gm_trust_snapshots (account_id, captured_at desc);

alter table gm_trust_snapshots enable row level security;
create policy gm_trust_snapshots_account_isolation on gm_trust_snapshots
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on gm_trust_snapshots to app_rls, app_admin;