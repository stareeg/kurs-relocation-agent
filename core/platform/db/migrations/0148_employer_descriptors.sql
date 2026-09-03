-- 0148_employer_descriptors — обобщённые описания работодателей для деперсонализации (Э4.1).
-- Кэш по (account_id, company_canonical): описание строится один раз и переживает
-- перегенерацию письма (кост-гард той же природы, что NegotiationBrief).

create table employer_descriptors (
    account_id        bigint      not null references accounts (id) on delete cascade,
    company_canonical text        not null,
    descriptor        jsonb       not null default '{}'::jsonb,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    primary key (account_id, company_canonical)
);

alter table employer_descriptors enable row level security;
create policy employer_descriptors_account_isolation on employer_descriptors
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on employer_descriptors to app_rls, app_admin;
