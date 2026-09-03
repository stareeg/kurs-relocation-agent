-- 0109_platform_account_id — M6 (plans/multitenancy_gaps_2026_08_06.md §3.8-§3.10, §3.12, §6):
-- платформенный слой (usage, очередь фоновых задач, лог-витрина) получает account_id.
--
-- В отличие от M1-M5 колонка здесь НЕ NOT NULL — обе таблицы по природе смешанные:
-- llm_usage.account_id — NULL для LLM-вызовов вне request/task-контекста (пока такие остаются:
-- market_snapshot_refresh/situation_refresh резолвят владельца сами через
-- resolve_default_account_id(), ContextVar не выставляют — М5/M8 сузят это позже).
-- background_tasks.account_id — NULL для системных kind (market_snapshot_refresh,
-- situation_refresh, empty_stub_purge, attachments_gc, tg_cleanup): они не принадлежат ни
-- одному аккаунту по смыслу, тот самый «системные kind перечисляются явно» из §8 рисков.
-- Поэтому обе таблицы не входят в REQUIRED_ACCOUNT_SCOPED_TABLES (tests/test_tenant_columns_
-- present.py) — тот список требует NOT NULL, здесь это архитектурно неверно.
--
-- Backfill: llm_usage — вся история сегодня принадлежит владельцу (единственный аккаунт до этой
-- недели), тот же приём, что 0097/.../0106. background_tasks — восстанавливаем из payload там,
-- где enqueue уже клал account_id (salary_estimate/attachment_read); остальное (системные
-- цепочки) остаётся NULL, это и есть корректный ответ, а не пробел.
--
-- copilot_logs — третья таблица (§3.9), но она классифицирована как SYSTEM, не ACCOUNT_SCOPED:
-- account_id тут поле для фильтра выдачи бандла, не предмет RLS-изоляции (значение просто
-- берётся из того же per-request ContextVar, что и task_id, — см. core.platform.observability).

do $$
declare
    v_owner_id bigint;
begin
    select id into v_owner_id from accounts where role = 'owner' order by id limit 1;

    -- === llm_usage (§3.8) ========================================================================
    alter table llm_usage add column account_id bigint;
    if v_owner_id is not null then
        update llm_usage set account_id = v_owner_id;
    end if;
    alter table llm_usage add constraint llm_usage_account_id_fkey
        foreign key (account_id) references accounts (id) on delete set null;
    create index llm_usage_account_id_idx on llm_usage (account_id, day);
    alter table llm_usage enable row level security;
    create policy llm_usage_account_isolation on llm_usage
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === background_tasks (§3.10) ================================================================
    alter table background_tasks add column account_id bigint;
    update background_tasks
        set account_id = (payload ->> 'account_id')::bigint
        where payload ? 'account_id' and payload ->> 'account_id' ~ '^\d+$';
    alter table background_tasks add constraint background_tasks_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index background_tasks_account_id_idx on background_tasks (account_id);
    alter table background_tasks enable row level security;
    -- Fail-closed для account-задач (не свой account_id — не видно), но системные (account_id
    -- is null) видны любому под app_rls — они не персональные (§8 рисков: «системные kind
    -- перечисляются явно»), а витрина «Параметры» показывает их всем как диагностику очереди.
    create policy background_tasks_account_isolation on background_tasks
        using (
            account_id is null
            or account_id = current_setting('app.account_id', true)::bigint
        );

    -- === copilot_logs (§3.9, SYSTEM — без RLS) ===================================================
    alter table copilot_logs add column account_id bigint;
    alter table copilot_logs add constraint copilot_logs_account_id_fkey
        foreign key (account_id) references accounts (id) on delete set null;
    create index copilot_logs_account_id_idx on copilot_logs (account_id);
end
$$;

grant select, insert, update, delete on llm_usage, background_tasks to app_rls, app_admin;

-- Обе identity-PK таблицы — под app_rls insert падает без grant на последовательность (0103).
grant usage, select on sequence llm_usage_id_seq, background_tasks_id_seq to app_rls, app_admin;
