-- 0106_market_career_account_id — M5 (plans/multitenancy_gaps_2026_08_06.md §3.6, §3.7, §6):
-- рынок, режим поиска, career, калибровка зарплат получают account_id + RLS. Закрывает S1/S2 из
-- §3.6/§3.7: «Рынок»/«Ситуация»/режим поиска были общими на всех аккаунтов — последний фон
-- перезаписывал кэш, друг видел аналитику и режим поиска владельца.
--
-- market_analytics_snapshot/market_snapshots/discovery_presets/salary_calibration_meta меняют
-- ключ (kind/day/name/key → account_id + тот же ключ) — тот же приём, что offers/prep_packs в
-- 0102/0104 (composite PK вместо голого natural key). tg_ui_messages/salary_calibration_queue/
-- salary_calibration_sessions уже де-факто изолированы по chat_id — account_id добавлен для
-- единообразия и будущего RLS (план §2), запросы остаются на chat_id.
--
-- Backfill: единственный сегодня account — role='owner' (тот же приём, что 0097/.../0105).
-- salary_calibration_samples донормализует account_id от очереди (queue_id), где есть связь;
-- историч. сэмплы без queue_id (0003, до пайплайна) уходят владельцу.

do $$
declare
    v_owner_id bigint;
begin
    select id into v_owner_id from accounts where role = 'owner' order by id limit 1;

    -- === search_state_log (ST-01) ===============================================================
    alter table search_state_log add column account_id bigint;
    if v_owner_id is not null then
        update search_state_log set account_id = v_owner_id;
    end if;
    alter table search_state_log alter column account_id set not null;
    alter table search_state_log add constraint search_state_log_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index search_state_log_account_id_idx on search_state_log (account_id, created_at desc, id desc);
    alter table search_state_log enable row level security;
    create policy search_state_log_account_isolation on search_state_log
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === situation_narratives (AF-4) =============================================================
    alter table situation_narratives add column account_id bigint;
    if v_owner_id is not null then
        update situation_narratives set account_id = v_owner_id;
    end if;
    alter table situation_narratives alter column account_id set not null;
    alter table situation_narratives add constraint situation_narratives_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index situation_narratives_account_id_idx
        on situation_narratives (account_id, created_at desc);
    alter table situation_narratives enable row level security;
    create policy situation_narratives_account_isolation on situation_narratives
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === market_analytics_snapshot (L-25, было PK(kind)) ========================================
    alter table market_analytics_snapshot add column account_id bigint;
    if v_owner_id is not null then
        update market_analytics_snapshot set account_id = v_owner_id;
    end if;
    alter table market_analytics_snapshot alter column account_id set not null;
    alter table market_analytics_snapshot drop constraint market_analytics_snapshot_pkey;
    alter table market_analytics_snapshot add constraint market_analytics_snapshot_pkey
        primary key (account_id, kind);
    alter table market_analytics_snapshot add constraint market_analytics_snapshot_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table market_analytics_snapshot enable row level security;
    create policy market_analytics_snapshot_account_isolation on market_analytics_snapshot
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === market_snapshots (было unique(day)) ====================================================
    alter table market_snapshots add column account_id bigint;
    if v_owner_id is not null then
        update market_snapshots set account_id = v_owner_id;
    end if;
    alter table market_snapshots alter column account_id set not null;
    alter table market_snapshots drop constraint market_snapshots_day_key;
    alter table market_snapshots add constraint market_snapshots_account_day_key
        unique (account_id, day);
    alter table market_snapshots add constraint market_snapshots_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index market_snapshots_account_day_idx on market_snapshots (account_id, day desc);
    alter table market_snapshots enable row level security;
    create policy market_snapshots_account_isolation on market_snapshots
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === discovery_presets (было PK(name)) ======================================================
    alter table discovery_presets add column account_id bigint;
    if v_owner_id is not null then
        update discovery_presets set account_id = v_owner_id;
    end if;
    alter table discovery_presets alter column account_id set not null;
    alter table discovery_presets drop constraint discovery_presets_pkey;
    alter table discovery_presets add constraint discovery_presets_pkey
        primary key (account_id, name);
    alter table discovery_presets add constraint discovery_presets_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table discovery_presets enable row level security;
    create policy discovery_presets_account_isolation on discovery_presets
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === tg_ui_messages (де-факто изолирована по chat_id — account_id для FK/единообразия) =====
    alter table tg_ui_messages add column account_id bigint;
    update tg_ui_messages t set account_id = coalesce(
        (select a.id from accounts a where a.telegram_chat_id = t.chat_id limit 1),
        v_owner_id
    );
    alter table tg_ui_messages alter column account_id set not null;
    alter table tg_ui_messages add constraint tg_ui_messages_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index tg_ui_messages_account_id_idx on tg_ui_messages (account_id);
    alter table tg_ui_messages enable row level security;
    create policy tg_ui_messages_account_isolation on tg_ui_messages
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === salary_calibration_queue (де-факто изолирована по chat_id) ============================
    alter table salary_calibration_queue add column account_id bigint;
    update salary_calibration_queue q set account_id = coalesce(
        (select a.id from accounts a where a.telegram_chat_id = q.chat_id limit 1),
        v_owner_id
    );
    alter table salary_calibration_queue alter column account_id set not null;
    alter table salary_calibration_queue add constraint salary_calibration_queue_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index salary_calibration_queue_account_id_idx on salary_calibration_queue (account_id);
    alter table salary_calibration_queue enable row level security;
    create policy salary_calibration_queue_account_isolation on salary_calibration_queue
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === salary_calibration_sessions (де-факто изолирована по chat_id, было PK(chat_id)) =======
    alter table salary_calibration_sessions add column account_id bigint;
    update salary_calibration_sessions s set account_id = coalesce(
        (select a.id from accounts a where a.telegram_chat_id = s.chat_id limit 1),
        v_owner_id
    );
    alter table salary_calibration_sessions alter column account_id set not null;
    alter table salary_calibration_sessions add constraint salary_calibration_sessions_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index salary_calibration_sessions_account_id_idx
        on salary_calibration_sessions (account_id);
    alter table salary_calibration_sessions enable row level security;
    create policy salary_calibration_sessions_account_isolation on salary_calibration_sessions
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === salary_calibration_samples (решение владельца 2026-08-06, план §9 п.1: личные ========
    -- наблюдения аккаунта, не общий корпус) — донорм от очереди (queue_id), историч. без queue_id
    -- (0003, до S9-пайплайна) уходят владельцу.
    alter table salary_calibration_samples add column account_id bigint;
    update salary_calibration_samples s set account_id = q.account_id
        from salary_calibration_queue q where q.id = s.queue_id;
    if v_owner_id is not null then
        update salary_calibration_samples set account_id = v_owner_id where account_id is null;
    end if;
    alter table salary_calibration_samples alter column account_id set not null;
    alter table salary_calibration_samples add constraint salary_calibration_samples_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index salary_calibration_samples_account_id_idx on salary_calibration_samples (account_id);
    alter table salary_calibration_samples enable row level security;
    create policy salary_calibration_samples_account_isolation on salary_calibration_samples
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === salary_calibration_meta (было PK(key)) =================================================
    alter table salary_calibration_meta add column account_id bigint;
    if v_owner_id is not null then
        update salary_calibration_meta set account_id = v_owner_id;
    end if;
    alter table salary_calibration_meta alter column account_id set not null;
    alter table salary_calibration_meta drop constraint salary_calibration_meta_pkey;
    alter table salary_calibration_meta add constraint salary_calibration_meta_pkey
        primary key (account_id, key);
    alter table salary_calibration_meta add constraint salary_calibration_meta_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table salary_calibration_meta enable row level security;
    create policy salary_calibration_meta_account_isolation on salary_calibration_meta
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === career_goals ============================================================================
    alter table career_goals add column account_id bigint;
    if v_owner_id is not null then
        update career_goals set account_id = v_owner_id;
    end if;
    alter table career_goals alter column account_id set not null;
    alter table career_goals add constraint career_goals_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index career_goals_account_id_idx on career_goals (account_id);
    alter table career_goals enable row level security;
    create policy career_goals_account_isolation on career_goals
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === career_timeline ==========================================================================
    alter table career_timeline add column account_id bigint;
    if v_owner_id is not null then
        update career_timeline set account_id = v_owner_id;
    end if;
    alter table career_timeline alter column account_id set not null;
    alter table career_timeline add constraint career_timeline_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index career_timeline_account_id_idx on career_timeline (account_id, occurred_at desc);
    alter table career_timeline enable row level security;
    create policy career_timeline_account_isolation on career_timeline
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === career_skill_targets ====================================================================
    alter table career_skill_targets add column account_id bigint;
    if v_owner_id is not null then
        update career_skill_targets set account_id = v_owner_id;
    end if;
    alter table career_skill_targets alter column account_id set not null;
    alter table career_skill_targets add constraint career_skill_targets_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index career_skill_targets_account_id_idx on career_skill_targets (account_id);
    alter table career_skill_targets enable row level security;
    create policy career_skill_targets_account_isolation on career_skill_targets
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === career_portfolio_items ===================================================================
    alter table career_portfolio_items add column account_id bigint;
    if v_owner_id is not null then
        update career_portfolio_items set account_id = v_owner_id;
    end if;
    alter table career_portfolio_items alter column account_id set not null;
    alter table career_portfolio_items add constraint career_portfolio_items_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index career_portfolio_items_account_id_idx on career_portfolio_items (account_id);
    alter table career_portfolio_items enable row level security;
    create policy career_portfolio_items_account_isolation on career_portfolio_items
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === career_relocation_steps ==================================================================
    alter table career_relocation_steps add column account_id bigint;
    if v_owner_id is not null then
        update career_relocation_steps set account_id = v_owner_id;
    end if;
    alter table career_relocation_steps alter column account_id set not null;
    alter table career_relocation_steps add constraint career_relocation_steps_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index career_relocation_steps_account_id_idx on career_relocation_steps (account_id);
    alter table career_relocation_steps enable row level security;
    create policy career_relocation_steps_account_isolation on career_relocation_steps
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === career_facts (A-28) ======================================================================
    alter table career_facts add column account_id bigint;
    if v_owner_id is not null then
        update career_facts set account_id = v_owner_id;
    end if;
    alter table career_facts alter column account_id set not null;
    alter table career_facts add constraint career_facts_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index career_facts_account_id_idx on career_facts (account_id, recorded_at desc);
    alter table career_facts enable row level security;
    create policy career_facts_account_isolation on career_facts
        using (account_id = current_setting('app.account_id', true)::bigint);
end
$$;

grant select, insert, update, delete on
    search_state_log, situation_narratives, market_analytics_snapshot, market_snapshots,
    discovery_presets, tg_ui_messages, salary_calibration_queue, salary_calibration_sessions,
    salary_calibration_samples, salary_calibration_meta, career_goals, career_timeline,
    career_skill_targets, career_portfolio_items, career_relocation_steps, career_facts
to app_rls, app_admin;

-- Все 16 таблиц заведены `bigint generated always as identity primary key` (кроме
-- market_analytics_snapshot/discovery_presets/salary_calibration_{sessions,meta} — natural-key
-- PK без identity) — под app_rls insert на identity-таблицах падает без grant на
-- последовательность (тот же класс ошибки, что 0103).
grant usage, select on sequence
    search_state_log_id_seq,
    situation_narratives_id_seq,
    market_snapshots_id_seq,
    tg_ui_messages_id_seq,
    salary_calibration_queue_id_seq,
    salary_calibration_samples_id_seq,
    career_goals_id_seq,
    career_timeline_id_seq,
    career_skill_targets_id_seq,
    career_portfolio_items_id_seq,
    career_relocation_steps_id_seq,
    career_facts_id_seq
to app_rls, app_admin;
