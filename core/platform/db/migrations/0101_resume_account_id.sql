-- 0101_resume_account_id — M1 (plans/multitenancy_gaps_2026_08_06.md §6): резюме-скор и его
-- производные получают account_id + RLS. Это ровно тот инвентарь, который держал S1-баг §3.1
-- ("резюме друга становится резюме для всех"): resume_score_history, resume_stats, resume_views,
-- resume_skill_snapshots, resume_skill_suggestions были общими на всю систему, без единой колонки
-- личности.
--
-- Backfill: единственный сегодня account — role='owner' (тот же приём, что 0097/0098).
-- resume_skill_suggestions денормализует account_id от родителя (resume_skill_snapshots) — RLS-
-- политике нужна колонка на самой строке, join внутри policy недопустим (тот же приём, что
-- hr_messages от hr_threads в 0097).

do $$
declare
    v_owner_id bigint;
begin
    select id into v_owner_id from accounts where role = 'owner' order by id limit 1;

    -- === resume_score_history (снимки балла резюме, FR2-46) ================================
    alter table resume_score_history add column account_id bigint;
    if v_owner_id is not null then
        update resume_score_history set account_id = v_owner_id;
    end if;
    alter table resume_score_history alter column account_id set not null;
    alter table resume_score_history add constraint resume_score_history_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index resume_score_history_account_id_idx on resume_score_history (account_id);
    alter table resume_score_history enable row level security;
    create policy resume_score_history_account_isolation on resume_score_history
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === resume_stats (снимки счётчиков резюме hh, AF-1) ====================================
    alter table resume_stats add column account_id bigint;
    if v_owner_id is not null then
        update resume_stats set account_id = v_owner_id;
    end if;
    alter table resume_stats alter column account_id set not null;
    alter table resume_stats add constraint resume_stats_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index resume_stats_account_id_idx on resume_stats (account_id);
    alter table resume_stats enable row level security;
    create policy resume_stats_account_isolation on resume_stats
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === resume_views (история просмотров резюме hh, AF-1) ==================================
    alter table resume_views add column account_id bigint;
    if v_owner_id is not null then
        update resume_views set account_id = v_owner_id;
    end if;
    alter table resume_views alter column account_id set not null;
    alter table resume_views add constraint resume_views_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    -- Натуральный ключ дедупа расширяется аккаунтом: тот же (работодатель, вакансия, момент)
    -- у двух аккаунтов — два разных просмотра резюме, не конфликт.
    drop index resume_views_natural_idx;
    create unique index resume_views_natural_idx on resume_views
        (account_id, employer, vacancy_url, viewed_at);
    create index resume_views_account_id_idx on resume_views (account_id);
    alter table resume_views enable row level security;
    create policy resume_views_account_isolation on resume_views
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === resume_skill_snapshots (шапка снимка навыков, S-04) ================================
    alter table resume_skill_snapshots add column account_id bigint;
    if v_owner_id is not null then
        update resume_skill_snapshots set account_id = v_owner_id;
    end if;
    alter table resume_skill_snapshots alter column account_id set not null;
    alter table resume_skill_snapshots add constraint resume_skill_snapshots_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index resume_skill_snapshots_account_id_idx on resume_skill_snapshots (account_id);
    alter table resume_skill_snapshots enable row level security;
    create policy resume_skill_snapshots_account_isolation on resume_skill_snapshots
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === resume_skill_suggestions (строки снимка, денорм account_id от snapshot) ============
    alter table resume_skill_suggestions add column account_id bigint;
    update resume_skill_suggestions s set account_id = h.account_id
        from resume_skill_snapshots h where h.id = s.snapshot_id;
    alter table resume_skill_suggestions alter column account_id set not null;
    alter table resume_skill_suggestions add constraint resume_skill_suggestions_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index resume_skill_suggestions_account_id_idx on resume_skill_suggestions (account_id);
    alter table resume_skill_suggestions enable row level security;
    create policy resume_skill_suggestions_account_isolation on resume_skill_suggestions
        using (account_id = current_setting('app.account_id', true)::bigint);
end
$$;

grant select, insert, update, delete on
    resume_score_history, resume_stats, resume_views, resume_skill_snapshots,
    resume_skill_suggestions
to app_rls, app_admin;
