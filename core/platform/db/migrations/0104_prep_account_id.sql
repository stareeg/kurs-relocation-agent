-- 0104_prep_account_id — M3 (plans/multitenancy_gaps_2026_08_06.md §3.3, §6): подготовка
-- (технички/скрининги/дебрифы/чат по вакансии) получает account_id + RLS. Тот самый S1-баг §3.3:
-- все эти таблицы ключевались только по vacancy_id (публичный HH/getmatch id) — два аккаунта,
-- готовящихся к одной вакансии (или совпавшему набору questions/pack), делили одну строку
-- подготовки, разборов, чата и карты компетенций.
--
-- Backfill: единственный сегодня account — role='owner' (тот же приём, что 0097/0098/0101/0102).
-- prep_packs (было PK(vacancy_id, stage)) → PK(account_id, vacancy_id, stage), тот же приём, что
-- offers в 0102. vacancy_screening_questions (было PK(vacancy_id)) → PK(account_id, vacancy_id).
-- prep_topics (было unique(vacancy_id, stage, topic)) → unique(account_id, vacancy_id, stage, topic).
-- debrief_attachments/prep_chat_message_attachments денормализуют account_id от родителя
-- (interview_debriefs/prep_chat_messages) — тот же приём, что resume_skill_suggestions от
-- resume_skill_snapshots в 0101 и hr_messages от hr_threads в 0097: RLS-политике нужна колонка
-- на самой строке, join внутри policy недопустим.

do $$
declare
    v_owner_id bigint;
