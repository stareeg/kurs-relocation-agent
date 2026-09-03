-- 0105_notes_attachments_account_id — M4 (plans/multitenancy_gaps_2026_08_06.md §3.4, §3.5, §6):
-- заметки, вложения-картинки, HR-guard-журнал получают account_id + RLS. Тот самый S1-баг §3.4/
-- §3.5: notes/attachments не различали аккаунт вообще — личная заметка/скриншот одного друга
-- видны (и удаляемы/перебираемы по id) любому другому аутентифицированному аккаунту.
--
-- attachments — особый случай (в отличие от M1-M3): раньше это была ОДНА таблица на всю систему,
-- контент-адресуемая по sha256 (§2.1 старого плана). Теперь дедуп содержимого происходит
-- per-account (unique(account_id, sha256) вместо unique(sha256)) — два аккаунта с одинаковыми
-- байтами скриншота получают по своей строке; осознанная цена структурной изоляции (совпадение
-- байт у разных людей практически нулевое, а IDOR через глобальный id/sha256 был реальным багом,
-- §3.5 — «перебор id выдаёт чужие скриншоты переписок и офферов»).
--
-- hr_message_attachments денормализует account_id от hr_messages (message_id), note_messages — от
-- notes (note_id): тот же приём, что debrief_attachments/prep_chat_message_attachments в 0104 —
-- RLS-политике нужна колонка на самой строке, join внутри policy недопустим.
--
-- Backfill: единственный сегодня account — role='owner' (тот же приём, что 0097/.../0104).

do $$
declare
    v_owner_id bigint;
begin
    select id into v_owner_id from accounts where role = 'owner' order by id limit 1;

    -- === notes ===================================================================================
    alter table notes add column account_id bigint;
    if v_owner_id is not null then
        update notes set account_id = v_owner_id;
    end if;
    alter table notes alter column account_id set not null;
    alter table notes add constraint notes_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index notes_account_id_idx on notes (account_id);
    alter table notes enable row level security;
    create policy notes_account_isolation on notes
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === note_messages (денорм account_id от notes) ============================================
    alter table note_messages add column account_id bigint;
    update note_messages m set account_id = n.account_id
        from notes n where n.id = m.note_id;
    alter table note_messages alter column account_id set not null;
    alter table note_messages add constraint note_messages_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index note_messages_account_id_idx on note_messages (account_id);
    alter table note_messages enable row level security;
    create policy note_messages_account_isolation on note_messages
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === attachments (было unique(sha256) — контент-адрес на всю систему) ======================
    alter table attachments add column account_id bigint;
    if v_owner_id is not null then
        update attachments set account_id = v_owner_id;
    end if;
    alter table attachments alter column account_id set not null;
    alter table attachments add constraint attachments_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table attachments drop constraint attachments_sha256_key;
    alter table attachments add constraint attachments_account_sha256_key unique (account_id, sha256);
    create index attachments_account_id_idx on attachments (account_id);
    alter table attachments enable row level security;
    create policy attachments_account_isolation on attachments
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === hr_message_attachments (денорм account_id от hr_messages) ============================
    alter table hr_message_attachments add column account_id bigint;
    update hr_message_attachments a set account_id = m.account_id
        from hr_messages m where m.id = a.message_id;
    alter table hr_message_attachments alter column account_id set not null;
    alter table hr_message_attachments add constraint hr_message_attachments_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index hr_message_attachments_account_id_idx on hr_message_attachments (account_id);
    alter table hr_message_attachments enable row level security;
    create policy hr_message_attachments_account_isolation on hr_message_attachments
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === hr_forward_journal ======================================================================
    alter table hr_forward_journal add column account_id bigint;
    if v_owner_id is not null then
        update hr_forward_journal set account_id = v_owner_id;
    end if;
    alter table hr_forward_journal alter column account_id set not null;
    alter table hr_forward_journal add constraint hr_forward_journal_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    create index hr_forward_journal_account_id_idx on hr_forward_journal (account_id);
    alter table hr_forward_journal enable row level security;
    create policy hr_forward_journal_account_isolation on hr_forward_journal
        using (account_id = current_setting('app.account_id', true)::bigint);
end
$$;

grant select, insert, update, delete on
    notes, note_messages, attachments, hr_message_attachments, hr_forward_journal
to app_rls, app_admin;

-- notes/note_messages заведены старым стилем `id bigserial primary key` (0029/0088) — под app_rls
-- insert падает без явного grant на последовательность (тот же класс ошибки, что 0103, найденный
-- на resume_skill_snapshots/offer_comparisons_cache/prep_topics/competency_ledger).
grant usage, select on sequence
    notes_id_seq,
    note_messages_id_seq
to app_rls, app_admin;
