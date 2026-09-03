-- 0097_pipeline_account_id — Этап 3, домен 1 (plans/vm_multitenant_hosting_2026_08_03.md §9):
-- ретрофит account_id + RLS на воронку/вакансии (opportunities: jobs, application_stages,
-- score_revisions, skipped_vacancies, vacancy_enrichment) и HR-переписку (pipeline: hr_threads,
-- hr_messages, hr_vacancy_links, stage_outcomes, tg_hr_pending). vacancy_skill_requirements
-- НЕ трогаем — кэш навыков из текста JD объективен и не зависит от того, чей это аккаунт (§2.2
-- "система"), а не персональные данные.
--
-- Backfill: единственный сегодня account — role='owner' (заведён в 0095). Для application_stages/
-- hr_messages используем более точный источник (join на родителя: jobs.account_id / hr_threads.
-- account_id) — на практике совпадает с owner-дефолтом (система была однотенантной до этой
-- миграции), но так не полагаемся на порядок операций UPDATE.
--
-- Важно (план §1, найдено при чтении схемы): `jobs.vacancy_id`, `skipped_vacancies.vacancy_id`
-- были ГЛОБАЛЬНО unique/PK — один HH-id на всю систему. Без правки уникальности два аккаунта,
-- трекающих одну и ту же вакансию, столкнулись бы на one row (одна оценка/стадия на двоих).
-- Меняем на составной unique/PK (account_id, vacancy_id) — то же для vacancy_enrichment.pkey и
-- hr_vacancy_links.pkey (hr_key может повторяться у разных аккаунтов — тот же внешний рекрутер).

do $$
declare
    v_owner_id bigint;
begin
    select id into v_owner_id from accounts where role = 'owner' order by id limit 1;

    -- === jobs (вакансии/воронка) ============================================================
    alter table jobs add column account_id bigint;
    if v_owner_id is not null then
        update jobs set account_id = v_owner_id;
    end if;
    alter table jobs alter column account_id set not null;
    alter table jobs add constraint jobs_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table jobs drop constraint jobs_vacancy_id_key;
    alter table jobs add constraint jobs_account_vacancy_key unique (account_id, vacancy_id);
    create index jobs_account_id_idx on jobs (account_id);
    alter table jobs enable row level security;
    create policy jobs_account_isolation on jobs
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === application_stages (история переходов воронки, FK на jobs) ========================
    alter table application_stages add column account_id bigint;
    update application_stages a set account_id = j.account_id
        from jobs j where j.id = a.job_id;
    alter table application_stages alter column account_id set not null;
    alter table application_stages add constraint application_stages_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index application_stages_account_id_idx on application_stages (account_id);
    alter table application_stages enable row level security;
    create policy application_stages_account_isolation on application_stages
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === score_revisions (провенанс пересчёта скора, vacancy_id БЕЗ FK на jobs) ==============
    alter table score_revisions add column account_id bigint;
    if v_owner_id is not null then
        update score_revisions set account_id = v_owner_id;
    end if;
    alter table score_revisions alter column account_id set not null;
    alter table score_revisions add constraint score_revisions_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index score_revisions_account_id_idx on score_revisions (account_id);
    alter table score_revisions enable row level security;
    create policy score_revisions_account_isolation on score_revisions
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === skipped_vacancies (решение «не подавать», было unique(vacancy_id)) =================
    alter table skipped_vacancies add column account_id bigint;
    if v_owner_id is not null then
        update skipped_vacancies set account_id = v_owner_id;
    end if;
    alter table skipped_vacancies alter column account_id set not null;
    alter table skipped_vacancies add constraint skipped_vacancies_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table skipped_vacancies drop constraint skipped_vacancies_vacancy_id_key;
    alter table skipped_vacancies add constraint skipped_vacancies_account_vacancy_key
        unique (account_id, vacancy_id);
    alter table skipped_vacancies enable row level security;
    create policy skipped_vacancies_account_isolation on skipped_vacancies
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === vacancy_enrichment (HR-факты по вакансии, было PK(vacancy_id)) ======================
    alter table vacancy_enrichment add column account_id bigint;
    if v_owner_id is not null then
        update vacancy_enrichment set account_id = v_owner_id;
    end if;
    alter table vacancy_enrichment alter column account_id set not null;
    alter table vacancy_enrichment add constraint vacancy_enrichment_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table vacancy_enrichment drop constraint vacancy_enrichment_pkey;
    alter table vacancy_enrichment add primary key (account_id, vacancy_id);
    alter table vacancy_enrichment enable row level security;
    create policy vacancy_enrichment_account_isolation on vacancy_enrichment
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === hr_threads (переписка с HR по вакансии) ==============================================
    alter table hr_threads add column account_id bigint;
    if v_owner_id is not null then
        update hr_threads set account_id = v_owner_id;
    end if;
    alter table hr_threads alter column account_id set not null;
    alter table hr_threads add constraint hr_threads_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index hr_threads_account_id_idx on hr_threads (account_id);
    alter table hr_threads enable row level security;
    create policy hr_threads_account_isolation on hr_threads
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === hr_messages (реплики тредов, денорм account_id от родителя) ========================
    alter table hr_messages add column account_id bigint;
    update hr_messages m set account_id = t.account_id
        from hr_threads t where t.id = m.thread_id;
    alter table hr_messages alter column account_id set not null;
    alter table hr_messages add constraint hr_messages_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index hr_messages_account_id_idx on hr_messages (account_id);
    alter table hr_messages enable row level security;
    create policy hr_messages_account_isolation on hr_messages
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === hr_vacancy_links (реестр HR↔vacancy_id, было PK(hr_key, vacancy_id)) ===============
    alter table hr_vacancy_links add column account_id bigint;
    if v_owner_id is not null then
        update hr_vacancy_links set account_id = v_owner_id;
    end if;
    alter table hr_vacancy_links alter column account_id set not null;
    alter table hr_vacancy_links add constraint hr_vacancy_links_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table hr_vacancy_links drop constraint hr_vacancy_links_pkey;
    alter table hr_vacancy_links add primary key (account_id, hr_key, vacancy_id);
    alter table hr_vacancy_links enable row level security;
    create policy hr_vacancy_links_account_isolation on hr_vacancy_links
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === stage_outcomes (структурный исход этапа собеса, vacancy_id БЕЗ FK) ==================
    alter table stage_outcomes add column account_id bigint;
    if v_owner_id is not null then
        update stage_outcomes set account_id = v_owner_id;
    end if;
    alter table stage_outcomes alter column account_id set not null;
    alter table stage_outcomes add constraint stage_outcomes_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index stage_outcomes_account_id_idx on stage_outcomes (account_id);
    alter table stage_outcomes enable row level security;
    create policy stage_outcomes_account_isolation on stage_outcomes
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === tg_hr_pending (pending HR-кнопок бота, PK — случайный token, без коллизии) ==========
    alter table tg_hr_pending add column account_id bigint;
    if v_owner_id is not null then
        update tg_hr_pending set account_id = v_owner_id;
    end if;
    alter table tg_hr_pending alter column account_id set not null;
    alter table tg_hr_pending add constraint tg_hr_pending_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table tg_hr_pending enable row level security;
    create policy tg_hr_pending_account_isolation on tg_hr_pending
        using (account_id = current_setting('app.account_id', true)::bigint);
end
$$;

grant select, insert, update, delete on
    jobs, application_stages, score_revisions, skipped_vacancies, vacancy_enrichment,
    hr_threads, hr_messages, hr_vacancy_links, stage_outcomes, tg_hr_pending
to app_rls, app_admin;