begin
    select id into v_owner_id from accounts where role = 'owner' order by id limit 1;

    -- === prep_sessions =========================================================================
    alter table prep_sessions add column account_id bigint;
    if v_owner_id is not null then
        update prep_sessions set account_id = v_owner_id;
    end if;
    alter table prep_sessions alter column account_id set not null;
    alter table prep_sessions add constraint prep_sessions_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index prep_sessions_account_id_idx on prep_sessions (account_id);
    alter table prep_sessions enable row level security;
    create policy prep_sessions_account_isolation on prep_sessions
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === prep_reminders =========================================================================
    alter table prep_reminders add column account_id bigint;
    if v_owner_id is not null then
        update prep_reminders set account_id = v_owner_id;
    end if;
    alter table prep_reminders alter column account_id set not null;
    alter table prep_reminders add constraint prep_reminders_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index prep_reminders_account_id_idx on prep_reminders (account_id);
    alter table prep_reminders enable row level security;
    create policy prep_reminders_account_isolation on prep_reminders
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === prep_packs (было PK(vacancy_id, stage)) ==============================================
    alter table prep_packs add column account_id bigint;
    if v_owner_id is not null then
        update prep_packs set account_id = v_owner_id;
    end if;
    alter table prep_packs alter column account_id set not null;
    alter table prep_packs add constraint prep_packs_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table prep_packs drop constraint prep_packs_pkey;
    alter table prep_packs add primary key (account_id, vacancy_id, stage);
    alter table prep_packs enable row level security;
    create policy prep_packs_account_isolation on prep_packs
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === prep_topics (было unique(vacancy_id, stage, topic)) ==================================
    alter table prep_topics add column account_id bigint;
    if v_owner_id is not null then
        update prep_topics set account_id = v_owner_id;
    end if;
    alter table prep_topics alter column account_id set not null;
    alter table prep_topics add constraint prep_topics_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table prep_topics drop constraint prep_topics_vacancy_id_stage_topic_key;
    alter table prep_topics add constraint prep_topics_account_vacancy_stage_topic_key
        unique (account_id, vacancy_id, stage, topic);
    create index prep_topics_account_id_idx on prep_topics (account_id);
    alter table prep_topics enable row level security;
    create policy prep_topics_account_isolation on prep_topics
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === interview_debriefs ====================================================================
    alter table interview_debriefs add column account_id bigint;
    if v_owner_id is not null then
        update interview_debriefs set account_id = v_owner_id;
    end if;
    alter table interview_debriefs alter column account_id set not null;
    alter table interview_debriefs add constraint interview_debriefs_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index interview_debriefs_account_id_idx on interview_debriefs (account_id);
    alter table interview_debriefs enable row level security;
    create policy interview_debriefs_account_isolation on interview_debriefs
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === debrief_attachments (денорм account_id от interview_debriefs) ========================
    alter table debrief_attachments add column account_id bigint;
    update debrief_attachments a set account_id = d.account_id
        from interview_debriefs d where d.id = a.debrief_id;
    alter table debrief_attachments alter column account_id set not null;
    alter table debrief_attachments add constraint debrief_attachments_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index debrief_attachments_account_id_idx on debrief_attachments (account_id);
    alter table debrief_attachments enable row level security;
    create policy debrief_attachments_account_isolation on debrief_attachments
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === vacancy_screening_questions (было PK(vacancy_id)) ====================================
    alter table vacancy_screening_questions add column account_id bigint;
    if v_owner_id is not null then
        update vacancy_screening_questions set account_id = v_owner_id;
    end if;
    alter table vacancy_screening_questions alter column account_id set not null;
    alter table vacancy_screening_questions add constraint vacancy_screening_questions_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table vacancy_screening_questions drop constraint vacancy_screening_questions_pkey;
    alter table vacancy_screening_questions add primary key (account_id, vacancy_id);
    alter table vacancy_screening_questions enable row level security;
    create policy vacancy_screening_questions_account_isolation on vacancy_screening_questions
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === prep_chat_messages =====================================================================
    alter table prep_chat_messages add column account_id bigint;
    if v_owner_id is not null then
        update prep_chat_messages set account_id = v_owner_id;
    end if;
    alter table prep_chat_messages alter column account_id set not null;
    alter table prep_chat_messages add constraint prep_chat_messages_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index prep_chat_messages_account_id_idx on prep_chat_messages (account_id);
    alter table prep_chat_messages enable row level security;
    create policy prep_chat_messages_account_isolation on prep_chat_messages
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === prep_chat_message_attachments (денорм account_id от prep_chat_messages) ==============
    alter table prep_chat_message_attachments add column account_id bigint;
    update prep_chat_message_attachments a set account_id = m.account_id
        from prep_chat_messages m where m.id = a.message_id;
    alter table prep_chat_message_attachments alter column account_id set not null;
    alter table prep_chat_message_attachments add constraint prep_chat_message_attachments_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index prep_chat_message_attachments_account_id_idx on prep_chat_message_attachments (account_id);
    alter table prep_chat_message_attachments enable row level security;
    create policy prep_chat_message_attachments_account_isolation on prep_chat_message_attachments
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === competency_ledger ======================================================================
    alter table competency_ledger add column account_id bigint;
    if v_owner_id is not null then
        update competency_ledger set account_id = v_owner_id;
    end if;
    alter table competency_ledger alter column account_id set not null;
    alter table competency_ledger add constraint competency_ledger_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index competency_ledger_account_id_idx on competency_ledger (account_id);
    alter table competency_ledger enable row level security;
    create policy competency_ledger_account_isolation on competency_ledger
        using (account_id = current_setting('app.account_id', true)::bigint);
end
$$;

grant select, insert, update, delete on
    prep_sessions, prep_reminders, prep_packs, prep_topics, interview_debriefs,
    debrief_attachments, vacancy_screening_questions, prep_chat_messages,
    prep_chat_message_attachments, competency_ledger
to app_rls, app_admin;

-- prep_topics/competency_ledger заведены старым стилем `id bigserial primary key` (0059/0046) —
-- под app_rls insert падает без явного grant на последовательность (тот же класс ошибки, что
-- 0103, найденный на resume_skill_snapshots/offer_comparisons_cache).
grant usage, select on sequence
    prep_topics_id_seq,
    competency_ledger_id_seq
to app_rls, app_admin;
