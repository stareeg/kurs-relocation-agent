-- 0123_job_links — дедупликация вакансий между площадками: одна логическая вакансия
-- может жить на hh/getmatch/habr одновременно; `jobs` остаётся канонической строкой
-- (unique по (account_id, vacancy_id)), а `job_links` хранит все площадочные ссылки.

create table job_links (
  id bigserial primary key,
  account_id bigint not null,
  job_id bigint not null references jobs(id) on delete cascade,
  source text not null,            -- канон ALL_JOB_SOURCES
  vacancy_id text,                 -- площадочный id
  url text,
  is_primary boolean not null default false,  -- true = строка, которую принесли первой
  created_at timestamptz not null default now(),
  unique (account_id, source, vacancy_id)
);

create index job_links_job_id_idx on job_links (account_id, job_id);

-- Префильтр кандидатов дедупликации: токены текста вакансии на jobs + GIN для пересечения
-- массивов. Точное сравнение (Jaccard > порога) всё равно идёт в Python — здесь только
-- выборка топ-N кандидатов без O(n) по всем jobs аккаунта.
alter table jobs add column if not exists text_tokens text[];
create index if not exists jobs_text_tokens_gin on jobs using gin (text_tokens);

-- RLS: площадочные ссылки одной логической вакансии — аккаунтные данные (account_id с нуля
-- в CREATE TABLE, RLS по тому же принципу, что jobs/hr_vacancy_links).
alter table job_links enable row level security;
create policy job_links_account_isolation on job_links
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on job_links to app_rls, app_admin;
