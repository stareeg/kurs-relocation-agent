-- 0102_offers_account_id — M2 (plans/multitenancy_gaps_2026_08_06.md §3.2, §6): офферы
-- получают account_id + RLS. Тот самый S1-баг §3.2: `offers`/`offer_comparisons_cache`
-- ключевались только по vacancy_id (публичный HH-id) — два аккаунта с оффером по одной
-- вакансии писали в одну строку и затирали друг друга; `GET /api/offers` отдавал офферы всех
-- аккаунтов с зарплатными вилками и заметками.
--
-- Backfill: единственный сегодня account — role='owner' (тот же приём, что 0097/0098/0101).
-- `offers` было PK(vacancy_id) → PK(account_id, vacancy_id) (тот же приём, что
-- vacancy_enrichment в 0097). `offer_comparisons_cache` было unique(vacancy_ids_hash) →
-- unique(account_id, vacancy_ids_hash) — кэш автосравнения теперь ключуется и по набору
-- офферов, и по тому, чей это набор.

do $$
declare
    v_owner_id bigint;
begin
    select id into v_owner_id from accounts where role = 'owner' order by id limit 1;

    -- === offers (было PK(vacancy_id)) ========================================================
    alter table offers add column account_id bigint;
    if v_owner_id is not null then
        update offers set account_id = v_owner_id;
    end if;
    alter table offers alter column account_id set not null;
    alter table offers add constraint offers_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table offers drop constraint offers_pkey;
    alter table offers add primary key (account_id, vacancy_id);
    alter table offers enable row level security;
    create policy offers_account_isolation on offers
        using (account_id = current_setting('app.account_id', true)::bigint);

    -- === offer_comparisons_cache (было unique(vacancy_ids_hash)) =============================
    alter table offer_comparisons_cache add column account_id bigint;
    if v_owner_id is not null then
        update offer_comparisons_cache set account_id = v_owner_id;
    end if;
    alter table offer_comparisons_cache alter column account_id set not null;
    alter table offer_comparisons_cache add constraint offer_comparisons_cache_account_id_fkey
        foreign key (account_id) references accounts (id) on delete cascade;
    alter table offer_comparisons_cache drop constraint offer_comparisons_cache_vacancy_ids_hash_key;
    alter table offer_comparisons_cache add constraint offer_comparisons_cache_account_hash_key
        unique (account_id, vacancy_ids_hash);
    alter table offer_comparisons_cache enable row level security;
    create policy offer_comparisons_cache_account_isolation on offer_comparisons_cache
        using (account_id = current_setting('app.account_id', true)::bigint);
end
$$;

grant select, insert, update, delete on offers, offer_comparisons_cache to app_rls, app_admin;
