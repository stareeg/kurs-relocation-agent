-- 0100_interview_stages_account_id — Этап 3, домен 2 (plans/vm_multitenant_hosting_2026_08_03.md
-- §9, продолжение после Этапа 5): ретрофит account_id + RLS на interview_stages. Предыдущий
-- проход Этапа 3 (0097) сделал только pipeline/funnel — digest «Собесы сегодня»
-- (bot_app/services/digest.py) и HR-пайплайн бота (bot_app/handlers/forwarded.py →
-- core/domains/pipeline/hr_actions.py) читали/писали эту таблицу вообще без account_id, отфильтрованную
-- только по vacancy_id — найдено при попытке открыть карточки вакансий/дайджест для self-serve
-- друзей (Этап 5): реальный cross-account leak (и потенциальная коллизия — два аккаунта, трекающих
-- одну и ту же публичную hh-вакансию, писали бы в ОДНИ И ТЕ ЖЕ строки), не гипотетический (см.
-- память project_openrouter_key_flow_2026_08_05).
--
-- Нет FK на jobs (0006: этап может быть распознан из письма HR раньше скоринга, для вакансии вне
-- jobs) — account_id поэтому обычная колонка, не наследуется автоматически через join.
--
-- Backfill: точный источник — join на jobs по vacancy_id (jobs.account_id), как application_stages
-- в 0097; если совпадения нет (этап есть, а jobs-строки нет — HR написал раньше скоринга) —
-- единственный на тот момент владелец.
do $$
declare
    v_owner_id bigint;
begin
    select id into v_owner_id from accounts where role = 'owner' order by id limit 1;

    alter table interview_stages add column account_id bigint;

    update interview_stages s set account_id = j.account_id
        from jobs j where j.vacancy_id = s.vacancy_id
        and s.account_id is null;

    if v_owner_id is not null then
        update interview_stages set account_id = v_owner_id where account_id is null;
    end if;

    alter table interview_stages alter column account_id set not null;
    alter table interview_stages add constraint interview_stages_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;

    create index interview_stages_account_id_idx on interview_stages (account_id);
    alter table interview_stages enable row level security;
    create policy interview_stages_account_isolation on interview_stages
        using (account_id = current_setting('app.account_id', true)::bigint);
end
$$;

grant select, insert, update, delete on interview_stages to app_rls, app_admin;
