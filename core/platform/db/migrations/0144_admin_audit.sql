-- 0144_admin_audit — реестр действий оператора (plans/admin_panel_2026_08_25.md Этап 5.4).
-- copilot_logs уже принимает event='АДМИН', но это поток, а не реестр: нет выборки
-- «кто кого отключил», и скачивание чужого бандла логов в панели не видно.
-- details — jsonb без секретов (маска ключа, не ключ); пишется рядом с АДМИН-событием.
create table admin_audit (
    id          bigint generated always as identity primary key,
    at          timestamptz not null default now(),
    actor_id    bigint not null references accounts(id),
    action      text   not null,
    target_id   bigint references accounts(id),
    details     jsonb  not null default '{}'::jsonb
);

create index admin_audit_at_idx on admin_audit (at desc);
create index admin_audit_target_idx on admin_audit (target_id, at desc);
